"""
FASE 4 — Análisis espacial avanzado
Archivo: app/services/advanced_analysis.py

Módulos:
- Buffer                       ✓ (en geo_service.py básico)
- Intersección                 ✓ (en geo_service.py básico)
- Unión espacial
- Reclasificación por atributos
- Cálculo de áreas
- Análisis de riesgo (amenaza + vulnerabilidad)
"""
import json
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union


# ─── 1. UNIÓN ESPACIAL (Spatial Join) ────────────────────────────────────────

async def run_spatial_union(
    table_target: str,
    table_source: str,
    join_fields: list[str],
    db: AsyncSession,
) -> dict:
    """
    Unión espacial (spatial join): agrega atributos de la capa fuente
    a cada feature de la capa objetivo basándose en relación espacial.

    Caso real Calarcá:
    - target: veredas (polígonos)
    - source: puntos de infraestructura (acueducto, escuelas)
    - resultado: cada vereda con el conteo de infraestructura dentro
    """
    fields_select = ", ".join([f"s.{f}" for f in join_fields]) if join_fields else "s.*"

    query = f"""
        SELECT
            t.*,
            {fields_select},
            ST_AsGeoJSON(t.geometry)::json AS geometry_json
        FROM {table_target} t
        LEFT JOIN {table_source} s
            ON ST_Within(s.geometry, t.geometry)
           OR ST_Intersects(s.geometry, t.geometry)
    """
    result = await db.execute(text(query))
    rows = result.mappings().all()

    features = []
    for row in rows:
        row_dict = dict(row)
        geom = row_dict.pop('geometry_json', None)
        row_dict.pop('geometry', None)
        if geom:
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {k: v for k, v in row_dict.items() if v is not None},
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "operation": "spatial_join",
            "target": table_target,
            "source": table_source,
            "joined_fields": join_fields,
            "feature_count": len(features),
        },
    }


async def run_count_within(
    table_polygons: str,
    table_points: str,
    db: AsyncSession,
) -> dict:
    """
    Cuenta cuántos puntos hay dentro de cada polígono.
    Caso real: cuántas edificaciones hay en cada predio,
    o cuántas escuelas por vereda.
    """
    query = f"""
        SELECT
            p.*,
            COUNT(pt.geometry) AS punto_count,
            ST_AsGeoJSON(p.geometry)::json AS geom_json
        FROM {table_polygons} p
        LEFT JOIN {table_points} pt
            ON ST_Contains(p.geometry, pt.geometry)
        GROUP BY p.geometry, p.id
    """
    result = await db.execute(text(query))
    rows = result.mappings().all()

    features = []
    for row in rows:
        row_dict = dict(row)
        geom = row_dict.pop('geom_json', None)
        row_dict.pop('geometry', None)
        if geom:
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": row_dict,
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {"operation": "count_within", "feature_count": len(features)},
    }


# ─── 2. RECLASIFICACIÓN POR ATRIBUTOS ────────────────────────────────────────

async def run_reclassify(
    table_name: str,
    attribute: str,
    rules: list[dict],
    output_field: str,
    db: AsyncSession,
) -> dict:
    """
    Reclasifica features según reglas sobre un atributo.

    rules = [
        {"min": 0,    "max": 100,  "label": "Bajo",  "value": 1},
        {"min": 100,  "max": 500,  "label": "Medio", "value": 2},
        {"min": 500,  "max": 99999,"label": "Alto",  "value": 3},
    ]

    Caso real Calarcá:
    - Reclasificar predios por área → pequeño/mediano/grande
    - Reclasificar zonas por nivel de amenaza → 1/2/3/4
    - Reclasificar población por densidad → baja/media/alta
    """
    # Construir CASE WHEN para SQL
    case_parts = []
    for rule in rules:
        if 'min' in rule and 'max' in rule:
            case_parts.append(
                f"WHEN {attribute}::numeric >= {rule['min']} AND {attribute}::numeric < {rule['max']} "
                f"THEN '{rule['label']}'"
            )
        elif 'values' in rule:
            vals = ", ".join([f"'{v}'" for v in rule['values']])
            case_parts.append(f"WHEN {attribute}::text IN ({vals}) THEN '{rule['label']}'")

    case_sql = "CASE\n  " + "\n  ".join(case_parts) + "\n  ELSE 'Sin clasificar'\nEND"

    query = f"""
        SELECT
            *,
            {case_sql} AS {output_field},
            ST_AsGeoJSON(geometry)::json AS geom_json
        FROM {table_name}
    """
    result = await db.execute(text(query))
    rows = result.mappings().all()

    # Contar por clase
    class_counts: dict = {}
    features = []
    for row in rows:
        row_dict = dict(row)
        geom = row_dict.pop('geom_json', None)
        row_dict.pop('geometry', None)
        label = row_dict.get(output_field, 'Sin clasificar')
        class_counts[label] = class_counts.get(label, 0) + 1
        if geom:
            features.append({"type": "Feature", "geometry": geom, "properties": row_dict})

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "operation": "reclassify",
            "attribute": attribute,
            "output_field": output_field,
            "class_counts": class_counts,
            "feature_count": len(features),
        },
    }


