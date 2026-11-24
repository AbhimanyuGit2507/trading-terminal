"""Backend Risk Engine, Mode Switch & Emergency Kill Switch endpoints (/api/v1/risk/*)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_risk_guard
from app.db.session import get_db_session
from app.schemas.domain import (
    ExecutionModeSwitchRequest,
    KillSwitchTriggerRequest,
    KillSwitchTriggerResponse,
    KillSwitchUnlockRequest,
    RiskConfigUpdateRequest,
    RiskStateResponse,
)
from app.services.risk_guard import RiskGuardService, RiskLimitError

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/status", response_model=RiskStateResponse)
async def get_risk_status(
    session: AsyncSession = Depends(get_db_session),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> RiskStateResponse:
    return await risk_guard.get_state(session)


@router.put("/config", response_model=RiskStateResponse)
async def update_risk_config(
    req: RiskConfigUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> RiskStateResponse:
    return await risk_guard.update_config(session, req)


@router.post("/mode", response_model=RiskStateResponse)
async def switch_execution_mode(
    req: ExecutionModeSwitchRequest,
    session: AsyncSession = Depends(get_db_session),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> RiskStateResponse:
    try:
        return await risk_guard.switch_execution_mode(
            session=session,
            target_mode=req.mode,
            confirmed=req.confirmed,
        )
    except RiskLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/kill-switch", response_model=KillSwitchTriggerResponse)
async def trigger_kill_switch(
    req: KillSwitchTriggerRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> KillSwitchTriggerResponse:
    reason = req.reason if req is not None else "Manual Emergency Exit triggered by user"
    return await risk_guard.trigger_kill_switch(session=session, reason=reason)


@router.post("/unlock", response_model=RiskStateResponse)
async def unlock_kill_switch(
    req: KillSwitchUnlockRequest,
    session: AsyncSession = Depends(get_db_session),
    risk_guard: RiskGuardService = Depends(get_risk_guard),
) -> RiskStateResponse:
    try:
        return await risk_guard.unlock_kill_switch(
            session=session,
            confirmation_text=req.confirmation_text,
        )
    except RiskLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

