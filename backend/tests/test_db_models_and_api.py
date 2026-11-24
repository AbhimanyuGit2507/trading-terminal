"""Tests for SQLAlchemy models (idempotency uniqueness, parent/child slicing) & FastAPI routes."""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import StrategyModel, VirtualOrderModel
from app.main import app


@pytest.mark.asyncio
async def test_sqlalchemy_strategy_and_idempotent_order_constraints() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    idem_key = uuid.uuid4()

    async with session_factory() as session:
        strat = StrategyModel(
            name="NIFTY Iron Fly",
            symbol="NIFTY",
            mode="builder",
            legs_json=[{"contract_id": "NSE_FNO:NIFTY:2026-11-23:24350:CE"}],
            realized_pnl=Decimal("1250.50"),
        )
        session.add(strat)
        await session.flush()

        parent = VirtualOrderModel(
            strategy_id=strat.id,
            idempotency_key=idem_key,
            trading_mode="SIMULATOR",
            contract_id="NSE_FNO:NIFTY:2026-11-23:24350:CE",
            side="SELL",
            action="OPEN",
            lots=60,
            quantity=3900,
            fill_price=Decimal("152.35"),
            total_slices=2,
            slice_index=0,
        )
        session.add(parent)
        await session.commit()

        # Duplicate idempotency_key must raise IntegrityError
        dup = VirtualOrderModel(
            strategy_id=strat.id,
            idempotency_key=idem_key,
            trading_mode="SIMULATOR",
            contract_id="NSE_FNO:NIFTY:2026-11-23:24350:CE",
            side="SELL",
            action="OPEN",
            lots=60,
            quantity=3900,
        )
        session.add(dup)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

    await engine.dispose()


def test_fastapi_milestone1_endpoints() -> None:
    client = TestClient(app)

    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["trading_mode"] == "SIMULATOR"

    r_inst = client.get("/api/v1/market/instruments")
    assert r_inst.status_code == 200
    symbols = {item["symbol"]: item for item in r_inst.json()}
    assert symbols["NIFTY"]["lot_size"] == 65
    assert symbols["BANKNIFTY"]["has_weekly"] is False

    r_chain = client.get("/api/v1/market/chain?symbol=NIFTY")
    assert r_chain.status_code == 200
    data = r_chain.json()
    assert len(data["rows"]) == 61
    assert data["lot_size"] == 65
