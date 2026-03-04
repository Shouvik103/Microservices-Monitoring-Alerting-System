"""
SQLAlchemy ORM models for the monitoring system.
"""

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    url = Column(String(2048), nullable=False)
    check_interval = Column(Integer, nullable=False, default=30)
    is_active = Column(Boolean, nullable=False, default=True)
    tags = Column(ARRAY(String), nullable=False, server_default="{}")
    custom_headers = Column(JSON, nullable=False, server_default="{}")
    check_method = Column(String(10), nullable=False, server_default="GET")
    check_body = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    health_checks = relationship(
        "HealthCheck", back_populates="service", cascade="all, delete-orphan"
    )
    alerts = relationship(
        "Alert", back_populates="service", cascade="all, delete-orphan"
    )


class HealthCheck(Base):
    __tablename__ = "health_checks"

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(
        Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(10), nullable=False)
    response_time_ms = Column(Float, nullable=True)
    status_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    checked_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    service = relationship("Service", back_populates="health_checks")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(
        Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    alert_type = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    sent_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    service = relationship("Service", back_populates="alerts")


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(
        Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    duration_s = Column(Integer, nullable=True)
    status = Column(String(10), nullable=False, default="ongoing")

    service = relationship("Service")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), unique=True, nullable=False, index=True)
    hashed_password = Column(Text, nullable=False)
    role = Column(String(20), nullable=False, default="viewer")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    service_id = Column(
        Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    metric = Column(String(30), nullable=False)  # response_time_ms | status_code | status
    operator = Column(String(5), nullable=False)  # > < >= <= == !=
    threshold = Column(Float, nullable=False)
    severity = Column(String(20), nullable=False, default="warning")
    is_active = Column(Boolean, nullable=False, default=True)
    cooldown_s = Column(Integer, nullable=False, default=300)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    service = relationship("Service")
