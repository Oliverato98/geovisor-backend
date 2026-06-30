"""
routers/tiles.py — Proxy de tiles desde Martin con CORS habilitado.
Esto resuelve el problema de CORS al servir los tiles a través del backend.
"""
import os
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(prefix="/tiles", tags=["Tiles"])

# En Railway el host interno se arma con MARTIN_HOST inyectado vía variable de entorno.
# En Docker local, el nombre del servicio es "martin" en el puerto 3000.
MARTIN_INTERNAL_URL = os.getenv("MARTIN_INTERNAL_URL", "http://martin:3000")


@router.get("/{table_name}/{z}/{x}/{y}")
async def get_tile(table_name: str, z: int, x: int, y: int):
    """
    Proxy a Martin tile server. Devuelve el tile MVT con CORS correcto.
    """
    url = f"{MARTIN_INTERNAL_URL}/{table_name}/{z}/{x}/{y}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Error conectando a Martin: {e}")

    if response.status_code == 204:
        # Tile vacío - devolver 204 sin contenido
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
