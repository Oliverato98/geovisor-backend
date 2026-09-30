"""
models/layer.py — Modelo de capa geoespacial
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Layer(Base):
    __tablename__ = "layers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Metadatos geoespaciales
    source_format: Mapped[str] = mapped_column(String(20))     # shp, geojson, kml, kmz
    geometry_type: Mapped[Optional[str]] = mapped_column(String(50))  # Point, Polygon, etc.
    # El WKT completo de un CRS pasa de 400 caracteres: va como texto libre.
    crs_original: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)

    # Extensión geográfica (bounding box)
    bbox_minx: Mapped[Optional[float]] = mapped_column()
    bbox_miny: Mapped[Optional[float]] = mapped_column()
    bbox_maxx: Mapped[Optional[float]] = mapped_column()
    bbox_maxy: Mapped[Optional[float]] = mapped_column()

    # Tabla en PostGIS donde viven las geometrías
    postgis_table: Mapped[str] = mapped_column(String(100), unique=True)

    # Archivo original guardado
    original_file_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Simbología (JSON con estilo MapLibre)
    style: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Atributos disponibles en la tabla (schema de columnas)
    attributes: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Capas oficiales del municipio: cualquiera las ve y las usa, nadie las borra.
    # Las que suban los visitantes nacen sin protección y sí se pueden eliminar.
    protegida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # El geovisor es de acceso libre: una capa puede no tener dueño.
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    owner: Mapped[Optional["User"]] = relationship("User", back_populates="layers")
