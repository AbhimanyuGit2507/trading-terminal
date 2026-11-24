"""DhanHQ daily API token & live orderbook/positions/funds endpoints (/api/v1/broker/dhan/*)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_dhan_broker, get_risk_guard, get_token_manager
from app.db.session import get_db_session
from app.providers.dhan_broker import DhanBrokerError, DhanExecutionProvider
from app.schemas.domain import (
    BrokerOrderRecordSchema,
    BrokerPositionRecordSchema,
    BrokerReconcileResponse,
    DhanStatusResponse,
    DhanTokenSaveRequest,
    DhanTotpGenerateRequest,
    FundLimitResponse,
)
from app.services.dhan_auth import DhanAuthError, DhanTokenManager
from app.services.risk_guard import RiskGuardService

router = APIRouter(prefix="/broker/dhan", tags=["broker"])


def _resolve_env(
    requested: Literal["SANDBOX", "LIVE"] | None, risk_guard: RiskGuardService
) -> Literal["SANDBOX", "LIVE"]:
    if requested is not None:
        return requested
    return "LIVE" if risk_guard.active_execution_mode == "DHAN_LIVE" else "SANDBOX"


@router.get("/status", response_model=DhanStatusResponse)
async def get_dhan_status(
    manager: DhanTokenManager = Depends(get_token_manager),
) -> DhanStatusResponse:
    return manager.get_status()


@router.post("/token", response_model=DhanStatusResponse)
async def save_dhan_token(
    req: DhanTokenSaveRequest,
    session: AsyncSession = Depends(get_db_session),
    manager: DhanTokenManager = Depends(get_token_manager),
) -> DhanStatusResponse:
    try:
        return await manager.validate_and_save_token(
            session=session,
            client_id=req.client_id,
            access_token=req.access_token,
        )
    except DhanAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/renew", response_model=DhanStatusResponse)
async def renew_dhan_token(
    session: AsyncSession = Depends(get_db_session),
    manager: DhanTokenManager = Depends(get_token_manager),
) -> DhanStatusResponse:
    try:
        return await manager.renew_active_token(session=session)
    except DhanAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate-totp", response_model=DhanStatusResponse)
async def generate_dhan_totp_token(
    req: DhanTotpGenerateRequest,
    session: AsyncSession = Depends(get_db_session),
    manager: DhanTokenManager = Depends(get_token_manager),
) -> DhanStatusResponse:
    try:
        return await manager.generate_totp_token(
            session=session,
            client_id=req.client_id,
            pin=req.pin,
            totp=req.totp,
        )
    except DhanAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/disconnect", response_model=DhanStatusResponse)
async def disconnect_dhan(
    manager: DhanTokenManager = Depends(get_token_manager),
) -> DhanStatusResponse:
    return await manager.disconnect_to_mock()


@router.get("/funds", response_model=FundLimitResponse)
async def get_dhan_funds(
    env: Literal["SANDBOX", "LIVE"] | None = Query(default=None),
    dhan_broker: DhanExecutionProvider = Depends(get_dhan_broker),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> FundLimitResponse:
    resolved_env = _resolve_env(env, risk_guard)
    try:
        return await dhan_broker.fetch_fund_limits(resolved_env)
    except (DhanAuthError, DhanBrokerError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/orders", response_model=list[BrokerOrderRecordSchema])
async def get_dhan_orderbook(
    env: Literal["SANDBOX", "LIVE"] | None = Query(default=None),
    dhan_broker: DhanExecutionProvider = Depends(get_dhan_broker),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> list[BrokerOrderRecordSchema]:
    resolved_env = _resolve_env(env, risk_guard)
    try:
        return await dhan_broker.fetch_orders(resolved_env)
    except (DhanAuthError, DhanBrokerError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/positions", response_model=list[BrokerPositionRecordSchema])
async def get_dhan_positions(
    env: Literal["SANDBOX", "LIVE"] | None = Query(default=None),
    dhan_broker: DhanExecutionProvider = Depends(get_dhan_broker),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> list[BrokerPositionRecordSchema]:
    resolved_env = _resolve_env(env, risk_guard)
    try:
        return await dhan_broker.fetch_positions(resolved_env)
    except (DhanAuthError, DhanBrokerError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reconcile", response_model=BrokerReconcileResponse)
async def reconcile_dhan_orders(
    env: Literal["SANDBOX", "LIVE"] | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    dhan_broker: DhanExecutionProvider = Depends(get_dhan_broker),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> BrokerReconcileResponse:
    resolved_env = _resolve_env(env, risk_guard)
    try:
        return await dhan_broker.reconcile_orders(session, resolved_env)
    except (DhanAuthError, DhanBrokerError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
