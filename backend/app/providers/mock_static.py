"""MockStaticProvider: SVI-consistent static or live-jitter Indian F&O MarketDataProvider."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, datetime

import numpy as np

from app.core.calendar import (
    IST,
    ExpiryInfo,
    InstrumentSpec,
    get_expiries,
    get_instrument_spec,
    round_to_tick,
    time_to_expiry_years,
    to_ist,
)
from app.core.contracts import parse_contract_id
from app.quant.black76 import greeks_black76_scalar
from app.quant.mock_chain import (
    DEFAULT_SPOTS,
    DEFAULT_VIX,
    MockChainData,
    generate_mock_option_chain,
    svi_skew_iv,
)
from app.schemas.domain import (
    IndexSymbol,
    LegQuoteSchema,
    OptionChainRowSchema,
    WsTickFrameSchema,
)


class MockStaticProvider:
    """MarketDataProvider backed by SVI + Black-76 option chain generator.

    - `deterministic=True`: returns exact reproducible prices for tests.
    - `live_jitter=True`: applies subtle mean-reverting spot & VIX micro-oscillations
      across consecutive ticks so Milestone 3/4 UI & WS pipelines can be stress-tested.
    """

    def __init__(
        self,
        deterministic: bool = True,
        live_jitter: bool = False,
        seed: int = 42,
    ) -> None:
        self.deterministic = deterministic
        self.live_jitter = live_jitter and not deterministic
        self._rng = random.Random(seed)
        self._spots: dict[str, float] = dict(DEFAULT_SPOTS)
        self._vix: float = DEFAULT_VIX
        self._tick_seq: int = 0

    def _current_spot_and_vix(self, symbol: str) -> tuple[float, float]:
        sym = symbol.upper()
        base_spot = DEFAULT_SPOTS[sym]
        if not self.live_jitter:
            return base_spot, DEFAULT_VIX

        cur = self._spots.get(sym, base_spot)
        # Mean-reverting micro random walk (~0.025% std dev per tick)
        revert = 0.04 * (base_spot - cur)
        shock = self._rng.gauss(0.0, base_spot * 0.00025)
        nxt = round(max(100.0, cur + revert + shock), 2)
        self._spots[sym] = nxt

        vix_revert = 0.05 * (DEFAULT_VIX - self._vix)
        self._vix = round(max(9.0, min(40.0, self._vix + vix_revert + self._rng.gauss(0.0, 0.04))), 2)
        return nxt, self._vix

    async def get_instrument_spec(
        self, symbol: str, as_of: datetime | date | None = None
    ) -> InstrumentSpec:
        return get_instrument_spec(symbol, as_of)

    async def get_expiries(
        self, symbol: str, as_of: datetime | None = None, count: int = 8
    ) -> list[ExpiryInfo]:
        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        return get_expiries(symbol, now_ist, count=count)

    async def get_option_chain(
        self, symbol: str, expiry: date | None = None, as_of: datetime | None = None
    ) -> tuple[MockChainData, list[ExpiryInfo]]:
        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        expiries = get_expiries(symbol, now_ist)
        if not expiries:
            raise ValueError(f"No active expiries found for {symbol}")
        chosen_expiry = expiry or expiries[0].expiry_date
        spot_val, vix_val = self._current_spot_and_vix(symbol)
        seed_offset = 42 if self.deterministic else (42 + (self._tick_seq % 997))
        chain = generate_mock_option_chain(
            symbol=symbol,
            expiry=chosen_expiry,
            as_of=now_ist,
            spot_override=spot_val,
            vix_override=vix_val,
            seed=seed_offset,
        )
        return chain, expiries

    async def get_contract_quotes(
        self, contract_ids: list[str], as_of: datetime | None = None
    ) -> dict[str, LegQuoteSchema]:
        """Batch-fetch quotes across multiple expiries/symbols for activeLegQuotes."""
        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        grouped: dict[tuple[str, date], list[tuple[str, str, float | None]]] = defaultdict(list)

        for cid in contract_ids:
            parsed = parse_contract_id(cid)
            if parsed.kind == "SPOT" or parsed.expiry is None:
                continue
            grouped[(parsed.symbol, parsed.expiry)].append((cid, parsed.kind, parsed.strike))

        quotes: dict[str, LegQuoteSchema] = {}
        for (sym, exp_date), items in grouped.items():
            chain, _ = await self.get_option_chain(sym, expiry=exp_date, as_of=now_ist)
            by_strike = {row.strike: row for row in chain.rows}
            spec = get_instrument_spec(sym, exp_date)
            t_years = max(time_to_expiry_years(now_ist, exp_date), 1.0 / (365.0 * 24.0))

            for cid, kind, strike in items:
                if kind == "FUT":
                    spread = max(spec.tick_size, round_to_tick(chain.futures_price * 0.0002, spec.tick_size))
                    quotes[cid] = LegQuoteSchema(
                        contract_id=cid,
                        expiry=exp_date,
                        strike=None,
                        option_type="FUT",
                        ltp=chain.futures_price,
                        bid=round(chain.futures_price - spread, 2),
                        ask=round(chain.futures_price + spread, 2),
                        iv=0.0,
                        delta=1.0,
                        gamma=0.0,
                        theta=0.0,
                        vega=0.0,
                        forward_price=chain.forward_price,
                        updated_at=now_ist,
                    )
                    continue

                assert strike is not None
                row = by_strike.get(float(strike))
                if row is not None:
                    if kind == "CE":
                        quotes[cid] = LegQuoteSchema(
                            contract_id=cid,
                            expiry=exp_date,
                            strike=row.strike,
                            option_type="CE",
                            ltp=row.ce_ltp,
                            bid=row.ce_bid,
                            ask=row.ce_ask,
                            iv=row.ce_iv,
                            delta=row.ce_delta,
                            gamma=row.ce_gamma,
                            theta=row.ce_theta,
                            vega=row.ce_vega,
                            forward_price=chain.forward_price,
                            updated_at=now_ist,
                        )
                    else:
                        quotes[cid] = LegQuoteSchema(
                            contract_id=cid,
                            expiry=exp_date,
                            strike=row.strike,
                            option_type="PE",
                            ltp=row.pe_ltp,
                            bid=row.pe_bid,
                            ask=row.pe_ask,
                            iv=row.pe_iv,
                            delta=row.pe_delta,
                            gamma=row.pe_gamma,
                            theta=row.pe_theta,
                            vega=row.pe_vega,
                            forward_price=chain.forward_price,
                            updated_at=now_ist,
                        )
                else:
                    # Fallback for far wing strikes outside +/-30 chain window
                    term_adj = 1.0 + 0.04 * math.exp(-t_years * 52.0)
                    atm_iv = (chain.india_vix / 100.0) * term_adj
                    iv_val = float(
                        svi_skew_iv(
                            np.array([strike], dtype=np.float64),
                            chain.forward_price,
                            atm_iv,
                            t_years,
                        )[0]
                    )
                    g = greeks_black76_scalar(
                        forward=chain.forward_price,
                        strike=strike,
                        t_years=t_years,
                        sigma=iv_val,
                        option_type="CE" if kind == "CE" else "PE",
                        r=0.0,
                    )
                    ltp = round_to_tick(g.price, spec.tick_size)
                    spread = max(spec.tick_size, round_to_tick(ltp * 0.004, spec.tick_size))
                    quotes[cid] = LegQuoteSchema(
                        contract_id=cid,
                        expiry=exp_date,
                        strike=strike,
                        option_type="CE" if kind == "CE" else "PE",
                        ltp=ltp,
                        bid=max(spec.tick_size, round(ltp - spread, 2)),
                        ask=round(ltp + spread, 2),
                        iv=round(iv_val * 100.0, 2),
                        delta=round(g.delta, 4),
                        gamma=round(g.gamma, 6),
                        theta=round(g.theta, 2),
                        vega=round(g.vega, 2),
                        forward_price=chain.forward_price,
                        updated_at=now_ist,
                    )
        return quotes

    async def build_tick_frame(
        self,
        symbol: IndexSymbol,
        chain_expiry: date | None,
        active_contracts: list[str],
        as_of: datetime | None = None,
    ) -> WsTickFrameSchema:
        self._tick_seq += 1
        now_ist = to_ist(as_of) if as_of is not None else datetime.now(IST)
        chain, _ = await self.get_option_chain(symbol, expiry=chain_expiry, as_of=now_ist)
        leg_quotes = (
            await self.get_contract_quotes(active_contracts, as_of=now_ist)
            if active_contracts
            else {}
        )
        return WsTickFrameSchema(
            type="tick",
            symbol=symbol,
            chain_expiry=chain.expiry,
            as_of=chain.as_of,
            spot=chain.spot,
            futures_price=chain.futures_price,
            forward_price=chain.forward_price,
            india_vix=chain.india_vix,
            atm_strike=chain.atm_strike,
            chain_deltas=[OptionChainRowSchema.model_validate(r, from_attributes=True) for r in chain.rows],
            leg_quotes=leg_quotes,
        )
