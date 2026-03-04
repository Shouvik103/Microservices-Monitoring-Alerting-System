"""
Dashboard Routes
=================
Dashboard summary endpoint, WebSocket live push, and broadcast loop.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session, get_session
from models import HealthCheck, Service, User
from auth import get_current_user
from schemas import DashboardService

logger = logging.getLogger("api")

router = APIRouter(tags=["Dashboard"])

# WebSocket client tracking
connected_clients: set[WebSocket] = set()


@router.get("/dashboard", response_model=list[DashboardService])
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


@router.websocket("/ws")
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
