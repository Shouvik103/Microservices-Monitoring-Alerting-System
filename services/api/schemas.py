"""
Pydantic schemas for request / response validation.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl, Field


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1, max_length=2048)
    check_interval: int = Field(default=30, ge=5, le=3600)
    tags: list[str] = Field(default_factory=list)
    custom_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Custom HTTP headers sent during health checks (e.g. API keys)",
    )


class ServiceResponse(BaseModel):
    id: int
    name: str
    url: str
    check_interval: int
    is_active: bool
    tags: list[str] = []
    custom_headers: dict[str, str] = {}
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------

class HealthCheckResponse(BaseModel):
    id: int
    service_id: int
    status: str
    response_time_ms: Optional[float] = None
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    checked_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Uptime
# ---------------------------------------------------------------------------

class UptimePeriod(BaseModel):
    period: str
    uptime_percent: float
    avg_response_time_ms: float
    total_checks: int


class UptimeResponse(BaseModel):
    service_id: int
    service_name: str
    periods: list[UptimePeriod]


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

class AlertResponse(BaseModel):
    id: int
    service_id: int
    alert_type: str
    message: str
    sent_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardService(BaseModel):
    service_id: int
    service_name: str
    url: str
    tags: list[str] = []
    current_status: Optional[str] = None
    uptime_24h: float
    avg_response_time: float
    last_checked: Optional[datetime] = None
