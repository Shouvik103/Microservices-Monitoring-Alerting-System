"""
API Service
===========
FastAPI application exposing REST endpoints for the monitoring system.
"""

import asyncio
import csv
import io
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

from database import get_session, async_session
from models import Alert, AlertRule, HealthCheck, Incident, Service, User
from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from schemas import (
    AlertResponse,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRuleUpdate,
    DashboardService,
    HealthCheckResponse,
    IncidentResponse,
    ServiceCreate,
    ServiceResponse,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
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

# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------
PROMETHEUS_REGISTRY = CollectorRegistry()

SERVICES_TOTAL = Gauge(
    "monitor_services_total",
    "Total number of registered services",
    registry=PROMETHEUS_REGISTRY,
)
SERVICES_UP = Gauge(
    "monitor_services_up",
    "Number of services currently UP",
    registry=PROMETHEUS_REGISTRY,
)
SERVICES_DOWN = Gauge(
    "monitor_services_down",
    "Number of services currently DOWN",
    registry=PROMETHEUS_REGISTRY,
)
HEALTH_CHECKS_TOTAL = Counter(
    "monitor_health_checks_total",
    "Total health checks recorded",
    ["status"],
    registry=PROMETHEUS_REGISTRY,
)
RESPONSE_TIME_HISTOGRAM = Histogram(
    "monitor_response_time_ms",
    "Response time of health checks in milliseconds",
    ["service_name"],
    buckets=[10, 25, 50, 100, 250, 500, 1000, 2000, 5000, 10000],
    registry=PROMETHEUS_REGISTRY,
)
ALERTS_TOTAL = Counter(
    "monitor_alerts_total",
    "Total alerts fired",
    ["alert_type"],
    registry=PROMETHEUS_REGISTRY,
)
INCIDENTS_ONGOING = Gauge(
    "monitor_incidents_ongoing",
    "Number of currently ongoing incidents",
    registry=PROMETHEUS_REGISTRY,
)
UPTIME_GAUGE = Gauge(
    "monitor_uptime_24h_percent",
    "24h uptime percentage per service",
    ["service_name"],
    registry=PROMETHEUS_REGISTRY,
)


# ====================================================================
# ENDPOINTS
# ====================================================================

# ------------------------------------------------------------------
# Authentication  (public — no JWT required)
# ------------------------------------------------------------------

@app.post("/auth/register", response_model=UserResponse, status_code=201, tags=["Auth"])
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


@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
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


@app.get("/auth/me", response_model=UserResponse, tags=["Auth"])
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's info."""
    return current_user

# ------------------------------------------------------------------
# Services
# ------------------------------------------------------------------

@app.get("/services", response_model=list[ServiceResponse], tags=["Services"])
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


@app.post("/services", response_model=ServiceResponse, status_code=201, tags=["Services"])
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


@app.delete("/services/{service_id}", response_model=ServiceResponse, tags=["Services"])
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


@app.put("/services/{service_id}/pause", response_model=ServiceResponse, tags=["Services"])
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


@app.put("/services/{service_id}/resume", response_model=ServiceResponse, tags=["Services"])
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
    _user: User = Depends(get_current_user),
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
    _user: User = Depends(get_current_user),
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


# ------------------------------------------------------------------
# Alerts
# ------------------------------------------------------------------

@app.get("/alerts", response_model=list[AlertResponse], tags=["Alerts"])
async def get_alerts(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
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
    _user: User = Depends(get_current_user),
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
                check_method=svc.check_method or "GET",
                current_status=last_hc.status if last_hc else None,
                uptime_24h=uptime_24h,
                avg_response_time=round(avg_rt, 2),
                last_checked=last_hc.checked_at if last_hc else None,
            )
        )

    return dashboard


# ------------------------------------------------------------------
# WebSocket — live dashboard push
# ------------------------------------------------------------------

connected_clients: set[WebSocket] = set()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(connected_clients))
    try:
        while True:
            # Keep the connection alive; client can send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        connected_clients.discard(ws)
        logger.info("WebSocket client disconnected (%d total)", len(connected_clients))


