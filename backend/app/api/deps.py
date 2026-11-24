"""FastAPI dependency providers for decoupled MarketData, Margin, and Execution adapters."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.providers.margin_provider import StressMarginProvider
from app.providers.mock_static import MockStaticProvider
from app.providers.parquet_hist import ParquetHistoricalProvider
from app.providers.virtual_broker import VirtualSimulatorBroker


@lru_cache
def get_market_provider() -> MockStaticProvider:
    settings = get_settings()
    return MockStaticProvider(
        deterministic=not settings.mock_live_jitter,
        live_jitter=settings.mock_live_jitter,
    )


@lru_cache
def get_historical_provider() -> ParquetHistoricalProvider:
    settings = get_settings()
    return ParquetHistoricalProvider(parquet_dir=settings.parquet_data_dir)


@lru_cache
def get_margin_provider() -> StressMarginProvider:
    settings = get_settings()
    return StressMarginProvider(risk_free_rate=settings.default_risk_free_rate)


def get_execution_provider() -> VirtualSimulatorBroker:
    return VirtualSimulatorBroker(market_provider=get_market_provider())

