"""Tests for DhanScripMaster CSV parsing, caching, and bidirectional ContractId mapping."""

from pathlib import Path

import httpx
import pytest

from app.services.dhan_scrip_master import DhanScripMaster

SAMPLE_CSV = """SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE
NSE,D,45001,OPTIDX,NIFTY-Nov2026-24350-CE,NIFTY 26 NOV 24350 CE,2026-11-26 14:30:00,24350.00,CE
NSE,D,45002,OPTIDX,NIFTY-Nov2026-24350-PE,NIFTY 26 NOV 24350 PE,2026-11-26 14:30:00,24350.00,PE
NSE,D,45010,FUTIDX,NIFTY-Nov2026-FUT,NIFTY NOV FUT,2026-11-26 14:30:00,-0.01,
BSE,D,89001,OPTIDX,SENSEX-Nov2026-80000-CE,SENSEX 26 NOV 80000 CE,2026-11-26 15:30:00,80000,CE
NSE,I,21,INDEX,INDIA VIX,INDIA VIX,,,
"""


@pytest.mark.asyncio
async def test_scrip_master_download_cache_and_bidirectional_lookup(tmp_path: Path) -> None:
    cache_file = tmp_path / "dhan_scrip_master.csv"
    calls = 0

    def _handler(_req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=SAMPLE_CSV)

    master = DhanScripMaster(cache_path=cache_file)
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        loaded_count = await master.ensure_loaded(http_client=client)
        assert loaded_count >= 4
        assert cache_file.exists()
        assert calls == 1

        # Second call same day uses local cache (0 HTTP calls)
        await master.ensure_loaded(http_client=client)
        assert calls == 1

    ce_cid = "NSE_FNO:NIFTY:2026-11-26:24350:CE"
    fut_cid = "NSE_FNO:NIFTY:2026-11-26:FUT"
    bse_cid = "BSE_FNO:SENSEX:2026-11-26:80000:CE"

    assert master.to_dhan(ce_cid) == ("NSE_FNO", "45001")
    assert master.to_dhan(fut_cid) == ("NSE_FNO", "45010")
    assert master.to_dhan(bse_cid) == ("BSE_FNO", "89001")

    assert master.to_contract(2, 45001) == ce_cid
    assert master.to_contract("NSE_FNO", "45010") == fut_cid
    assert master.to_contract(8, 89001) == bse_cid
    assert master.to_contract(0, 13) == "IDX_I:NIFTY:SPOT"
    assert master.to_contract(0, 21) == "IDX_I:INDIAVIX:SPOT"
