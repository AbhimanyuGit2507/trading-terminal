"""Milestone 2 integration tests: Postgres CRUD, idempotency, freeze slicing, multi-expiry quotes, WS."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_market_provider
from app.core.calendar import IST, get_expiries
from app.core.contracts import build_future_contract_id, build_option_contract_id
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.providers.mock_static import MockStaticProvider


@pytest.fixture()
def isolated_client(tmp_path) -> TestClient:
    """Provide a TestClient backed by an isolated async SQLite DB (or Postgres when configured)."""
    db_file = tmp_path / "m2_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _init_db() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    import asyncio

    asyncio.run(_init_db())

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    det_provider = MockStaticProvider(deterministic=True, live_jitter=False)

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_market_provider] = lambda: det_provider

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def test_strategy_crud_round_trip(isolated_client: TestClient) -> None:
    expiries = isolated_client.get("/api/v1/market/expiries?symbol=NIFTY").json()
    near_exp = expiries[0]["expiry_date"]
    far_exp = expiries[1]["expiry_date"]

    create_payload = {
        "name": "NIFTY Calendar + Closed Leg",
        "symbol": "NIFTY",
        "mode": "builder",
        "legs": [
            {
                "leg_id": "leg-1",
                "contract_id": f"NSE_FNO:NIFTY:{near_exp}:24350:CE",
                "symbol": "NIFTY",
                "exchange": "NSE_FNO",
                "expiry": near_exp,
                "strike": 24350.0,
                "option_type": "CE",
                "side": "SELL",
                "lots": 2,
                "lot_size": 65,
                "entry_price": 145.5,
                "entry_iv": 0.14,
                "enabled": True,
                "status": "OPEN",
            },
            {
                "leg_id": "leg-2",
                "contract_id": f"NSE_FNO:NIFTY:{far_exp}:24350:CE",
                "symbol": "NIFTY",
                "exchange": "NSE_FNO",
                "expiry": far_exp,
                "strike": 24350.0,
                "option_type": "CE",
                "side": "BUY",
                "lots": 2,
                "lot_size": 65,
                "entry_price": 320.0,
                "entry_iv": 0.145,
                "enabled": True,
                "status": "OPEN",
            },
        ],
        "closed_legs": [
            {
                "leg_id": "leg-0",
                "contract_id": f"NSE_FNO:NIFTY:{near_exp}:24500:CE",
                "symbol": "NIFTY",
                "expiry": near_exp,
                "strike": 24500.0,
                "option_type": "CE",
                "side": "SELL",
                "lots_closed": 1,
                "lot_size": 65,
                "entry_price": 90.0,
                "exit_price": 62.0,
                "realized_pnl": 1820.0,
                "closed_at": datetime(2026, 11, 25, 10, 15, tzinfo=IST).isoformat(),
            }
        ],
        "realized_pnl": "1820.00",
        "metadata": {"preset": "calendar_spread", "tag": "weekly_vs_next"},
        "notes": "Initial calendar test",
    }

    r_create = isolated_client.post("/api/v1/strategies", json=create_payload)
    assert r_create.status_code == 201
    created = r_create.json()
    strat_id = created["id"]
    assert created["name"] == "NIFTY Calendar + Closed Leg"
    assert len(created["legs"]) == 2
    assert len(created["closed_legs"]) == 1
    assert Decimal(created["realized_pnl"]) == Decimal("1820.00")
    assert created["metadata"]["preset"] == "calendar_spread"

    r_list = isolated_client.get("/api/v1/strategies")
    assert r_list.status_code == 200
    assert any(item["id"] == strat_id for item in r_list.json())

    r_get = isolated_client.get(f"/api/v1/strategies/{strat_id}")
    assert r_get.status_code == 200
    assert r_get.json()["notes"] == "Initial calendar test"

    r_put = isolated_client.put(
        f"/api/v1/strategies/{strat_id}",
        json={"name": "NIFTY Calendar Updated", "realized_pnl": "2500.50"},
    )
    assert r_put.status_code == 200
    assert r_put.json()["name"] == "NIFTY Calendar Updated"
    assert Decimal(r_put.json()["realized_pnl"]) == Decimal("2500.50")

    r_del = isolated_client.delete(f"/api/v1/strategies/{strat_id}")
    assert r_del.status_code == 204
    assert isolated_client.get(f"/api/v1/strategies/{strat_id}").status_code == 404


def test_idempotent_order_replay_and_freeze_slicing(isolated_client: TestClient) -> None:
    exp = get_expiries("NIFTY", datetime(2026, 11, 25, 10, 0, tzinfo=IST))[0].expiry_date
    cid = build_option_contract_id("NSE_FNO", "NIFTY", exp, 24350, "CE")
    idem_key = str(uuid.uuid4())

    # 120 lots * 65 = 7800 qty > 3510 freeze_qty -> 1 parent + 3 child slices (54, 54, 12 lots)
    order_req = {
        "trading_mode": "SIMULATOR",
        "action": "OPEN_LEGS",
        "slice_if_frozen": True,
        "legs": [
            {
                "leg_id": "big-leg",
                "contract_id": cid,
                "side": "SELL",
                "lots": 120,
                "limit_price": "152.37",  # should snap to 152.35
            }
        ],
    }

    r1 = isolated_client.post(
        "/api/v1/orders/execute",
        json=order_req,
        headers={"X-Idempotency-Key": idem_key},
    )
    assert r1.status_code == 200
    res1 = r1.json()
    assert res1["deduplicated"] is False
    assert len(res1["fills"]) == 4  # 1 parent + 3 child slices
    parent_fill = res1["fills"][0]
    child_fills = res1["fills"][1:]
    assert parent_fill["is_parent"] is True
    assert parent_fill["total_slices"] == 3
    assert parent_fill["quantity"] == 7800
    assert parent_fill["fill_price"] == "152.35"  # tick snapped
    assert [c["lots"] for c in child_fills] == [54, 54, 12]
    assert all(c["parent_order_id"] == parent_fill["order_id"] for c in child_fills)

    # Replay exact same X-Idempotency-Key -> deduplicated=True, 0 new DB rows
    r2 = isolated_client.post(
        "/api/v1/orders/execute",
        json=order_req,
        headers={"X-Idempotency-Key": idem_key},
    )
    assert r2.status_code == 200
    res2 = r2.json()
    assert res2["deduplicated"] is True
    assert res2["fills"] == res1["fills"]

    audit_rows = isolated_client.get("/api/v1/orders").json()
    assert len(audit_rows) == 4


def test_partial_exit_realized_pnl_and_multi_expiry_quotes(isolated_client: TestClient) -> None:
    expiries = get_expiries("NIFTY", datetime(2026, 11, 25, 10, 0, tzinfo=IST), count=3)
    near_exp = expiries[0].expiry_date
    far_exp = expiries[-1].expiry_date

    cid_near = build_option_contract_id("NSE_FNO", "NIFTY", near_exp, 24350, "CE")
    cid_far = build_option_contract_id("NSE_FNO", "NIFTY", far_exp, 24350, "CE")
    cid_fut = build_future_contract_id("NSE_FNO", "NIFTY", near_exp)

    r_quotes = isolated_client.post(
        "/api/v1/market/quotes",
        json={"contract_ids": [cid_near, cid_far, cid_fut]},
    )
    assert r_quotes.status_code == 200
    quotes = r_quotes.json()["quotes"]
    assert set(quotes.keys()) == {cid_near, cid_far, cid_fut}
    assert quotes[cid_far]["ltp"] > quotes[cid_near]["ltp"]
    assert quotes[cid_fut]["option_type"] == "FUT"

    # Partial exit: closing 2 lots of a SELL position entered at 180.00 via BUY at 120.00
    # Realized PnL = (180.00 - 120.00) * (2 * 65) = +7800.00
    exit_req = {
        "trading_mode": "SIMULATOR",
        "action": "PARTIAL_EXIT",
        "legs": [
            {
                "leg_id": "exit-leg",
                "contract_id": cid_near,
                "side": "BUY",
                "lots": 2,
                "limit_price": "120.02",  # snaps to 120.00
                "entry_price": "180.00",
            }
        ],
    }
    r_exit = isolated_client.post(
        "/api/v1/orders/execute",
        json=exit_req,
        headers={"X-Idempotency-Key": str(uuid.uuid4())},
    )
    assert r_exit.status_code == 200
    exit_res = r_exit.json()
    assert Decimal(exit_res["realized_pnl_delta"]) == Decimal("7800.00")

    # Verify analytics & simulator step endpoints
    step_req = {
        "symbol": "NIFTY",
        "current_as_of": datetime(2026, 11, 25, 10, 0, tzinfo=IST).isoformat(),
        "step": "+15m",
        "chain_expiry": near_exp.isoformat(),
        "active_contracts": [cid_near, cid_far],
    }
    r_step = isolated_client.post("/api/v1/simulator/step", json=step_req)
    assert r_step.status_code == 200
    step_data = r_step.json()
    assert "10:15:00" in step_data["new_as_of"]
    assert set(step_data["leg_quotes"].keys()) == {cid_near, cid_far}

    eval_req = {
        "symbol": "NIFTY",
        "spot": 24350.0,
        "as_of": datetime(2026, 11, 25, 10, 0, tzinfo=IST).isoformat(),
        "legs": [
            {
                "leg_id": "l1",
                "contract_id": cid_near,
                "symbol": "NIFTY",
                "exchange": "NSE_FNO",
                "expiry": near_exp.isoformat(),
                "strike": 24350.0,
                "option_type": "CE",
                "side": "SELL",
                "lots": 1,
                "lot_size": 65,
                "entry_price": 150.0,
                "entry_iv": 0.14,
            }
        ],
    }
    r_eval = isolated_client.post("/api/v1/analytics/evaluate", json=eval_req)
    assert r_eval.status_code == 200
    assert r_eval.json()["margin"]["margin_source"] == "estimated_stress"


def test_websocket_multi_expiry_tick_stream() -> None:
    jitter_provider = MockStaticProvider(deterministic=False, live_jitter=True, seed=99)
    app.dependency_overrides[get_market_provider] = lambda: jitter_provider

    expiries = get_expiries("NIFTY", datetime(2026, 11, 25, 10, 0, tzinfo=IST), count=3)
    near_exp = expiries[0].expiry_date
    far_exp = expiries[-1].expiry_date
    far_contract = build_option_contract_id("NSE_FNO", "NIFTY", far_exp, 24350, "CE")

    try:
        with (
            TestClient(app) as client,
            client.websocket_connect("/api/v1/ws/stream?interval_ms=25") as ws,
        ):
            ws.send_json({"action": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"

            ws.send_json(
                {
                    "action": "subscribe",
                    "symbol": "NIFTY",
                    "chain_expiry": near_exp.isoformat(),
                    "active_contracts": [far_contract],
                }
            )
            frame1 = ws.receive_json()
            frame2 = ws.receive_json()

            assert frame1["type"] == "tick"
            assert frame1["symbol"] == "NIFTY"
            assert frame1["chain_expiry"] == near_exp.isoformat()
            assert len(frame1["chain_deltas"]) == 61
            assert far_contract in frame1["leg_quotes"]
            assert frame1["leg_quotes"][far_contract]["expiry"] == far_exp.isoformat()
            # Live jitter produces non-identical frames across ticks
            assert frame1["spot"] != frame2["spot"] or frame1["india_vix"] != frame2["india_vix"]
    finally:
        app.dependency_overrides.clear()
