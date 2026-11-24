"""Tests for DhanMarginProvider (5s cache + stress fallback) and DhanLiveMarketProvider fallback."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.providers.dhan_margin import DhanMarginProvider
from app.providers.dhan_ws import DhanLiveMarketProvider
from app.providers.margin_provider import StressMarginProvider
from app.providers.mock_static import MockStaticProvider
from app.quant.payoff import PayoffLeg
from app.services.dhan_auth import DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster


@pytest.mark.asyncio
async def test_dhan_margin_api_caching_and_fallback(tmp_path: Path) -> None:
    master = DhanScripMaster(tmp_path / "scrip.csv")
    master.load_from_csv_text(
        "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE\n"
        "NSE,D,45001,OPTIDX,NIFTY-Nov2026-24350-CE,NIFTY,2026-11-26,24350,CE\n"
    )
    mgr = DhanTokenManager()
    legs = [
        PayoffLeg("l1", "NIFTY", date(2026, 11, 26), "CE", "SELL", 1, 65, 150.0, 0.14, 24350.0)
    ]
    as_of = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)

    # 1. Without credentials -> seamless fallback to StressMarginProvider
    provider_offline = DhanMarginProvider(mgr, master, StressMarginProvider())
    res_fb = await provider_offline.estimate_margin(legs, 24350.0, as_of)
    assert res_fb.margin_source == "estimated_stress"
    assert res_fb.total_margin > 0

    # 2. With valid credentials -> calls Dhan /v2/margincalculator and caches for 5s
    mgr.client_id = "110011"
    mgr.access_token = "valid-token-123"
    mgr.expires_at = datetime.now(UTC) + timedelta(hours=12)

    api_calls = 0

    def _handler(_req: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        api_calls += 1
        return httpx.Response(
            200,
            json={"totalMargin": 124500.0, "spanMargin": 95000.0, "exposureMargin": 29500.0},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        provider_live = DhanMarginProvider(
            mgr, master, StressMarginProvider(), cache_ttl_seconds=5.0, http_client=client
        )
        res1 = await provider_live.estimate_margin(legs, 24350.0, as_of)
        res2 = await provider_live.estimate_margin(legs, 24350.0, as_of)
        assert res1.margin_source == "dhan_span_api"
        assert res1.total_margin == 124500.0
        assert res2.total_margin == 124500.0
        assert api_calls == 1  # second call served from 5s cache


@pytest.mark.asyncio
async def test_market_provider_graceful_fallback_on_missing_or_expired_token(tmp_path: Path) -> None:
    mgr = DhanTokenManager()
    master = DhanScripMaster(tmp_path / "scrip.csv")
    provider = DhanLiveMarketProvider(mgr, master, MockStaticProvider(deterministic=True))

    assert provider.feed_status == "MOCK_FALLBACK"
    chain, _ = await provider.get_option_chain("NIFTY")
    assert len(chain.rows) == 61

    mgr.client_id = "110011"
    mgr.access_token = "old-token"
    mgr.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    assert provider.feed_status == "TOKEN_EXPIRED"

    # Still serves fallback chain cleanly without raising
    chain2, _ = await provider.get_option_chain("NIFTY")
    assert len(chain2.rows) == 61

