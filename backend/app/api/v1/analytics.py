"""Strategy analytics & payoff evaluation endpoint (/api/v1/analytics/*)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_margin_provider
from app.core.config import get_settings
from app.providers.base import MarginProvider
from app.quant.payoff import PayoffLeg, evaluate_payoff
from app.schemas.domain import (
    MarginBreakdownSchema,
    NetGreeksSchema,
    PayoffEvaluateRequest,
    PayoffEvaluateResponse,
    PayoffPointSchema,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/evaluate", response_model=PayoffEvaluateResponse)
async def evaluate_strategy_payoff(
    req: PayoffEvaluateRequest,
    margin_provider: MarginProvider = Depends(get_margin_provider),
) -> PayoffEvaluateResponse:
    settings = get_settings()
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
    margin = await margin_provider.estimate_margin(
        legs=payoff_legs,
        spot=req.spot,
        as_of=req.as_of,
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
