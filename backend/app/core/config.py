"""Application settings and safety configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "StockMock Indian F&O Terminal API"
    app_version: str = "0.2.0"
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

    # Mock market streaming defaults
    mock_live_jitter: bool = False
    ws_tick_interval_ms: int = 250

    # Phase 2/3 Historical Parquet + DhanHQ v2 Live Market Feed
    parquet_data_dir: str = str(_ROOT_DIR / "data" / "parquet")
    scrip_master_cache_path: str = str(_ROOT_DIR / "data" / "cache" / "dhan_scrip_master.csv")
    market_data_source: Literal["auto", "dhan", "mock"] = "auto"
    dhan_client_id: str = ""
    dhan_access_token: str = ""

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()

