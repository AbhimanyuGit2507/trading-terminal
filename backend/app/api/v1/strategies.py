"""Postgres CRUD endpoints for saved strategies (/api/v1/strategies/*)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StrategyModel
from app.db.session import get_db_session
from app.schemas.domain import (
    ClosedLegRecordSchema,
    StrategyCreateRequest,
    StrategyLegSchema,
    StrategyResponse,
    StrategyUpdateRequest,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _to_response(model: StrategyModel) -> StrategyResponse:
    return StrategyResponse(
        id=model.id,
        name=model.name,
        symbol=model.symbol,  # type: ignore[arg-type]
        mode=model.mode,
        legs=[StrategyLegSchema.model_validate(leg) for leg in model.legs_json],
        closed_legs=[
            ClosedLegRecordSchema.model_validate(cl) for cl in model.closed_legs_json
        ],
        realized_pnl=model.realized_pnl,
        metadata=model.metadata_json,
        notes=model.notes,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(
    session: AsyncSession = Depends(get_db_session),
) -> list[StrategyResponse]:
    stmt = select(StrategyModel).order_by(StrategyModel.updated_at.desc())
    rows = (await session.execute(stmt)).scalars().all()
    return [_to_response(row) for row in rows]


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
async def create_strategy(
    req: StrategyCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> StrategyResponse:
    model = StrategyModel(
        name=req.name,
        symbol=req.symbol,
        mode=req.mode,
        legs_json=[leg.model_dump(mode="json") for leg in req.legs],
        closed_legs_json=[cl.model_dump(mode="json") for cl in req.closed_legs],
        realized_pnl=req.realized_pnl,
        metadata_json=req.metadata,
        notes=req.notes,
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)
    return _to_response(model)


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(
    strategy_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> StrategyResponse:
    model = await session.get(StrategyModel, strategy_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _to_response(model)


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: UUID,
    req: StrategyUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> StrategyResponse:
    model = await session.get(StrategyModel, strategy_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if req.name is not None:
        model.name = req.name
    if req.symbol is not None:
        model.symbol = req.symbol
    if req.mode is not None:
        model.mode = req.mode
    if req.legs is not None:
        model.legs_json = [leg.model_dump(mode="json") for leg in req.legs]
    if req.closed_legs is not None:
        model.closed_legs_json = [cl.model_dump(mode="json") for cl in req.closed_legs]
    if req.realized_pnl is not None:
        model.realized_pnl = req.realized_pnl
    if req.metadata is not None:
        model.metadata_json = req.metadata
    if req.notes is not None:
        model.notes = req.notes

    await session.commit()
    await session.refresh(model)
    return _to_response(model)


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(
    strategy_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    model = await session.get(StrategyModel, strategy_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    await session.delete(model)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

