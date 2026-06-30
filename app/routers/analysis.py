"""
routers/analysis.py — Endpoints de análisis espacial
Todos requieren rol ADMIN.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import require_admin
from app.models.layer import Layer
from app.models.user import User
from app.schemas.schemas import BufferRequest, IntersectionRequest, DissolveRequest
from app.services.geo_service import run_buffer, run_intersection, run_dissolve

router = APIRouter(prefix="/analysis", tags=["Análisis espacial"])


async def _get_layer_or_404(layer_id: int, db: AsyncSession) -> Layer:
    result = await db.execute(select(Layer).where(Layer.id == layer_id, Layer.is_active == True))
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail=f"Capa {layer_id} no encontrada")
    return layer


@router.post("/buffer")
async def buffer_analysis(
    payload: BufferRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Genera zonas de influencia (buffer) alrededor de las geometrías.

    Ejemplo de uso:
    - Buffer de 500m alrededor de escuelas para calcular área de cobertura
    - Buffer de 200m de ríos para zonas de protección hídrica

    Retorna: GeoJSON con los buffers generados
    """
    layer = await _get_layer_or_404(payload.layer_id, db)

    geojson = await run_buffer(
        table_name=layer.postgis_table,
        distance_meters=payload.distance_meters,
        db=db,
        filter_ids=payload.filter_ids,
    )

    return JSONResponse(content=geojson)


@router.post("/intersection")
async def intersection_analysis(
    payload: IntersectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Intersección espacial entre dos capas.

    Ejemplo de uso:
    - Predios urbanos INTERSECTA zonas de riesgo → predios en riesgo
    - Veredas INTERSECTA cobertura de acueducto → veredas sin servicio

    Retorna: GeoJSON con las geometrías resultantes de la intersección
    """
    layer_a = await _get_layer_or_404(payload.layer_a_id, db)
    layer_b = await _get_layer_or_404(payload.layer_b_id, db)

    geojson = await run_intersection(
        table_a=layer_a.postgis_table,
        table_b=layer_b.postgis_table,
        db=db,
    )
    return JSONResponse(content=geojson)


@router.post("/dissolve")
async def dissolve_analysis(
    payload: DissolveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Disuelve (agrupa y fusiona) geometrías por un atributo común.

    Ejemplo de uso:
    - Disolver veredas por corregimiento → límites de corregimiento
    - Disolver predios por uso de suelo → zonas de uso consolidado

    Retorna: GeoJSON con geometrías disueltas y conteo por grupo
    """
    layer = await _get_layer_or_404(payload.layer_id, db)

    # Verificar que el atributo existe
    if layer.attributes and payload.attribute not in layer.attributes:
        available = list(layer.attributes.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Atributo '{payload.attribute}' no existe. Disponibles: {available}",
        )

    geojson = await run_dissolve(
        table_name=layer.postgis_table,
        attribute=payload.attribute,
        db=db,
    )
    return JSONResponse(content=geojson)


@router.get("/spatial-query/{layer_id}")
async def spatial_query(
    layer_id: int,
    lat: float,
    lon: float,
    radius_m: float = 100,
    db: AsyncSession = Depends(get_db),
):
    """
    Consulta espacial por punto: encuentra features dentro de un radio.
    Útil para el click del usuario en el mapa.
    Acceso público.
    """
    from sqlalchemy import text

    layer = await _get_layer_or_404(layer_id, db)

    query = f"""
        SELECT
            ST_AsGeoJSON(geometry)::json AS geometry,
            to_jsonb(t) - 'geometry' AS properties
        FROM {layer.postgis_table} t
        WHERE ST_DWithin(
            geometry::geography,
            ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)::geography,
            {radius_m}
        )
        LIMIT 20
    """
    result = await db.execute(text(query))
    rows = result.fetchall()

    features = [
        {
            "type": "Feature",
            "geometry": row.geometry,
            "properties": dict(row.properties) if row.properties else {},
        }
        for row in rows
    ]
    return {"type": "FeatureCollection", "features": features, "count": len(features)}
