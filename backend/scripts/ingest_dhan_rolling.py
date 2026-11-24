"""CLI script to ingest DhanHQ /charts/rollingoption into local Hive-partitioned Parquet."""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings
from app.services.historical_ingestor import DhanRollingOptionIngestor


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest DhanHQ expired rolling option data to Parquet.")
    parser.add_argument("--symbol", required=True, choices=["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"])
    parser.add_argument("--from", dest="from_date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--strikes", type=int, default=15, help="Strikes each side of ATM (default 15)")
    parser.add_argument("--expiry-flag", choices=["WEEK", "MONTH"], default="WEEK")
    args = parser.parse_args()

    settings = get_settings()
    ingestor = DhanRollingOptionIngestor(
        client_id=settings.dhan_client_id,
        access_token=settings.dhan_access_token,
        parquet_dir=settings.parquet_data_dir,
    )
    stats = asyncio.run(
        ingestor.ingest_symbol(
            symbol=args.symbol,
            from_date=date.fromisoformat(args.from_date),
            to_date=date.fromisoformat(args.to_date),
            strikes_each_side=args.strikes,
            expiry_flag=args.expiry_flag,
        )
    )
    print(
        f"[{stats.symbol}] bars={stats.bars_written} files={stats.files_written} "
        f"iv_backfilled={stats.iv_backfilled} requests={stats.requests_made}"
    )


if __name__ == "__main__":
    main()
