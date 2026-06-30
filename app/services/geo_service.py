"""
services/geo_service.py
Procesamiento de archivos geoespaciales: SHP, GeoJSON, KML, KMZ → PostGIS
"""
import os
import uuid
import zipfile
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
import fiona
from shapely.geometry import mapping
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

settings = get_settings()

# CRS estándar para el geovisor
TARGET_CRS = "EPSG:4326"


class GeoProcessingError(Exception):
    pass


def _safe_table_name(name: str) -> str:
    """Genera nombre de tabla seguro para PostgreSQL."""
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in name.lower())
    return f"layer_{safe}_{uuid.uuid4().hex[:8]}"


def _get_default_style(geometry_type: str) -> dict:
    """Retorna estilo MapLibre por defecto según tipo de geometría."""
    base = geometry_type.lower() if geometry_type else ""

    if "point" in base or "multi_point" in base:
        return {
            "type": "circle",
            "paint": {
                "circle-radius": 6,
                "circle-color": "#e63946",
                "circle-stroke-width": 1.5,
                "circle-stroke-color": "#ffffff",
            },
        }
    elif "line" in base or "multiline" in base:
        return {
            "type": "line",
            "paint": {"line-color": "#2176ae", "line-width": 2},
        }
    else:
        return {
            "type": "fill",
            "paint": {
                "fill-color": "#4CAF50",
                "fill-opacity": 0.5,
                "fill-outline-color": "#1B5E20",
            },
        }


