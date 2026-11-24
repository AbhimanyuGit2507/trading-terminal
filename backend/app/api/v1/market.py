"""Market data REST endpoints (/api/v1/market/*)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_market_provider
from app.core.calendar import IST, to_ist
from app.providers.base import MarketDataProvider
from app.schemas.domain import (
    ExpiryInfoSchema,
    IndexSymbol,
    InstrumentSpecSchema,
    OptionChainRowSchema,
    OptionChainSnapshotSchema,
    QuoteBatchRequest,
    QuoteBatchResponse,
)

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/instruments", response_model=list[InstrumentSpecSchema])
async def list_instruments(
    as_of: date | None = None,
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[InstrumentSpecSchema]:
    symbols: tuple[IndexSymbol, ...] = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX")
    specs = [await provider.get_instrument_spec(sym, as_of) for sym in symbols]
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
        for s in specs
    ]


@router.get("/expiries", response_model=list[ExpiryInfoSchema])
async def list_expiries(
    symbol: IndexSymbol = "NIFTY",
    as_of: datetime | None = None,
    count: int = 8,
    provider: MarketDataProvider = Depends(get_market_provider),
) -> list[ExpiryInfoSchema]:
    expiries = await provider.get_expiries(symbol, as_of=as_of, count=count)
    return [
        ExpiryInfoSchema(
            expiry_date=e.expiry_date,
            label=e.label,
            is_weekly=e.is_weekly,
            is_monthly=e.is_monthly,
            dte=e.dte,
            lot_size=e.lot_size,
        )
        for e in expiries
    ]


@router.get("/chain", response_model=OptionChainSnapshotSchema)
async def get_option_chain(
    symbol: IndexSymbol = "NIFTY",
    expiry: date | None = None,
    as_of: datetime | None = None,
    provider: MarketDataProvider = Depends(get_market_provider),
) -> OptionChainSnapshotSchema:
    try:
        chain, expiries = await provider.get_option_chain(symbol, expiry=expiry, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    feed_status = getattr(provider, "feed_status", "MOCK_FALLBACK")
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
        feed_status=feed_status,
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


@router.post("/quotes", response_model=QuoteBatchResponse)
async def get_batch_quotes(
    req: QuoteBatchRequest,
    provider: MarketDataProvider = Depends(get_market_provider),
) -> QuoteBatchResponse:
    eval_dt = to_ist(req.as_of) if req.as_of is not None else datetime.now(IST)
    try:
        quotes = await provider.get_contract_quotes(req.contract_ids, as_of=eval_dt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return QuoteBatchResponse(as_of=eval_dt, quotes=quotes)
