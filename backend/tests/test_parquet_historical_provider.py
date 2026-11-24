"""Tests for ParquetHistoricalProvider: Hive partitions, 15m forward-fill, and IV backfill."""

from datetime import date, datetime
from pathlib import Path

import pytest

from app.core.calendar import IST
from app.core.contracts import build_option_contract_id
from app.providers.parquet_hist import ParquetHistoricalProvider
from app.services.historical_ingestor import HistoricalOptionBar, write_parquet_partitions


@pytest.mark.asyncio
async def test_parquet_partition_pruning_forward_fill_and_iv_backfill(tmp_path: Path) -> None:
    parquet_dir = tmp_path / "parquet"
    exp = date(2026, 11, 23)
    ts_0915 = datetime(2026, 11, 23, 9, 15, 0)
    ts_0920 = datetime(2026, 11, 23, 9, 20, 0)

    bars = [
        # 09:15 bar: 24350 ATM CE/PE + far-OTM 24800 CE (missing at 09:20 -> tests forward-fill)
        HistoricalOptionBar(ts_0915, "NIFTY", exp, 24350.0, "CE", 120.0, 122.0, 119.0, 121.0, 5000, 150000, 0.14, 24350.0, 24360.0),
        HistoricalOptionBar(ts_0915, "NIFTY", exp, 24350.0, "PE", 110.0, 112.0, 109.0, 111.0, 4800, 140000, 0.145, 24350.0, 24360.0),
        HistoricalOptionBar(ts_0915, "NIFTY", exp, 24800.0, "CE", 8.5, 9.0, 8.0, 8.5, 100, 90000, 0.18, 24350.0, 24360.0),
        # 09:20 bar: 24350 CE has iv=0.0 -> tests Black-76 IV backfill; 24800 CE omitted -> forward-filled from 09:15
        HistoricalOptionBar(ts_0920, "NIFTY", exp, 24350.0, "CE", 125.0, 126.0, 124.0, 125.0, 6200, 155000, 0.0, 24355.0, 24365.0),
        HistoricalOptionBar(ts_0920, "NIFTY", exp, 24350.0, "PE", 114.0, 115.0, 113.0, 115.0, 5900, 142000, 0.15, 24355.0, 24365.0),
    ]
    files = write_parquet_partitions(parquet_dir, bars)
    assert files == 1
    assert (parquet_dir / "symbol=NIFTY" / "year=2026" / "month=11" / "data.parquet").exists()

    provider = ParquetHistoricalProvider(parquet_dir=parquet_dir, forward_fill_minutes=15)
    assert provider.get_available_dates("NIFTY") == [date(2026, 11, 23)]
    assert provider.has_data_for_date("NIFTY", date(2026, 11, 23)) is True
    assert provider.has_data_for_date("NIFTY", date(2026, 11, 20)) is False

    eval_dt = datetime(2026, 11, 23, 9, 20, tzinfo=IST)
    chain, expiries = await provider.get_option_chain("NIFTY", expiry=exp, as_of=eval_dt)
    assert chain.spot == 24355.0
    assert expiries[0].expiry_date == exp

    by_k = {r.strike: r for r in chain.rows}
    # 24350 CE IV was 0.0 in raw bar -> back-solved via Black-76 (> 0)
    assert by_k[24350.0].ce_iv > 5.0
    # 24800 CE was missing at 09:20 -> forward-filled from 09:15 (8.50)
    assert by_k[24800.0].ce_ltp == 8.5

    # Active leg quote for unprinted strike 24950 CE -> Black-76 theoretical fallback (not 0)
    unprinted_cid = build_option_contract_id("NSE_FNO", "NIFTY", exp, 24950, "CE")
    quotes = await provider.get_contract_quotes([unprinted_cid], as_of=eval_dt)
    assert unprinted_cid in quotes
    assert quotes[unprinted_cid].ltp >= 0.05

