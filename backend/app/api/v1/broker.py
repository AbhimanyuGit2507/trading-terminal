"""DhanHQ daily API token management endpoints (/api/v1/broker/dhan/*)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_token_manager
from app.db.session import get_db_session
from app.schemas.domain import (
    DhanStatusResponse,
    DhanTokenSaveRequest,
    DhanTotpGenerateRequest,
)
from app.services.dhan_auth import DhanAuthError, DhanTokenManager

router = APIRouter(prefix="/broker/dhan", tags=["broker"])


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