async def process_shapefile(zip_path: str, layer_name: str, db: AsyncSession) -> dict:
    """
    Procesa un ZIP que contiene UN Shapefile (uso individual).
    Retorna metadata de la capa.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmpdir)

        shp_files = list(Path(tmpdir).rglob("*.shp"))
        if not shp_files:
            raise GeoProcessingError("No se encontró archivo .shp dentro del ZIP")
        shp_path = str(shp_files[0])

        gdf = gpd.read_file(shp_path)
        return await _ingest_geodataframe(gdf, layer_name, "shp", db)


async def process_shapefile_zip_multi(zip_path: str, base_name: str, db: AsyncSession) -> list[dict]:
    """
    Procesa un ZIP que puede contener UNO o MÚLTIPLES shapefiles.
    Retorna lista de metadatos de capas (una por cada .shp encontrado).
    """
    results = []
    errors = []

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(tmpdir)

        shp_files = list(Path(tmpdir).rglob("*.shp"))
        if not shp_files:
            raise GeoProcessingError("No se encontró ningún archivo .shp dentro del ZIP")

        for shp_path in shp_files:
            shp_name = shp_path.stem  # nombre sin extensión

            # Si solo hay un shapefile, usar el base_name del usuario
            # Si hay múltiples, usar el nombre del archivo .shp
            if len(shp_files) == 1:
                layer_name = base_name
            else:
                layer_name = f"{shp_name}"

            try:
                gdf = gpd.read_file(str(shp_path))
                meta = await _ingest_geodataframe(gdf, layer_name, "shp", db)
                meta["original_filename"] = shp_name
                results.append(meta)
            except Exception as e:
                errors.append({"file": shp_name, "error": str(e)})
                continue

        if not results:
            raise GeoProcessingError(
                f"No se pudo procesar ningún shapefile. Errores: {errors}"
            )

    return {"layers": results, "errors": errors}


async def process_geojson(file_path: str, layer_name: str, db: AsyncSession) -> dict:
    """Procesa un archivo GeoJSON."""
    gdf = gpd.read_file(file_path)
    return await _ingest_geodataframe(gdf, layer_name, "geojson", db)


async def process_kml_kmz(file_path: str, layer_name: str, db: AsyncSession) -> dict:
    """
    Procesa KML o KMZ.
    KMZ es un ZIP con un doc.kml dentro.
    """
    actual_path = file_path

    if file_path.lower().endswith(".kmz"):
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(file_path, "r") as z:
                z.extractall(tmpdir)
            kml_files = list(Path(tmpdir).rglob("*.kml"))
            if not kml_files:
                raise GeoProcessingError("No se encontró .kml dentro del KMZ")
            actual_path = str(kml_files[0])
            # Habilitar KML en fiona
            fiona.drvsupport.supported_drivers["KML"] = "rw"
            fiona.drvsupport.supported_drivers["LIBKML"] = "rw"
            gdf = gpd.read_file(actual_path, driver="KML")
            return await _ingest_geodataframe(gdf, layer_name, "kmz", db)
    else:
        fiona.drvsupport.supported_drivers["KML"] = "rw"
        fiona.drvsupport.supported_drivers["LIBKML"] = "rw"
        gdf = gpd.read_file(actual_path, driver="KML")
        return await _ingest_geodataframe(gdf, layer_name, "kml", db)


async def _ingest_geodataframe(
    gdf: gpd.GeoDataFrame,
    layer_name: str,
    source_format: str,
    db: AsyncSession,
) -> dict:
    """
    Núcleo del proceso:
    1. Reproyectar a WGS84
    2. Limpiar geometrías inválidas
    3. Insertar en PostGIS
    4. Retornar metadata
    """
    if gdf.empty:
        raise GeoProcessingError("El archivo no contiene features")

    # Asegurar que la columna activa de geometría se llame 'geometry'
    active_geom = gdf.geometry.name
    if active_geom != 'geometry':
        # Si ya existe una columna 'geometry' que no es la activa, eliminarla
        if 'geometry' in gdf.columns:
            gdf = gdf.drop(columns=['geometry'])
        gdf = gdf.rename_geometry('geometry')

    # Guardar CRS original ANTES de cualquier transformación
    original_crs = gdf.crs.to_string() if gdf.crs is not None else "Unknown"

    # 1. Reproyectar a EPSG:4326
    if gdf.crs is None:
        gdf = gdf.set_crs(TARGET_CRS, allow_override=True)
    elif gdf.crs.to_string() != TARGET_CRS:
        gdf = gdf.to_crs(TARGET_CRS)

    # 2. Eliminar geometrías nulas o inválidas
    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[~gdf.geometry.is_empty].copy()

    # Reparar geometrías inválidas con buffer(0)
    invalid_mask = ~gdf.geometry.is_valid
    if invalid_mask.any():
        gdf.loc[invalid_mask, 'geometry'] = gdf.loc[invalid_mask, 'geometry'].buffer(0)

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf = gdf[gdf.geometry.is_valid].copy()

    if gdf.empty:
        raise GeoProcessingError("El archivo no contiene geometrías válidas después de la limpieza")

    # 3. Obtener info
    geom_type = gdf.geometry.geom_type.iloc[0] if not gdf.empty else "Unknown"
    bbox = gdf.total_bounds  # [minx, miny, maxx, maxy]
    feature_count = len(gdf)

    # 4. Columnas de atributos (excluir geometry)
    attr_cols = [c for c in gdf.columns if c != "geometry"]
    attributes = {
        col: str(gdf[col].dtype) for col in attr_cols
    }

    # 5. Nombre de tabla en PostGIS
    table_name = _safe_table_name(layer_name)

    # 6. Insertar en PostGIS usando to_postgis con dtype de Geometry
    from sqlalchemy import create_engine
    from geoalchemy2 import Geometry
    import pandas as pd

    sync_engine = create_engine(settings.sync_database_url)

    # Eliminar tabla anterior si existe para evitar conflictos de tipo
    with sync_engine.connect() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
        conn.commit()

    # Convertir columnas datetime a string para evitar problemas con PostGIS
    for col in gdf.columns:
        if col != gdf.geometry.name and pd.api.types.is_datetime64_any_dtype(gdf[col]):
            gdf[col] = gdf[col].astype(str)

    # Asegurar que la columna activa siga siendo geometry
    if gdf.geometry.name != 'geometry':
        gdf = gdf.set_geometry('geometry')

    # Tipo de geometría en MAYÚSCULAS para PostGIS
    pg_geom_type = geom_type.upper()

    gdf.to_postgis(
        name=table_name,
        con=sync_engine,
        if_exists="replace",
        index=False,
        schema="public",
        dtype={"geometry": Geometry(geometry_type=pg_geom_type, srid=4326)},
    )
    sync_engine.dispose()

    # 7. Crear índice espacial para rendimiento
    await db.execute(
        text(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_geom ON {table_name} USING GIST(geometry)")
    )
    await db.commit()

    return {
        "postgis_table": table_name,
        "geometry_type": geom_type,
        "crs_original": original_crs,
        "feature_count": feature_count,
        "bbox_minx": float(bbox[0]),
        "bbox_miny": float(bbox[1]),
        "bbox_maxx": float(bbox[2]),
        "bbox_maxy": float(bbox[3]),
        "attributes": attributes,
        "style": _get_default_style(geom_type),
        "source_format": source_format,
    }


async def delete_layer_table(table_name: str, db: AsyncSession):
    """Elimina la tabla de PostGIS cuando se borra una capa."""
    await db.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
    await db.commit()


# ── Análisis espacial ─────────────────────────────────────────────────────────

async def run_buffer(
    table_name: str,
    distance_meters: float,
    db: AsyncSession,
    filter_ids: Optional[list[int]] = None,
) -> dict:
    """
    Genera buffer alrededor de las geometrías de una capa.
    distance_meters: metros (se convierte a grados con factor aproximado)
    Retorna GeoJSON de los buffers.
    """
    # Para Colombia: 1 grado ≈ 111,320 metros
    distance_deg = distance_meters / 111320.0

    where = ""
    if filter_ids:
        ids_str = ", ".join(str(i) for i in filter_ids)
        where = f"WHERE id IN ({ids_str})"

    query = f"""
        SELECT
            ST_AsGeoJSON(
                ST_Buffer(geometry::geography, {distance_meters})::geometry
            ) AS geojson
        FROM {table_name}
        {where}
    """
    result = await db.execute(text(query))
    rows = result.fetchall()

    features = [
        {"type": "Feature", "geometry": __import__("json").loads(row.geojson), "properties": {}}
        for row in rows
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "operation": "buffer",
            "distance_meters": distance_meters,
            "feature_count": len(features),
        },
    }


async def run_intersection(
    table_a: str,
    table_b: str,
    db: AsyncSession,
) -> dict:
    """
    Intersección espacial entre dos capas.
    Retorna features de A que intersectan con B.
    """
    query = f"""
        SELECT ST_AsGeoJSON(ST_Intersection(a.geometry, b.geometry)) AS geojson
        FROM {table_a} a, {table_b} b
        WHERE ST_Intersects(a.geometry, b.geometry)
          AND NOT ST_IsEmpty(ST_Intersection(a.geometry, b.geometry))
    """
    result = await db.execute(text(query))
    rows = result.fetchall()

    features = [
        {"type": "Feature", "geometry": __import__("json").loads(row.geojson), "properties": {}}
        for row in rows
        if row.geojson
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "operation": "intersection",
            "layer_a": table_a,
            "layer_b": table_b,
            "feature_count": len(features),
        },
    }


async def run_dissolve(
    table_name: str,
    attribute: str,
    db: AsyncSession,
) -> dict:
    """
    Disuelve (agrupa) geometrías por un atributo.
    Equivale a ST_Union agrupado.
    """
    query = f"""
        SELECT
            {attribute},
            ST_AsGeoJSON(ST_Union(geometry)) AS geojson,
            COUNT(*) AS count
        FROM {table_name}
        GROUP BY {attribute}
    """
    result = await db.execute(text(query))
    rows = result.fetchall()

    features = [
        {
            "type": "Feature",
            "geometry": __import__("json").loads(row.geojson),
            "properties": {attribute: getattr(row, attribute), "count": row.count},
        }
        for row in rows
        if row.geojson
    ]
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "operation": "dissolve",
            "attribute": attribute,
            "groups": len(features),
        },
    }


async def get_layer_as_geojson(table_name: str, db: AsyncSession, limit: int = 5000) -> dict:
    """Exporta una capa completa como GeoJSON."""
    query = f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geometry)::json,
                    'properties', to_jsonb(t) - 'geometry'
                )
            )
        ) AS geojson
        FROM (SELECT * FROM {table_name} LIMIT {limit}) t
    """
    result = await db.execute(text(query))
    row = result.fetchone()
    return row.geojson if row and row.geojson else {"type": "FeatureCollection", "features": []}
