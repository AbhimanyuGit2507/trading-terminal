"""FastAPI application entrypoint mounting all v1 REST, Broker, & WS routes."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_market_provider, get_token_manager
from app.api.v1 import analytics, broker, market, orders, simulator, strategies
from app.api.ws import router as ws_router
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal, engine, get_db_session

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
    token_mgr = get_token_manager()
    market_provider = get_market_provider()
    if get_db_session not in app_instance.dependency_overrides:
        try:
            async with AsyncSessionLocal() as session:
                await token_mgr.load_on_startup(session)
        except (OSError, SQLAlchemyError) as exc:
            logger.warning("Skipping Dhan startup credential load: %s", exc)
    yield
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
    return {
        "status": "ok",
        "trading_mode": settings.trading_mode,
        "kill_switch_engaged": settings.kill_switch_engaged,
        "feed_mode": status.mode,
    }


app.include_router(market.router, prefix=settings.api_v1_prefix)
app.include_router(analytics.router, prefix=settings.api_v1_prefix)
app.include_router(orders.router, prefix=settings.api_v1_prefix)
app.include_router(strategies.router, prefix=settings.api_v1_prefix)
app.include_router(simulator.router, prefix=settings.api_v1_prefix)
app.include_router(broker.router, prefix=settings.api_v1_prefix)
app.include_router(ws_router, prefix=settings.api_v1_prefix)
