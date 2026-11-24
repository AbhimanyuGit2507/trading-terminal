"""MarginProvider implementation wrapping the stress-grid portfolio estimator."""

from __future__ import annotations

from datetime import datetime

from app.quant.margin import MarginBreakdown, estimate_portfolio_margin
from app.quant.payoff import PayoffLeg


class StressMarginProvider:
    """Phase 1-3 portfolio margin estimator (swaps to Dhan SPAN API in Phase 3/4)."""

    def __init__(self, risk_free_rate: float = 0.0) -> None:
        self._r = risk_free_rate

    async def estimate_margin(
        self,
        legs: list[PayoffLeg],
        spot: float,
        as_of: datetime,
    ) -> MarginBreakdown:
        return estimate_portfolio_margin(legs=legs, spot=spot, as_of=as_of, r=self._r)

