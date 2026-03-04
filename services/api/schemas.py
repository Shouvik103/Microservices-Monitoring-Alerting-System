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
    check_method: str = Field(
        default="GET",
        description="HTTP method for health checks: GET, POST, HEAD, or TCP",
        pattern="^(GET|POST|HEAD|TCP)$",
    )
    check_body: Optional[str] = Field(
        default=None,
        description="Request body for POST health checks",
    )


class ServiceResponse(BaseModel):
    id: int
    name: str
    url: str
    check_interval: int
    is_active: bool
    tags: list[str] = []
    custom_headers: dict[str, str] = {}
    check_method: str = "GET"
    check_body: Optional[str] = None
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
    check_method: str = "GET"
    current_status: Optional[str] = None
    uptime_24h: float
    avg_response_time: float
    last_checked: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Incident
# ---------------------------------------------------------------------------

class IncidentResponse(BaseModel):
    id: int
    service_id: int
    service_name: Optional[str] = None
    started_at: datetime
    resolved_at: Optional[datetime] = None
    duration_s: Optional[int] = None
    status: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=150)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="viewer", pattern="^(admin|editor|viewer)$")


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Custom Alert Rules
# ---------------------------------------------------------------------------

class AlertRuleCreate(BaseModel):
    service_id: int
    metric: str = Field(
        ...,
        description="Metric to evaluate: response_time_ms, status_code, or status",
        pattern="^(response_time_ms|status_code|status)$",
    )
    operator: str = Field(
        ...,
        description="Comparison operator: >, <, >=, <=, ==, !=",
        pattern=r"^(>|<|>=|<=|==|!=)$",
    )
    threshold: float = Field(
        ...,
        description="Threshold value (e.g. 500 for 500ms, 0 for DOWN status)",
    )
    severity: str = Field(default="warning", pattern="^(critical|warning|info)$")
    is_active: bool = True
    cooldown_s: int = Field(default=300, ge=30, le=86400)
    description: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    metric: Optional[str] = Field(default=None, pattern="^(response_time_ms|status_code|status)$")
    operator: Optional[str] = Field(default=None, pattern=r"^(>|<|>=|<=|==|!=)$")
    threshold: Optional[float] = None
    severity: Optional[str] = Field(default=None, pattern="^(critical|warning|info)$")
    is_active: Optional[bool] = None
    cooldown_s: Optional[int] = Field(default=None, ge=30, le=86400)
    description: Optional[str] = None


class AlertRuleResponse(BaseModel):
    id: int
    service_id: int
    service_name: Optional[str] = None
    metric: str
    operator: str
    threshold: float
    severity: str
    is_active: bool
    cooldown_s: int
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
