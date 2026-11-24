"""FastAPI application entrypoint mounting all v1 REST, Broker, Risk, System, & WS routes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import (
    get_dhan_broker,
    get_market_provider,
    get_risk_guard,
    get_token_manager,
)
from app.api.v1 import analytics, broker, market, orders, risk, simulator, strategies, system
from app.api.ws import router as ws_router
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal, engine, get_db_session
from app.providers.dhan_broker import DhanBrokerError, resolve_dhan_env
from app.services.dhan_auth import DhanAuthError
from app.services.risk_guard import is_market_hours_ist

logger = logging.getLogger(__name__)
settings = get_settings()


async def _mtm_circuit_breaker_loop() -> None:
    """Poll net MTM every 1 second during market hours and enforce daily max loss."""
    risk_guard = get_risk_guard()
    dhan_broker = get_dhan_broker()
    while True:
        await asyncio.sleep(1.0)
        try:
            if (
                risk_guard.active_execution_mode not in ("DHAN_SANDBOX", "DHAN_LIVE")
                or risk_guard.daily_kill_switch_active
                or not is_market_hours_ist()
            ):
                continue

            env = resolve_dhan_env(risk_guard.active_execution_mode)
            positions = await dhan_broker.fetch_positions(env)
            net_mtm = sum(p.realized_profit + p.unrealized_profit for p in positions)
            async with AsyncSessionLocal() as session:
                await risk_guard.evaluate_mtm_and_enforce(session, net_mtm, env=env)
        except asyncio.CancelledError:
            raise
        except (
            httpx.HTTPError,
            SQLAlchemyError,
            DhanAuthError,
            DhanBrokerError,
            OSError,
            ValueError,
        ) as exc:  # pragma: no cover - defensive loop guard
            logger.debug("MTM breaker poll skipped: %s", exc)


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
    token_mgr = get_token_manager()
    market_provider = get_market_provider()
    risk_guard = get_risk_guard()
    monitor_task: asyncio.Task[None] | None = None

    if get_db_session not in app_instance.dependency_overrides:
        try:
            async with AsyncSessionLocal() as session:
                await token_mgr.load_on_startup(session)
                await risk_guard.load_or_init(session)
        except (OSError, SQLAlchemyError) as exc:
            logger.warning("Skipping startup DB state load: %s", exc)
        monitor_task = asyncio.create_task(_mtm_circuit_breaker_loop())

    yield

    if monitor_task is not None:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
    await market_provider.stop()
    if get_db_session not in app_instance.dependency_overrides:
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str | bool]:
    status = get_token_manager().get_status()
    risk_guard = get_risk_guard()
    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "execution_mode": risk_guard.active_execution_mode,
        "kill_switch_engaged": settings.kill_switch_engaged or risk_guard.daily_kill_switch_active,
        "feed_mode": status.mode,
    }


app.include_router(market.router, prefix=settings.api_v1_prefix)
app.include_router(analytics.router, prefix=settings.api_v1_prefix)
app.include_router(orders.router, prefix=settings.api_v1_prefix)
app.include_router(strategies.router, prefix=settings.api_v1_prefix)
app.include_router(simulator.router, prefix=settings.api_v1_prefix)
app.include_router(broker.router, prefix=settings.api_v1_prefix)
app.include_router(risk.router, prefix=settings.api_v1_prefix)
app.include_router(system.router, prefix=settings.api_v1_prefix)
app.include_router(ws_router, prefix=settings.api_v1_prefix)
