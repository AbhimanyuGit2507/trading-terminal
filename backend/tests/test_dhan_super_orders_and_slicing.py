"""Tests for Dhan Super Orders, Freeze-Qty Slicing, and X-Idempotency-Key deduplication."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.calendar import IST
from app.db.base import Base
from app.db.models import LiveOrderModel
from app.providers.dhan_broker import DhanExecutionProvider
from app.providers.mock_static import MockStaticProvider
from app.schemas.domain import BatchOrderRequest, OrderLegInstruction
from app.services.dhan_auth import DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster


async def _make_session() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_super_order_payload_freeze_slicing_and_idempotency(tmp_path: Any) -> None:
    dispatched: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        dispatched.append((request.url.path, body))
        idx = len(dispatched)
        return httpx.Response(
            200,
            json={
                "orderId": f"SUP-{idx}",
                "orderStatus": "TRADED",
                "averageTradedPrice": body.get("price") or 145.50,
            },
        )

    scrip = DhanScripMaster(tmp_path / "scrip.csv")
    scrip.contract_to_dhan["NSE_FNO:NIFTY:2026-12-01:24400:CE"] = ("NSE_FNO", "51001")
    scrip.loaded_at = datetime.now(IST)

    tokens = DhanTokenManager()
    tokens.client_id = "1100998877"
    tokens.access_token = "eyJ_sandbox_tok"

    engine, session_factory = await _make_session()
    idem_key = uuid.uuid4()

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client,
        session_factory() as session,
    ):
        broker = DhanExecutionProvider(
            token_manager=tokens,
            scrip_master=scrip,
            market_provider=MockStaticProvider(deterministic=True),
            http_client=client,
            poll_timeout_s=0.5,
            poll_interval_s=0.01,
        )
        # 60 lots * 65 = 3900 qty > NIFTY 2026 freeze_qty (3510) => splits into 54L (3510) + 6L (390)
        req = BatchOrderRequest(
            trading_mode="DHAN_SANDBOX",
            action="OPEN_LEGS",
            slice_if_frozen=True,
            legs=[
                OrderLegInstruction(
                    contract_id="NSE_FNO:NIFTY:2026-12-01:24400:CE",
                    side="SELL",
                    lots=60,
                    lot_size=65,
                    limit_price=Decimal("145.50"),
                    target_price=Decimal("80.00"),
                    stop_loss_price=Decimal("210.00"),
                    trailing_jump=Decimal("10.00"),
                )
            ],
        )

        res1 = await broker.execute_orders(session, req, idem_key)
        assert res1.deduplicated is False
        assert len(res1.fills) == 2
        assert [f.quantity for f in res1.fills] == [3510, 390]
        assert all(f.is_super_order for f in res1.fills)
        assert all(f.parent_order_id is not None for f in res1.fills)
        assert res1.fills[0].parent_order_id == res1.fills[1].parent_order_id

        # Verify Super Order endpoint & fields
        assert len(dispatched) == 2
        for path, payload in dispatched:
            assert path == "/v2/super/orders"
            assert payload["targetPrice"] == 80.0
            assert payload["stopLossPrice"] == 210.0
            assert payload["trailingJump"] == 10.0

        # Replay identical X-Idempotency-Key -> zero new HTTP calls!
        res2 = await broker.execute_orders(session, req, idem_key)
        assert res2.deduplicated is True
        assert res2.fills == res1.fills
        assert len(dispatched) == 2

        total_rows = (await session.execute(select(func.count(LiveOrderModel.id)))).scalar_one()
        # 1 parent row + 2 child slices
        assert total_rows == 3

    await engine.dispose()
