"""Realistic Indian F&O Option Chain generator with SVI-inspired skew and OI walls."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np

from app.core.calendar import (
    get_instrument_spec,
    round_to_tick,
    time_to_expiry_years,
    to_ist,
)
from app.core.contracts import build_future_contract_id, build_option_contract_id
from app.quant.black76 import compute_synthetic_forward, greeks_black76_vectorized

DEFAULT_SPOTS: dict[str, float] = {
    "NIFTY": 24350.0,
    "BANKNIFTY": 52240.0,
    "FINNIFTY": 23820.0,
    "SENSEX": 80180.0,
}

DEFAULT_VIX = 13.85


@dataclass(frozen=True, slots=True)
class MockOptionRow:
    strike: float
    ce_contract_id: str
    pe_contract_id: str
    ce_ltp: float
    ce_bid: float
    ce_ask: float
    ce_iv: float
    ce_delta: float
    ce_gamma: float
    ce_theta: float
    ce_vega: float
    ce_oi: int
    ce_oi_change: int
    pe_ltp: float
    pe_bid: float
    pe_ask: float
    pe_iv: float
    pe_delta: float
    pe_gamma: float
    pe_theta: float
    pe_vega: float
    pe_oi: int
    pe_oi_change: int


@dataclass(frozen=True, slots=True)
class MockChainData:
    symbol: str
    exchange: str
    expiry: date
    as_of: datetime
    spot: float
    futures_price: float
    forward_price: float
    india_vix: float
    atm_strike: float
    lot_size: int
    strike_step: int
    futures_contract_id: str
    rows: list[MockOptionRow]


def svi_skew_iv(
    strikes: np.ndarray,
    forward: float,
    atm_iv: float,
    t_years: float,
) -> np.ndarray:
    """Generate realistic Indian index SVI-like volatility smile/skew.

    Downside Puts carry steeper crash skew; far OTM Calls show mild wing convexity.
    """
    k = np.log(np.maximum(strikes, 1.0) / max(forward, 1.0))
    # Slight term-structure scaling: 0DTE/short expiries exhibit sharper wings
    wing_scale = min(1.6, max(0.85, 0.12 / math.sqrt(max(t_years, 2.0 / 365.0))))
    alpha = -0.34 * wing_scale
    beta = 0.95 * wing_scale
    iv = atm_iv + alpha * k + beta * (k * k)
    return np.clip(iv, 0.06, 1.25)


def generate_mock_option_chain(
    symbol: str,
    expiry: date,
    as_of: datetime | None = None,
    spot_override: float | None = None,
    vix_override: float | None = None,
    strikes_each_side: int = 30,
    seed: int = 42,
) -> MockChainData:
    """Generate a 61+ strike Indian F&O option chain with Black-76 consistency."""
    sym = symbol.upper()
    now_ist = to_ist(as_of) if as_of is not None else datetime.now().astimezone()
    now_ist = to_ist(now_ist)
    spec = get_instrument_spec(sym, expiry)

    spot = float(spot_override if spot_override is not None else DEFAULT_SPOTS[sym])
    vix = float(vix_override if vix_override is not None else DEFAULT_VIX)

    t_years = max(time_to_expiry_years(now_ist, expiry), 1.0 / (365.0 * 24.0))
    # Modest cost-of-carry basis for futures/synthetic forward (~6.5% annualized carry)
    futures_price = round_to_tick(spot * math.exp(0.065 * t_years), spec.tick_size)

    atm_strike = float(round(spot / spec.strike_step) * spec.strike_step)
    strikes = np.array(
        [atm_strike + i * spec.strike_step for i in range(-strikes_each_side, strikes_each_side + 1)],
        dtype=np.float64,
    )

    # Term-structure ATM IV anchored to India VIX
    term_adj = 1.0 + 0.04 * math.exp(-t_years * 52.0)
    atm_iv = (vix / 100.0) * term_adj
    ivs = svi_skew_iv(strikes, futures_price, atm_iv, t_years)

    ce_greeks = greeks_black76_vectorized(
        forward=futures_price,
        strike=strikes,
        t_years=t_years,
        sigma=ivs,
        is_call=True,
        r=0.0,
    )
    pe_greeks = greeks_black76_vectorized(
        forward=futures_price,
        strike=strikes,
        t_years=t_years,
        sigma=ivs,
        is_call=False,
        r=0.0,
    )

    rng = np.random.default_rng(seed + int(atm_strike))
    dist_steps = np.abs(strikes - atm_strike) / spec.strike_step

    ce_ltps = np.array([round_to_tick(float(p), spec.tick_size) for p in ce_greeks["price"]])
    pe_ltps = np.array([round_to_tick(float(p), spec.tick_size) for p in pe_greeks["price"]])

    # Re-derive synthetic forward directly from ATM Call-Put parity on rounded LTPs
    fwd_price, syn_atm = compute_synthetic_forward(
        strikes=strikes,
        call_ltps=ce_ltps,
        put_ltps=pe_ltps,
        spot_fallback=futures_price,
        r=0.0,
        t_years=t_years,
    )

    rows: list[MockOptionRow] = []
    for i, k in enumerate(strikes):
        k_val = float(k)
        # Round-number strike OI walls (500/1000 multiples)
        is_major_wall = int(k_val) % (spec.strike_step * 10) == 0
        wall_mult = 2.4 if is_major_wall else (1.5 if int(k_val) % (spec.strike_step * 5) == 0 else 1.0)
        base_oi = int(max(12000, 1_800_000 * math.exp(-0.018 * (dist_steps[i] ** 1.4)) * wall_mult))

        ce_skew_oi = 1.35 if k_val >= atm_strike else 0.45
        pe_skew_oi = 1.35 if k_val <= atm_strike else 0.45
        ce_oi = int(base_oi * ce_skew_oi * float(rng.uniform(0.85, 1.15)))
        pe_oi = int(base_oi * pe_skew_oi * float(rng.uniform(0.85, 1.15)))
        ce_oi_chg = int(ce_oi * float(rng.uniform(-0.12, 0.28)))
        pe_oi_chg = int(pe_oi * float(rng.uniform(-0.12, 0.28)))

        ce_ltp = float(ce_ltps[i])
        pe_ltp = float(pe_ltps[i])
        ce_spread = max(spec.tick_size, round_to_tick(ce_ltp * 0.004, spec.tick_size))
        pe_spread = max(spec.tick_size, round_to_tick(pe_ltp * 0.004, spec.tick_size))

        rows.append(
            MockOptionRow(
                strike=k_val,
                ce_contract_id=build_option_contract_id(spec.exchange, sym, expiry, k_val, "CE"),
                pe_contract_id=build_option_contract_id(spec.exchange, sym, expiry, k_val, "PE"),
                ce_ltp=ce_ltp,
                ce_bid=max(spec.tick_size, round(ce_ltp - ce_spread, 2)),
                ce_ask=round(ce_ltp + ce_spread, 2),
                ce_iv=round(float(ivs[i]) * 100.0, 2),
                ce_delta=round(float(ce_greeks["delta"][i]), 4),
                ce_gamma=round(float(ce_greeks["gamma"][i]), 6),
                ce_theta=round(float(ce_greeks["theta"][i]), 2),
                ce_vega=round(float(ce_greeks["vega"][i]), 2),
                ce_oi=ce_oi,
                ce_oi_change=ce_oi_chg,
                pe_ltp=pe_ltp,
                pe_bid=max(spec.tick_size, round(pe_ltp - pe_spread, 2)),
                pe_ask=round(pe_ltp + pe_spread, 2),
                pe_iv=round(float(ivs[i]) * 100.0, 2),
                pe_delta=round(float(pe_greeks["delta"][i]), 4),
                pe_gamma=round(float(pe_greeks["gamma"][i]), 6),
                pe_theta=round(float(pe_greeks["theta"][i]), 2),
                pe_vega=round(float(pe_greeks["vega"][i]), 2),
                pe_oi=pe_oi,
                pe_oi_change=pe_oi_chg,
            )
        )

    return MockChainData(
        symbol=sym,
        exchange=spec.exchange,
        expiry=expiry,
        as_of=now_ist,
        spot=round(spot, 2),
        futures_price=round(futures_price, 2),
        forward_price=round(fwd_price, 2),
        india_vix=round(vix, 2),
        atm_strike=syn_atm,
        lot_size=spec.lot_size,
        strike_step=spec.strike_step,
        futures_contract_id=build_future_contract_id(spec.exchange, sym, expiry),
        rows=rows,
    )
