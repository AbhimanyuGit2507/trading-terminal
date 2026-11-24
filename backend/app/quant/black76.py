"""Vectorized Black-76 option pricing, Greeks, synthetic forward, and IV solver.

Conventions locked for StockMock parity:
- r = 0.0 default (pure Black-76 on expiry-specific Synthetic Forward).
- Theta returned as per-calendar-day decay (annual_theta / 365.0).
- Vega returned per 1% (0.01) move in implied volatility.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import brentq
from scipy.special import ndtr

OptionType = Literal["CE", "PE"]

INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)
T_FLOOR = 1e-6
SIGMA_FLOOR = 1e-4


@dataclass(frozen=True, slots=True)
class GreeksResult:
    price: float
    delta: float
    gamma: float
    theta: float  # per-calendar-day decay
    vega: float  # per 1% IV change


def _norm_cdf(x: NDArray[np.float64] | float) -> NDArray[np.float64] | float:
    return ndtr(x)


def _norm_pdf(x: NDArray[np.float64]) -> NDArray[np.float64]:
    return INV_SQRT_2PI * np.exp(-0.5 * x * x)


def price_black76_scalar(
    forward: float,
    strike: float,
    t_years: float,
    sigma: float,
    option_type: OptionType,
    r: float = 0.0,
) -> float:
    """Scalar Black-76 price for a European CE or PE option."""
    if t_years <= 0.0:
        return max(forward - strike, 0.0) if option_type == "CE" else max(strike - forward, 0.0)

    f = max(forward, 1e-8)
    k = max(strike, 1e-8)
    t_eff = max(t_years, T_FLOOR)
    sig = max(sigma, SIGMA_FLOOR)
    sqrt_t = math.sqrt(t_eff)
    df = math.exp(-r * t_eff)

    d1 = (math.log(f / k) + 0.5 * sig * sig * t_eff) / (sig * sqrt_t)
    d2 = d1 - sig * sqrt_t

    nd1 = float(ndtr(d1))
    nd2 = float(ndtr(d2))

    if option_type == "CE":
        return df * (f * nd1 - k * nd2)
    return df * (k * (1.0 - nd2) - f * (1.0 - nd1))


def greeks_black76_scalar(
    forward: float,
    strike: float,
    t_years: float,
    sigma: float,
    option_type: OptionType,
    r: float = 0.0,
) -> GreeksResult:
    """Scalar Black-76 price and Greeks (daily theta, 1%-scaled vega)."""
    if t_years <= 0.0:
        if option_type == "CE":
            intrinsic = max(forward - strike, 0.0)
            delta = 1.0 if forward > strike else 0.0
        else:
            intrinsic = max(strike - forward, 0.0)
            delta = -1.0 if forward < strike else 0.0
        return GreeksResult(price=intrinsic, delta=delta, gamma=0.0, theta=0.0, vega=0.0)

    f = max(forward, 1e-8)
    k = max(strike, 1e-8)
    t_eff = max(t_years, T_FLOOR)
    sig = max(sigma, SIGMA_FLOOR)
    sqrt_t = math.sqrt(t_eff)
    df = math.exp(-r * t_eff)

    d1 = (math.log(f / k) + 0.5 * sig * sig * t_eff) / (sig * sqrt_t)
    d2 = d1 - sig * sqrt_t

    nd1 = float(ndtr(d1))
    nd2 = float(ndtr(d2))
    pdf1 = INV_SQRT_2PI * math.exp(-0.5 * d1 * d1)

    if option_type == "CE":
        price = df * (f * nd1 - k * nd2)
        delta = df * nd1
        theta_annual = -(df * f * pdf1 * sig) / (2.0 * sqrt_t) + r * price
    else:
        price = df * (k * (1.0 - nd2) - f * (1.0 - nd1))
        delta = df * (nd1 - 1.0)
        theta_annual = -(df * f * pdf1 * sig) / (2.0 * sqrt_t) + r * price

    gamma = df * pdf1 / (f * sig * sqrt_t)
    vega = df * f * pdf1 * sqrt_t * 0.01
    theta_daily = theta_annual / 365.0

    return GreeksResult(
        price=price,
        delta=delta,
        gamma=gamma,
        theta=theta_daily,
        vega=vega,
    )


def greeks_black76_vectorized(
    forward: NDArray[np.float64] | float,
    strike: NDArray[np.float64] | float,
    t_years: NDArray[np.float64] | float,
    sigma: NDArray[np.float64] | float,
    is_call: NDArray[np.bool_] | bool,
    r: float = 0.0,
) -> dict[str, NDArray[np.float64]]:
    """Vectorized Black-76 pricing and Greeks across NumPy arrays."""
    f = np.maximum(np.asarray(forward, dtype=np.float64), 1e-8)
    k = np.maximum(np.asarray(strike, dtype=np.float64), 1e-8)
    t = np.asarray(t_years, dtype=np.float64)
    sig = np.maximum(np.asarray(sigma, dtype=np.float64), SIGMA_FLOOR)
    call_mask = np.asarray(is_call, dtype=np.bool_)

    f, k, t, sig, call_mask = np.broadcast_arrays(f, k, t, sig, call_mask)

    expired = t <= 0.0
    t_eff = np.maximum(t, T_FLOOR)
    sqrt_t = np.sqrt(t_eff)
    df = np.exp(-r * t_eff)

    d1 = (np.log(f / k) + 0.5 * sig * sig * t_eff) / (sig * sqrt_t)
    d2 = d1 - sig * sqrt_t

    nd1 = ndtr(d1)
    nd2 = ndtr(d2)
    pdf1 = _norm_pdf(d1)

    call_price = df * (f * nd1 - k * nd2)
    put_price = df * (k * (1.0 - nd2) - f * (1.0 - nd1))
    price = np.where(call_mask, call_price, put_price)

    delta = np.where(call_mask, df * nd1, df * (nd1 - 1.0))
    gamma = df * pdf1 / (f * sig * sqrt_t)
    vega = df * f * pdf1 * sqrt_t * 0.01
    theta_annual = -(df * f * pdf1 * sig) / (2.0 * sqrt_t) + r * price
    theta = theta_annual / 365.0

    if np.any(expired):
        intrinsic = np.where(call_mask, np.maximum(f - k, 0.0), np.maximum(k - f, 0.0))
        exp_delta = np.where(
            call_mask,
            np.where(f > k, 1.0, 0.0),
            np.where(f < k, -1.0, 0.0),
        )
        price = np.where(expired, intrinsic, price)
        delta = np.where(expired, exp_delta, delta)
        gamma = np.where(expired, 0.0, gamma)
        theta = np.where(expired, 0.0, theta)
        vega = np.where(expired, 0.0, vega)

    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
    }


def compute_synthetic_forward(
    strikes: NDArray[np.float64] | list[float],
    call_ltps: NDArray[np.float64] | list[float],
    put_ltps: NDArray[np.float64] | list[float],
    spot_fallback: float,
    r: float = 0.0,
    t_years: float = 0.0,
) -> tuple[float, float]:
    """Derive expiry-specific Synthetic Forward F_T = K_atm + e^(rT)*(C_atm - P_atm).

    Selects the strike minimizing |C - P| (ignoring zero/stale quotes).
    Returns (forward_price, atm_strike).
    """
    k_arr = np.asarray(strikes, dtype=np.float64)
    c_arr = np.asarray(call_ltps, dtype=np.float64)
    p_arr = np.asarray(put_ltps, dtype=np.float64)

    valid = (k_arr > 0) & (c_arr > 0) & (p_arr > 0)
    if not np.any(valid):
        if len(k_arr) == 0:
            return spot_fallback, spot_fallback
        idx = int(np.argmin(np.abs(k_arr - spot_fallback)))
        return spot_fallback * math.exp(r * max(t_years, 0.0)), float(k_arr[idx])

    valid_indices = np.where(valid)[0]
    diffs = np.abs(c_arr[valid_indices] - p_arr[valid_indices])
    best_pos = int(valid_indices[int(np.argmin(diffs))])
    k_atm = float(k_arr[best_pos])
    df_inv = math.exp(r * max(t_years, 0.0))
    fwd = k_atm + df_inv * (float(c_arr[best_pos]) - float(p_arr[best_pos]))
    return max(fwd, 1e-4), k_atm


def implied_volatility_black76(
    market_price: float,
    forward: float,
    strike: float,
    t_years: float,
    option_type: OptionType,
    r: float = 0.0,
) -> float:
    """Solve Black-76 implied volatility with Newton-Raphson + Brent fallback."""
    if t_years <= 0.0 or market_price <= 0.0:
        return 0.0

    t_eff = max(t_years, T_FLOOR)
    df = math.exp(-r * t_eff)
    intrinsic = df * (
        max(forward - strike, 0.0) if option_type == "CE" else max(strike - forward, 0.0)
    )
    if market_price <= intrinsic + 1e-6:
        return SIGMA_FLOOR

    # Brenner-Subrahmanyam ATM seed
    sigma = max(0.05, min(2.0, math.sqrt(2.0 * math.pi / t_eff) * (market_price / max(forward, 1.0))))

    for _ in range(12):
        g = greeks_black76_scalar(forward, strike, t_eff, sigma, option_type, r)
        diff = g.price - market_price
        if abs(diff) < 1e-6:
            return float(sigma)
        vega_raw = g.vega * 100.0
        if vega_raw < 1e-7:
            break
        step = diff / vega_raw
        sigma = max(SIGMA_FLOOR, min(5.0, sigma - step))

    def obj(s: float) -> float:
        return price_black76_scalar(forward, strike, t_eff, s, option_type, r) - market_price

    low, high = SIGMA_FLOOR, 5.0
    try:
        if obj(low) * obj(high) <= 0:
            return float(brentq(obj, low, high, xtol=1e-6, maxiter=60))
    except ValueError:
        pass
    return float(max(SIGMA_FLOOR, min(5.0, sigma)))
