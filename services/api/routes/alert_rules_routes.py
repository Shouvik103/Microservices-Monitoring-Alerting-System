"""
Alert Rules Routes
===================
CRUD endpoints for custom per-service alert rules.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import AlertRule, Service, User
from auth import get_current_user, require_role
from schemas import AlertRuleCreate, AlertRuleResponse, AlertRuleUpdate

logger = logging.getLogger("api")

router = APIRouter(tags=["Alert Rules"])


@router.get("/alert-rules", response_model=list[AlertRuleResponse])
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


@router.post("/alert-rules", response_model=AlertRuleResponse, status_code=201)
async def create_alert_rule(
    payload: AlertRuleCreate,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_role("admin", "editor")),
):
    """Create a custom per-service alert rule."""
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


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleResponse)
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


@router.delete("/alert-rules/{rule_id}")
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
