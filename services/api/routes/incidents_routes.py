"""
Incidents Routes
=================
Endpoints for listing incidents (outage tracking).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Incident, Service, User
from auth import get_current_user
from schemas import IncidentResponse

router = APIRouter(tags=["Incidents"])


@router.get("/incidents", response_model=list[IncidentResponse])
async def list_incidents(
    status: Optional[str] = Query(default=None, description="Filter: ongoing or resolved"),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Return recent incidents, optionally filtered by status."""
    query = select(Incident).order_by(Incident.started_at.desc()).limit(limit)
    if status:
        query = query.where(Incident.status == status)
    result = await session.execute(query)
    incidents = result.scalars().all()

    # Enrich with service names
    out = []
    for inc in incidents:
        svc_q = await session.execute(select(Service.name).where(Service.id == inc.service_id))
        svc_name = svc_q.scalar_one_or_none() or "Unknown"
        out.append(IncidentResponse(
            id=inc.id,
            service_id=inc.service_id,
            service_name=svc_name,
            started_at=inc.started_at,
            resolved_at=inc.resolved_at,
            duration_s=inc.duration_s,
            status=inc.status,
        ))
    return out


@router.get(
    "/services/{service_id}/incidents",
    response_model=list[IncidentResponse],
)
async def get_service_incidents(
    service_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Return incidents for a specific service."""
    svc_q = await session.execute(select(Service).where(Service.id == service_id))
    svc = svc_q.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    result = await session.execute(
        select(Incident)
        .where(Incident.service_id == service_id)
        .order_by(Incident.started_at.desc())
        .limit(limit)
    )
    incidents = result.scalars().all()
    return [
        IncidentResponse(
            id=inc.id,
            service_id=inc.service_id,
            service_name=svc.name,
            started_at=inc.started_at,
            resolved_at=inc.resolved_at,
            duration_s=inc.duration_s,
            status=inc.status,
        )
        for inc in incidents
    ]
