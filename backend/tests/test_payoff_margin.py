"""Tests for Payoff edge cases (unlimited risk, calendar spreads, realized PnL) & Margin."""

from datetime import date, datetime

from app.core.calendar import IST
from app.quant.margin import estimate_portfolio_margin
from app.quant.payoff import PayoffLeg, evaluate_payoff


def test_short_straddle_unlimited_loss_and_exact_breakevens() -> None:
    base_dt = datetime(2026, 11, 18, 10, 0, tzinfo=IST)
    exp = date(2026, 11, 23)
    legs = [
        PayoffLeg("c", "NIFTY", exp, "CE", "SELL", 1, 65, 150.0, 0.14, 24350.0, 24350.0),
        PayoffLeg("p", "NIFTY", exp, "PE", "SELL", 1, 65, 150.0, 0.14, 24350.0, 24350.0),
    ]
    res = evaluate_payoff(spot=24350.0, legs=legs, base_dt=base_dt)

    assert res.max_profit == round(300.0 * 65, 2)
    assert res.max_profit_unlimited is False
    assert res.max_loss is None
    assert res.max_loss_unlimited is True
    assert res.breakevens == [24050.0, 24650.0]
    assert res.net_greeks.theta > 0.0  # short straddle has positive daily theta


def test_partial_exit_realized_pnl_shifts_curve_and_charges_toggle() -> None:
    base_dt = datetime(2026, 11, 18, 10, 0, tzinfo=IST)
    exp = date(2026, 11, 23)
    legs = [
        PayoffLeg("c", "NIFTY", exp, "CE", "BUY", 1, 65, 120.0, 0.14, 24350.0, 24350.0),
    ]
    clean = evaluate_payoff(spot=24350.0, legs=legs, base_dt=base_dt, realized_pnl=2500.0)
    with_charges = evaluate_payoff(
        spot=24350.0, legs=legs, base_dt=base_dt, realized_pnl=2500.0, include_charges=True
    )
    assert clean.estimated_charges == 0.0
    assert with_charges.estimated_charges > 20.0
    assert with_charges.current_mtm_pnl < clean.current_mtm_pnl


def test_margin_hedge_benefit_iron_condor_vs_naked_strangle() -> None:
    as_of = datetime(2026, 11, 18, 10, 0, tzinfo=IST)
    exp = date(2026, 11, 23)
    strangle = [
        PayoffLeg("sc", "NIFTY", exp, "CE", "SELL", 1, 65, 90.0, 0.14, 24500.0, 24350.0),
        PayoffLeg("sp", "NIFTY", exp, "PE", "SELL", 1, 65, 90.0, 0.14, 24200.0, 24350.0),
    ]
    condor = [
        *strangle,
        PayoffLeg("bc", "NIFTY", exp, "CE", "BUY", 1, 65, 30.0, 0.14, 24700.0, 24350.0),
        PayoffLeg("bp", "NIFTY", exp, "PE", "BUY", 1, 65, 30.0, 0.14, 24000.0, 24350.0),
    ]
    m_strangle = estimate_portfolio_margin(strangle, 24350.0, as_of)
    m_condor = estimate_portfolio_margin(condor, 24350.0, as_of)

    assert m_condor.total_margin < m_strangle.total_margin
    assert m_condor.hedge_benefit > 0.0

