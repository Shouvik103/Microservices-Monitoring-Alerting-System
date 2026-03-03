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
