"""Tests for DhanHQ /charts/rollingoption mocked ingestion, chunking, and Parquet output."""

from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from app.core.calendar import IST
from app.providers.parquet_hist import ParquetHistoricalProvider
from app.services.historical_ingestor import (
    DhanRollingOptionIngestor,
    chunk_date_windows,
)


def test_chunk_date_windows_respects_30_day_limit() -> None:
    windows = chunk_date_windows(date(2026, 1, 1), date(2026, 3, 15), max_days=30)
    assert len(windows) == 3
    assert windows[0] == (date(2026, 1, 1), date(2026, 1, 30))
    assert windows[1] == (date(2026, 1, 31), date(2026, 3, 1))
    assert windows[2] == (date(2026, 3, 2), date(2026, 3, 15))


@pytest.mark.asyncio
async def test_dhan_ingestor_mocked_response_and_iv_backfill(tmp_path: Path) -> None:
    parquet_dir = tmp_path / "parquet"
    ts_epoch = int(datetime(2026, 11, 20, 10, 15, tzinfo=IST).timestamp())

    def _handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content.decode("utf-8"))
        is_call = body["drvOptionType"] == "CALL"
        return httpx.Response(
            200,
            json={
                "data": {
                    "ce" if is_call else "pe": {
                        "timestamp": [ts_epoch],
                        "open": [140.0 if is_call else 120.0],
                        "high": [142.0 if is_call else 122.0],
                        "low": [139.0 if is_call else 119.0],
                        "close": [141.0 if is_call else 121.0],
                        "volume": [4500],
                        "oi": [185000],
                        "iv": [0.0],  # missing IV -> should back-solve via Black-76
                        "spot": [24350.0],
                        "strike": [24350.0],
                        "expiry": ["2026-11-23"],
                    }
                }
            },
        )

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ingestor = DhanRollingOptionIngestor(
            client_id="demo-client",
            access_token="demo-token",
            parquet_dir=parquet_dir,
            max_req_per_sec=100.0,
            http_client=client,
        )
        stats = await ingestor.ingest_symbol(
            symbol="NIFTY",
            from_date=date(2026, 11, 20),
            to_date=date(2026, 11, 20),
            strikes_each_side=0,  # ATM only => 2 requests (CE + PE)
            expiry_flag="WEEK",
        )

    assert stats.requests_made == 2
    assert stats.bars_written == 2
    assert stats.iv_backfilled == 2
    assert stats.files_written == 1

    provider = ParquetHistoricalProvider(parquet_dir)
    chain, _ = await provider.get_option_chain(
        "NIFTY",
        expiry=date(2026, 11, 23),
        as_of=datetime(2026, 11, 20, 10, 15, tzinfo=IST),
    )
    assert len(chain.rows) == 1
    assert chain.rows[0].ce_ltp == 141.0
    assert chain.rows[0].ce_iv > 5.0

