"""Daily DhanHQ API Token Manager with Postgres persistence and hot-reload hooks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar import IST
from app.core.config import get_settings
from app.db.models import BrokerCredentialModel
from app.schemas.domain import DhanStatusResponse, FeedStatus

DHAN_PROFILE_URL = "https://api.dhan.co/v2/profile"
DHAN_RENEW_URL = "https://api.dhan.co/v2/RenewToken"
DHAN_GENERATE_TOTP_URL = "https://auth.dhan.co/app/generateAccessToken"


class DhanAuthError(RuntimeError):
    """Raised when DhanHQ token validation, renewal, or TOTP generation fails."""


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _mask_client_id(cid: str | None) -> str | None:
    if not cid:
        return None
    if len(cid) <= 4:
        return "*" * len(cid)
    return f"{cid[:2]}{'*' * (len(cid) - 4)}{cid[-2:]}"


def _parse_dhan_expiry(raw: Any) -> datetime:
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        for fmt in ("%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=IST).astimezone(UTC)
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(s)
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=IST).astimezone(UTC)
        except ValueError:
            pass
    return datetime.now(UTC) + timedelta(hours=24)


HotReloadCallback = Callable[[str | None, str | None, bool], Awaitable[None]]


class DhanTokenManager:
    """Manages active Dhan credentials in memory + Postgres with live hot-reload."""

    def __init__(self) -> None:
        self.client_id: str | None = None
        self.access_token: str | None = None
        self.account_name: str | None = None
        self.ucc: str | None = None
        self.expires_at: datetime | None = None
        self.force_mock_override: bool = False
        self.token_expired: bool = False
        self.last_message: str | None = None
        self._listeners: list[HotReloadCallback] = []

    def register_reload_listener(self, cb: HotReloadCallback) -> None:
        self._listeners.append(cb)

    async def _notify_listeners(self) -> None:
        active = not self.force_mock_override and bool(self.client_id and self.access_token)
        for cb in self._listeners:
            await cb(self.client_id, self.access_token, active)

    async def load_on_startup(self, session: AsyncSession) -> None:
        """Load saved Dhan credentials from Postgres, falling back to .env."""
        stmt = select(BrokerCredentialModel).where(BrokerCredentialModel.broker == "DHAN")
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is not None and row.access_token:
            exp_utc = _as_utc(row.expires_at)
            self.client_id = row.client_id
            self.access_token = row.access_token
            self.account_name = row.account_name
            self.ucc = row.ucc
            self.expires_at = exp_utc
            self.force_mock_override = False
            self.token_expired = bool(
                exp_utc is not None and exp_utc <= datetime.now(UTC)
            )
            self.last_message = "Loaded persisted Dhan token from PostgreSQL."
        else:
            settings = get_settings()
            if settings.dhan_client_id and settings.dhan_access_token:
                self.client_id = settings.dhan_client_id
                self.access_token = settings.dhan_access_token
                self.expires_at = datetime.now(UTC) + timedelta(hours=24)
                self.token_expired = False
                self.last_message = "Loaded Dhan credentials from environment."

        await self._notify_listeners()

    async def _upsert_credential(
        self,
        session: AsyncSession,
        client_id: str,
        access_token: str,
        account_name: str | None,
        ucc: str | None,
        expires_at: datetime,
    ) -> None:
        stmt = select(BrokerCredentialModel).where(BrokerCredentialModel.broker == "DHAN")
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = BrokerCredentialModel(
                broker="DHAN",
                client_id=client_id,
                access_token=access_token,
                account_name=account_name,
                ucc=ucc,
                expires_at=expires_at,
            )
            session.add(row)
        else:
            row.client_id = client_id
            row.access_token = access_token
            row.account_name = account_name
            row.ucc = ucc
            row.expires_at = expires_at
        await session.commit()

        self.client_id = client_id
        self.access_token = access_token
        self.account_name = account_name
        self.ucc = ucc
        self.expires_at = expires_at
        self.force_mock_override = False
        self.token_expired = False

    async def validate_and_save_token(
        self,
        session: AsyncSession,
        client_id: str,
        access_token: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> DhanStatusResponse:
        headers = {
            "access-token": access_token.strip(),
            "client-id": client_id.strip(),
            "Accept": "application/json",
        }
        try:
            if http_client is not None:
                resp = await http_client.get(DHAN_PROFILE_URL, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(DHAN_PROFILE_URL, headers=headers)
        except httpx.HTTPError as exc:
            raise DhanAuthError(f"Network error contacting Dhan /v2/profile: {exc}") from exc

        if resp.status_code in (401, 403):
            raise DhanAuthError("Invalid or expired Dhan access token (401/403 from /v2/profile).")
        if resp.status_code >= 400:
            raise DhanAuthError(f"Dhan /v2/profile rejected token (HTTP {resp.status_code}).")

        data = resp.json()
        verified_cid = str(data.get("dhanClientId") or client_id).strip()
        account_name = data.get("dhanClientName") or data.get("clientName") or verified_cid
        ucc = data.get("dhanClientUcc") or data.get("ucc") or verified_cid
        expires_at = _parse_dhan_expiry(data.get("tokenValidity"))

        await self._upsert_credential(
            session=session,
            client_id=verified_cid,
            access_token=access_token.strip(),
            account_name=str(account_name) if account_name else None,
            ucc=str(ucc) if ucc else None,
            expires_at=expires_at,
        )
        self.last_message = "Connected to DhanHQ live market feed."
        await self._notify_listeners()
        return self.get_status()

    async def renew_active_token(
        self,
        session: AsyncSession,
        http_client: httpx.AsyncClient | None = None,
    ) -> DhanStatusResponse:
        if not self.client_id or not self.access_token:
            raise DhanAuthError("No active Dhan token to renew. Paste a daily token first.")

        headers = {
            "access-token": self.access_token,
            "dhanClientId": self.client_id,
            "Accept": "application/json",
        }
        try:
            if http_client is not None:
                resp = await http_client.get(DHAN_RENEW_URL, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(DHAN_RENEW_URL, headers=headers)
        except httpx.HTTPError as exc:
            raise DhanAuthError(f"Network error renewing Dhan token: {exc}") from exc

        if resp.status_code in (401, 403):
            self.token_expired = True
            raise DhanAuthError("Active token already expired; cannot renew. Paste a fresh token.")
        if resp.status_code >= 400:
            raise DhanAuthError(f"Dhan /v2/RenewToken failed (HTTP {resp.status_code}).")

        data = resp.json()
        new_token = str(data.get("token") or data.get("accessToken") or "").strip()
        if not new_token:
            raise DhanAuthError("Dhan /v2/RenewToken did not return a renewed token.")

        new_exp = _parse_dhan_expiry(data.get("expiryTime"))
        await self._upsert_credential(
            session=session,
            client_id=self.client_id,
            access_token=new_token,
            account_name=self.account_name,
            ucc=self.ucc,
            expires_at=new_exp,
        )
        self.last_message = "Renewed Dhan access token (+24h)."
        await self._notify_listeners()
        return self.get_status()

    async def generate_totp_token(
        self,
        session: AsyncSession,
        client_id: str,
        pin: str,
        totp: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> DhanStatusResponse:
        params = {
            "dhanClientId": client_id.strip(),
            "pin": pin.strip(),
            "totp": totp.strip(),
        }
        try:
            if http_client is not None:
                resp = await http_client.post(DHAN_GENERATE_TOTP_URL, params=params)
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(DHAN_GENERATE_TOTP_URL, params=params)
        except httpx.HTTPError as exc:
            raise DhanAuthError(f"Network error generating TOTP token: {exc}") from exc

        if resp.status_code >= 400:
            raise DhanAuthError(f"Dhan TOTP token generation failed (HTTP {resp.status_code}).")

        data = resp.json()
        new_token = str(data.get("accessToken") or data.get("token") or "").strip()
        if not new_token:
            raise DhanAuthError("Dhan TOTP endpoint returned empty access token.")

        return await self.validate_and_save_token(
            session=session,
            client_id=client_id.strip(),
            access_token=new_token,
            http_client=http_client,
        )

    async def disconnect_to_mock(self) -> DhanStatusResponse:
        self.force_mock_override = True
        self.last_message = "Switched to Mock market feed."
        await self._notify_listeners()
        return self.get_status()

    def mark_token_expired(self, reason: str = "Dhan token expired") -> None:
        self.token_expired = True
        self.last_message = reason

    def has_live_credentials(self) -> bool:
        settings = get_settings()
        if settings.market_data_source == "mock" or self.force_mock_override:
            return False
        if not self.client_id or not self.access_token:
            return False
        if self.token_expired:
            return False
        if self.expires_at is not None and _as_utc(self.expires_at) <= datetime.now(UTC):
            self.token_expired = True
            return False
        return True

    def get_status(self) -> DhanStatusResponse:
        settings = get_settings()
        now_utc = datetime.now(UTC)
        exp_utc = _as_utc(self.expires_at)

        if exp_utc is not None and exp_utc <= now_utc and not self.force_mock_override:
            self.token_expired = True

        mode: FeedStatus
        connected = False
        if settings.market_data_source == "mock" or self.force_mock_override:
            mode = "MOCK_FALLBACK"
        elif self.token_expired:
            mode = "TOKEN_EXPIRED"
        elif self.client_id and self.access_token:
            mode = "LIVE_DHAN"
            connected = True
        else:
            mode = "MOCK_FALLBACK"

        secs_rem: int | None = None
        if exp_utc is not None:
            secs_rem = max(0, int((exp_utc - now_utc).total_seconds()))

        return DhanStatusResponse(
            connected=connected,
            mode=mode,
            client_id_masked=_mask_client_id(self.client_id),
            account_name=self.account_name,
            ucc=self.ucc,
            expires_at=exp_utc,
            seconds_remaining=secs_rem,
            message=self.last_message,
        )
