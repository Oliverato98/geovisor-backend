"""
app/main.py — Punto de entrada del Geovisor Backend
Municipio de Calarcá, Quindío, Colombia
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.core.config import get_settings
from app.core.database import init_db
from app.routers import auth, layers, upload, analysis, tiles

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: inicializar PostGIS y tablas
    await init_db()
    yield
    # Shutdown: cerrar el cliente HTTP del proxy de tiles
    await tiles._cliente.aclose()


app = FastAPI(
    title="Geovisor Calarcá — API",
    description="""
    API REST para el geovisor web del Municipio de Calarcá, Quindío.
    Permite gestión de capas geoespaciales, análisis espacial y exportación de datos.
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middlewares ───────────────────────────────────────────────────────────────

# Comprime JSON y GeoJSON. El umbral alto evita recomprimir los tiles MVT,
# que Martin ya entrega comprimidos: hacerlo solo gastaría CPU (y dinero).
app.add_middleware(GZipMiddleware, minimum_size=5000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(auth.router, prefix="/api/v1")
app.include_router(layers.router, prefix="/api/v1")
app.include_router(upload.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(tiles.router, prefix="/api/v1")


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["Sistema"])
async def health():
    """Estado del servicio y configuración efectiva (sin datos sensibles)."""
    return {
        "status": "ok",
        "service": "Geovisor Calarcá API",
        "version": "1.0.0",
        "public_url": settings.public_url,
        "martin_internal_url": settings.martin_internal_url,
        "allowed_origins": settings.origins_list,
    }


@app.get("/", tags=["Sistema"])
async def root():
    return {
        "message": "Geovisor Calarcá — API activa",
        "docs": "/docs",
        "version": "1.0.0",
    }
