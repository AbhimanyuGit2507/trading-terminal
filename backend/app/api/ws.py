"""Unified WebSocket tick stream (/api/v1/ws/stream)."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import date

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.deps import get_market_provider
from app.core.config import get_settings
from app.providers.base import MarketDataProvider
from app.schemas.domain import IndexSymbol, WsSubscribeMessage, WsTickFrameSchema

router = APIRouter(tags=["ws"])


@router.websocket("/ws/stream")
async def websocket_stream(
    websocket: WebSocket,
    interval_ms: int | None = Query(default=None, ge=20, le=5000),
    provider: MarketDataProvider = Depends(get_market_provider),
) -> None:
    await websocket.accept()
    settings = get_settings()
    cadence_sec = (interval_ms if interval_ms is not None else settings.ws_tick_interval_ms) / 1000.0

    state: dict[str, object] = {
        "subscribed": False,
        "symbol": "NIFTY",
        "chain_expiry": None,
        "active_contracts": [],
    }
    sub_event = asyncio.Event()

    async def _push_once() -> None:
        sym: IndexSymbol = state["symbol"]  # type: ignore[assignment]
        exp: date | None = state["chain_expiry"]  # type: ignore[assignment]
        contracts: list[str] = list(state["active_contracts"])  # type: ignore[arg-type]
        frame = await provider.build_tick_frame(
            symbol=sym,
            chain_expiry=exp,
            active_contracts=contracts,
        )
        await websocket.send_json(frame.model_dump(mode="json"))

    async def _sender_loop() -> None:
        while True:
            await sub_event.wait()
            while state["subscribed"]:
                await _push_once()
                await asyncio.sleep(cadence_sec)

    sender_task = asyncio.create_task(_sender_loop())
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                msg = WsSubscribeMessage.model_validate(raw)
            except ValidationError as exc:
                err_frame = WsTickFrameSchema(type="error", message=str(exc))
                await websocket.send_json(err_frame.model_dump(mode="json"))
                continue

            if msg.action == "ping":
                await websocket.send_json(WsTickFrameSchema(type="pong").model_dump(mode="json"))
            elif msg.action == "subscribe":
                state["symbol"] = msg.symbol
                state["chain_expiry"] = msg.chain_expiry
                state["active_contracts"] = msg.active_contracts
                state["subscribed"] = True
                sub_event.set()
            elif msg.action == "unsubscribe":
                state["subscribed"] = False
                sub_event.clear()
    except WebSocketDisconnect:
        pass
    finally:
        sender_task.cancel()
        with suppress(asyncio.CancelledError):
            await sender_task

