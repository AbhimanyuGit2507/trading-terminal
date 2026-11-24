"""Indian F&O date-versioned contract specifications, IST market hours, and expiry calendar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from app.core.contracts import ExchangeSegment

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN_IST = time(9, 15)
MARKET_CLOSE_IST = time(15, 30)
SECONDS_PER_CALENDAR_YEAR = 365.0 * 86400.0

IndexSymbol = Literal["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

# Major NSE/BSE trading holidays (2025-2026) — extensible via external calendar file in Phase 2.
TRADING_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2025
        date(2025, 2, 26),
        date(2025, 3, 14),
        date(2025, 3, 31),
        date(2025, 4, 10),
        date(2025, 4, 14),
        date(2025, 4, 18),
        date(2025, 5, 1),
        date(2025, 8, 15),
        date(2025, 8, 27),
        date(2025, 10, 2),
        date(2025, 10, 21),
        date(2025, 10, 22),
        date(2025, 11, 5),
        date(2025, 12, 25),
        # 2026
        date(2026, 1, 26),
        date(2026, 3, 3),
        date(2026, 3, 26),
        date(2026, 3, 31),
        date(2026, 4, 3),
        date(2026, 4, 14),
        date(2026, 5, 1),
        date(2026, 5, 28),
        date(2026, 6, 26),
        date(2026, 9, 14),
        date(2026, 10, 2),
        date(2026, 10, 20),
        date(2026, 11, 10),
        date(2026, 11, 24),
        date(2026, 12, 25),
    }
)


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    symbol: IndexSymbol
    exchange: ExchangeSegment
    lot_size: int
    strike_step: int
    tick_size: float
    freeze_qty: int
    has_weekly: bool
    expiry_weekday: int  # 0=Mon .. 4=Fri
    effective_from: date


@dataclass(frozen=True, slots=True)
class ExpiryInfo:
    expiry_date: date
    label: str
    is_weekly: bool
    is_monthly: bool
    dte: int
    lot_size: int


# Date-versioned specification timeline (ordered chronologically per symbol).
# Reflects 2026 NSE/BSE baseline plus historical transitions (2021-2026) for Phase 2 replay.
_SPEC_HISTORY: dict[IndexSymbol, tuple[InstrumentSpec, ...]] = {
    "NIFTY": (
        InstrumentSpec("NIFTY", "NSE_FNO", 50, 50, 0.05, 1800, True, 3, date(2021, 1, 1)),
        InstrumentSpec("NIFTY", "NSE_FNO", 25, 50, 0.05, 1800, True, 3, date(2024, 4, 26)),
        InstrumentSpec("NIFTY", "NSE_FNO", 75, 50, 0.05, 2800, True, 3, date(2024, 11, 20)),
        InstrumentSpec("NIFTY", "NSE_FNO", 75, 50, 0.05, 2800, True, 1, date(2025, 9, 1)),
        InstrumentSpec("NIFTY", "NSE_FNO", 65, 50, 0.05, 3510, True, 1, date(2025, 12, 30)),
    ),
    "BANKNIFTY": (
        InstrumentSpec("BANKNIFTY", "NSE_FNO", 25, 100, 0.05, 900, True, 3, date(2021, 1, 1)),
        InstrumentSpec("BANKNIFTY", "NSE_FNO", 15, 100, 0.05, 900, True, 2, date(2023, 9, 6)),
        InstrumentSpec("BANKNIFTY", "NSE_FNO", 30, 100, 0.05, 900, False, 3, date(2024, 11, 20)),
        InstrumentSpec("BANKNIFTY", "NSE_FNO", 30, 100, 0.05, 900, False, 1, date(2025, 9, 1)),
        InstrumentSpec("BANKNIFTY", "NSE_FNO", 30, 100, 0.05, 1440, False, 1, date(2025, 12, 30)),
    ),
    "FINNIFTY": (
        InstrumentSpec("FINNIFTY", "NSE_FNO", 40, 50, 0.05, 1800, True, 1, date(2021, 1, 1)),
        InstrumentSpec("FINNIFTY", "NSE_FNO", 25, 50, 0.05, 1800, True, 1, date(2024, 4, 26)),
        InstrumentSpec("FINNIFTY", "NSE_FNO", 65, 50, 0.05, 1800, False, 3, date(2024, 11, 20)),
        InstrumentSpec("FINNIFTY", "NSE_FNO", 65, 50, 0.05, 1800, False, 1, date(2025, 9, 1)),
        InstrumentSpec("FINNIFTY", "NSE_FNO", 60, 50, 0.05, 3240, False, 1, date(2025, 12, 30)),
    ),
    "SENSEX": (
        InstrumentSpec("SENSEX", "BSE_FNO", 10, 100, 0.05, 1000, True, 4, date(2023, 5, 1)),
        InstrumentSpec("SENSEX", "BSE_FNO", 20, 100, 0.05, 1000, True, 4, date(2024, 11, 20)),
        InstrumentSpec("SENSEX", "BSE_FNO", 20, 100, 0.05, 1000, True, 1, date(2025, 1, 1)),
        InstrumentSpec("SENSEX", "BSE_FNO", 20, 100, 0.05, 1000, True, 3, date(2025, 9, 1)),
    ),
}


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in TRADING_HOLIDAYS


def shift_to_previous_trading_day(d: date) -> date:
    cur = d
    while not is_trading_day(cur):
        cur -= timedelta(days=1)
    return cur


def get_instrument_spec(symbol: str, as_of: date | datetime | None = None) -> InstrumentSpec:
    sym = symbol.upper()
    if sym not in _SPEC_HISTORY:
        raise ValueError(f"Unsupported F&O index symbol: {symbol}")
    as_of_date = (
        date.today()
        if as_of is None
        else (to_ist(as_of).date() if isinstance(as_of, datetime) else as_of)
    )
    history = _SPEC_HISTORY[sym]  # type: ignore[index]
    selected = history[0]
    for entry in history:
        if entry.effective_from <= as_of_date:
            selected = entry
        else:
            break
    return selected


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    cur = next_first - timedelta(days=1)
    while cur.weekday() != weekday:
        cur -= timedelta(days=1)
    return shift_to_previous_trading_day(cur)


def get_expiries(
    symbol: str,
    as_of: datetime | date | None = None,
    count: int = 8,
) -> list[ExpiryInfo]:
    """Return sorted upcoming weekly/monthly expiries as of a given IST date/time."""
    now_ist = to_ist(as_of) if isinstance(as_of, datetime) else (
        datetime.combine(as_of, MARKET_OPEN_IST, tzinfo=IST)
        if isinstance(as_of, date)
        else datetime.now(IST)
    )
    today = now_ist.date()
    spec = get_instrument_spec(symbol, today)

    # Pre-compute monthly expiries for next 6 months
    monthly_dates: set[date] = set()
    y, m = today.year, today.month
    for offset in range(7):
        mm = ((m - 1 + offset) % 12) + 1
        yy = y + ((m - 1 + offset) // 12)
        m_exp = _last_weekday_of_month(yy, mm, spec.expiry_weekday)
        if m_exp > today or (m_exp == today and now_ist.time() <= MARKET_CLOSE_IST):
            monthly_dates.add(m_exp)

    candidates: dict[date, bool] = {}  # date -> is_monthly
    for md in monthly_dates:
        candidates[md] = True

    if spec.has_weekly:
        days_ahead = (spec.expiry_weekday - today.weekday()) % 7
        cur = today + timedelta(days=days_ahead)
        for _ in range(count + 4):
            shifted = shift_to_previous_trading_day(cur)
            if shifted > today or (shifted == today and now_ist.time() <= MARKET_CLOSE_IST):
                candidates.setdefault(shifted, shifted in monthly_dates)
            cur += timedelta(days=7)

    ordered = sorted(candidates.items(), key=lambda kv: kv[0])[:count]
    result: list[ExpiryInfo] = []
    for exp_date, is_monthly in ordered:
        exp_spec = get_instrument_spec(symbol, exp_date)
        dte = max((exp_date - today).days, 0)
        tag = "Monthly" if is_monthly else "Weekly"
        label = f"{exp_date.strftime('%d %b %y')} ({tag[:1]})"
        result.append(
            ExpiryInfo(
                expiry_date=exp_date,
                label=label,
                is_weekly=not is_monthly,
                is_monthly=is_monthly,
                dte=dte,
                lot_size=exp_spec.lot_size,
            )
        )
    return result


def expiry_settlement_datetime(expiry_date: date) -> datetime:
    return datetime.combine(expiry_date, MARKET_CLOSE_IST, tzinfo=IST)


def time_to_expiry_years(eval_dt: datetime, expiry_date: date) -> float:
    """Exact calendar-year fraction until 15:30 IST on expiry_date (0.0 if expired)."""
    t_eval = to_ist(eval_dt)
    t_exp = expiry_settlement_datetime(expiry_date)
    delta_sec = (t_exp - t_eval).total_seconds()
    if delta_sec <= 0.0:
        return 0.0
    return delta_sec / SECONDS_PER_CALENDAR_YEAR


def round_to_tick(price: float, tick_size: float = 0.05, min_price: float = 0.05) -> float:
    if price <= min_price:
        return min_price
    ticks = Decimal(str(price)) / Decimal(str(tick_size))
    rounded = float(ticks.quantize(Decimal(1)) * Decimal(str(tick_size)))
    return max(min_price, round(rounded, 2))
