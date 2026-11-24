"""Tests for DhanHQ v2 binary packet decoder & WS subscription diff logic."""

import struct
from datetime import datetime, timedelta
from pathlib import Path

from app.providers.dhan_ws import DhanLiveMarketProvider, decode_dhan_binary_packet
from app.providers.mock_static import MockStaticProvider
from app.services.dhan_auth import DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster


def test_decode_dhan_binary_packets() -> None:
    # 1. Ticker packet (code=2, NSE_FNO=2, sec_id=45001, ltp=154.25, ltt=1700000100)
    pkt_ticker = struct.pack("<BHBIfI", 2, 16, 2, 45001, 154.25, 1700000100)
    d_tick = decode_dhan_binary_packet(pkt_ticker)
    assert d_tick is not None
    assert d_tick.feed_code == 2
    assert d_tick.exchange_segment == "NSE_FNO"
    assert d_tick.security_id == "45001"
    assert d_tick.ltp == 154.25
    assert d_tick.ltt == 1700000100

    # 2. OI packet (code=5, NSE_FNO=2, sec_id=45001, oi=2450000)
    pkt_oi = struct.pack("<BHBII", 5, 12, 2, 45001, 2450000)
    d_oi = decode_dhan_binary_packet(pkt_oi)
    assert d_oi is not None
    assert d_oi.oi == 2450000

    # 3. Full packet (code=8) with OI + first depth level (bid=154.10, ask=154.35)
    body_quote = struct.pack(
        "<fHIfIIIffff",
        154.20,
        65,
        1700000200,
        150.5,
        125000,
        5000,
        6000,
        148.0,
        145.0,
        160.0,
        140.0,
    )
    oi_bytes = struct.pack("<I", 2500000)
    depth_lvl1 = struct.pack("<IIHHff", 650, 1300, 3, 5, 154.10, 154.35)
    total_len = 8 + len(body_quote) + len(oi_bytes) + len(depth_lvl1)
    hdr = struct.pack("<BHBI", 8, total_len, 2, 45001)
    d_full = decode_dhan_binary_packet(hdr + body_quote + oi_bytes + depth_lvl1)
    assert d_full is not None
    assert d_full.feed_code == 8
    assert d_full.ltp == 154.20
    assert d_full.volume == 125000
    assert d_full.oi == 2500000
    assert d_full.best_bid == 154.10
    assert d_full.best_ask == 154.35

    # 4. Server disconnect auth-expired packet (code=50, reason=807)
    pkt_disc = struct.pack("<BHBIH", 50, 10, 0, 0, 807)
    d_disc = decode_dhan_binary_packet(pkt_disc)
    assert d_disc is not None
    assert d_disc.disconnect_reason == 807


def test_subscription_diff_and_binary_cache_update(tmp_path: Path) -> None:
    master = DhanScripMaster(tmp_path / "scrip.csv")
    master.load_from_csv_text(
        "SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_TRADING_SYMBOL,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE\n"
        "NSE,D,45001,OPTIDX,NIFTY-Nov2026-24350-CE,NIFTY,2026-11-26,24350,CE\n"
        "NSE,D,45002,OPTIDX,NIFTY-Nov2026-24350-PE,NIFTY,2026-11-26,24350,PE\n"
    )
    mgr = DhanTokenManager()
    mgr.client_id = "110011"
    mgr.access_token = "tok123456"
    mgr.expires_at = datetime.now().astimezone() + timedelta(hours=12)

    provider = DhanLiveMarketProvider(
        token_manager=mgr,
        scrip_master=master,
        mock_fallback=MockStaticProvider(deterministic=True),
    )

    ce_cid = "NSE_FNO:NIFTY:2026-11-26:24350:CE"
    pe_cid = "NSE_FNO:NIFTY:2026-11-26:24350:PE"

    # Initial diff subscribes CE + Spot
    to_add, to_remove = provider.compute_subscription_diff({ce_cid, "IDX_I:NIFTY:SPOT"})
    assert len(to_add) == 2
    assert to_remove == []

    # Simulate subscribed state, then switch to PE -> CE unsubscribed, PE added
    provider._subscribed_keys = {("NSE_FNO", "45001"), ("IDX_I", "13")}
    to_add2, to_remove2 = provider.compute_subscription_diff({pe_cid, "IDX_I:NIFTY:SPOT"})
    assert to_add2 == [{"ExchangeSegment": "NSE_FNO", "SecurityId": "45002"}]
    assert to_remove2 == [{"ExchangeSegment": "NSE_FNO", "SecurityId": "45001"}]

    # Feed binary ticker packet -> updates live cache
    pkt_ce = struct.pack("<BHBIfI", 2, 16, 2, 45001, 162.80, 1700000100)
    provider.process_binary_message(pkt_ce)
    assert provider.ticks[ce_cid].ltp == 162.80
