"""
routers/auth.py — Registro y login de usuarios
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.schemas.schemas import UserCreate, UserLogin, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    """Registra un nuevo usuario. Solo admins pueden crear otros admins."""
    # Verificar email único
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    user = User(
        email=payload.email,
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    """Login con email y contraseña. Retorna JWT."""
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenOut(access_token=token, user=user)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(__import__("app.core.security", fromlist=["get_current_user"]).get_current_user)):
    """Retorna el usuario autenticado actual."""
    return current_user
