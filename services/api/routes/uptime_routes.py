"""
Uptime Routes
==============
Uptime statistics endpoints.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import HealthCheck, Service, User
from auth import get_current_user
from schemas import UptimePeriod, UptimeResponse

router = APIRouter(tags=["Uptime"])


async def _compute_uptime(
    session: AsyncSession,
    service_id: int,
    period_label: str,
    hours: int,
) -> UptimePeriod:
    """Compute uptime % and avg response time for a time window."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    total_q = await session.execute(
        select(func.count(HealthCheck.id)).where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.checked_at >= since,
            )
        )
    )
    total = total_q.scalar() or 0

    up_q = await session.execute(
        select(func.count(HealthCheck.id)).where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.checked_at >= since,
                HealthCheck.status == "UP",
            )
        )
    )
    up = up_q.scalar() or 0

    avg_q = await session.execute(
        select(func.avg(HealthCheck.response_time_ms)).where(
            and_(
                HealthCheck.service_id == service_id,
                HealthCheck.checked_at >= since,
            )
        )
    )
    avg_rt = avg_q.scalar() or 0.0

    uptime_pct = round((up / total) * 100, 2) if total > 0 else 0.0

    return UptimePeriod(
        period=period_label,
        uptime_percent=uptime_pct,
        avg_response_time_ms=round(avg_rt, 2),
        total_checks=total,
    )


@router.get(
    "/services/{service_id}/uptime",
    response_model=UptimeResponse,
)
async def get_uptime(
    service_id: int,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """
    Uptime percentage and average response time for the last 1 h,
    24 h, 7 d, and 30 d.
    """
    result = await session.execute(select(Service).where(Service.id == service_id))
    svc = result.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    periods = [
        ("1h", 1),
        ("24h", 24),
        ("7d", 168),
        ("30d", 720),
    ]
    uptime_data = []
    for label, hours in periods:
        uptime_data.append(await _compute_uptime(session, service_id, label, hours))

    return UptimeResponse(
        service_id=svc.id,
        service_name=svc.name,
        periods=uptime_data,
    )
