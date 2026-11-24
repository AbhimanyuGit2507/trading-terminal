"""Synthetic 1-minute historical options generator for local Parquet replay testing."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from app.core.calendar import (
    IST,
    get_expiries,
    get_instrument_spec,
    is_trading_day,
    round_to_tick,
    time_to_expiry_years,
)
from app.quant.black76 import greeks_black76_vectorized
from app.quant.mock_chain import DEFAULT_SPOTS, DEFAULT_VIX, svi_skew_iv
from app.services.historical_ingestor import (
    HistoricalOptionBar,
    IngestionStats,
    write_parquet_partitions,
)


def _recent_trading_days(end_date: date, count: int) -> list[date]:
    days: list[date] = []
    cur = end_date
    while len(days) < count:
        if is_trading_day(cur):
            days.append(cur)
        cur -= timedelta(days=1)
    days.reverse()
    return days


def generate_synthetic_history(
    parquet_dir: str | Path,
    symbols: tuple[str, ...] = ("NIFTY", "BANKNIFTY"),
    end_date: date = date(2026, 11, 25),
    trading_days: int = 10,
    strikes_each_side: int = 15,
    seed: int = 2026,
) -> list[IngestionStats]:
    """Generate realistic 1-minute OHLCV/OI/IV Parquet bars across multiple trading & expiry days."""
    days = _recent_trading_days(end_date, trading_days)
    results: list[IngestionStats] = []

    for sym_idx, sym in enumerate(symbols):
        sym_u = sym.upper()
        rng = np.random.default_rng(seed + sym_idx * 101)
        spot = float(DEFAULT_SPOTS[sym_u])
        vix = float(DEFAULT_VIX)
        bars: list[HistoricalOptionBar] = []

        for day in days:
            spec = get_instrument_spec(sym_u, day)
            session_open = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
            expiries = get_expiries(sym_u, session_open, count=2)
            primary_exp = expiries[0].expiry_date
            next_exp = expiries[1].expiry_date if len(expiries) > 1 else primary_exp
            is_expiry_day = primary_exp == day

            # Center strike grid on day's opening ATM (+/- strikes_each_side)
            open_atm = float(round(spot / spec.strike_step) * spec.strike_step)
            strikes = np.array(
                [
                    open_atm + i * spec.strike_step
                    for i in range(-strikes_each_side, strikes_each_side + 1)
                ],
                dtype=np.float64,
            )

            # Intraday spot path: 375 bars (09:15 to 15:29 IST)
            shocks = rng.normal(0.0, spot * 0.00042, size=375)
            # Mild opening move + intraday drift
            spot_path = np.empty(375, dtype=np.float64)
            cur_s = spot
            for m in range(375):
                cur_s = max(100.0, cur_s + shocks[m])
                spot_path[m] = round(cur_s, 2)
            spot = float(spot_path[-1])

            # Expiry-day IV crush profile
            vix_day = max(9.5, min(32.0, vix + float(rng.normal(0.0, 0.35))))
            vix = vix_day

            for m in range(375):
                ts_ist = session_open + timedelta(minutes=m)
                ts_naive = ts_ist.replace(tzinfo=None)
                s_val = float(spot_path[m])

                # Gentle afternoon IV crush especially on expiry days
                intraday_frac = m / 374.0
                crush_mult = (1.0 - 0.14 * intraday_frac) if is_expiry_day else (1.0 - 0.03 * intraday_frac)

                target_exps = [primary_exp]
                if next_exp != primary_exp and m % 5 == 0:
                    # Also populate 5-min snapshots for next expiry to support Calendar Spread replay
                    target_exps.append(next_exp)

                for exp_d in target_exps:
                    t_years = max(time_to_expiry_years(ts_ist, exp_d), 1.0 / (365.0 * 24.0))
                    fut_val = round(s_val * math.exp(0.065 * t_years), 2)
                    atm_iv = (vix_day / 100.0) * crush_mult
                    ivs = svi_skew_iv(strikes, fut_val, atm_iv, t_years)

                    ce_res = greeks_black76_vectorized(fut_val, strikes, t_years, ivs, True, r=0.0)
                    pe_res = greeks_black76_vectorized(fut_val, strikes, t_years, ivs, False, r=0.0)

                    ce_prices = ce_res["price"]
                    pe_prices = pe_res["price"]

                    for k_idx, k_val in enumerate(strikes):
                        dist = abs(k_val - open_atm) / spec.strike_step
                        # Simulate realistic far-OTM missing bars on ~12% of outer strikes
                        if dist >= 11 and ((m + k_idx) % 8 == 0):
                            continue

                        oi_base = int(
                            max(15000, 1_400_000 * math.exp(-0.02 * (dist**1.35)) * (1.0 + 0.25 * intraday_frac))
                        )
                        vol_base = int(max(100, (12000 / (1.0 + dist * 0.4))))

                        for opt_type, px_arr in (("CE", ce_prices), ("PE", pe_prices)):
                            c_px = round_to_tick(float(px_arr[k_idx]), spec.tick_size)
                            spread = max(spec.tick_size, round(c_px * 0.004, 2))
                            bars.append(
                                HistoricalOptionBar(
                                    timestamp_ist=ts_naive,
                                    symbol=sym_u,
                                    expiry=exp_d,
                                    strike=float(k_val),
                                    option_type=opt_type,
                                    open=c_px,
                                    high=round_to_tick(c_px + spread, spec.tick_size),
                                    low=max(spec.tick_size, round_to_tick(c_px - spread, spec.tick_size)),
                                    close=c_px,
                                    volume=vol_base,
                                    oi=oi_base,
                                    iv=round(float(ivs[k_idx]), 6),
                                    spot_close=s_val,
                                    futures_close=fut_val,
                                )
                            )

        files_written = write_parquet_partitions(parquet_dir, bars)
        results.append(
            IngestionStats(
                symbol=sym_u,
                bars_written=len(bars),
                files_written=files_written,
                iv_backfilled=0,
                requests_made=0,
            )
        )

    return results
