"""
routers/layers.py — Gestión de capas geoespaciales
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.database import get_db
from app.core.security import get_current_user, require_admin, get_optional_user
from app.models.layer import Layer
from app.models.user import User
from app.schemas.schemas import LayerOut, LayerUpdate
from app.services.geo_service import delete_layer_table, get_layer_as_geojson

router = APIRouter(prefix="/layers", tags=["Capas"])


@router.get("/", response_model=list[LayerOut])
async def list_layers(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    format: Optional[str] = Query(None, description="Filtrar por formato: shp, geojson, kml"),
    geom_type: Optional[str] = Query(None, description="Filtrar por tipo: Point, Polygon, LineString"),
):
    """
    Lista capas activas.
    - Visitante/anónimo: solo capas públicas
    - Admin: todas las capas
    """
    stmt = select(Layer).where(Layer.is_active == True)

    if not current_user or current_user.role != "admin":
        stmt = stmt.where(Layer.is_public == True)

    if format:
        stmt = stmt.where(Layer.source_format == format.lower())
    if geom_type:
        stmt = stmt.where(Layer.geometry_type == geom_type)

    stmt = stmt.offset(skip).limit(limit).order_by(Layer.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{layer_id}", response_model=LayerOut)
async def get_layer(
    layer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Obtiene una capa por ID."""
    result = await db.execute(select(Layer).where(Layer.id == layer_id, Layer.is_active == True))
    layer = result.scalar_one_or_none()

    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")
    if not layer.is_public and (not current_user or current_user.role != "admin"):
        raise HTTPException(status_code=403, detail="No tiene acceso a esta capa")

    return layer


@router.patch("/{layer_id}", response_model=LayerOut)
async def update_layer(
    layer_id: int,
    payload: LayerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Actualiza nombre, descripción, estilo o visibilidad de una capa. Solo ADMIN."""
    result = await db.execute(select(Layer).where(Layer.id == layer_id))
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(layer, field, value)

    await db.commit()
    await db.refresh(layer)
    return layer


@router.delete("/{layer_id}", status_code=204)
async def delete_layer(
    layer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Elimina una capa:
    1. Borra la tabla de PostGIS
    2. Elimina el registro de la BD
    Solo ADMIN.
    """
    result = await db.execute(select(Layer).where(Layer.id == layer_id))
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")

    # Eliminar tabla PostGIS
    await delete_layer_table(layer.postgis_table, db)

    # Eliminar registro
    await db.execute(delete(Layer).where(Layer.id == layer_id))
    await db.commit()


@router.get("/{layer_id}/export/geojson")
async def export_layer_geojson(
    layer_id: int,
    limit: int = Query(5000, le=50000),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Exporta una capa completa como GeoJSON.
    Útil para descargar o alimentar análisis externos.
    """
    result = await db.execute(select(Layer).where(Layer.id == layer_id, Layer.is_active == True))
    layer = result.scalar_one_or_none()

    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")
    if not layer.is_public and (not current_user or current_user.role != "admin"):
        raise HTTPException(status_code=403, detail="Sin acceso")

    geojson = await get_layer_as_geojson(layer.postgis_table, db, limit=limit)
    return JSONResponse(
        content=geojson,
        headers={"Content-Disposition": f'attachment; filename="{layer.name}.geojson"'},
    )


@router.get("/{layer_id}/tile-url")
async def get_tile_url(layer_id: int, db: AsyncSession = Depends(get_db)):
    """
    Retorna la URL del tile server (Martin) para esta capa.
    El frontend la usa directamente en MapLibre.
    """
    result = await db.execute(select(Layer).where(Layer.id == layer_id))
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")

    return {
        "tile_url": f"http://localhost:8000/api/v1/tiles/{layer.postgis_table}/{{z}}/{{x}}/{{y}}",
        "layer_name": layer.name,
        "geometry_type": layer.geometry_type,
        "style": layer.style,
    }
