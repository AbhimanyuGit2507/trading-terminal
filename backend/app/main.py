"""FastAPI application entrypoint and Milestone 1 core routes for OpenAPI generation."""

from datetime import date, datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.core.calendar import IST, get_expiries, get_instrument_spec, to_ist
from app.core.config import get_settings
from app.quant.margin import estimate_portfolio_margin
from app.quant.mock_chain import generate_mock_option_chain
from app.quant.payoff import PayoffLeg, evaluate_payoff
from app.schemas.domain import (
    BatchOrderRequest,
    ExecutionResultSchema,
    ExpiryInfoSchema,
    IndexSymbol,
    InstrumentSpecSchema,
    LegQuoteSchema,
    MarginBreakdownSchema,
    NetGreeksSchema,
    OptionChainRowSchema,
    OptionChainSnapshotSchema,
    PayoffEvaluateRequest,
    PayoffEvaluateResponse,
    PayoffPointSchema,
    StrategyResponse,
)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "kill_switch_engaged": settings.kill_switch_engaged,
    }


@app.get(
    f"{settings.api_v1_prefix}/market/instruments",
    response_model=list[InstrumentSpecSchema],
)
async def list_instruments(as_of: date | None = None) -> list[InstrumentSpecSchema]:
    symbols: tuple[IndexSymbol, ...] = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")
    return [
        InstrumentSpecSchema(
            symbol=s.symbol,
            exchange=s.exchange,  # type: ignore[arg-type]
            lot_size=s.lot_size,
            strike_step=s.strike_step,
            tick_size=s.tick_size,
            freeze_qty=s.freeze_qty,
            has_weekly=s.has_weekly,
            expiry_weekday=s.expiry_weekday,
            effective_from=s.effective_from,
        )
        for s in (get_instrument_spec(sym, as_of) for sym in symbols)
    ]


@app.get(
    f"{settings.api_v1_prefix}/market/chain",
    response_model=OptionChainSnapshotSchema,
)
async def get_option_chain(
    symbol: IndexSymbol = "NIFTY",
    expiry: date | None = None,
    as_of: datetime | None = None,
) -> OptionChainSnapshotSchema:
    now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
    expiries = get_expiries(symbol, now_ist)
    if not expiries:
        raise HTTPException(status_code=404, detail=f"No active expiries found for {symbol}")
    chosen_expiry = expiry or expiries[0].expiry_date
    chain = generate_mock_option_chain(symbol=symbol, expiry=chosen_expiry, as_of=now_ist)
    return OptionChainSnapshotSchema(
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


@app.post(
    f"{settings.api_v1_prefix}/analytics/evaluate",
    response_model=PayoffEvaluateResponse,
)
async def evaluate_strategy_payoff(req: PayoffEvaluateRequest) -> PayoffEvaluateResponse:
    payoff_legs = [
        PayoffLeg(
            leg_id=leg.leg_id,
            symbol=leg.symbol,
            expiry=leg.expiry,
            option_type=leg.option_type,
            side=leg.side,
            lots=leg.lots,
            lot_size=leg.lot_size,
            entry_price=leg.entry_price,
            entry_iv=leg.entry_iv,
            strike=leg.strike,
            forward_at_base=leg.forward_at_base,
            enabled=leg.enabled,
            status=leg.status,
            exchange=leg.exchange,
        )
        for leg in req.legs
    ]
    eval_spot = req.what_if.target_spot if req.what_if else req.spot
    target_dt = req.what_if.target_datetime if req.what_if else req.as_of
    iv_shift = req.what_if.iv_shift_pct if req.what_if else 0.0

    result = evaluate_payoff(
        spot=req.spot,
        legs=payoff_legs,
        base_dt=req.as_of,
        target_spot=eval_spot,
        target_dt=target_dt,
        iv_shift_pct=iv_shift,
        realized_pnl=req.realized_pnl,
        include_charges=req.include_charges,
        atm_iv=req.atm_iv,
        r=settings.default_risk_free_rate,
    )
    margin = estimate_portfolio_margin(
        legs=payoff_legs,
        spot=req.spot,
        as_of=req.as_of,
        r=settings.default_risk_free_rate,
    )
    return PayoffEvaluateResponse(
        points=[PayoffPointSchema.model_validate(p, from_attributes=True) for p in result.points],
        breakevens=result.breakevens,
        target_breakevens=result.target_breakevens,
        max_profit=result.max_profit,
        max_loss=result.max_loss,
        max_profit_unlimited=result.max_profit_unlimited,
        max_loss_unlimited=result.max_loss_unlimited,
        risk_reward=result.risk_reward,
        pop=result.pop,
        net_greeks=NetGreeksSchema.model_validate(result.net_greeks, from_attributes=True),
        current_mtm_pnl=result.current_mtm_pnl,
        estimated_charges=result.estimated_charges,
        margin=MarginBreakdownSchema.model_validate(margin, from_attributes=True),
        sd_1_low=result.sd_1_low,
        sd_1_high=result.sd_1_high,
        sd_2_low=result.sd_2_low,
        sd_2_high=result.sd_2_high,
    )


# Registered in schema for shared type generation (wired to VirtualSimulatorBroker in Milestone 2)
@app.get(
    f"{settings.api_v1_prefix}/market/quotes-schema",
    response_model=dict[str, LegQuoteSchema],
    include_in_schema=True,
)
async def _quotes_schema_placeholder() -> dict[str, LegQuoteSchema]:
    return {}


@app.post(
    f"{settings.api_v1_prefix}/orders/preview-schema",
    response_model=ExecutionResultSchema,
    include_in_schema=True,
)
async def _orders_schema_placeholder(req: BatchOrderRequest) -> ExecutionResultSchema:
    raise HTTPException(status_code=501, detail="Execution routes wired in Milestone 2")


@app.get(
    f"{settings.api_v1_prefix}/strategies",
    response_model=list[StrategyResponse],
)
async def list_strategies_placeholder() -> list[StrategyResponse]:
    return []
