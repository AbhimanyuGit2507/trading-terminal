"""DhanMarginProvider: live Dhan /v2/margincalculator adapter with 5s cache & stress fallback."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime

import httpx

from app.core.contracts import build_future_contract_id, build_option_contract_id
from app.providers.margin_provider import StressMarginProvider
from app.quant.margin import MarginBreakdown
from app.quant.payoff import PayoffLeg
from app.services.dhan_auth import DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster

DHAN_MARGIN_URL = "https://api.dhan.co/v2/margincalculator"


class DhanMarginProvider:
    """MarginProvider querying DhanHQ /v2/margincalculator with 5s TTL cache & stress fallback."""

    def __init__(
        self,
        token_manager: DhanTokenManager,
        scrip_master: DhanScripMaster,
        fallback: StressMarginProvider,
        cache_ttl_seconds: float = 5.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token_manager = token_manager
        self.scrip_master = scrip_master
        self.fallback = fallback
        self.cache_ttl_seconds = cache_ttl_seconds
        self._external_client = http_client
        self._cache: dict[str, tuple[float, MarginBreakdown]] = {}

    def _cache_key(self, legs: list[PayoffLeg], spot: float) -> str:
        payload = {
            "spot": round(spot, 1),
            "legs": [
                (
                    l.symbol,
                    l.expiry.isoformat(),
                    l.option_type,
                    l.side,
                    l.lots * l.lot_size,
                    l.strike,
                    round(l.entry_price, 2),
                )
                for l in legs
                if l.enabled and l.status == "OPEN"
            ],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    async def estimate_margin(
        self,
        legs: list[PayoffLeg],
        spot: float,
        as_of: datetime,
    ) -> MarginBreakdown:
        active = [l for l in legs if l.enabled and l.status == "OPEN"]
        if not active:
            return MarginBreakdown(0.0, 0.0, 0.0, 0.0, margin_source="dhan_span_api")

        if not self.token_manager.has_live_credentials():
            return await self.fallback.estimate_margin(active, spot, as_of)

        key = self._cache_key(active, spot)
        now_ts = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and (now_ts - cached[0]) < self.cache_ttl_seconds:
            return cached[1]

        client_id = self.token_manager.client_id or ""
        access_token = self.token_manager.access_token or ""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "access-token": access_token,
        }

        try:
            await self.scrip_master.ensure_loaded()
            total_span = 0.0
            total_exposure = 0.0
            total_margin = 0.0

            async def _query_legs(client: httpx.AsyncClient) -> None:
                nonlocal total_span, total_exposure, total_margin
                for leg in active:
                    cid = (
                        build_future_contract_id(leg.exchange, leg.symbol, leg.expiry)
                        if leg.option_type == "FUT"
                        else build_option_contract_id(
                            leg.exchange,
                            leg.symbol,
                            leg.expiry,
                            float(leg.strike or spot),
                            leg.option_type,
                        )
                    )
                    mapped = self.scrip_master.to_dhan(cid)
                    if mapped is None:
                        raise ValueError(f"Unmapped contract for Dhan margin: {cid}")
                    exch_seg, sec_id = mapped
                    body = {
                        "dhanClientId": client_id,
                        "exchangeSegment": exch_seg,
                        "transactionType": leg.side,
                        "quantity": leg.lots * leg.lot_size,
                        "productType": "MARGIN",
                        "securityId": sec_id,
                        "price": max(0.05, float(leg.entry_price)),
                    }
                    resp = await client.post(DHAN_MARGIN_URL, json=body, headers=headers)
                    if resp.status_code in (401, 403):
                        self.token_manager.mark_token_expired("Dhan margin auth rejected (401/403).")
                        raise PermissionError("Token expired")
                    resp.raise_for_status()
                    data = resp.json()
                    total_span += float(data.get("spanMargin") or 0.0)
                    total_exposure += float(data.get("exposureMargin") or 0.0)
                    total_margin += float(data.get("totalMargin") or 0.0)

            if self._external_client is not None:
                await _query_legs(self._external_client)
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await _query_legs(client)

            # Apply portfolio hedge awareness against standalone sum using stress model ceiling if multi-leg
            stress = await self.fallback.estimate_margin(active, spot, as_of)
            if len(active) > 1 and stress.hedge_benefit > 0:
                effective_total = min(total_margin, stress.total_margin)
                hedge_benefit = round(max(0.0, total_margin - effective_total), 2)
            else:
                effective_total = total_margin
                hedge_benefit = 0.0

            breakdown = MarginBreakdown(
                span_proxy=round(total_span, 2),
                exposure_proxy=round(total_exposure, 2),
                total_margin=round(effective_total, 2),
                hedge_benefit=hedge_benefit,
                margin_source="dhan_span_api",
            )
            self._cache[key] = (now_ts, breakdown)
            return breakdown
        except (httpx.HTTPError, ValueError, PermissionError, OSError):
            return await self.fallback.estimate_margin(active, spot, as_of)
