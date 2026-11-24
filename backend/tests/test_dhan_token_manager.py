"""Tests for Daily Dhan Token Manager: /v2/profile validation, Postgres persistence, RenewToken, & WS hot-reload."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.providers.dhan_ws import DhanLiveMarketProvider
from app.providers.mock_static import MockStaticProvider
from app.services.dhan_auth import DhanAuthError, DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster


@pytest.mark.asyncio
async def test_dhan_token_validation_persistence_renew_and_hot_reload(tmp_path: Path) -> None:
    db_file = tmp_path / "dhan_auth.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    mgr = DhanTokenManager()
    reloads: list[tuple[str | None, str | None, bool]] = []

    async def _on_reload(cid: str | None, tok: str | None, active: bool) -> None:
        reloads.append((cid, tok, active))

    mgr.register_reload_listener(_on_reload)

    def _handler(req: httpx.Request) -> httpx.Response:
        if "/v2/profile" in str(req.url):
            if req.headers.get("access-token") == "bad-token":
                return httpx.Response(401, json={"error": "Invalid token"})
            return httpx.Response(
                200,
                json={
                    "dhanClientId": "11009988",
                    "dhanClientName": "Avi F&O",
                    "dhanClientUcc": "AVIUCC1",
                    "tokenValidity": (datetime.now(UTC) + timedelta(hours=18)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                },
            )
        if "/v2/RenewToken" in str(req.url):
            return httpx.Response(
                200,
                json={
                    "token": "renewed-jwt-token-999",
                    "expiryTime": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
                },
            )
        return httpx.Response(404)

    async with (
        session_factory() as session,
        httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client,
    ):
        # 1. Invalid token fails cleanly without activating live mode
        with pytest.raises(DhanAuthError):
            await mgr.validate_and_save_token(session, "11009988", "bad-token", http_client=client)
        assert mgr.get_status().mode == "MOCK_FALLBACK"

        # 2. Valid token persists to Postgres and triggers hot-reload
        status = await mgr.validate_and_save_token(
            session, "11009988", "daily-jwt-token-111", http_client=client
        )
        assert status.connected is True
        assert status.mode == "LIVE_DHAN"
        assert status.client_id_masked == "11****88"
        assert status.account_name == "Avi F&O"
        assert reloads[-1] == ("11009988", "daily-jwt-token-111", True)

        # 3. Simulate backend restart: fresh DhanTokenManager loads token from Postgres
        mgr_restarted = DhanTokenManager()
        master = DhanScripMaster(tmp_path / "scrip.csv")
        live_provider = DhanLiveMarketProvider(
            mgr_restarted, master, MockStaticProvider(deterministic=True)
        )
        await mgr_restarted.load_on_startup(session)
        assert mgr_restarted.get_status().mode == "LIVE_DHAN"
        assert mgr_restarted.access_token == "daily-jwt-token-111"
        await live_provider.stop()

        # 4. Renew active token (+24h)
        renewed = await mgr.renew_active_token(session, http_client=client)
        assert renewed.connected is True
        assert mgr.access_token == "renewed-jwt-token-999"
        assert reloads[-1] == ("11009988", "renewed-jwt-token-999", True)

        # 5. Disconnect switches cleanly back to mock
        disc = await mgr.disconnect_to_mock()
        assert disc.mode == "MOCK_FALLBACK"
        assert reloads[-1][2] is False

    await engine.dispose()

