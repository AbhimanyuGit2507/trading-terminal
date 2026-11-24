"""Simulator time-travel interface stub (ready for Phase 2 DuckDB/Parquet replay)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_market_provider
from app.core.calendar import (
    IST,
    MARKET_CLOSE_IST,
    MARKET_OPEN_IST,
    is_trading_day,
    to_ist,
)
from app.providers.base import MarketDataProvider
from app.schemas.domain import (
    ExpiryInfoSchema,
    OptionChainRowSchema,
    OptionChainSnapshotSchema,
    SimulatorStepRequest,
    SimulatorStepResponse,
    SimulatorStepSize,
)

router = APIRouter(prefix="/simulator", tags=["simulator"])

_MINUTE_STEPS: dict[SimulatorStepSize, int] = {
    "-30m": -30,
    "-15m": -15,
    "-5m": -5,
    "-1m": -1,
    "+1m": 1,
    "+5m": 5,
    "+15m": 15,
    "+30m": 30,
}


def _shift_trading_days(dt: datetime, direction: int) -> datetime:
    cur_date = dt.date() + timedelta(days=direction)
    while not is_trading_day(cur_date):
        cur_date += timedelta(days=direction)
    return datetime.combine(cur_date, dt.timetz()).replace(tzinfo=IST)


def _advance_sim_clock(current: datetime, step: SimulatorStepSize) -> datetime:
    cur = to_ist(current)
    if step == "+1d":
        return _shift_trading_days(cur, 1)
    if step == "-1d":
        return _shift_trading_days(cur, -1)

    mins = _MINUTE_STEPS[step]
    nxt = cur + timedelta(minutes=mins)
    open_dt = datetime.combine(cur.date(), MARKET_OPEN_IST, tzinfo=IST)
    close_dt = datetime.combine(cur.date(), MARKET_CLOSE_IST, tzinfo=IST)

    if nxt > close_dt:
        overflow = nxt - close_dt
        next_day = _shift_trading_days(cur, 1)
        return datetime.combine(next_day.date(), MARKET_OPEN_IST, tzinfo=IST) + overflow
    if nxt < open_dt:
        underflow = open_dt - nxt
        prev_day = _shift_trading_days(cur, -1)
        return datetime.combine(prev_day.date(), MARKET_CLOSE_IST, tzinfo=IST) - underflow
    return nxt


@router.post("/step", response_model=SimulatorStepResponse)
async def step_simulator(
    req: SimulatorStepRequest,
    provider: MarketDataProvider = Depends(get_market_provider),
) -> SimulatorStepResponse:
    prev_ist = to_ist(req.current_as_of)
    new_ist = _advance_sim_clock(prev_ist, req.step)

    try:
        chain, expiries = await provider.get_option_chain(
            req.symbol, expiry=req.chain_expiry, as_of=new_ist
        )
        leg_quotes = (
            await provider.get_contract_quotes(req.active_contracts, as_of=new_ist)
            if req.active_contracts
            else {}
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SimulatorStepResponse(
        symbol=req.symbol,
        previous_as_of=prev_ist,
        new_as_of=new_ist,
        chain=OptionChainSnapshotSchema(
            symbol=req.symbol,
            exchange=chain.exchange,  # type: ignore[arg-type]
            expiry=chain.expiry,
            as_of=chain.as_of,
            spot=chain.spot,
            futures_price=chain.futures_price,
            forward_price=chain.forward_price,
            india_vix=chain.india_vix,
            atm_strike=chain.atm_strike,
            lot_size=chain.lot_size,
            strike_step=chain.strike_step,
            futures_contract_id=chain.futures_contract_id,
            expiries=[
                ExpiryInfoSchema(
                    expiry_date=e.expiry_date,
                    label=e.label,
                    is_weekly=e.is_weekly,
                    is_monthly=e.is_monthly,
                    dte=e.dte,
                    lot_size=e.lot_size,
                )
                for e in expiries
            ],
            rows=[
                OptionChainRowSchema.model_validate(r, from_attributes=True)
                for r in chain.rows
            ],
        ),
        leg_quotes=leg_quotes,
    )

