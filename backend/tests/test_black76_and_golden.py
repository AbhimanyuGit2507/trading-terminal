"""Black-76 quant tests and golden JSON vector generator for TS parity verification."""

import json
import math
from datetime import date, datetime
from pathlib import Path

import numpy as np

from app.core.calendar import IST
from app.quant.black76 import (
    compute_synthetic_forward,
    greeks_black76_scalar,
    greeks_black76_vectorized,
    implied_volatility_black76,
)
from app.quant.mock_chain import generate_mock_option_chain
from app.quant.payoff import PayoffLeg, evaluate_payoff

ROOT_DIR = Path(__file__).resolve().parents[2]
GOLDEN_PATH = ROOT_DIR / "shared" / "golden" / "quant_vectors.json"


def test_put_call_parity_and_iv_recovery() -> None:
    fwd = 24410.0
    strike = 24300.0
    t = 14.0 / 365.0
    sigma = 0.165

    ce = greeks_black76_scalar(fwd, strike, t, sigma, "CE", r=0.0)
    pe = greeks_black76_scalar(fwd, strike, t, sigma, "PE", r=0.0)

    # Put-Call Parity with r=0: C - P == F - K, and Call Delta - Put Delta == 1.0
    assert math.isclose(ce.price - pe.price, fwd - strike, abs_tol=1e-9)
    assert math.isclose(ce.delta - pe.delta, 1.0, abs_tol=1e-9)
    assert ce.theta < 0.0 and pe.theta < 0.0
    assert math.isclose(ce.vega, pe.vega, abs_tol=1e-9)

    # IV recovery
    iv_ce = implied_volatility_black76(ce.price, fwd, strike, t, "CE", r=0.0)
    iv_pe = implied_volatility_black76(pe.price, fwd, strike, t, "PE", r=0.0)
    assert math.isclose(iv_ce, sigma, abs_tol=1e-5)
    assert math.isclose(iv_pe, sigma, abs_tol=1e-5)


def test_mock_chain_and_synthetic_forward() -> None:
    as_of = datetime(2026, 11, 18, 11, 30, tzinfo=IST)
    chain = generate_mock_option_chain("NIFTY", date(2026, 11, 23), as_of=as_of)
    assert len(chain.rows) == 61  # +/- 30 strikes
    assert abs(chain.forward_price - chain.futures_price) < 5.0

    # Verify SVI downside Put skew (OTM put IV > ATM IV)
    atm_row = min(chain.rows, key=lambda r: abs(r.strike - chain.atm_strike))
    otm_put_row = chain.rows[5]
    assert otm_put_row.pe_iv > atm_row.ce_iv

    # Verify vectorized matches scalar
    strikes = np.array([r.strike for r in chain.rows])
    vec = greeks_black76_vectorized(chain.futures_price, strikes, 5.0 / 365.0, 0.14, True)
    sc = greeks_black76_scalar(chain.futures_price, float(strikes[10]), 5.0 / 365.0, 0.14, "CE")
    assert math.isclose(float(vec["price"][10]), sc.price, abs_tol=1e-10)