# ─── 3. CÁLCULO DE ÁREAS ─────────────────────────────────────────────────────

async def run_area_calculation(
    table_name: str,
    group_by: Optional[str],
    db: AsyncSession,
) -> dict:
    """
    Calcula áreas en metros cuadrados usando la proyección geográfica.
    Opcionalmente agrupa y suma por un atributo.

    Caso real Calarcá:
    - Área total de cada vereda
    - Área de uso del suelo por categoría
    - Área de predios por estrato
    """
    if group_by:
        query = f"""
            SELECT
                {group_by},
                COUNT(*) AS feature_count,
                ROUND(SUM(ST_Area(geometry::geography))::numeric, 2) AS area_m2,
                ROUND(SUM(ST_Area(geometry::geography) / 10000)::numeric, 4) AS area_ha,
                ROUND(SUM(ST_Area(geometry::geography) / 1000000)::numeric, 6) AS area_km2,
                ST_AsGeoJSON(ST_Union(geometry))::json AS geometry
            FROM {table_name}
            GROUP BY {group_by}
            ORDER BY area_m2 DESC
        """
    else:
        query = f"""
            SELECT
                *,
                ROUND(ST_Area(geometry::geography)::numeric, 2) AS area_m2,
                ROUND(ST_Area(geometry::geography)::numeric / 10000, 4) AS area_ha,
                ROUND(ST_Area(geometry::geography)::numeric / 1000000, 6) AS area_km2,
                ST_AsGeoJSON(geometry)::json AS geom_json
            FROM {table_name}
            ORDER BY area_m2 DESC
        """

    result = await db.execute(text(query))
    rows = result.mappings().all()

    total_area_m2 = 0
    features = []
    for row in rows:
        row_dict = dict(row)
        geom = row_dict.pop('geom_json', None) or row_dict.pop('geometry', None)
        row_dict.pop('geometry', None)
        total_area_m2 += float(row_dict.get('area_m2', 0) or 0)
        if isinstance(geom, str):
            geom = json.loads(geom)
        if geom:
            features.append({"type": "Feature", "geometry": geom, "properties": row_dict})

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "operation": "area_calculation",
            "group_by": group_by,
            "total_area_m2": round(total_area_m2, 2),
            "total_area_ha": round(total_area_m2 / 10000, 4),
            "total_area_km2": round(total_area_m2 / 1000000, 6),
            "feature_count": len(features),
        },
    }


# ─── 4. ANÁLISIS DE RIESGO (Amenaza × Vulnerabilidad) ────────────────────────

