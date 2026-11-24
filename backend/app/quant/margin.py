"""Hedge-aware portfolio stress margin estimator (Phase 1 proxy for NSE/BSE SPAN + Exposure)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.core.calendar import time_to_expiry_years
from app.quant.black76 import greeks_black76_vectorized
from app.quant.payoff import PayoffLeg


@dataclass(frozen=True, slots=True)
class MarginBreakdown:
    span_proxy: float
    exposure_proxy: float
    total_margin: float
    hedge_benefit: float
    margin_source: str = "estimated_stress"


def estimate_portfolio_margin(
    legs: list[PayoffLeg],
    spot: float,
    as_of: datetime,
    r: float = 0.0,
) -> MarginBreakdown:
    """Estimate portfolio margin using a 17-point spot x IV stress grid + exposure margin.

    Accounts for hedge/spread benefits (e.g., Iron Condor, Credit Spreads) while preventing
    under-margining on naked short straddles/strangles.
    """
    active = [leg for leg in legs if leg.enabled and leg.status == "OPEN"]
    if not active:
        return MarginBreakdown(0.0, 0.0, 0.0, 0.0)

    spot_shocks = np.linspace(spot * 0.85, spot * 1.15, 17, dtype=np.float64)
    iv_multipliers = (0.85, 1.0, 1.25)

    # Compute unhedged standalone short margin to measure hedge_benefit
    standalone_short_margin = 0.0
    net_short_notional = 0.0
    long_hedge_notional = 0.0

    for leg in active:
        qty = leg.lots * leg.lot_size
        notional = spot * qty
        if leg.side == "SELL":
            net_short_notional += notional
            standalone_short_margin += notional * 0.14
        elif leg.option_type == "FUT":
            net_short_notional += notional
            standalone_short_margin += notional * 0.12
        else:
            long_hedge_notional += notional

    worst_loss = 0.0
    for iv_mult in iv_multipliers:
        scenario_pnl = np.zeros_like(spot_shocks)
        for leg in active:
            signed_qty = leg.lots * leg.lot_size * (1 if leg.side == "BUY" else -1)
            t_rem = max(time_to_expiry_years(as_of, leg.expiry), 1.0 / 365.0)
            if leg.option_type == "FUT":
                vals = spot_shocks - leg.entry_price
            else:
                res = greeks_black76_vectorized(
                    forward=spot_shocks,
                    strike=float(leg.strike or spot),
                    t_years=t_rem,
                    sigma=max(leg.entry_iv * iv_mult, 0.05),
                    is_call=(leg.option_type == "CE"),
                    r=r,
                )
                vals = res["price"] - leg.entry_price
            scenario_pnl += signed_qty * vals
        min_pnl = float(np.min(scenario_pnl))
        worst_loss = max(worst_loss, -min_pnl)

    # Floor SPAN proxy for pure long-option debit (premium paid) vs short/futures positions
    long_debit = sum(
        leg.lots * leg.lot_size * leg.entry_price
        for leg in active
        if leg.side == "BUY" and leg.option_type != "FUT"
    )
    span_proxy = max(worst_loss, long_debit)

    # Exposure margin (~2% on unhedged short/futures notional, reduced up to 60% by long option hedges)
    hedge_ratio = min(0.60, (long_hedge_notional / net_short_notional) * 0.60) if net_short_notional > 0 else 0.0
    exposure_proxy = net_short_notional * 0.02 * (1.0 - hedge_ratio)

    total_margin = round(span_proxy + exposure_proxy, 2)
    hedge_benefit = round(max(0.0, standalone_short_margin - total_margin), 2)

    return MarginBreakdown(
        span_proxy=round(span_proxy, 2),
        exposure_proxy=round(exposure_proxy, 2),
        total_margin=total_margin,
        hedge_benefit=hedge_benefit,
    )