async def _build_dashboard_payload():
    """Build the dashboard JSON payload for WebSocket broadcast."""
    async with async_session() as session:
        svc_result = await session.execute(
            select(Service).where(Service.is_active.is_(True)).order_by(Service.name)
        )
        services = svc_result.scalars().all()
        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        dashboard = []

        for svc in services:
            last_hc_q = await session.execute(
                select(HealthCheck)
                .where(HealthCheck.service_id == svc.id)
                .order_by(HealthCheck.checked_at.desc())
                .limit(1)
            )
            last_hc = last_hc_q.scalar_one_or_none()

            total_q = await session.execute(
                select(func.count(HealthCheck.id)).where(
                    and_(HealthCheck.service_id == svc.id, HealthCheck.checked_at >= since_24h)
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
                    and_(HealthCheck.service_id == svc.id, HealthCheck.checked_at >= since_24h)
                )
            )
            avg_rt = avg_q.scalar() or 0.0
            uptime_24h = round((up / total) * 100, 2) if total > 0 else 0.0

            dashboard.append({
                "service_id": svc.id,
                "service_name": svc.name,
                "url": svc.url,
                "tags": svc.tags or [],
                "check_method": svc.check_method or "GET",
                "current_status": last_hc.status if last_hc else None,
                "uptime_24h": uptime_24h,
                "avg_response_time": round(avg_rt, 2),
                "last_checked": last_hc.checked_at.isoformat() if last_hc else None,
            })

        return dashboard


async def broadcast_loop():
    """Background task: push dashboard data to all WebSocket clients every 5 s."""
    while True:
        await asyncio.sleep(5)
        if not connected_clients:
            continue
        try:
            payload = await _build_dashboard_payload()
            message = json.dumps({"type": "dashboard", "data": payload})
            dead = set()
            for ws in connected_clients:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.add(ws)
            connected_clients.difference_update(dead)
        except Exception as exc:
            logger.error("WebSocket broadcast error: %s", exc)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_loop())
    logger.info("WebSocket broadcast loop started")


# ------------------------------------------------------------------
# Incidents
# ------------------------------------------------------------------

@app.get("/incidents", response_model=list[IncidentResponse], tags=["Incidents"])
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


@app.get(
    "/services/{service_id}/incidents",
    response_model=list[IncidentResponse],
    tags=["Incidents"],
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


# ------------------------------------------------------------------
# Custom Alert Rules
# ------------------------------------------------------------------

@app.get("/alert-rules", response_model=list[AlertRuleResponse], tags=["Alert Rules"])
async def list_alert_rules(
    service_id: Optional[int] = Query(default=None, description="Filter by service"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
):
    """List all custom alert rules. Optionally filter by service_id."""
    query = select(AlertRule).order_by(AlertRule.created_at.desc())
    if service_id is not None:
        query = query.where(AlertRule.service_id == service_id)
    result = await session.execute(query)
    rules = result.scalars().all()

    out = []
    for rule in rules:
        svc_q = await session.execute(select(Service.name).where(Service.id == rule.service_id))
        svc_name = svc_q.scalar_one_or_none() or "Unknown"
        out.append(AlertRuleResponse(
            id=rule.id,
            service_id=rule.service_id,
            service_name=svc_name,
            metric=rule.metric,
            operator=rule.operator,
            threshold=rule.threshold,
            severity=rule.severity,
            is_active=rule.is_active,
            cooldown_s=rule.cooldown_s,
            description=rule.description,
            created_at=rule.created_at,
        ))
    return out


@app.post("/alert-rules", response_model=AlertRuleResponse, status_code=201, tags=["Alert Rules"])
async def create_alert_rule(
    payload: AlertRuleCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_role("admin", "editor")),
):
    """Create a custom per-service alert rule."""
    # Verify service exists
    svc_q = await session.execute(select(Service).where(Service.id == payload.service_id))
    svc = svc_q.scalar_one_or_none()
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    rule = AlertRule(
        service_id=payload.service_id,
        metric=payload.metric,
        operator=payload.operator,
        threshold=payload.threshold,
        severity=payload.severity,
        is_active=payload.is_active,
        cooldown_s=payload.cooldown_s,
        description=payload.description,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    logger.info("Alert rule created: id=%s service=%s %s %s %s",
                rule.id, svc.name, rule.metric, rule.operator, rule.threshold)
    return AlertRuleResponse(
        id=rule.id,
        service_id=rule.service_id,
        service_name=svc.name,
        metric=rule.metric,
        operator=rule.operator,
        threshold=rule.threshold,
        severity=rule.severity,
        is_active=rule.is_active,
        cooldown_s=rule.cooldown_s,
        description=rule.description,
        created_at=rule.created_at,
    )


@app.put("/alert-rules/{rule_id}", response_model=AlertRuleResponse, tags=["Alert Rules"])
async def update_alert_rule(
    rule_id: int,
    payload: AlertRuleUpdate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_role("admin", "editor")),
):
    """Update an existing alert rule."""
    result = await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rule, field, value)

    await session.commit()
    await session.refresh(rule)

    svc_q = await session.execute(select(Service.name).where(Service.id == rule.service_id))
    svc_name = svc_q.scalar_one_or_none() or "Unknown"

    logger.info("Alert rule updated: id=%s", rule.id)
    return AlertRuleResponse(
        id=rule.id,
        service_id=rule.service_id,
        service_name=svc_name,
        metric=rule.metric,
        operator=rule.operator,
        threshold=rule.threshold,
        severity=rule.severity,
        is_active=rule.is_active,
        cooldown_s=rule.cooldown_s,
        description=rule.description,
        created_at=rule.created_at,
    )


