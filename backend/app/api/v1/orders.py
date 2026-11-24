"""Idempotent order execution and audit log endpoints (/api/v1/orders/*)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_execution_provider
from app.db.models import LiveOrderModel, VirtualOrderModel
from app.db.session import get_db_session
from app.providers.base import ExecutionProvider
from app.providers.dhan_broker import DhanBrokerError, HedgeExecutionAbortedError
from app.providers.virtual_broker import KillSwitchEngagedError, TradingModeMismatchError
from app.schemas.domain import (
    BatchOrderRequest,
    ExecutionResultSchema,
    OrderAuditLogSchema,
)
from app.services.dhan_auth import DhanAuthError
from app.services.risk_guard import RiskLimitError

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
    except (KillSwitchEngagedError, TradingModeMismatchError, RiskLimitError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (HedgeExecutionAbortedError, DhanBrokerError, DhanAuthError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=list[OrderAuditLogSchema])
async def list_orders(
    strategy_id: UUID | None = None,
    source: Literal["all", "virtual", "live"] = "all",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> list[OrderAuditLogSchema]:
    logs: list[OrderAuditLogSchema] = []

    if source in ("all", "virtual"):
        v_stmt = select(VirtualOrderModel).order_by(VirtualOrderModel.created_at.desc())
        if strategy_id is not None:
            v_stmt = v_stmt.where(VirtualOrderModel.strategy_id == strategy_id)
        v_rows = (await session.execute(v_stmt.limit(limit + offset))).scalars().all()
        logs.extend(OrderAuditLogSchema.model_validate(r, from_attributes=True) for r in v_rows)

    if source in ("all", "live"):
        l_stmt = select(LiveOrderModel).order_by(LiveOrderModel.created_at.desc())
        if strategy_id is not None:
            l_stmt = l_stmt.where(LiveOrderModel.strategy_id == strategy_id)
        l_rows = (await session.execute(l_stmt.limit(limit + offset))).scalars().all()
        logs.extend(OrderAuditLogSchema.model_validate(r, from_attributes=True) for r in l_rows)

    logs.sort(key=lambda item: item.created_at, reverse=True)
    return logs[offset : offset + limit]
