"""FastAPI dependency providers for decoupled MarketData, Margin, Execution, and Dhan Auth."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.providers.dhan_broker import CompositeExecutionProvider, DhanExecutionProvider
from app.providers.dhan_margin import DhanMarginProvider
from app.providers.dhan_ws import DhanLiveMarketProvider
from app.providers.margin_provider import StressMarginProvider
from app.providers.mock_static import MockStaticProvider
from app.providers.parquet_hist import ParquetHistoricalProvider
from app.providers.virtual_broker import VirtualSimulatorBroker
from app.services.dhan_auth import DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster
from app.services.risk_guard import RiskGuardService


@lru_cache
def get_token_manager() -> DhanTokenManager:
    return DhanTokenManager()


@lru_cache
def get_scrip_master() -> DhanScripMaster:
    settings = get_settings()
    return DhanScripMaster(cache_path=settings.scrip_master_cache_path)


@lru_cache
def get_mock_provider() -> MockStaticProvider:
    settings = get_settings()
    return MockStaticProvider(
        deterministic=not settings.mock_live_jitter,
        live_jitter=settings.mock_live_jitter,
    )


@lru_cache
def get_market_provider() -> DhanLiveMarketProvider:
    return DhanLiveMarketProvider(
        token_manager=get_token_manager(),
        scrip_master=get_scrip_master(),
        mock_fallback=get_mock_provider(),
    )


@lru_cache
def get_historical_provider() -> ParquetHistoricalProvider:
    settings = get_settings()
    return ParquetHistoricalProvider(parquet_dir=settings.parquet_data_dir)


@lru_cache
def get_margin_provider() -> DhanMarginProvider:
    settings = get_settings()
    return DhanMarginProvider(
        token_manager=get_token_manager(),
        scrip_master=get_scrip_master(),
        fallback=StressMarginProvider(risk_free_rate=settings.default_risk_free_rate),
    )


@lru_cache
def get_risk_guard() -> RiskGuardService:
    return RiskGuardService(
        token_manager=get_token_manager(),
        market_provider=get_market_provider(),
        margin_provider=get_margin_provider(),
    )


@lru_cache
def get_dhan_broker() -> DhanExecutionProvider:
    return DhanExecutionProvider(
        token_manager=get_token_manager(),
        scrip_master=get_scrip_master(),
        market_provider=get_market_provider(),
        risk_guard=get_risk_guard(),
    )


def get_execution_provider() -> CompositeExecutionProvider:
    return CompositeExecutionProvider(
        virtual_broker=VirtualSimulatorBroker(market_provider=get_market_provider()),
        dhan_broker=get_dhan_broker(),
        risk_guard=get_risk_guard(),
    )
