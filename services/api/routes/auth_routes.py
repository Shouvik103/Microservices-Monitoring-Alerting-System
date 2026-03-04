"""
Auth Routes
===========
User registration, login, and profile endpoints.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import User
from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from schemas import TokenResponse, UserCreate, UserLogin, UserResponse

logger = logging.getLogger("api")

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
):
    """Register a new user account."""
    existing = await session.execute(select(User).where(User.username == payload.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    logger.info("User registered: %s (role=%s)", user.username, user.role)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: UserLogin,
    session: AsyncSession = Depends(get_session),
):
    """Authenticate and receive a JWT access token."""
    result = await session.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    token = create_access_token({"sub": user.username, "role": user.role})
    return TokenResponse(access_token=token, role=user.role, username=user.username)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's info."""
    return current_user