def test_generate_golden_parity_vectors() -> None:
    """Emit authoritative Python quant golden vectors consumed by frontend Vitest."""
    black76_cases = [
        {"forward": 24410.5, "strike": 24400.0, "t_years": 7.0 / 365.0, "sigma": 0.142, "option_type": "CE"},
        {"forward": 24410.5, "strike": 24400.0, "t_years": 7.0 / 365.0, "sigma": 0.142, "option_type": "PE"},
        {"forward": 52300.0, "strike": 51000.0, "t_years": 25.0 / 365.0, "sigma": 0.195, "option_type": "CE"},
        {"forward": 52300.0, "strike": 53500.0, "t_years": 25.0 / 365.0, "sigma": 0.175, "option_type": "PE"},
        {"forward": 24350.0, "strike": 24350.0, "t_years": 1e-4, "sigma": 0.18, "option_type": "CE"},
        {"forward": 24350.0, "strike": 24200.0, "t_years": 0.0, "sigma": 0.15, "option_type": "CE"},
        {"forward": 24350.0, "strike": 24200.0, "t_years": 0.0, "sigma": 0.15, "option_type": "PE"},
        {"forward": 80180.0, "strike": 82000.0, "t_years": 60.0 / 365.0, "sigma": 0.22, "option_type": "CE"},
    ]

    black76_vectors = []
    for c in black76_cases:
        g = greeks_black76_scalar(
            c["forward"], c["strike"], c["t_years"], c["sigma"], c["option_type"], r=0.0
        )
        black76_vectors.append(
            {
                **c,
                "expected": {
                    "price": g.price,
                    "delta": g.delta,
                    "gamma": g.gamma,
                    "theta": g.theta,
                    "vega": g.vega,
                },
            }
        )

    base_dt = datetime(2026, 11, 18, 10, 30, tzinfo=IST)
    near_exp = date(2026, 11, 23)
    far_exp = date(2026, 12, 29)

    def _serialize_leg(leg: PayoffLeg) -> dict:
        return {
            "leg_id": leg.leg_id,
            "symbol": leg.symbol,
            "expiry": leg.expiry.isoformat(),
            "option_type": leg.option_type,
            "side": leg.side,
            "lots": leg.lots,
            "lot_size": leg.lot_size,
            "entry_price": leg.entry_price,
            "entry_iv": leg.entry_iv,
            "strike": leg.strike,
            "forward_at_base": leg.forward_at_base,
            "enabled": leg.enabled,
            "status": leg.status,
            "exchange": leg.exchange,
        }

    scenarios = [
        {
            "name": "nifty_short_straddle",
            "spot": 24350.0,
            "base_dt": base_dt.isoformat(),
            "target_spot": 24350.0,
            "target_dt": base_dt.isoformat(),
            "iv_shift_pct": 0.0,
            "realized_pnl": 0.0,
            "include_charges": False,
            "atm_iv": 0.14,
            "legs": [
                PayoffLeg("l1", "NIFTY", near_exp, "CE", "SELL", 2, 65, 165.5, 0.14, 24350.0, 24372.0),
                PayoffLeg("l2", "NIFTY", near_exp, "PE", "SELL", 2, 65, 148.0, 0.145, 24350.0, 24372.0),
            ],
        },
        {
            "name": "nifty_iron_condor_what_if",
            "spot": 24350.0,
            "base_dt": base_dt.isoformat(),
            "target_spot": 24500.0,
            "target_dt": datetime(2026, 11, 20, 14, 0, tzinfo=IST).isoformat(),
            "iv_shift_pct": -2.0,
            "realized_pnl": 1850.0,
            "include_charges": True,
            "atm_iv": 0.14,
            "legs": [
                PayoffLeg("c1", "NIFTY", near_exp, "CE", "SELL", 1, 65, 92.0, 0.138, 24500.0, 24372.0),
                PayoffLeg("c2", "NIFTY", near_exp, "CE", "BUY", 1, 65, 34.0, 0.142, 24700.0, 24372.0),
                PayoffLeg("p1", "NIFTY", near_exp, "PE", "SELL", 1, 65, 88.0, 0.146, 24200.0, 24372.0),
                PayoffLeg("p2", "NIFTY", near_exp, "PE", "BUY", 1, 65, 31.0, 0.155, 24000.0, 24372.0),
            ],
        },
        {
            "name": "calendar_spread_multi_expiry",
            "spot": 24350.0,
            "base_dt": base_dt.isoformat(),
            "target_spot": 24420.0,
            "target_dt": datetime(2026, 11, 21, 11, 0, tzinfo=IST).isoformat(),
            "iv_shift_pct": 1.5,
            "realized_pnl": 0.0,
            "include_charges": False,
            "atm_iv": 0.14,
            "legs": [
                PayoffLeg("near", "NIFTY", near_exp, "CE", "SELL", 1, 65, 165.0, 0.14, 24350.0, 24372.0),
                PayoffLeg("far", "NIFTY", far_exp, "CE", "BUY", 1, 65, 420.0, 0.148, 24350.0, 24510.0),
            ],
        },
        {
            "name": "protective_put_with_future",
            "spot": 52240.0,
            "base_dt": base_dt.isoformat(),
            "target_spot": 51900.0,
            "target_dt": base_dt.isoformat(),
            "iv_shift_pct": 0.0,
            "realized_pnl": -500.0,
            "include_charges": False,
            "atm_iv": 0.16,
            "legs": [
                PayoffLeg("f1", "BANKNIFTY", near_exp, "FUT", "BUY", 1, 30, 52300.0, 0.0, None, 52300.0),
                PayoffLeg("p1", "BANKNIFTY", near_exp, "PE", "BUY", 1, 30, 310.0, 0.16, 52000.0, 52300.0),
            ],
        },
    ]

    payoff_vectors = []
    for sc in scenarios:
        res = evaluate_payoff(
            spot=sc["spot"],
            legs=sc["legs"],
            base_dt=base_dt,
            target_spot=sc["target_spot"],
            target_dt=datetime.fromisoformat(sc["target_dt"]),
            iv_shift_pct=sc["iv_shift_pct"],
            realized_pnl=sc["realized_pnl"],
            include_charges=sc["include_charges"],
            atm_iv=sc["atm_iv"],
            r=0.0,
        )
        payoff_vectors.append(
            {
                "name": sc["name"],
                "spot": sc["spot"],
                "base_dt": sc["base_dt"],
                "target_spot": sc["target_spot"],
                "target_dt": sc["target_dt"],
                "iv_shift_pct": sc["iv_shift_pct"],
                "realized_pnl": sc["realized_pnl"],
                "include_charges": sc["include_charges"],
                "atm_iv": sc["atm_iv"],
                "legs": [_serialize_leg(l) for l in sc["legs"]],
                "expected": {
                    "breakevens": res.breakevens,
                    "target_breakevens": res.target_breakevens,
                    "max_profit": res.max_profit,
                    "max_loss": res.max_loss,
                    "max_profit_unlimited": res.max_profit_unlimited,
                    "max_loss_unlimited": res.max_loss_unlimited,
                    "risk_reward": res.risk_reward,
                    "pop": res.pop,
                    "net_greeks": {
                        "delta": res.net_greeks.delta,
                        "gamma": res.net_greeks.gamma,
                        "theta": res.net_greeks.theta,
                        "vega": res.net_greeks.vega,
                    },
                    "current_mtm_pnl": res.current_mtm_pnl,
                    "estimated_charges": res.estimated_charges,
                    "sd_1_low": res.sd_1_low,
                    "sd_1_high": res.sd_1_high,
                    "sample_points": [
                        {
                            "spot": p.spot,
                            "expiry_pnl": p.expiry_pnl,
                            "target_pnl": p.target_pnl,
                        }
                        for p in res.points[::25]
                    ],
                },
            }
        )

    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(
            {
                "black76": black76_vectors,
                "payoff": payoff_vectors,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert GOLDEN_PATH.exists()

    # Sanity check synthetic forward helper
    fwd, atm = compute_synthetic_forward([24300, 24350, 24400], [180, 150, 120], [120, 140, 170], 24350)
    assert atm == 24350.0
    assert fwd == 24360.0
