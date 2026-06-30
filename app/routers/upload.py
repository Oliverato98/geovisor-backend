"""
routers/upload.py — Subida de archivos geoespaciales
Acepta: .zip (shapefile), .geojson, .kml, .kmz
Solo ADMIN puede subir capas.
"""
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import require_admin
from app.core.config import get_settings
from app.models.user import User
from app.models.layer import Layer
from app.schemas.schemas import LayerOut
from app.services.geo_service import (
    process_shapefile,
    process_shapefile_zip_multi,
    process_geojson,
    process_kml_kmz,
    GeoProcessingError,
)

router = APIRouter(prefix="/upload", tags=["Subida de capas"])
settings = get_settings()

ALLOWED_EXTENSIONS = {".zip", ".geojson", ".kml", ".kmz", ".json"}
MAX_BYTES = settings.max_file_size_mb * 1024 * 1024


async def _save_upload(upload: UploadFile) -> str:
    """Guarda el archivo en disco y retorna la ruta."""
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(upload.filename).suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = upload_dir / unique_name

    content = await upload.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo demasiado grande. Máximo {settings.max_file_size_mb} MB",
        )

    with open(dest, "wb") as f:
        f.write(content)

    return str(dest)


@router.post("/shapefile", status_code=201)
async def upload_shapefile(
    file: UploadFile = File(..., description="ZIP con uno o más shapefiles"),
    name: str = Form(..., description="Nombre base de la capa"),
    description: str = Form("", description="Descripción opcional"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """
    Sube un ZIP con uno o múltiples shapefiles.

    - Si el ZIP tiene 1 shapefile: usa el nombre proporcionado
    - Si el ZIP tiene varios: cada uno se crea como capa separada usando
      su nombre original. El campo "name" se ignora en ese caso.

    Retorna lista de capas creadas.
    """
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos .zip")

    file_path = await _save_upload(file)

    try:
        result = await process_shapefile_zip_multi(file_path, name, db)
    except GeoProcessingError as e:
        os.remove(file_path)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Error procesando ZIP: {str(e)}")

    created_layers = []
    for geo_meta in result["layers"]:
        layer_name = geo_meta.pop("original_filename", name)
        layer = Layer(
            name=layer_name,
            description=description or None,
            original_file_path=file_path,
            owner_id=current_user.id,
            **geo_meta,
        )
        db.add(layer)
        await db.commit()
        await db.refresh(layer)
        created_layers.append({
            "id": layer.id,
            "name": layer.name,
            "geometry_type": layer.geometry_type,
            "feature_count": layer.feature_count,
            "postgis_table": layer.postgis_table,
        })

    return {
        "created_count": len(created_layers),
        "error_count": len(result["errors"]),
        "layers": created_layers,
        "errors": result["errors"],
    }


@router.post("/geojson", response_model=LayerOut, status_code=201)
async def upload_geojson(
    file: UploadFile = File(..., description="Archivo GeoJSON o JSON"),
    name: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sube un archivo GeoJSON."""
    ext = Path(file.filename).suffix.lower()
    if ext not in {".geojson", ".json"}:
        raise HTTPException(status_code=400, detail="Extensión no válida. Use .geojson o .json")

    file_path = await _save_upload(file)

    try:
        geo_meta = await process_geojson(file_path, name, db)
    except GeoProcessingError as e:
        os.remove(file_path)
        raise HTTPException(status_code=422, detail=str(e))

    layer = Layer(
        name=name,
        description=description or None,
        original_file_path=file_path,
        owner_id=current_user.id,
        **geo_meta,
    )
    db.add(layer)
    await db.commit()
    await db.refresh(layer)
    return layer


@router.post("/kml", response_model=LayerOut, status_code=201)
async def upload_kml_kmz(
    file: UploadFile = File(..., description="Archivo KML o KMZ"),
    name: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sube un archivo KML o KMZ (Google Earth)."""
    ext = Path(file.filename).suffix.lower()
    if ext not in {".kml", ".kmz"}:
        raise HTTPException(status_code=400, detail="Solo se aceptan .kml o .kmz")

    file_path = await _save_upload(file)

    try:
        geo_meta = await process_kml_kmz(file_path, name, db)
    except GeoProcessingError as e:
        os.remove(file_path)
        raise HTTPException(status_code=422, detail=str(e))

    layer = Layer(
        name=name,
        description=description or None,
        original_file_path=file_path,
        owner_id=current_user.id,
        **geo_meta,
    )
    db.add(layer)
    await db.commit()
    await db.refresh(layer)
    return layer
