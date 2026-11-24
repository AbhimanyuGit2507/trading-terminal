"""Multi-expiry Payoff Graph, Breakevens, Max Profit/Loss, POP, and Net Greeks."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.special import ndtr

from app.core.calendar import expiry_settlement_datetime, time_to_expiry_years
from app.quant.black76 import greeks_black76_vectorized
from app.quant.charges import estimate_leg_charges

Side = Literal["BUY", "SELL"]
LegInstrumentType = Literal["CE", "PE", "FUT"]


@dataclass(frozen=True, slots=True)
class PayoffLeg:
    leg_id: str
    symbol: str
    expiry: date
    option_type: LegInstrumentType
    side: Side
    lots: int
    lot_size: int
    entry_price: float
    entry_iv: float
    strike: float | None = None
    forward_at_base: float | None = None
    enabled: bool = True
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    exchange: Literal["NSE_FNO", "BSE_FNO"] = "NSE_FNO"


@dataclass(frozen=True, slots=True)
class PayoffCurvePoint:
    spot: float
    expiry_pnl: float
    target_pnl: float


@dataclass(frozen=True, slots=True)
class NetGreeks:
    delta: float  # share/index-unit equivalent delta (signed_qty * option_delta)
    gamma: float
    theta: float  # daily INR decay across portfolio
    vega: float  # INR change per +1% IV shift across portfolio


@dataclass(frozen=True, slots=True)
class PayoffEvaluation:
    points: list[PayoffCurvePoint]
    breakevens: list[float]
    target_breakevens: list[float]
    max_profit: float | None  # None => Unlimited
    max_loss: float | None  # None => Unlimited
    max_profit_unlimited: bool
    max_loss_unlimited: bool
    risk_reward: float | None
    pop: float  # 0..100 probability of profit (%)
    net_greeks: NetGreeks
    current_mtm_pnl: float
    estimated_charges: float
    sd_1_low: float
    sd_1_high: float
    sd_2_low: float
    sd_2_high: float


def _build_spot_grid(
    spot: float,
    legs: list[PayoffLeg],
    atm_iv: float,
    max_t: float,
    num_points: int = 251,
) -> NDArray[np.float64]:
    strikes = [leg.strike for leg in legs if leg.strike is not None]
    min_ref = min([spot, *strikes]) if strikes else spot
    max_ref = max([spot, *strikes]) if strikes else spot
    vol_move = 3.5 * spot * max(atm_iv, 0.08) * math.sqrt(max(max_t, 1.0 / 365.0))
    pad = max(vol_move, 0.08 * spot)

    low = max(1.0, min_ref - pad)
    high = max_ref + pad
    base_grid = np.linspace(low, high, num_points, dtype=np.float64)
    if strikes:
        extras = np.asarray(strikes + [spot], dtype=np.float64)
        extras = extras[(extras >= low) & (extras <= high)]
        grid = np.unique(np.concatenate([base_grid, extras]))
    else:
        grid = np.unique(np.concatenate([base_grid, np.asarray([spot], dtype=np.float64)]))
    return grid


def _find_zero_crossings(xs: NDArray[np.float64], ys: NDArray[np.float64]) -> list[float]:
    roots: list[float] = []
    n = len(xs)
    for i in range(n - 1):
        y0, y1 = float(ys[i]), float(ys[i + 1])
        x0, x1 = float(xs[i]), float(xs[i + 1])
        if y0 == 0.0:
            if not roots or abs(roots[-1] - x0) > 1e-4:
                roots.append(round(x0, 2))
        elif (y0 < 0.0 < y1) or (y0 > 0.0 > y1):
            frac = -y0 / (y1 - y0)
            root = x0 + frac * (x1 - x0)
            if not roots or abs(roots[-1] - root) > 1e-4:
                roots.append(round(root, 2))
    if n > 0 and ys[-1] == 0.0:
        x_last = round(float(xs[-1]), 2)
        if not roots or abs(roots[-1] - x_last) > 1e-4:
            roots.append(x_last)
    return roots


def _evaluate_legs_at_datetime(
    spot_grid: NDArray[np.float64],
    legs: list[PayoffLeg],
    base_spot: float,
    base_dt: datetime,
    eval_dt: datetime,
    iv_shift_pct: float,
    r: float = 0.0,
) -> NDArray[np.float64]:
    total = np.zeros_like(spot_grid, dtype=np.float64)
    iv_delta = iv_shift_pct / 100.0

    for leg in legs:
        if not leg.enabled or leg.status != "OPEN":
            continue
        signed_qty = leg.lots * leg.lot_size * (1 if leg.side == "BUY" else -1)
        t_base = time_to_expiry_years(base_dt, leg.expiry)
        t_eval = time_to_expiry_years(eval_dt, leg.expiry)
        base_fwd = leg.forward_at_base if leg.forward_at_base is not None else base_spot
        basis = base_fwd - base_spot
        basis_scale = (t_eval / t_base) if t_base > 1e-9 else 0.0
        fwd_grid = np.maximum(spot_grid + basis * basis_scale, 0.01)

        if leg.option_type == "FUT":
            leg_vals = fwd_grid - leg.entry_price
        else:
            strike = float(leg.strike or base_spot)
            sigma = max(leg.entry_iv + iv_delta, 0.005)
            res = greeks_black76_vectorized(
                forward=fwd_grid,
                strike=strike,
                t_years=t_eval,
                sigma=sigma,
                is_call=(leg.option_type == "CE"),
                r=r,
            )
            leg_vals = res["price"] - leg.entry_price

        total += signed_qty * leg_vals

    return total


def _detect_unlimited(legs: list[PayoffLeg]) -> tuple[bool, bool]:
    """Analytically determine if Max Profit or Max Loss is unbounded as S -> inf or S -> 0."""
    # As S -> +inf: CE and FUT have +1 slope per unit qty; PE has 0 slope.
    upside_slope = 0.0
    # As S -> 0 (dS < 0): PE has -1 slope (increases value as S drops => +qty when S->0), FUT has -1 slope (decreases value as S drops)
    # Specifically, P&L(S) as S -> 0 changes by (net_fut_qty - net_put_qty) * S + const, so downward move (delta_S < 0) gives (net_put_qty - net_fut_qty) * |drop|.
    downside_gain_per_drop = 0.0

    for leg in legs:
        if not leg.enabled or leg.status != "OPEN":
            continue
        q = float(leg.lots * leg.lot_size * (1 if leg.side == "BUY" else -1))
        if leg.option_type == "CE":
            upside_slope += q
        elif leg.option_type == "PE":
            downside_gain_per_drop += q
        elif leg.option_type == "FUT":
            upside_slope += q
            downside_gain_per_drop -= q

    # Upside is unbounded only in S -> +inf; downside S is floored at 0 (so P&L at S=0 is finite!),
    # however in Indian index F&O convention, naked short PUT or long FUT down to 0 is huge finite loss,
    # while upside short CALL / short FUT has true unlimited loss and long CALL / long FUT has unlimited profit.
    max_profit_unlimited = upside_slope > 1e-9
    max_loss_unlimited = upside_slope < -1e-9
    return max_profit_unlimited, max_loss_unlimited


def _compute_pop(
    spot: float,
    breakevens: list[float],
    expiry_fn_values: NDArray[np.float64],
    spot_grid: NDArray[np.float64],
    atm_iv: float,
    t_years: float,
) -> float:
    """Compute risk-neutral log-normal Probability of Profit (%) from profitable intervals."""
    if len(spot_grid) < 2 or t_years <= 1e-6:
        idx = int(np.argmin(np.abs(spot_grid - spot)))
        return 100.0 if expiry_fn_values[idx] > 0 else 0.0

    sig = max(atm_iv, 0.05)
    sqrt_t = math.sqrt(t_years)

    def cdf_spot(x: float) -> float:
        if x <= 0.0:
            return 0.0
        z = (math.log(x / spot) + 0.5 * sig * sig * t_years) / (sig * sqrt_t)
        return float(ndtr(z))

    boundaries = [0.0, *sorted(breakevens), float("inf")]
    prob = 0.0
    for i in range(len(boundaries) - 1):
        lo, hi = boundaries[i], boundaries[i + 1]
        if hi == float("inf"):
            sample_x = max(lo * 1.05 + 1.0, float(spot_grid[-1]))
        elif lo == 0.0:
            sample_x = min(hi * 0.95, float(spot_grid[0]))
        else:
            sample_x = 0.5 * (lo + hi)

        # Evaluate sign at sample_x via linear interp on grid (or endpoint slope)
        if sample_x <= spot_grid[0]:
            val = float(expiry_fn_values[0])
        elif sample_x >= spot_grid[-1]:
            val = float(expiry_fn_values[-1])
        else:
            val = float(np.interp(sample_x, spot_grid, expiry_fn_values))

        if val > 0.0:
            p_hi = 1.0 if hi == float("inf") else cdf_spot(hi)
            p_lo = 0.0 if lo == 0.0 else cdf_spot(lo)
            prob += max(0.0, p_hi - p_lo)

    return round(min(100.0, max(0.0, prob * 100.0)), 2)


def evaluate_payoff(
    spot: float,
    legs: list[PayoffLeg],
    base_dt: datetime,
    target_spot: float | None = None,
    target_dt: datetime | None = None,
    iv_shift_pct: float = 0.0,
    realized_pnl: float = 0.0,
    include_charges: bool = False,
    atm_iv: float = 0.14,
    r: float = 0.0,
) -> PayoffEvaluation:
    """Evaluate expiry & What-If target MTM payoff curves, breakevens, POP, and Greeks."""
    eval_spot = target_spot if target_spot is not None else spot
    eval_dt = target_dt if target_dt is not None else base_dt
    active_legs = [leg for leg in legs if leg.enabled and leg.status == "OPEN"]

    charges = 0.0
    if include_charges:
        for leg in active_legs:
            qty = leg.lots * leg.lot_size
            charges += estimate_leg_charges(
                price=leg.entry_price,
                quantity=qty,
                side=leg.side,
                option_type=leg.option_type,
                exchange=leg.exchange,
            ).total

    net_offset = realized_pnl - charges

    if not active_legs:
        grid = _build_spot_grid(spot, [], atm_iv, 7.0 / 365.0)
        pts = [
            PayoffCurvePoint(
                spot=round(float(s), 2),
                expiry_pnl=round(net_offset, 2),
                target_pnl=round(net_offset, 2),
            )
            for s in grid
        ]
        vol = spot * max(atm_iv, 0.05) * math.sqrt(7.0 / 365.0)
        return PayoffEvaluation(
            points=pts,
            breakevens=[],
            target_breakevens=[],
            max_profit=round(net_offset, 2),
            max_loss=round(net_offset, 2),
            max_profit_unlimited=False,
            max_loss_unlimited=False,
            risk_reward=None,
            pop=100.0 if net_offset > 0 else 0.0,
            net_greeks=NetGreeks(0.0, 0.0, 0.0, 0.0),
            current_mtm_pnl=round(net_offset, 2),
            estimated_charges=round(charges, 2),
            sd_1_low=round(spot - vol, 2),
            sd_1_high=round(spot + vol, 2),
            sd_2_low=round(spot - 2.0 * vol, 2),
            sd_2_high=round(spot + 2.0 * vol, 2),
        )

    nearest_expiry = min(leg.expiry for leg in active_legs)
    nearest_exp_dt = expiry_settlement_datetime(nearest_expiry)
    max_t = max(time_to_expiry_years(base_dt, leg.expiry) for leg in active_legs)
    nearest_t = max(time_to_expiry_years(base_dt, nearest_expiry), 1.0 / 365.0)

    grid = _build_spot_grid(spot, active_legs, atm_iv, max_t)

    expiry_vals = (
        _evaluate_legs_at_datetime(
            grid, active_legs, spot, base_dt, nearest_exp_dt, iv_shift_pct, r=r
        )
        + net_offset
    )
    target_vals = (
        _evaluate_legs_at_datetime(grid, active_legs, spot, base_dt, eval_dt, iv_shift_pct, r=r)
        + net_offset
    )

    breakevens = _find_zero_crossings(grid, expiry_vals)
    target_breakevens = _find_zero_crossings(grid, target_vals)

    mp_unlim, ml_unlim = _detect_unlimited(active_legs)
    # Include S=0 boundary analytically for accurate finite max_loss / max_profit on puts/futs
    zero_grid = np.asarray([0.0], dtype=np.float64)
    val_at_zero = float(
        _evaluate_legs_at_datetime(
            zero_grid, active_legs, spot, base_dt, nearest_exp_dt, iv_shift_pct, r=r
        )[0]
        + net_offset
    )

    raw_max = max(float(np.max(expiry_vals)), val_at_zero)
    raw_min = min(float(np.min(expiry_vals)), val_at_zero)

    max_profit = None if mp_unlim else round(raw_max, 2)
    max_loss = None if ml_unlim else round(raw_min, 2)

    risk_reward: float | None = None
    if max_profit is not None and max_loss is not None and max_loss < 0.0:
        risk_reward = round(abs(max_profit / max_loss), 2)

    # Net Greeks & Current MTM at (spot, eval_dt)
    net_delta = 0.0
    net_gamma = 0.0
    net_theta = 0.0
    net_vega = 0.0
    iv_delta = iv_shift_pct / 100.0
    mtm_total = net_offset

    for leg in active_legs:
        signed_qty = float(leg.lots * leg.lot_size * (1 if leg.side == "BUY" else -1))
        t_base = time_to_expiry_years(base_dt, leg.expiry)
        t_eval = time_to_expiry_years(eval_dt, leg.expiry)
        base_fwd = leg.forward_at_base if leg.forward_at_base is not None else spot
        basis = base_fwd - spot
        basis_scale = (t_eval / t_base) if t_base > 1e-9 else 0.0
        fwd = max(eval_spot + basis * basis_scale, 0.01)

        if leg.option_type == "FUT":
            mtm_total += signed_qty * (fwd - leg.entry_price)
            net_delta += signed_qty * 1.0
        else:
            res = greeks_black76_vectorized(
                forward=fwd,
                strike=float(leg.strike or eval_spot),
                t_years=t_eval,
                sigma=max(leg.entry_iv + iv_delta, 0.005),
                is_call=(leg.option_type == "CE"),
                r=r,
            )
            mtm_total += signed_qty * (float(res["price"]) - leg.entry_price)
            net_delta += signed_qty * float(res["delta"])
            net_gamma += signed_qty * float(res["gamma"])
            net_theta += signed_qty * float(res["theta"])
            net_vega += signed_qty * float(res["vega"])

    avg_iv = float(np.mean([leg.entry_iv for leg in active_legs])) if active_legs else atm_iv
    pop = _compute_pop(spot, breakevens, expiry_vals, grid, avg_iv, nearest_t)

    vol = spot * max(avg_iv, 0.05) * math.sqrt(nearest_t)
    points = [
        PayoffCurvePoint(
            spot=round(float(grid[i]), 2),
            expiry_pnl=round(float(expiry_vals[i]), 2),
            target_pnl=round(float(target_vals[i]), 2),
        )
        for i in range(len(grid))
    ]

    return PayoffEvaluation(
        points=points,
        breakevens=breakevens,
        target_breakevens=target_breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        max_profit_unlimited=mp_unlim,
        max_loss_unlimited=ml_unlim,
        risk_reward=risk_reward,
        pop=pop,
        net_greeks=NetGreeks(
            delta=round(net_delta, 2),
            gamma=round(net_gamma, 4),
            theta=round(net_theta, 2),
            vega=round(net_vega, 2),
        ),
        current_mtm_pnl=round(mtm_total, 2),
        estimated_charges=round(charges, 2),
        sd_1_low=round(spot - vol, 2),
        sd_1_high=round(spot + vol, 2),
        sd_2_low=round(spot - 2.0 * vol, 2),
        sd_2_high=round(spot + 2.0 * vol, 2),
    )
