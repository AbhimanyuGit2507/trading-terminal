"""Tests for Margin-Safe Basket Ordering: BUY hedge legs first, abort SELL if hedge fails."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.calendar import IST
from app.db.base import Base
from app.providers.dhan_broker import DhanExecutionProvider, HedgeExecutionAbortedError
from app.providers.mock_static import MockStaticProvider
from app.schemas.domain import BatchOrderRequest, OrderLegInstruction
from app.services.dhan_auth import DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster


async def _make_session() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


def _setup_scrip(tmp_path: Any) -> DhanScripMaster:
    csv_path = tmp_path / "scrip.csv"
    scrip = DhanScripMaster(csv_path)
    scrip.contract_to_dhan["NSE_FNO:NIFTY:2026-12-01:24200:CE"] = ("NSE_FNO", "41001")
    scrip.contract_to_dhan["NSE_FNO:NIFTY:2026-12-01:24400:CE"] = ("NSE_FNO", "41002")
    scrip.contract_to_dhan["NSE_FNO:NIFTY:2026-12-01:24000:PE"] = ("NSE_FNO", "41003")
    scrip.contract_to_dhan["NSE_FNO:NIFTY:2026-12-01:24300:PE"] = ("NSE_FNO", "41004")
    scrip.loaded_at = datetime.now(IST)
    return scrip


def _setup_tokens() -> DhanTokenManager:
    mgr = DhanTokenManager()
    mgr.client_id = "1100998877"
    mgr.access_token = "eyJ_mock_sandbox_token"
    mgr.token_expired = False
    return mgr


@pytest.mark.asyncio
async def test_buy_hedges_execute_before_sell_legs_and_confirm_traded(tmp_path: Any) -> None:
    call_sequence: list[tuple[str, str, str]] = []
    poll_counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/orders":
            import json

            body = json.loads(request.content.decode("utf-8"))
            sec = str(body["securityId"])
            side = str(body["transactionType"])
            oid = f"ORD-{sec}"
            call_sequence.append(("POST", side, sec))
            return httpx.Response(
                200,
                json={"orderId": oid, "orderStatus": "PENDING"},
            )
        if request.method == "GET" and request.url.path.startswith("/v2/orders/ORD-"):
            oid = request.url.path.rsplit("/", 1)[-1]
            poll_counts[oid] = poll_counts.get(oid, 0) + 1
            call_sequence.append(("POLL", "CHECK", oid))
            return httpx.Response(
                200,
                json={
                    "orderId": oid,
                    "orderStatus": "TRADED",
                    "averageTradedPrice": 115.25,
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    engine, session_factory = await _make_session()
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        broker = DhanExecutionProvider(
            token_manager=_setup_tokens(),
            scrip_master=_setup_scrip(tmp_path),
            market_provider=MockStaticProvider(deterministic=True),
            http_client=client,
            poll_timeout_s=1.0,
            poll_interval_s=0.01,
        )
        # Deliberately pass SELL legs BEFORE BUY legs in request
        req = BatchOrderRequest(
            trading_mode="DHAN_SANDBOX",
            action="OPEN_LEGS",
            legs=[
                OrderLegInstruction(
                    contract_id="NSE_FNO:NIFTY:2026-12-01:24400:CE",
                    side="SELL",
                    lots=1,
                    lot_size=65,
                    limit_price=Decimal("130.00"),
                ),
                OrderLegInstruction(
                    contract_id="NSE_FNO:NIFTY:2026-12-01:24200:CE",
                    side="BUY",
                    lots=1,
                    lot_size=65,
                    limit_price=Decimal("210.00"),
                ),
                OrderLegInstruction(
                    contract_id="NSE_FNO:NIFTY:2026-12-01:24300:PE",
                    side="SELL",
                    lots=1,
                    lot_size=65,
                    limit_price=Decimal("125.00"),
                ),
                OrderLegInstruction(
                    contract_id="NSE_FNO:NIFTY:2026-12-01:24000:PE",
                    side="BUY",
                    lots=1,
                    lot_size=65,
                    limit_price=Decimal("60.00"),
                ),
            ],
        )
        res = await broker.execute_orders(session, req, uuid.uuid4())

    await engine.dispose()

    post_sides = [item[1] for item in call_sequence if item[0] == "POST"]
    assert post_sides == ["BUY", "BUY", "SELL", "SELL"]
    assert len(res.fills) == 4
    assert all(f.broker_order_id is not None for f in res.fills)
    # BUY hedges polled to TRADED before first SELL fired
    first_sell_idx = next(i for i, item in enumerate(call_sequence) if item[1] == "SELL")
    assert ("POLL", "CHECK", "ORD-41001") in call_sequence[:first_sell_idx]
    assert ("POLL", "CHECK", "ORD-41003") in call_sequence[:first_sell_idx]
    assert date(2026, 12, 1)  # sanity keep


@pytest.mark.asyncio
async def test_sell_legs_abort_if_buy_hedge_rejected(tmp_path: Any) -> None:
    posted_sides: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/v2/orders":
            import json

            body = json.loads(request.content.decode("utf-8"))
            side = str(body["transactionType"])
            posted_sides.append(side)
            return httpx.Response(
                200,
                json={
                    "orderId": "ORD-HEDGE-REJ",
                    "orderStatus": "REJECTED",
                    "omsErrorDescription": "RMS: Strike out of execution range",
                },
            )
        return httpx.Response(404)

    engine, session_factory = await _make_session()
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        broker = DhanExecutionProvider(
            token_manager=_setup_tokens(),
            scrip_master=_setup_scrip(tmp_path),
            market_provider=MockStaticProvider(deterministic=True),
            http_client=client,
            poll_timeout_s=0.5,
            poll_interval_s=0.01,
        )
        req = BatchOrderRequest(
            trading_mode="DHAN_SANDBOX",
            action="OPEN_LEGS",
            legs=[
                OrderLegInstruction(
                    contract_id="NSE_FNO:NIFTY:2026-12-01:24200:CE",
                    side="BUY",
                    lots=1,
                    lot_size=65,
                    limit_price=Decimal("210.00"),
                ),
                OrderLegInstruction(
                    contract_id="NSE_FNO:NIFTY:2026-12-01:24400:CE",
                    side="SELL",
                    lots=1,
                    lot_size=65,
                    limit_price=Decimal("130.00"),
                ),
            ],
        )
        with pytest.raises(HedgeExecutionAbortedError, match="SELL legs aborted"):
            await broker.execute_orders(session, req, uuid.uuid4())

    await engine.dispose()
    # SELL leg MUST NEVER fire after BUY hedge rejects
    assert posted_sides == ["BUY"]

