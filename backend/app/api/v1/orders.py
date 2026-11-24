"""Idempotent order execution and audit log endpoints (/api/v1/orders/*)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_execution_provider
from app.db.models import VirtualOrderModel
from app.db.session import get_db_session
from app.providers.base import ExecutionProvider
from app.providers.virtual_broker import KillSwitchEngagedError, TradingModeMismatchError
from app.schemas.domain import (
    BatchOrderRequest,
    ExecutionResultSchema,
    OrderAuditLogSchema,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/execute", response_model=ExecutionResultSchema)
async def execute_orders(
    req: BatchOrderRequest,
    x_idempotency_key: UUID = Header(..., alias="X-Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
    broker: ExecutionProvider = Depends(get_execution_provider),
) -> ExecutionResultSchema:
    if req.idempotency_key is not None and req.idempotency_key != x_idempotency_key:
        raise HTTPException(
            status_code=400,
            detail="Mismatched idempotency key between X-Idempotency-Key header and request body.",
        )

    try:
        return await broker.execute_orders(session, req, x_idempotency_key)
    except (KillSwitchEngagedError, TradingModeMismatchError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[OrderAuditLogSchema])
async def list_orders(
    strategy_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> list[OrderAuditLogSchema]:
    stmt = select(VirtualOrderModel).order_by(VirtualOrderModel.created_at.desc())
    if strategy_id is not None:
        stmt = stmt.where(VirtualOrderModel.strategy_id == strategy_id)
    stmt = stmt.offset(offset).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [OrderAuditLogSchema.model_validate(row, from_attributes=True) for row in rows]
