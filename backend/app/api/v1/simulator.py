"""Historical Simulator endpoints: available dates, time-jump, time-step & auto-expiry settlement."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_historical_provider, get_market_provider
from app.core.calendar import (
    IST,
    MARKET_OPEN_IST,
    expiry_settlement_datetime,
    get_expiries,
    is_trading_day,
    to_ist,
)
from app.db.session import get_db_session
from app.providers.base import MarketDataProvider
from app.providers.parquet_hist import ParquetHistoricalProvider
from app.providers.virtual_broker import VirtualSimulatorBroker
from app.schemas.domain import (
    AvailableDatesResponse,
    BatchOrderRequest,
    ExpiryInfoSchema,
    IndexSymbol,
    OptionChainRowSchema,
    OptionChainSnapshotSchema,
    OptionSide,
    OrderLegInstruction,
    SettledLegEventSchema,
    SimulatorJumpRequest,
    SimulatorStepRequest,
    SimulatorStepResponse,
    SimulatorStepSize,
    StrategyLegSchema,
)

router = APIRouter(prefix="/simulator", tags=["simulator"])

LAST_BAR_IST = time(15, 29)
SETTLEMENT_CLOCK_IST = time(15, 30)

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


def _shift_trading_days(d: date, direction: int) -> date:
    cur = d + timedelta(days=direction)
    while not is_trading_day(cur):
        cur += timedelta(days=direction)
    return cur


def _clamp_session_bar(dt_ist: datetime) -> datetime:
    d = dt_ist.date()
    open_dt = datetime.combine(d, MARKET_OPEN_IST, tzinfo=IST)
    last_dt = datetime.combine(d, LAST_BAR_IST, tzinfo=IST)
    return max(open_dt, min(last_dt, dt_ist.replace(second=0, microsecond=0)))


def advance_sim_clock(current: datetime, step: SimulatorStepSize) -> datetime:
    """Advance/rewind simulator clock respecting 09:15..15:29 IST session boundaries."""
    cur = to_ist(current).replace(second=0, microsecond=0)
    if step == "+1d":
        nxt_d = _shift_trading_days(cur.date(), 1)
        return _clamp_session_bar(datetime.combine(nxt_d, cur.time(), tzinfo=IST))
    if step == "-1d":
        prv_d = _shift_trading_days(cur.date(), -1)
        return _clamp_session_bar(datetime.combine(prv_d, cur.time(), tzinfo=IST))

    mins = _MINUTE_STEPS[step]
    nxt = cur + timedelta(minutes=mins)
    open_dt = datetime.combine(cur.date(), MARKET_OPEN_IST, tzinfo=IST)
    settle_dt = datetime.combine(cur.date(), SETTLEMENT_CLOCK_IST, tzinfo=IST)

    if nxt >= settle_dt:
        overflow = nxt - settle_dt
        next_day = _shift_trading_days(cur.date(), 1)
        return _clamp_session_bar(datetime.combine(next_day, MARKET_OPEN_IST, tzinfo=IST) + overflow)
    if nxt < open_dt:
        underflow = open_dt - nxt
        prev_day = _shift_trading_days(cur.date(), -1)
        return _clamp_session_bar(
            datetime.combine(prev_day, SETTLEMENT_CLOCK_IST, tzinfo=IST) - underflow
        )
    return nxt


def _snap_to_available_date(
    target_dt: datetime,
    available_dates: list[date],
    direction: int,
) -> tuple[datetime, bool]:
    """Snap target_dt onto available Parquet dates when stepping across missing dates."""
    if not available_dates:
        return target_dt, False

    d = target_dt.date()
    if d in available_dates:
        return target_dt, False

    if direction >= 0:
        for avail in available_dates:
            if avail > d:
                return datetime.combine(avail, MARKET_OPEN_IST, tzinfo=IST), False
        # Past end of available Parquet data -> clamp to final bar of last available day
        return datetime.combine(available_dates[-1], LAST_BAR_IST, tzinfo=IST), True
    else:
        for avail in reversed(available_dates):
            if avail < d:
                return datetime.combine(avail, LAST_BAR_IST, tzinfo=IST), False
        return datetime.combine(available_dates[0], MARKET_OPEN_IST, tzinfo=IST), True


async def _settle_expired_legs(
    session: AsyncSession,
    symbol: IndexSymbol,
    prev_ist: datetime,
    new_ist: datetime,
    open_legs: list[StrategyLegSchema],
    hist_provider: ParquetHistoricalProvider,
    mock_provider: MarketDataProvider,
    fallback_spot: float,
) -> tuple[list[SettledLegEventSchema], Decimal]:
    """Auto-settle open legs whose 15:30 IST expiry boundary was reached or crossed."""
    to_settle: list[StrategyLegSchema] = []
    for leg in open_legs:
        if not leg.enabled or leg.status != "OPEN":
            continue
        settle_dt = expiry_settlement_datetime(leg.expiry)
        if prev_ist < settle_dt <= new_ist:
            to_settle.append(leg)

    if not to_settle:
        return [], Decimal("0.00")

    broker = VirtualSimulatorBroker(market_provider=mock_provider)
    settled_events: list[SettledLegEventSchema] = []
    total_delta = Decimal("0.00")
    spot_cache: dict[date, float] = {}

    for leg in to_settle:
        if leg.expiry not in spot_cache:
            close_bar_dt = datetime.combine(leg.expiry, LAST_BAR_IST, tzinfo=IST)
            try:
                if hist_provider.has_data_for_date(leg.symbol, leg.expiry):
                    exp_chain, _ = await hist_provider.get_option_chain(
                        leg.symbol, expiry=leg.expiry, as_of=close_bar_dt
                    )
                    spot_cache[leg.expiry] = exp_chain.spot
                else:
                    exp_chain, _ = await mock_provider.get_option_chain(
                        leg.symbol, expiry=leg.expiry, as_of=close_bar_dt
                    )
                    spot_cache[leg.expiry] = exp_chain.spot
            except (FileNotFoundError, ValueError):
                spot_cache[leg.expiry] = fallback_spot

        settle_spot = spot_cache[leg.expiry]
        if leg.option_type == "CE":
            intrinsic = max(settle_spot - float(leg.strike or settle_spot), 0.0)
        elif leg.option_type == "PE":
            intrinsic = max(float(leg.strike or settle_spot) - settle_spot, 0.0)
        else:
            intrinsic = settle_spot
        settle_px = round(intrinsic, 2)

        closing_side: OptionSide = "SELL" if leg.side == "BUY" else "BUY"
        settle_dt = expiry_settlement_datetime(leg.expiry)
        idem_key = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"sim-settle:{symbol}:{leg.leg_id}:{leg.contract_id}:{leg.expiry.isoformat()}",
        )
        exec_res = await broker.execute_orders(
            session=session,
            req=BatchOrderRequest(
                idempotency_key=idem_key,
                trading_mode="SIMULATOR",
                action="SETTLED_AT_EXPIRY",
                slice_if_frozen=False,
                as_of=settle_dt,
                legs=[
                    OrderLegInstruction(
                        leg_id=leg.leg_id,
                        contract_id=leg.contract_id,
                        side=closing_side,
                        lots=leg.lots,
                        lot_size=leg.lot_size,
                        limit_price=Decimal(f"{settle_px:.2f}"),
                        entry_price=Decimal(f"{leg.entry_price:.2f}"),
                    )
                ],
            ),
            idempotency_key=idem_key,
        )
        leg_delta = exec_res.realized_pnl_delta
        total_delta += leg_delta
        settled_events.append(
            SettledLegEventSchema(
                leg_id=leg.leg_id,
                contract_id=leg.contract_id,
                symbol=leg.symbol,
                expiry=leg.expiry,
                strike=leg.strike,
                option_type=leg.option_type,
                side=leg.side,
                lots_settled=leg.lots,
                lot_size=leg.lot_size,
                entry_price=leg.entry_price,
                settlement_price=settle_px,
                realized_pnl=float(leg_delta),
                settled_at=settle_dt,
                order_id=exec_res.fills[0].order_id if exec_res.fills else None,
            )
        )

    return settled_events, total_delta.quantize(Decimal("0.01"))


async def _load_snapshot_and_quotes(
    symbol: IndexSymbol,
    target_ist: datetime,
    chain_expiry: date | None,
    active_contracts: list[str],
    hist_provider: ParquetHistoricalProvider,
    mock_provider: MarketDataProvider,
) -> tuple[OptionChainSnapshotSchema, dict, str]:
    use_parquet = hist_provider.has_data_for_date(symbol, target_ist.date())
    active_provider: MarketDataProvider = hist_provider if use_parquet else mock_provider
    data_source = "parquet" if use_parquet else "mock_fallback"

    try:
        chain, expiries = await active_provider.get_option_chain(
            symbol, expiry=chain_expiry, as_of=target_ist
        )
    except (FileNotFoundError, ValueError):
        # Fallback if selected chain_expiry wasn't present in that historical partition
        if use_parquet and chain_expiry is not None:
            try:
                chain, expiries = await active_provider.get_option_chain(
                    symbol, expiry=None, as_of=target_ist
                )
            except (FileNotFoundError, ValueError):
                chain, expiries = await mock_provider.get_option_chain(
                    symbol, expiry=chain_expiry, as_of=target_ist
                )
                active_provider = mock_provider
                data_source = "mock_fallback"
        else:
            chain, expiries = await mock_provider.get_option_chain(
                symbol, expiry=chain_expiry, as_of=target_ist
            )
            active_provider = mock_provider
            data_source = "mock_fallback"

    leg_quotes = (
        await active_provider.get_contract_quotes(active_contracts, as_of=target_ist)
        if active_contracts
        else {}
    )

    snap = OptionChainSnapshotSchema(
        symbol=symbol,
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
        rows=[OptionChainRowSchema.model_validate(r, from_attributes=True) for r in chain.rows],
    )
    return snap, leg_quotes, data_source


@router.get("/available-dates", response_model=AvailableDatesResponse)
async def get_available_dates(
    symbol: IndexSymbol = "NIFTY",
    hist_provider: ParquetHistoricalProvider = Depends(get_historical_provider),
) -> AvailableDatesResponse:
    dates = hist_provider.get_available_dates(symbol)
    if not dates:
        return AvailableDatesResponse(
            symbol=symbol,
            dates=[],
            expiry_dates=[],
            min_date=None,
            max_date=None,
            data_source="mock_fallback",
        )

    expiry_dates: list[date] = []
    for d in dates:
        exps = get_expiries(symbol, datetime.combine(d, MARKET_OPEN_IST, tzinfo=IST), count=1)
        if exps and exps[0].expiry_date == d:
            expiry_dates.append(d)

    return AvailableDatesResponse(
        symbol=symbol,
        dates=dates,
        expiry_dates=expiry_dates,
        min_date=dates[0],
        max_date=dates[-1],
        data_source="parquet",
    )


@router.post("/jump", response_model=SimulatorStepResponse)
async def jump_simulator(
    req: SimulatorJumpRequest,
    session: AsyncSession = Depends(get_db_session),
    hist_provider: ParquetHistoricalProvider = Depends(get_historical_provider),
    mock_provider: MarketDataProvider = Depends(get_market_provider),
) -> SimulatorStepResponse:
    target_ist = _clamp_session_bar(to_ist(req.target_dt))
    avail_dates = hist_provider.get_available_dates(req.symbol)
    end_of_data = False
    if avail_dates:
        target_ist, end_of_data = _snap_to_available_date(target_ist, avail_dates, direction=1)

    try:
        snap, leg_quotes, data_source = await _load_snapshot_and_quotes(
            symbol=req.symbol,
            target_ist=target_ist,
            chain_expiry=req.chain_expiry,
            active_contracts=req.active_contracts,
            hist_provider=hist_provider,
            mock_provider=mock_provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SimulatorStepResponse(
        symbol=req.symbol,
        previous_as_of=target_ist,
        new_as_of=target_ist,
        data_source=data_source,  # type: ignore[arg-type]
        end_of_data=end_of_data,
        chain=snap,
        leg_quotes=leg_quotes,
        settled_legs=[],
        realized_pnl_delta=Decimal("0.00"),
    )


@router.post("/step", response_model=SimulatorStepResponse)
async def step_simulator(
    req: SimulatorStepRequest,
    session: AsyncSession = Depends(get_db_session),
    hist_provider: ParquetHistoricalProvider = Depends(get_historical_provider),
    mock_provider: MarketDataProvider = Depends(get_market_provider),
) -> SimulatorStepResponse:
    prev_ist = to_ist(req.current_as_of).replace(second=0, microsecond=0)
    raw_new_ist = advance_sim_clock(prev_ist, req.step)
    direction = -1 if req.step.startswith("-") else 1

    avail_dates = hist_provider.get_available_dates(req.symbol)
    end_of_data = False
    new_ist = raw_new_ist
    if avail_dates:
        new_ist, end_of_data = _snap_to_available_date(raw_new_ist, avail_dates, direction=direction)

    try:
        snap, leg_quotes, data_source = await _load_snapshot_and_quotes(
            symbol=req.symbol,
            target_ist=new_ist,
            chain_expiry=req.chain_expiry,
            active_contracts=req.active_contracts,
            hist_provider=hist_provider,
            mock_provider=mock_provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Check expiry settlement against raw_new_ist so crossing 15:30 IST on the final available day still settles!
    settle_check_dt = raw_new_ist if end_of_data and direction > 0 else new_ist
    settled_legs, realized_delta = await _settle_expired_legs(
        session=session,
        symbol=req.symbol,
        prev_ist=prev_ist,
        new_ist=settle_check_dt,
        open_legs=req.open_legs,
        hist_provider=hist_provider,
        mock_provider=mock_provider,
        fallback_spot=snap.spot,
    )

    return SimulatorStepResponse(
        symbol=req.symbol,
        previous_as_of=prev_ist,
        new_as_of=new_ist,
        data_source=data_source,  # type: ignore[arg-type]
        end_of_data=end_of_data,
        chain=snap,
        leg_quotes=leg_quotes,
        settled_legs=settled_legs,
        realized_pnl_delta=realized_delta,
    )