async def run_risk_analysis(
    table_amenaza: str,
    table_vulnerabilidad: str,
    amenaza_field: str,
    vulnerabilidad_field: str,
    db: AsyncSession,
) -> dict:
    """
    Análisis de riesgo = Amenaza × Vulnerabilidad
    Metodología basada en UNGRD (Unidad Nacional Gestión del Riesgo de Desastres).

    Niveles:
    - Amenaza: 1=Baja, 2=Media, 3=Alta, 4=Muy Alta
    - Vulnerabilidad: 1=Baja, 2=Media, 3=Alta, 4=Muy Alta
    - Riesgo = Amenaza × Vulnerabilidad → 1-16

    Clasificación de riesgo:
    - 1-3:   Riesgo Bajo
    - 4-6:   Riesgo Medio
    - 7-12:  Riesgo Alto
    - 13-16: Riesgo Muy Alto

    Caso real Calarcá:
    - Amenaza: zonas de deslizamiento (mapa geológico)
    - Vulnerabilidad: densidad de construcciones/población
    - Resultado: mapa de riesgo por sectores
    """
    query = f"""
        WITH interseccion AS (
            SELECT
                a.geometry AS geom_a,
                v.geometry AS geom_v,
                a.{amenaza_field}::integer AS nivel_amenaza,
                v.{vulnerabilidad_field}::integer AS nivel_vulnerabilidad,
                ST_Intersection(a.geometry, v.geometry) AS geom_intersect
            FROM {table_amenaza} a
            JOIN {table_vulnerabilidad} v
                ON ST_Intersects(a.geometry, v.geometry)
            WHERE NOT ST_IsEmpty(ST_Intersection(a.geometry, v.geometry))
        )
        SELECT
            nivel_amenaza,
            nivel_vulnerabilidad,
            nivel_amenaza * nivel_vulnerabilidad AS indice_riesgo,
            CASE
                WHEN nivel_amenaza * nivel_vulnerabilidad BETWEEN 1 AND 3  THEN 'Riesgo Bajo'
                WHEN nivel_amenaza * nivel_vulnerabilidad BETWEEN 4 AND 6  THEN 'Riesgo Medio'
                WHEN nivel_amenaza * nivel_vulnerabilidad BETWEEN 7 AND 12 THEN 'Riesgo Alto'
                ELSE 'Riesgo Muy Alto'
            END AS categoria_riesgo,
            ROUND(ST_Area(geom_intersect::geography)::numeric / 10000, 4) AS area_ha,
            ST_AsGeoJSON(geom_intersect)::json AS geometry
        FROM interseccion
        ORDER BY indice_riesgo DESC
    """
    result = await db.execute(text(query))
    rows = result.mappings().all()

    # Resumen estadístico
    summary: dict = {}
    features = []
    for row in rows:
        row_dict = dict(row)
        geom = row_dict.pop('geometry', None)
        categoria = row_dict.get('categoria_riesgo', 'Sin datos')

        if categoria not in summary:
            summary[categoria] = {"count": 0, "area_ha": 0}
        summary[categoria]["count"] += 1
        summary[categoria]["area_ha"] += float(row_dict.get('area_ha', 0) or 0)

        if geom:
            features.append({"type": "Feature", "geometry": geom, "properties": row_dict})

    # Estilo sugerido por categoría
    style_map = {
        "Riesgo Bajo":      "#22c55e",
        "Riesgo Medio":     "#f59e0b",
        "Riesgo Alto":      "#ef4444",
        "Riesgo Muy Alto":  "#7f1d1d",
    }

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "operation": "risk_analysis",
            "methodology": "UNGRD - Amenaza × Vulnerabilidad",
            "table_amenaza": table_amenaza,
            "table_vulnerabilidad": table_vulnerabilidad,
            "summary": summary,
            "style_map": style_map,
            "feature_count": len(features),
        },
    }


# ─── 5. CERCANÍA / ACCESIBILIDAD ─────────────────────────────────────────────

async def run_nearest_facility(
    table_origin: str,
    table_facilities: str,
    max_distance_m: float,
    db: AsyncSession,
) -> dict:
    """
    Para cada punto de origen, encuentra la instalación más cercana
    y la distancia en metros.

    Caso real Calarcá:
    - Origen: predios/viviendas
    - Facilidades: escuelas, hospitales, parques
    - Resultado: distancia de cada vivienda a la escuela más cercana
    Útil para análisis de cobertura de servicios.
    """
    query = f"""
        SELECT
            o.*,
            f_nearest.id AS facility_id,
            f_nearest.distance_m,
            CASE
                WHEN f_nearest.distance_m <= {max_distance_m} THEN 'Con acceso'
                ELSE 'Sin acceso'
            END AS acceso,
            ST_AsGeoJSON(o.geometry)::json AS geometry
        FROM {table_origin} o
        LEFT JOIN LATERAL (
            SELECT
                f.id,
                ROUND(ST_Distance(o.geometry::geography, f.geometry::geography)::numeric, 1) AS distance_m
            FROM {table_facilities} f
            ORDER BY o.geometry::geography <-> f.geometry::geography
            LIMIT 1
        ) f_nearest ON true
    """
    result = await db.execute(text(query))
    rows = result.mappings().all()

    with_access = sum(1 for r in rows if r.get('acceso') == 'Con acceso')
    features = []
    for row in rows:
        row_dict = dict(row)
        geom = row_dict.pop('geometry', None)
        if geom:
            features.append({"type": "Feature", "geometry": geom, "properties": row_dict})

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "operation": "nearest_facility",
            "max_distance_m": max_distance_m,
            "with_access": with_access,
            "without_access": len(features) - with_access,
            "coverage_pct": round(with_access / max(len(features), 1) * 100, 1),
            "feature_count": len(features),
        },
    }
