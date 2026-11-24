"""Tests for 2026 Indian F&O specs, date-versioned history, holidays, and ContractId."""

from datetime import date, datetime

from app.core.calendar import (
    IST,
    get_expiries,
    get_instrument_spec,
    round_to_tick,
    time_to_expiry_years,
)
from app.core.contracts import (
    build_future_contract_id,
    build_option_contract_id,
    build_spot_contract_id,
    parse_contract_id,
)


def test_2026_indian_fno_specs_baseline() -> None:
    d2026 = date(2026, 11, 25)
    nifty = get_instrument_spec("NIFTY", d2026)
    banknifty = get_instrument_spec("BANKNIFTY", d2026)
    finnifty = get_instrument_spec("FINNIFTY", d2026)
    sensex = get_instrument_spec("SENSEX", d2026)

    assert (nifty.lot_size, nifty.strike_step, nifty.freeze_qty, nifty.has_weekly) == (
        65,
        50,
        3510,
        True,
    )
    assert nifty.expiry_weekday == 1  # Tuesday

    assert (banknifty.lot_size, banknifty.strike_step, banknifty.freeze_qty, banknifty.has_weekly) == (
        30,
        100,
        1440,
        False,
    )
    assert (finnifty.lot_size, finnifty.strike_step, finnifty.freeze_qty, finnifty.has_weekly) == (
        60,
        50,
        3240,
        False,
    )
    assert (sensex.lot_size, sensex.strike_step, sensex.freeze_qty, sensex.has_weekly) == (
        20,
        100,
        1000,
        True,
    )
    assert sensex.exchange == "BSE_FNO"
    assert sensex.expiry_weekday == 3  # Thursday


def test_historical_lot_size_and_weekly_transitions() -> None:
    assert get_instrument_spec("NIFTY", date(2023, 6, 1)).lot_size == 50
    assert get_instrument_spec("NIFTY", date(2024, 6, 1)).lot_size == 25
    assert get_instrument_spec("NIFTY", date(2025, 6, 1)).lot_size == 75
    assert get_instrument_spec("NIFTY", date(2026, 2, 1)).lot_size == 65

    assert get_instrument_spec("BANKNIFTY", date(2024, 6, 1)).has_weekly is True
    assert get_instrument_spec("BANKNIFTY", date(2025, 6, 1)).has_weekly is False


def test_holiday_expiry_shift_and_monthly_only() -> None:
    # 2026-11-24 (Tuesday) is a configured holiday -> NIFTY expiry shifts to Monday 2026-11-23
    expiries = get_expiries("NIFTY", datetime(2026, 11, 20, 10, 0, tzinfo=IST), count=4)
    assert expiries[0].expiry_date == date(2026, 11, 23)
    assert expiries[0].is_monthly is True

    bn_expiries = get_expiries("BANKNIFTY", datetime(2026, 11, 20, 10, 0, tzinfo=IST), count=3)
    assert all(e.is_monthly and not e.is_weekly for e in bn_expiries)


def test_contract_id_round_trip() -> None:
    opt = build_option_contract_id("NSE_FNO", "NIFTY", date(2026, 11, 23), 24500, "CE")
    assert opt == "NSE_FNO:NIFTY:2026-11-23:24500:CE"
    parsed = parse_contract_id(opt)
    assert parsed.strike == 24500.0
    assert parsed.kind == "CE"

    fut = build_future_contract_id("BSE_FNO", "SENSEX", date(2026, 11, 26))
    assert parse_contract_id(fut).kind == "FUT"

    spot = build_spot_contract_id("NIFTY")
    assert parse_contract_id(spot).kind == "SPOT"


def test_tick_rounding_and_0dte_time() -> None:
    assert round_to_tick(123.47) == 123.45
    assert round_to_tick(123.48) == 123.5
    assert round_to_tick(0.01) == 0.05

    exp_d = date(2026, 11, 23)
    assert time_to_expiry_years(datetime(2026, 11, 23, 15, 31, tzinfo=IST), exp_d) == 0.0
    t_mid = time_to_expiry_years(datetime(2026, 11, 23, 9, 15, tzinfo=IST), exp_d)
    assert 0.0 < t_mid < 1.0 / 365.0
