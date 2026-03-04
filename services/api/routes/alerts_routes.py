"""
Alerts Routes
==============
Endpoint for listing recent alerts.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import Alert, User
from auth import get_current_user
from schemas import AlertResponse

router = APIRouter(tags=["Alerts"])


@router.get("/alerts", response_model=list[AlertResponse])
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
