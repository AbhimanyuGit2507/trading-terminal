"""Tests for RiskGuard MTM Circuit Breaker, Emergency Kill Switch, & Typed Unlock."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.calendar import IST
from app.db.base import Base
from app.providers.dhan_broker import DhanExecutionProvider
from app.providers.margin_provider import StressMarginProvider
from app.providers.mock_static import MockStaticProvider
from app.providers.virtual_broker import KillSwitchEngagedError
from app.schemas.domain import BatchOrderRequest, OrderLegInstruction
from app.services.dhan_auth import DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster
from app.services.risk_guard import RiskGuardService, RiskLimitError


async def _make_session() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_mtm_breaker_cancels_orders_exits_positions_and_blocks_subsequent_orders(
    tmp_path: Any,
) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/v2/orders":
            return httpx.Response(
                200,
                json=[{"orderId": "ORD-PENDING-1", "orderStatus": "PENDING"}],
            )
        if request.method == "GET" and request.url.path == "/v2/super/orders":
            return httpx.Response(
                200,
                json=[{"orderId": "SUP-TRANSIT-1", "orderStatus": "TRANSIT"}],
            )
        if request.method == "DELETE" and request.url.path in (
            "/v2/orders/ORD-PENDING-1",
            "/v2/super/orders/SUP-TRANSIT-1",
            "/v2/positions",
        ):
            return httpx.Response(200, json={"status": "SUCCESS"})
        if request.method == "GET" and request.url.path == "/v2/positions":
            # Simulate 1 residual open short position that needed individual MARKET fallback
            return httpx.Response(
                200,
                json=[
                    {
                        "tradingSymbol": "NIFTY-24400-CE",
                        "exchangeSegment": "NSE_FNO",
                        "securityId": "51001",
                        "productType": "MARGIN",
                        "netQty": -65,
                    }
                ],
            )
        if request.method == "POST" and request.url.path == "/v2/orders":
            body = json.loads(request.content.decode("utf-8"))
            assert body["transactionType"] == "BUY"
            assert body["orderType"] == "MARKET"
            assert body["quantity"] == 65
            return httpx.Response(200, json={"orderId": "ORD-FB-1", "orderStatus": "TRADED"})
        return httpx.Response(404)

    tokens = DhanTokenManager()
    tokens.client_id = "1100998877"
    tokens.access_token = "eyJ_sandbox_tok"

    market = MockStaticProvider(deterministic=True)
    scrip = DhanScripMaster(tmp_path / "scrip.csv")
    scrip.contract_to_dhan["NSE_FNO:NIFTY:2026-12-01:24400:CE"] = ("NSE_FNO", "51001")
    scrip.loaded_at = datetime.now(IST)

    engine, session_factory = await _make_session()
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        guard = RiskGuardService(
            token_manager=tokens,
            market_provider=market,
            margin_provider=StressMarginProvider(),
            http_client=client,
        )
        guard.daily_max_loss_inr = 10000.0
        guard.active_execution_mode = "DHAN_SANDBOX"

        # 1. Small loss within limit does NOT trigger breaker
        assert await guard.evaluate_mtm_and_enforce(session, -4000.0, env="SANDBOX") is None
        assert guard.daily_kill_switch_active is False

        # 2. Loss breaching daily_max_loss_inr triggers full Kill Switch cascade
        trig = await guard.evaluate_mtm_and_enforce(session, -10500.0, env="SANDBOX")
        assert trig is not None
        assert trig.kill_switch_active is True
        assert trig.cancelled_orders == 2
        assert trig.exited_positions == 1
        assert trig.fallback_exits == 1
        assert guard.daily_kill_switch_active is True

        assert ("DELETE", "/v2/orders/ORD-PENDING-1") in calls
        assert ("DELETE", "/v2/super/orders/SUP-TRANSIT-1") in calls
        assert ("DELETE", "/v2/positions") in calls
        assert ("POST", "/v2/orders") in calls

        # 3. Subsequent orders MUST be blocked while kill switch active
        broker = DhanExecutionProvider(
            token_manager=tokens,
            scrip_master=scrip,
            market_provider=market,
            risk_guard=guard,
            http_client=client,
        )
        req = BatchOrderRequest(
            trading_mode="DHAN_SANDBOX",
            action="OPEN_LEGS",
            legs=[
                OrderLegInstruction(
                    contract_id="NSE_FNO:NIFTY:2026-12-01:24400:CE",
                    side="BUY",
                    lots=1,
                    lot_size=65,
                    limit_price=Decimal("150.00"),
                )
            ],
        )
        with pytest.raises(KillSwitchEngagedError):
            await broker.execute_orders(session, req, uuid.uuid4())

        # 4. Wrong unlock phrase fails; typed UNLOCK restores normal state
        with pytest.raises(RiskLimitError):
            await guard.unlock_kill_switch(session, "wrong")
        unlocked = await guard.unlock_kill_switch(session, "UNLOCK")
        assert unlocked.daily_kill_switch_active is False

    await engine.dispose()

