"""
Metrics Routes
===============
Prometheus-compatible /metrics endpoint and metric definitions.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from sqlalchemy import func, select, and_

from database import async_session
from models import Alert, HealthCheck, Incident, Service

# ---------------------------------------------------------------------------
# Prometheus Registry & Metrics
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

router = APIRouter(tags=["Metrics"])


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


@router.get("/metrics", include_in_schema=True)
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
