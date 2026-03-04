"""
Health Check Routes
====================
Endpoints for querying and exporting health-check history.
"""

import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import HealthCheck, Service, User
from auth import get_current_user
from schemas import HealthCheckResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/services/{service_id}/health",
    response_model=list[HealthCheckResponse],
)
async def get_health_checks(
    service_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Return recent health-check results for a service."""
    svc_result = await session.execute(select(Service).where(Service.id == service_id))
    if not svc_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Service not found")

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(HealthCheck)
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.checked_at >= since,
            )
        )
        .order_by(HealthCheck.checked_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get(
    "/services/{service_id}/export",
    summary="Export health-check history as CSV or JSON",
)
async def export_health_checks(
    service_id: int,
    format: str = Query(default="csv", description="Export format: csv or json"),
    hours: int = Query(default=24, ge=1, le=8760),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """Download health-check history for a service."""
    svc_result = await session.execute(select(Service).where(Service.id == service_id))
    svc = svc_result.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await session.execute(
        select(HealthCheck)
        .where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.checked_at >= since,
            )
        )
        .order_by(HealthCheck.checked_at.desc())
    )
    checks = result.scalars().all()

    if format.lower() == "json":
        return [
            {
                "service_name": svc.name,
                "status": c.status,
                "response_time_ms": c.response_time_ms,
                "status_code": c.status_code,
                "error_message": c.error_message,
                "checked_at": c.checked_at.isoformat(),
            }
            for c in checks
        ]

    # CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "service_name", "status", "response_time_ms",
        "status_code", "error_message", "checked_at",
    ])
    for c in checks:
        writer.writerow([
            svc.name,
            c.status,
            c.response_time_ms,
            c.status_code,
            c.error_message or "",
            c.checked_at.isoformat(),
        ])
    output.seek(0)

    filename = f"{svc.name.replace(' ', '_')}_health_{hours}h.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
