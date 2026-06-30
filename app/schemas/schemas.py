"""
schemas/auth.py — Esquemas de autenticación
schemas/layer.py — Esquemas de capas
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator


# ── Auth ──────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    username: str
    password: str
    role: str = "visitante"

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v):
        if v not in ("admin", "visitante"):
            raise ValueError("Rol debe ser 'admin' o 'visitante'")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v):
        if len(v) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Layers ────────────────────────────────────────────────────────────────────

class LayerOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    source_format: str
    geometry_type: Optional[str]
    crs_original: Optional[str]
    feature_count: int
    bbox_minx: Optional[float]
    bbox_miny: Optional[float]
    bbox_maxx: Optional[float]
    bbox_maxy: Optional[float]
    postgis_table: str
    style: Optional[dict]
    attributes: Optional[dict]
    is_public: bool
    is_active: bool
    owner_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class LayerUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    style: Optional[dict] = None
    is_public: Optional[bool] = None


# ── Análisis ──────────────────────────────────────────────────────────────────

class BufferRequest(BaseModel):
    layer_id: int
    distance_meters: float
    filter_ids: Optional[list[int]] = None

    @field_validator("distance_meters")
    @classmethod
    def distance_positive(cls, v):
        if v <= 0:
            raise ValueError("La distancia debe ser positiva")
        if v > 50000:
            raise ValueError("La distancia máxima es 50 km")
        return v


class IntersectionRequest(BaseModel):
    layer_a_id: int
    layer_b_id: int


class DissolveRequest(BaseModel):
    layer_id: int
    attribute: str
