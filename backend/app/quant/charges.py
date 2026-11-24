"""Indian F&O statutory charges estimator (excluded by default per product decision)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BROKERAGE_PER_ORDER = 20.0
STT_OPTION_SELL = 0.001  # 0.1% on option sell turnover (2024+ Indian F&O rate)
STT_FUT_SELL = 0.0002  # 0.02% on futures sell turnover
EXCHANGE_TXN_NSE_OPT = 0.0003503
EXCHANGE_TXN_BSE_OPT = 0.000325
EXCHANGE_TXN_FUT = 0.0000173
SEBI_TURNOVER_FEE = 0.000001  # ₹10 per crore
STAMP_DUTY_OPT_BUY = 0.00003  # 0.003% on buy side
STAMP_DUTY_FUT_BUY = 0.00002
GST_RATE = 0.18


@dataclass(frozen=True, slots=True)
class ChargesBreakdown:
    brokerage: float
    stt: float
    exchange_txn: float
    sebi_fee: float
    stamp_duty: float
    gst: float
    total: float


def estimate_leg_charges(
    price: float,
    quantity: int,
    side: Literal["BUY", "SELL"],
    option_type: Literal["CE", "PE", "FUT"],
    exchange: Literal["NSE_FNO", "BSE_FNO"] = "NSE_FNO",
    orders_count: int = 1,
) -> ChargesBreakdown:
    """Estimate round-trip or single-side statutory charges for an F&O leg."""
    turnover = max(price, 0.0) * abs(quantity)
    brokerage = BROKERAGE_PER_ORDER * orders_count

    if option_type == "FUT":
        stt = turnover * STT_FUT_SELL if side == "SELL" else 0.0
        exch = turnover * EXCHANGE_TXN_FUT
        stamp = turnover * STAMP_DUTY_FUT_BUY if side == "BUY" else 0.0
    else:
        stt = turnover * STT_OPTION_SELL if side == "SELL" else 0.0
        exch_rate = EXCHANGE_TXN_BSE_OPT if exchange == "BSE_FNO" else EXCHANGE_TXN_NSE_OPT
        exch = turnover * exch_rate
        stamp = turnover * STAMP_DUTY_OPT_BUY if side == "BUY" else 0.0

    sebi_fee = turnover * SEBI_TURNOVER_FEE
    gst = GST_RATE * (brokerage + exch + sebi_fee)
    total = brokerage + stt + exch + sebi_fee + stamp + gst
    return ChargesBreakdown(
        brokerage=round(brokerage, 2),
        stt=round(stt, 2),
        exchange_txn=round(exch, 2),
        sebi_fee=round(sebi_fee, 2),
        stamp_duty=round(stamp, 2),
        gst=round(gst, 2),
        total=round(total, 2),
    )
