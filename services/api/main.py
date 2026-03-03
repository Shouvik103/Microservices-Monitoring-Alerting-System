"""
API Service
===========
FastAPI application exposing REST endpoints for the monitoring system.
"""

import csv
import io
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Alert, HealthCheck, Service
from schemas import (
    AlertResponse,
    DashboardService,
    HealthCheckResponse,
    ServiceCreate,
    ServiceResponse,
    UptimePeriod,
    UptimeResponse,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Microservices Monitor API",
    description="REST API for monitoring microservice health, uptime, and alerts.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ====================================================================
# ENDPOINTS
# ====================================================================

# ------------------------------------------------------------------
# Services
# ------------------------------------------------------------------

@app.get("/services", response_model=list[ServiceResponse], tags=["Services"])
async def list_services(
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
    session: AsyncSession = Depends(get_session),
):
    """List all registered services. Optionally filter by tag."""
    query = select(Service).order_by(Service.created_at.desc())
    if tag:
        query = query.where(Service.tags.any(tag))
    result = await session.execute(query)
    services = result.scalars().all()
    return services


@app.post("/services", response_model=ServiceResponse, status_code=201, tags=["Services"])
async def create_service(
    payload: ServiceCreate,
    session: AsyncSession = Depends(get_session),
):
    """Register a new service for monitoring."""
    svc = Service(
        name=payload.name,
        url=payload.url,
        check_interval=payload.check_interval,
        tags=payload.tags,
        custom_headers=payload.custom_headers,
    )
    session.add(svc)
    await session.commit()
    await session.refresh(svc)
    logger.info("Service registered: %s (%s)", svc.name, svc.url)
    return svc


@app.delete("/services/{service_id}", response_model=ServiceResponse, tags=["Services"])
async def deactivate_service(
    service_id: int,
    session: AsyncSession = Depends(get_session),
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


@app.put("/services/{service_id}/pause", response_model=ServiceResponse, tags=["Services"])
async def pause_service(
    service_id: int,
    session: AsyncSession = Depends(get_session),
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


@app.put("/services/{service_id}/resume", response_model=ServiceResponse, tags=["Services"])
async def resume_service(
    service_id: int,
    session: AsyncSession = Depends(get_session),
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


# ------------------------------------------------------------------
# Health Checks
# ------------------------------------------------------------------

@app.get(
    "/services/{service_id}/health",
    response_model=list[HealthCheckResponse],
    tags=["Health"],
)
async def get_health_checks(
    service_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    hours: int = Query(default=24, ge=1, le=720),
    session: AsyncSession = Depends(get_session),
):
    """Return recent health-check results for a service."""
    # Verify service exists
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


@app.get(
    "/services/{service_id}/export",
    tags=["Health"],
    summary="Export health-check history as CSV or JSON",
)
async def export_health_checks(
    service_id: int,
    format: str = Query(default="csv", description="Export format: csv or json"),
    hours: int = Query(default=24, ge=1, le=8760),
    session: AsyncSession = Depends(get_session),
):
    """Download health-check history for a service."""
    # Verify service exists
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


# ------------------------------------------------------------------
# Uptime
# ------------------------------------------------------------------

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


@app.get(
    "/services/{service_id}/uptime",
    response_model=UptimeResponse,
    tags=["Uptime"],
)
async def get_uptime(
    service_id: int,
    session: AsyncSession = Depends(get_session),
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


# ------------------------------------------------------------------
# Alerts
# ------------------------------------------------------------------

@app.get("/alerts", response_model=list[AlertResponse], tags=["Alerts"])
async def get_alerts(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """Return most recent alerts."""
    result = await session.execute(
        select(Alert).order_by(Alert.sent_at.desc()).limit(limit)
    )
    return result.scalars().all()


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

@app.get("/dashboard", response_model=list[DashboardService], tags=["Dashboard"])
async def get_dashboard(
    tag: Optional[str] = Query(default=None, description="Filter by tag"),
    session: AsyncSession = Depends(get_session),
):
    """
    Summary of every active service: current status, 24 h uptime,
    average response time, and last checked timestamp.
    Optionally filter by tag.
    """
    query = select(Service).where(Service.is_active.is_(True)).order_by(Service.name)
    if tag:
        query = query.where(Service.tags.any(tag))
    svc_result = await session.execute(query)
    services = svc_result.scalars().all()

    dashboard = []
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    for svc in services:
        # Last health check
        last_hc_q = await session.execute(
            select(HealthCheck)
            .where(HealthCheck.service_id == svc.id)
            .order_by(HealthCheck.checked_at.desc())
            .limit(1)
        )
        last_hc = last_hc_q.scalar_one_or_none()

        # 24 h stats
        total_q = await session.execute(
            select(func.count(HealthCheck.id)).where(
                and_(
                    HealthCheck.service_id == svc.id,
                    HealthCheck.checked_at >= since_24h,
                )
            )
        )
        total = total_q.scalar() or 0

        up_q = await session.execute(
            select(func.count(HealthCheck.id)).where(
                and_(
                    HealthCheck.service_id == svc.id,
                    HealthCheck.checked_at >= since_24h,
                    HealthCheck.status == "UP",
                )
            )
        )
        up = up_q.scalar() or 0

        avg_q = await session.execute(
            select(func.avg(HealthCheck.response_time_ms)).where(
                and_(
                    HealthCheck.service_id == svc.id,
                    HealthCheck.checked_at >= since_24h,
                )
            )
        )
        avg_rt = avg_q.scalar() or 0.0

        uptime_24h = round((up / total) * 100, 2) if total > 0 else 0.0

        dashboard.append(
            DashboardService(
                service_id=svc.id,
                service_name=svc.name,
                url=svc.url,
                tags=svc.tags or [],
                current_status=last_hc.status if last_hc else None,
                uptime_24h=uptime_24h,
                avg_response_time=round(avg_rt, 2),
                last_checked=last_hc.checked_at if last_hc else None,
            )
        )

    return dashboard


# ------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
