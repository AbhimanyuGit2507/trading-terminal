"""Side-by-side StockMock Parity Verification CLI.

Usage:
  uv run python scripts/verify_parity_report.py --symbol NIFTY --preset iron_condor
  uv run python scripts/verify_parity_report.py --symbol NIFTY --as-of 2026-11-23T09:20:00+05:30 --source parquet
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.calendar import IST, to_ist
from app.core.config import get_settings
from app.providers.mock_static import MockStaticProvider
from app.providers.parquet_hist import ParquetHistoricalProvider
from app.quant.margin import estimate_portfolio_margin
from app.quant.payoff import PayoffLeg, evaluate_payoff


def _build_preset_legs(symbol: str, preset: str, chain) -> list[PayoffLeg]:
    rows = chain.rows
    atm_idx = min(range(len(rows)), key=lambda i: abs(rows[i].strike - chain.atm_strike))

    def _row(offset: int):
        return rows[max(0, min(len(rows) - 1, atm_idx + offset))]

    def _leg(row, opt: str, side: str) -> PayoffLeg:
        is_ce = opt == "CE"
        return PayoffLeg(
            leg_id=f"{row.strike}-{opt}-{side}",
            symbol=symbol,
            expiry=chain.expiry,
            option_type=opt,  # type: ignore[arg-type]
            side=side,  # type: ignore[arg-type]
            lots=1,
            lot_size=chain.lot_size,
            entry_price=row.ce_ltp if is_ce else row.pe_ltp,
            entry_iv=(row.ce_iv if is_ce else row.pe_iv) / 100.0,
            strike=row.strike,
            forward_at_base=chain.forward_price,
            exchange=chain.exchange,  # type: ignore[arg-type]
        )

    if preset == "short_straddle":
        r0 = _row(0)
        return [_leg(r0, "CE", "SELL"), _leg(r0, "PE", "SELL")]
    if preset == "iron_fly":
        r0 = _row(0)
        return [
            _leg(r0, "CE", "SELL"),
            _leg(r0, "PE", "SELL"),
            _leg(_row(4), "CE", "BUY"),
            _leg(_row(-4), "PE", "BUY"),
        ]
    # default iron_condor
    return [
        _leg(_row(2), "CE", "SELL"),
        _leg(_row(5), "CE", "BUY"),
        _leg(_row(-2), "PE", "SELL"),
        _leg(_row(-5), "PE", "BUY"),
    ]


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    eval_dt = to_ist(datetime.fromisoformat(args.as_of)) if args.as_of else datetime.now(IST)

    if args.source == "parquet":
        provider = ParquetHistoricalProvider(settings.parquet_data_dir)
    else:
        provider = MockStaticProvider(deterministic=True)

    chain, _ = await provider.get_option_chain(args.symbol, as_of=eval_dt)
    legs = _build_preset_legs(args.symbol, args.preset, chain)

    res = evaluate_payoff(
        spot=chain.spot,
        legs=legs,
        base_dt=eval_dt,
        atm_iv=chain.india_vix / 100.0,
        r=0.0,
    )
    margin = estimate_portfolio_margin(legs, chain.spot, eval_dt, r=0.0)

    print(f"\n=== StockMock Parity Verification Report ({args.symbol} · {args.preset}) ===")
    print(f"Timestamp IST     : {chain.as_of.isoformat()}")
    print(f"Expiry            : {chain.expiry.isoformat()} (Lot Size: {chain.lot_size})")
    print(
        f"Spot / Fut / SynF : {chain.spot:.2f} / {chain.futures_price:.2f} / {chain.forward_price:.2f}"
    )
    print(f"ATM Strike / VIX  : {chain.atm_strike:.0f} / {chain.india_vix:.2f}%")
    print("-" * 86)
    print(f"{'Leg':<18} {'Side':<6} {'LTP':>9} {'IV%':>7} {'Delta':>8} {'Theta/d':>9} {'Vega':>8}")
    print("-" * 86)

    row_by_k = {r.strike: r for r in chain.rows}
    for leg in legs:
        r = row_by_k[float(leg.strike or chain.atm_strike)]
        is_ce = leg.option_type == "CE"
        ltp = r.ce_ltp if is_ce else r.pe_ltp
        iv = r.ce_iv if is_ce else r.pe_iv
        delta = r.ce_delta if is_ce else r.pe_delta
        theta = r.ce_theta if is_ce else r.pe_theta
        vega = r.ce_vega if is_ce else r.pe_vega
        print(
            f"{str(int(leg.strike or 0)) + ' ' + leg.option_type:<18} {leg.side:<6} "
            f"{ltp:>9.2f} {iv:>6.2f}% {delta:>8.4f} {theta:>9.2f} {vega:>8.2f}"
        )

    print("-" * 86)
    mp = "Unlimited" if res.max_profit_unlimited else f"₹{res.max_profit:,.2f}"
    ml = "Unlimited" if res.max_loss_unlimited else f"₹{res.max_loss:,.2f}"
    bes = ", ".join(f"{b:.2f}" for b in res.breakevens) or "--"
    print(f"Max Profit        : {mp}")
    print(f"Max Loss          : {ml}")
    print(f"Breakevens        : {bes}")
    print(f"POP               : {res.pop:.2f}%")
    print(
        f"Net Greeks        : Δ={res.net_greeks.delta:.2f}, Θ={res.net_greeks.theta:.2f}/day, "
        f"Γ={res.net_greeks.gamma:.4f}, V={res.net_greeks.vega:.2f}"
    )
    print(
        f"Est. Margin       : ₹{margin.total_margin:,.2f} "
        f"(Hedge Benefit: ₹{margin.hedge_benefit:,.2f}, Source: {margin.margin_source})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Print StockMock parity verification metrics.")
    parser.add_argument("--symbol", default="NIFTY", choices=["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"])
    parser.add_argument("--preset", default="iron_condor", choices=["short_straddle", "iron_fly", "iron_condor"])
    parser.add_argument("--as-of", default=None, help="ISO IST timestamp e.g. 2026-11-23T09:20:00+05:30")
    parser.add_argument("--source", default="mock", choices=["mock", "parquet"])
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
