"""
routers/tiles.py — Proxy de tiles desde Martin con CORS habilitado.
Esto resuelve el problema de CORS al servir los tiles a través del backend.
"""
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.config import get_settings

settings = get_settings()

router = APIRouter(prefix="/tiles", tags=["Tiles"])

# URL interna de Martin. Se configura con MARTIN_INTERNAL_URL:
#   Railway -> http://martin.railway.internal:3000
#   Docker local -> http://martin:3000
MARTIN_INTERNAL_URL = settings.martin_internal_url.rstrip("/")

# Cliente HTTP reutilizado: abrir uno nuevo por tile satura el contenedor
# cuando MapLibre pide decenas de tiles al mismo tiempo.
_cliente = httpx.AsyncClient(timeout=30.0)


@router.get("/{table_name}/{z}/{x}/{y}")
async def get_tile(table_name: str, z: int, x: int, y: int):
    """
    Proxy a Martin tile server. Devuelve el tile MVT con CORS correcto.
    """
    url = f"{MARTIN_INTERNAL_URL}/{table_name}/{z}/{x}/{y}"

    try:
        response = await _cliente.get(url)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Error conectando a Martin: {e}")

    # 204 = tile sin geometrías; 404 = Martin aún no registra la tabla.
    # En ambos casos se responde vacío para no llenar la consola de MapLibre
    # de errores rojos en zonas donde la capa simplemente no tiene datos.
    if response.status_code in (204, 404):
        return Response(status_code=204)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Error de Martin: {response.text}",
        )

    return Response(
        content=response.content,
        media_type="application/x-protobuf",
        headers={
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/_debug/catalogo", tags=["Tiles"])
async def catalogo_martin():
    """
    Diagnóstico: lista las tablas que Martin está publicando.
    Sirve para confirmar desde producción que Martin ve las 21 capas.
    """
    try:
        response = await _cliente.get(f"{MARTIN_INTERNAL_URL}/catalog")
        return {
            "martin_url": MARTIN_INTERNAL_URL,
            "status": response.status_code,
            "catalogo": response.json() if response.status_code == 200 else response.text,
        }
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=f"No hay conexión con Martin en {MARTIN_INTERNAL_URL}: {e}",
        )
