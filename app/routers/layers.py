"""
routers/layers.py — Gestión de capas geoespaciales

El geovisor es de acceso libre: cualquiera puede consultar, subir y editar capas.
La única restricción es que las capas oficiales del municipio (`protegida=True`)
no se pueden eliminar.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.database import get_db
from app.core.config import get_settings

settings = get_settings()
from app.core.security import get_optional_user
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
    """Lista las capas activas. Abierto a cualquier visitante."""
    stmt = select(Layer).where(Layer.is_active == True, Layer.is_public == True)

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

    return layer


@router.patch("/{layer_id}", response_model=LayerOut)
async def update_layer(
    layer_id: int,
    payload: LayerUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Actualiza nombre, descripción, estilo o visibilidad de una capa.
    Cualquiera puede cambiar la simbología; el nombre de las capas oficiales
    se conserva para que el municipio siga reconociéndolas.
    """
    result = await db.execute(select(Layer).where(Layer.id == layer_id))
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")

    cambios = payload.model_dump(exclude_none=True)
    if layer.protegida:
        cambios.pop("name", None)

    for field, value in cambios.items():
        setattr(layer, field, value)

    await db.commit()
    await db.refresh(layer)
    return layer


@router.delete("/{layer_id}", status_code=204)
async def delete_layer(
    layer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Elimina una capa: borra su tabla en PostGIS y su registro.
    Las capas oficiales del municipio están protegidas y no se pueden eliminar.
    """
    result = await db.execute(select(Layer).where(Layer.id == layer_id))
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")

    if layer.protegida:
        raise HTTPException(
            status_code=403,
            detail=(
                f"«{layer.name}» es una capa oficial del municipio y no se puede eliminar. "
                "Puedes ocultarla en el panel de capas o cambiar su simbología."
            ),
        )

    await delete_layer_table(layer.postgis_table, db)
    await db.execute(delete(Layer).where(Layer.id == layer_id))
    await db.commit()


@router.get("/{layer_id}/export/geojson")
async def export_layer_geojson(
    layer_id: int,
    limit: int = Query(5000, le=50000),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Exporta una capa completa como GeoJSON, para descargar o analizar aparte."""
    result = await db.execute(select(Layer).where(Layer.id == layer_id, Layer.is_active == True))
    layer = result.scalar_one_or_none()

    if not layer:
        raise HTTPException(status_code=404, detail="Capa no encontrada")

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
        "tile_url": f"{settings.public_url}/api/v1/tiles/{layer.postgis_table}/{{z}}/{{x}}/{{y}}",
        "layer_name": layer.name,
        "geometry_type": layer.geometry_type,
        "style": layer.style,
    }
