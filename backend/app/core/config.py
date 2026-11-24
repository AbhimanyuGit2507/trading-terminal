"""Application settings and safety configuration."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "StockMock Indian F&O Terminal API"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"

    database_url: str = (
        "postgresql+asyncpg://stockmock:stockmock_dev@localhost:5434/stockmock"
    )

    # Safety guards (Phase 4 readiness)
    trading_mode: Literal["SIMULATOR", "PAPER", "SANDBOX", "LIVE"] = "SIMULATOR"
    kill_switch_engaged: bool = False

    # Quant defaults locked by Tech Lead
    default_risk_free_rate: float = 0.0
    include_charges_default: bool = False

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
