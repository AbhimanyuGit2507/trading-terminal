"""Tests for Simulator clock rollover, holiday skipping, MTM repricing, and 15:30 IST expiry settlement."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_historical_provider, get_market_provider
from app.api.v1.simulator import advance_sim_clock
from app.core.calendar import IST
from app.core.contracts import build_option_contract_id
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.providers.mock_static import MockStaticProvider
from app.providers.parquet_hist import ParquetHistoricalProvider
from app.services.historical_ingestor import HistoricalOptionBar, write_parquet_partitions


def test_simulator_clock_market_hours_rollover_and_holiday_skip() -> None:
    # 2026-11-23 (Mon) 15:29 + 1m -> skips 2026-11-24 (configured holiday) -> 2026-11-25 09:15 IST
    t1 = datetime(2026, 11, 23, 15, 29, tzinfo=IST)
    nxt = advance_sim_clock(t1, "+1m")
    assert nxt == datetime(2026, 11, 25, 9, 15, tzinfo=IST)

    # Rewinding 1m from 2026-11-25 09:15 -> 2026-11-23 15:29 IST
    prv = advance_sim_clock(nxt, "-1m")
    assert prv == datetime(2026, 11, 23, 15, 29, tzinfo=IST)

    # Weekend skip: Friday 15:25 + 15m -> Monday 09:25 IST
    fri = datetime(2026, 11, 20, 15, 25, tzinfo=IST)
    mon = advance_sim_clock(fri, "+15m")
    assert mon == datetime(2026, 11, 23, 9, 25, tzinfo=IST)


def test_simulator_mtm_and_auto_expiry_settlement(tmp_path: Path) -> None:
    parquet_dir = tmp_path / "parquet"
    exp = date(2026, 11, 23)
    next_day = date(2026, 11, 25)

    # Seed bars on expiry day (09:20, 15:25, and 15:29 settling at spot 24450) + next trading day 09:15
    bars = [
        HistoricalOptionBar(datetime(2026, 11, 23, 9, 20), "NIFTY", exp, 24350.0, "CE", 95.0, 96.0, 94.0, 95.0, 1000, 100000, 0.14, 24350.0, 24355.0),
        HistoricalOptionBar(datetime(2026, 11, 23, 9, 20), "NIFTY", exp, 24350.0, "PE", 90.0, 91.0, 89.0, 90.0, 1000, 100000, 0.14, 24350.0, 24355.0),
        HistoricalOptionBar(datetime(2026, 11, 23, 15, 25), "NIFTY", exp, 24350.0, "CE", 98.0, 99.0, 97.0, 98.0, 1800, 115000, 0.125, 24410.0, 24412.0),
        HistoricalOptionBar(datetime(2026, 11, 23, 15, 25), "NIFTY", exp, 24350.0, "PE", 12.0, 13.0, 11.0, 12.0, 1800, 115000, 0.125, 24410.0, 24412.0),
        HistoricalOptionBar(datetime(2026, 11, 23, 15, 29), "NIFTY", exp, 24350.0, "CE", 100.0, 101.0, 99.0, 100.0, 2000, 120000, 0.12, 24450.0, 24450.0),
        HistoricalOptionBar(datetime(2026, 11, 23, 15, 29), "NIFTY", exp, 24350.0, "PE", 0.05, 0.1, 0.05, 0.05, 2000, 120000, 0.12, 24450.0, 24450.0),
        HistoricalOptionBar(datetime(2026, 11, 25, 9, 15), "NIFTY", date(2026, 12, 1), 24450.0, "CE", 180.0, 181.0, 179.0, 180.0, 1500, 110000, 0.14, 24460.0, 24470.0),
        HistoricalOptionBar(datetime(2026, 11, 25, 9, 15), "NIFTY", date(2026, 12, 1), 24450.0, "PE", 170.0, 171.0, 169.0, 170.0, 1500, 110000, 0.14, 24460.0, 24470.0),
    ]
    write_parquet_partitions(parquet_dir, bars)

    db_file = tmp_path / "sim_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _init() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())

    async def _override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    hist_provider = ParquetHistoricalProvider(parquet_dir=parquet_dir)
    mock_provider = MockStaticProvider(deterministic=True)

    app.dependency_overrides[get_db_session] = _override_db
    app.dependency_overrides[get_historical_provider] = lambda: hist_provider
    app.dependency_overrides[get_market_provider] = lambda: mock_provider

    ce_cid = build_option_contract_id("NSE_FNO", "NIFTY", exp, 24350, "CE")
    pe_cid = build_option_contract_id("NSE_FNO", "NIFTY", exp, 24350, "PE")

    try:
        with TestClient(app) as client:
            r_dates = client.get("/api/v1/simulator/available-dates?symbol=NIFTY")
            assert r_dates.status_code == 200
            assert r_dates.json()["dates"] == [exp.isoformat(), next_day.isoformat()]
            assert r_dates.json()["data_source"] == "parquet"

            # Jump to 2026-11-23 15:25 IST holding a Short Straddle sold at 95 + 90
            r_jump = client.post(
                "/api/v1/simulator/jump",
                json={
                    "symbol": "NIFTY",
                    "target_dt": datetime(2026, 11, 23, 15, 25, tzinfo=IST).isoformat(),
                    "chain_expiry": exp.isoformat(),
                    "active_contracts": [ce_cid, pe_cid],
                },
            )
            assert r_jump.status_code == 200
            assert r_jump.json()["data_source"] == "parquet"
            assert r_jump.json()["leg_quotes"][ce_cid]["ltp"] == 98.0

            # Step +5m crossing 15:30 IST -> triggers auto-settlement at 24450 spot!
            # Short 24350 CE (entry 95, intrinsic 100) => (95 - 100) * 65 = -325
            # Short 24350 PE (entry 90, intrinsic 0)   => (90 - 0) * 65   = +5850
            # Net realized_pnl_delta = +5525.00
            open_legs = [
                {
                    "leg_id": "ce-leg",
                    "contract_id": ce_cid,
                    "symbol": "NIFTY",
                    "exchange": "NSE_FNO",
                    "expiry": exp.isoformat(),
                    "strike": 24350.0,
                    "option_type": "CE",
                    "side": "SELL",
                    "lots": 1,
                    "lot_size": 65,
                    "entry_price": 95.0,
                    "entry_iv": 0.14,
                    "enabled": True,
                    "status": "OPEN",
                },
                {
                    "leg_id": "pe-leg",
                    "contract_id": pe_cid,
                    "symbol": "NIFTY",
                    "exchange": "NSE_FNO",
                    "expiry": exp.isoformat(),
                    "strike": 24350.0,
                    "option_type": "PE",
                    "side": "SELL",
                    "lots": 1,
                    "lot_size": 65,
                    "entry_price": 90.0,
                    "entry_iv": 0.14,
                    "enabled": True,
                    "status": "OPEN",
                },
            ]
            r_step = client.post(
                "/api/v1/simulator/step",
                json={
                    "symbol": "NIFTY",
                    "current_as_of": datetime(2026, 11, 23, 15, 25, tzinfo=IST).isoformat(),
                    "step": "+5m",
                    "chain_expiry": exp.isoformat(),
                    "active_contracts": [ce_cid, pe_cid],
                    "open_legs": open_legs,
                },
            )
            assert r_step.status_code == 200
            step_data = r_step.json()
            assert step_data["new_as_of"].startswith("2026-11-25T09:15:00")
            assert len(step_data["settled_legs"]) == 2
            assert Decimal(step_data["realized_pnl_delta"]) == Decimal("5525.00")

            # Verify SETTLED_AT_EXPIRY orders were persisted in virtual_orders
            orders = client.get("/api/v1/orders").json()
            assert len(orders) == 2
            assert all(o["action"] == "SETTLED_AT_EXPIRY" for o in orders)
    finally:
        app.dependency_overrides.clear()
        asyncio.run(engine.dispose())
