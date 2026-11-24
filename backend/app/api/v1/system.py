"""System utilities for SEBI Static-IP deployment checks (/api/v1/system/*)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.domain import EgressIpResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/egress-ip", response_model=EgressIpResponse)
async def get_egress_ip() -> EgressIpResponse:
    settings = get_settings()
    now_utc = datetime.now(UTC)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(settings.egress_ip_check_url)
            resp.raise_for_status()
            data = resp.json()
            ip = str(data.get("ip") or "").strip() or None
            return EgressIpResponse(
                public_ip=ip,
                provider="api.ipify.org",
                checked_at=now_utc,
                error=None if ip else "Empty IP returned",
            )
    except (httpx.HTTPError, ValueError) as exc:
        return EgressIpResponse(
            public_ip=None,
            provider="api.ipify.org",
            checked_at=now_utc,
            error=str(exc),
        )

