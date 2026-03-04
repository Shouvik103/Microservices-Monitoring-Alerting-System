"""
Services Routes
================
CRUD endpoints for managing monitored services.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Service, User
from auth import get_current_user, require_role
from schemas import ServiceCreate, ServiceResponse

logger = logging.getLogger("api")

router = APIRouter(tags=["Services"])


@router.get("/services", response_model=list[ServiceResponse])
async def list_services(
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """List all registered services. Optionally filter by tag."""
    query = select(Service).order_by(Service.created_at.desc())
    if tag:
        query = query.where(Service.tags.any(tag))
    result = await session.execute(query)
    services = result.scalars().all()
    return services


@router.post("/services", response_model=ServiceResponse, status_code=201)
async def create_service(
    payload: ServiceCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_role("admin", "editor")),
):
    """Register a new service for monitoring."""
    svc = Service(
        name=payload.name,
        url=payload.url,
        check_interval=payload.check_interval,
        tags=payload.tags,
        custom_headers=payload.custom_headers,
        check_method=payload.check_method,
        check_body=payload.check_body,
    )
    session.add(svc)
    await session.commit()
    await session.refresh(svc)
    logger.info("Service registered: %s (%s)", svc.name, svc.url)
    return svc


@router.delete("/services/{service_id}", response_model=ServiceResponse)
async def deactivate_service(
    service_id: int,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_role("admin")),
):
    """Deactivate a service (soft delete)."""
    result = await session.execute(select(Service).where(Service.id == service_id))
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    svc.is_active = False
    await session.commit()
    await session.refresh(svc)
    logger.info("Service deactivated: %s", svc.name)
    return svc


@router.put("/services/{service_id}/pause", response_model=ServiceResponse)
async def pause_service(
    service_id: int,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_role("admin", "editor")),
):
    """Pause monitoring for a service (sets is_active=False)."""
    result = await session.execute(select(Service).where(Service.id == service_id))
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if not svc.is_active:
        raise HTTPException(status_code=400, detail="Service is already paused")
    svc.is_active = False
    await session.commit()
    await session.refresh(svc)
    logger.info("Service paused: %s", svc.name)
    return svc


@router.put("/services/{service_id}/resume", response_model=ServiceResponse)
async def resume_service(
    service_id: int,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_role("admin", "editor")),
):
    """Resume monitoring for a previously paused service."""
    result = await session.execute(select(Service).where(Service.id == service_id))
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if svc.is_active:
        raise HTTPException(status_code=400, detail="Service is already active")
    svc.is_active = True
    await session.commit()
    await session.refresh(svc)
    logger.info("Service resumed: %s", svc.name)
    return svc
