"""CLI script to seed 10 realistic trading days of 1-minute Parquet data for NIFTY & BANKNIFTY."""

import argparse
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings
from app.services.synthetic_history import generate_synthetic_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic 1-minute historical Parquet data.")
    parser.add_argument("--days", type=int, default=10, help="Number of trading days (default 10)")
    parser.add_argument("--end-date", default="2026-11-25", help="End date YYYY-MM-DD")
    args = parser.parse_args()

    settings = get_settings()
    stats_list = generate_synthetic_history(
        parquet_dir=settings.parquet_data_dir,
        symbols=("NIFTY", "BANKNIFTY"),
        end_date=date.fromisoformat(args.end_date),
        trading_days=args.days,
    )
    for st in stats_list:
        print(f"Seeded [{st.symbol}]: bars={st.bars_written:,}, parquet_files={st.files_written}")


if __name__ == "__main__":
    main()