@app.delete("/alert-rules/{rule_id}", tags=["Alert Rules"])
async def delete_alert_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_role("admin")),
):
    """Delete a custom alert rule."""
    result = await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    await session.delete(rule)
    await session.commit()
    logger.info("Alert rule deleted: id=%s", rule_id)
    return {"detail": "Alert rule deleted"}


# ------------------------------------------------------------------
# Prometheus /metrics
# ------------------------------------------------------------------

async def _refresh_prometheus_metrics():
    """Scrape DB and update all Prometheus gauges/counters."""
    async with async_session() as session:
        # Total services
        total_q = await session.execute(
            select(func.count(Service.id)).where(Service.is_active.is_(True))
        )
        total_services = total_q.scalar() or 0
        SERVICES_TOTAL.set(total_services)

        # Current UP / DOWN counts from last health check per service
        svc_result = await session.execute(
            select(Service).where(Service.is_active.is_(True))
        )
        services = svc_result.scalars().all()
        up_count = 0
        down_count = 0
        since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

        for svc in services:
            last_hc_q = await session.execute(
                select(HealthCheck)
                .where(HealthCheck.service_id == svc.id)
                .order_by(HealthCheck.checked_at.desc())
                .limit(1)
            )
            last_hc = last_hc_q.scalar_one_or_none()
            if last_hc:
                if last_hc.status == "UP":
                    up_count += 1
                else:
                    down_count += 1
                if last_hc.response_time_ms is not None:
                    RESPONSE_TIME_HISTOGRAM.labels(service_name=svc.name).observe(
                        last_hc.response_time_ms
                    )

            # 24h uptime per service
            total_c = await session.execute(
                select(func.count(HealthCheck.id)).where(
                    and_(HealthCheck.service_id == svc.id, HealthCheck.checked_at >= since_24h)
                )
            )
            up_c = await session.execute(
                select(func.count(HealthCheck.id)).where(
                    and_(
                        HealthCheck.service_id == svc.id,
                        HealthCheck.checked_at >= since_24h,
                        HealthCheck.status == "UP",
                    )
                )
            )
            t = total_c.scalar() or 0
            u = up_c.scalar() or 0
            pct = round((u / t) * 100, 2) if t > 0 else 0.0
            UPTIME_GAUGE.labels(service_name=svc.name).set(pct)

        SERVICES_UP.set(up_count)
        SERVICES_DOWN.set(down_count)

        # Health check totals
        for status_val in ("UP", "DOWN"):
            cnt_q = await session.execute(
                select(func.count(HealthCheck.id)).where(HealthCheck.status == status_val)
            )
            HEALTH_CHECKS_TOTAL.labels(status=status_val)._value.set(
                cnt_q.scalar() or 0
            )

        # Alert totals
        for atype in ("DOWN", "SLOW", "RECOVERED"):
            acnt_q = await session.execute(
                select(func.count(Alert.id)).where(Alert.alert_type == atype)
            )
            ALERTS_TOTAL.labels(alert_type=atype)._value.set(
                acnt_q.scalar() or 0
            )

        # Ongoing incidents
        ong_q = await session.execute(
            select(func.count(Incident.id)).where(Incident.status == "ongoing")
        )
        INCIDENTS_ONGOING.set(ong_q.scalar() or 0)


@app.get("/metrics", tags=["Metrics"], include_in_schema=True)
async def prometheus_metrics():
    """
    Prometheus-compatible /metrics endpoint.
    Scrape this with Prometheus and visualise in Grafana.
    """
    await _refresh_prometheus_metrics()
    return Response(
        content=generate_latest(PROMETHEUS_REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )


# ------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
