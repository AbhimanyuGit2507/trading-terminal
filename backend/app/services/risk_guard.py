"""Backend Pre-Trade Risk Engine, Real-Time 1s MTM Circuit Breaker & Emergency Kill Switch."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any, Literal

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar import IST
from app.core.config import get_settings
from app.core.contracts import parse_contract_id
from app.db.models import LiveOrderModel, RiskConfigModel
from app.providers.base import MarginProvider, MarketDataProvider
from app.providers.dhan_broker import base_url_for_env
from app.providers.virtual_broker import KillSwitchEngagedError
from app.quant.payoff import PayoffLeg
from app.schemas.domain import (
    BatchOrderRequest,
    ExecutionMode,
    FundLimitResponse,
    KillSwitchTriggerResponse,
    ProductType,
    RiskConfigUpdateRequest,
    RiskStateResponse,
)
from app.services.dhan_auth import DhanTokenManager

logger = logging.getLogger(__name__)


class RiskLimitError(RuntimeError):
    """Raised when pre-trade risk limits or margin checks reject an order."""


def is_market_hours_ist(now_ist: datetime | None = None) -> bool:
    dt = (now_ist or datetime.now(IST)).astimezone(IST)
    if dt.weekday() >= 5:
        return False
    t = dt.time()
    return time(9, 15) <= t <= time(15, 30)


class RiskGuardService:
    """Enforces pre-trade capital caps, live margin checks, 1s MTM breaker & Kill Switch."""

    def __init__(
        self,
        token_manager: DhanTokenManager,
        market_provider: MarketDataProvider,
        margin_provider: MarginProvider,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        settings = get_settings()
        self._tokens = token_manager
        self._market = market_provider
        self._margin = margin_provider
        self._http_client = http_client

        # Never auto-boot into DHAN_LIVE
        self.active_execution_mode: ExecutionMode = "PAPER_LIVE"
        self.daily_kill_switch_active: bool = settings.kill_switch_engaged
        self.kill_switch_reason: str | None = None
        self.kill_switch_engaged_at: datetime | None = None
        self.daily_max_loss_inr: float = settings.daily_max_loss_inr
        self.max_lots_per_order: int = settings.max_lots_per_order
        self.max_open_lots: int = settings.max_open_lots
        self.max_daily_trades: int = settings.max_daily_trades
        self.product_type: ProductType = "MARGIN"
        self.limit_buffer_ticks: int = 2
        self.last_net_mtm_inr: float = 0.0

    async def load_or_init(self, session: AsyncSession) -> RiskConfigModel:
        row = await session.get(RiskConfigModel, "global")
        if row is None:
            row = RiskConfigModel(
                id="global",
                active_execution_mode="PAPER_LIVE",
                daily_kill_switch_active=self.daily_kill_switch_active,
                daily_max_loss_inr=Decimal(f"{self.daily_max_loss_inr:.2f}"),
                max_lots_per_order=self.max_lots_per_order,
                max_open_lots=self.max_open_lots,
                max_daily_trades=self.max_daily_trades,
                product_type=self.product_type,
                limit_buffer_ticks=self.limit_buffer_ticks,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        else:
            # Never auto-boot into DHAN_LIVE on restart
            if row.active_execution_mode == "DHAN_LIVE":
                row.active_execution_mode = "PAPER_LIVE"
                await session.commit()
            self.active_execution_mode = row.active_execution_mode  # type: ignore[assignment]
            self.daily_kill_switch_active = bool(row.daily_kill_switch_active)
            self.kill_switch_reason = row.kill_switch_reason
            self.kill_switch_engaged_at = row.kill_switch_engaged_at
            self.daily_max_loss_inr = float(row.daily_max_loss_inr)
            self.max_lots_per_order = int(row.max_lots_per_order)
            self.max_open_lots = int(row.max_open_lots)
            self.max_daily_trades = int(row.max_daily_trades)
            self.product_type = row.product_type  # type: ignore[assignment]
            self.limit_buffer_ticks = int(row.limit_buffer_ticks)
        return row

    async def _sync_row(self, session: AsyncSession) -> RiskConfigModel:
        row = await session.get(RiskConfigModel, "global")
        if row is None:
            row = await self.load_or_init(session)
        row.active_execution_mode = self.active_execution_mode
        row.daily_kill_switch_active = self.daily_kill_switch_active
        row.kill_switch_reason = self.kill_switch_reason
        row.kill_switch_engaged_at = self.kill_switch_engaged_at
        row.daily_max_loss_inr = Decimal(f"{self.daily_max_loss_inr:.2f}")
        row.max_lots_per_order = self.max_lots_per_order
        row.max_open_lots = self.max_open_lots
        row.max_daily_trades = self.max_daily_trades
        row.product_type = self.product_type
        row.limit_buffer_ticks = self.limit_buffer_ticks
        await session.commit()
        return row

    async def count_trades_today(self, session: AsyncSession) -> int:
        today_start_ist = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(func.count(LiveOrderModel.id)).where(
            LiveOrderModel.slice_index <= 1,
            LiveOrderModel.executed_at >= today_start_ist,
        )
        return int((await session.execute(stmt)).scalar_one() or 0)

    async def get_state(self, session: AsyncSession) -> RiskStateResponse:
        trades_today = await self.count_trades_today(session)
        return RiskStateResponse(
            active_execution_mode=self.active_execution_mode,
            daily_kill_switch_active=self.daily_kill_switch_active,
            kill_switch_reason=self.kill_switch_reason,
            kill_switch_engaged_at=self.kill_switch_engaged_at,
            daily_max_loss_inr=self.daily_max_loss_inr,
            max_lots_per_order=self.max_lots_per_order,
            max_open_lots=self.max_open_lots,
            max_daily_trades=self.max_daily_trades,
            product_type=self.product_type,
            limit_buffer_ticks=self.limit_buffer_ticks,
            trades_today=trades_today,
            net_mtm_inr=round(self.last_net_mtm_inr, 2),
        )

    async def update_config(
        self, session: AsyncSession, patch: RiskConfigUpdateRequest
    ) -> RiskStateResponse:
        if patch.daily_max_loss_inr is not None:
            self.daily_max_loss_inr = float(patch.daily_max_loss_inr)
        if patch.max_lots_per_order is not None:
            self.max_lots_per_order = int(patch.max_lots_per_order)
        if patch.max_open_lots is not None:
            self.max_open_lots = int(patch.max_open_lots)
        if patch.max_daily_trades is not None:
            self.max_daily_trades = int(patch.max_daily_trades)
        if patch.product_type is not None:
            self.product_type = patch.product_type
        if patch.limit_buffer_ticks is not None:
            self.limit_buffer_ticks = int(patch.limit_buffer_ticks)
        await self._sync_row(session)
        return await self.get_state(session)

    async def switch_execution_mode(
        self,
        session: AsyncSession,
        target_mode: ExecutionMode,
        confirmed: bool,
    ) -> RiskStateResponse:
        if target_mode == "DHAN_LIVE" and not confirmed:
            raise RiskLimitError(
                "Switching to DHAN_LIVE real-money mode requires explicit user confirmation."
            )
        if target_mode in ("DHAN_SANDBOX", "DHAN_LIVE") and (
            not self._tokens.client_id or not self._tokens.access_token or self._tokens.token_expired
        ):
            raise RiskLimitError(
                f"Cannot switch to {target_mode}: connect a valid DhanHQ daily token first."
            )
        self.active_execution_mode = target_mode
        await self._sync_row(session)
        return await self.get_state(session)

    async def validate_pre_trade(
        self,
        session: AsyncSession,
        req: BatchOrderRequest,
        env: Literal["SANDBOX", "LIVE"],
        fund_fetcher: Callable[[Literal["SANDBOX", "LIVE"]], Awaitable[FundLimitResponse]],
    ) -> None:
        settings = get_settings()
        if settings.kill_switch_engaged or self.daily_kill_switch_active:
            raise KillSwitchEngagedError(
                f"Execution blocked: DAILY_KILL_SWITCH_ACTIVE=True ({self.kill_switch_reason or 'Kill switch active'})."
            )

        total_order_lots = sum(leg.lots for leg in req.legs)
        for leg in req.legs:
            if leg.lots > self.max_lots_per_order:
                raise RiskLimitError(
                    f"Order lot cap exceeded: leg {leg.contract_id} asks {leg.lots} lots > max_lots_per_order={self.max_lots_per_order}."
                )
        if total_order_lots > self.max_open_lots:
            raise RiskLimitError(
                f"Open lots cap exceeded: {total_order_lots} lots > max_open_lots={self.max_open_lots}."
            )

        trades_today = await self.count_trades_today(session)
        if trades_today >= self.max_daily_trades:
            raise RiskLimitError(
                f"Daily trade limit reached: {trades_today} >= max_daily_trades={self.max_daily_trades}."
            )

        # Verify available Dhan balance for new risk-adding orders (OPEN_LEGS / ADD_LOTS)
        if req.action in ("OPEN_LEGS", "ADD_LOTS"):
            eval_dt = datetime.now(IST)
            payoff_legs: list[PayoffLeg] = []
            quotes = await self._market.get_contract_quotes(
                [leg.contract_id for leg in req.legs], as_of=eval_dt
            )
            first_sym = parse_contract_id(req.legs[0].contract_id).symbol
            chain, _ = await self._market.get_option_chain(first_sym, as_of=eval_dt)
            for leg in req.legs:
                pcid = parse_contract_id(leg.contract_id)
                q = quotes.get(leg.contract_id)
                ltp = float(leg.limit_price) if leg.limit_price is not None else (q.ltp if q else 100.0)
                iv = (q.iv / 100.0) if q else 0.14
                payoff_legs.append(
                    PayoffLeg(
                        contract_id=leg.contract_id,
                        symbol=pcid.symbol,
                        expiry=pcid.expiry or eval_dt.date(),
                        strike=pcid.strike,
                        option_type=pcid.option_type,
                        side=leg.side,
                        lots=leg.lots,
                        lot_size=leg.lot_size or chain.lot_size,
                        entry_price=ltp,
                        entry_iv=iv,
                        forward_at_base=chain.forward_price,
                    )
                )

            est_margin = await self._margin.estimate_margin(
                legs=payoff_legs, spot=chain.spot, as_of=eval_dt
            )
            funds = await fund_fetcher(env)
            if funds.available_balance < est_margin.total_margin:
                raise RiskLimitError(
                    f"Insufficient Dhan funds: available ₹{funds.available_balance:,.2f} "
                    f"< required margin ₹{est_margin.total_margin:,.2f}."
                )

    async def _http_req(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.request(method, url, headers=headers, json=json_body)
        async with httpx.AsyncClient(timeout=15.0) as client:
            return await client.request(method, url, headers=headers, json=json_body)

    async def trigger_kill_switch(
        self,
        session: AsyncSession,
        reason: str = "Manual Emergency Exit triggered by user",
        env: Literal["SANDBOX", "LIVE"] | None = None,
    ) -> KillSwitchTriggerResponse:
        now_utc = datetime.now(UTC)
        self.daily_kill_switch_active = True
        self.kill_switch_reason = reason
        self.kill_switch_engaged_at = now_utc
        await self._sync_row(session)

        resolved_env: Literal["SANDBOX", "LIVE"] = (
            env
            if env is not None
            else ("LIVE" if self.active_execution_mode == "DHAN_LIVE" else "SANDBOX")
        )
        base = base_url_for_env(resolved_env)

        cancelled_orders = 0
        exited_positions = 0
        fallback_exits = 0
        errors: list[str] = []

        cid = self._tokens.client_id
        tok = self._tokens.access_token
        if not cid or not tok:
            return KillSwitchTriggerResponse(
                kill_switch_active=True,
                cancelled_orders=0,
                exited_positions=0,
                fallback_exits=0,
                errors=["No active Dhan credentials loaded; kill switch engaged locally."],
                triggered_at=now_utc,
                reason=reason,
            )

        headers = {
            "access-token": tok,
            "client-id": cid,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # 1. Cancel all PENDING / TRANSIT standard & super orders
        for list_url, del_prefix in (
            (f"{base}/orders", f"{base}/orders"),
            (f"{base}/super/orders", f"{base}/super/orders"),
        ):
            try:
                r_list = await self._http_req("GET", list_url, headers)
                if r_list.status_code < 400:
                    data = r_list.json()
                    items = data if isinstance(data, list) else data.get("data", [])
                    for item in items if isinstance(items, list) else []:
                        status = str(item.get("orderStatus") or "").upper()
                        oid = item.get("orderId")
                        if oid and status in ("PENDING", "TRANSIT", "PART_TRADED"):
                            r_del = await self._http_req("DELETE", f"{del_prefix}/{oid}", headers)
                            if r_del.status_code < 400:
                                cancelled_orders += 1
                            else:
                                errors.append(f"Cancel {oid} failed: HTTP {r_del.status_code}")
            except httpx.HTTPError as exc:
                errors.append(f"Order cancellation error ({list_url}): {exc}")

        # 2. Primary Exit All Positions via Dhan DELETE /v2/positions
        try:
            r_exit_all = await self._http_req("DELETE", f"{base}/positions", headers)
            if r_exit_all.status_code < 400:
                exited_positions += 1
            else:
                errors.append(f"DELETE /positions HTTP {r_exit_all.status_code}: {r_exit_all.text}")
        except httpx.HTTPError as exc:
            errors.append(f"DELETE /positions error: {exc}")

        # 3. Fallback: verify GET /v2/positions and submit MARKET counter-orders for any open netQty
        try:
            r_pos = await self._http_req("GET", f"{base}/positions", headers)
            if r_pos.status_code < 400:
                pdata = r_pos.json()
                pitems = pdata if isinstance(pdata, list) else pdata.get("data", [])
                for pos in pitems if isinstance(pitems, list) else []:
                    net_qty = int(pos.get("netQty") or 0)
                    if net_qty == 0:
                        continue
                    close_side = "SELL" if net_qty > 0 else "BUY"
                    fallback_payload = {
                        "dhanClientId": cid,
                        "transactionType": close_side,
                        "exchangeSegment": str(pos.get("exchangeSegment") or "NSE_FNO"),
                        "productType": str(pos.get("productType") or "MARGIN"),
                        "orderType": "MARKET",
                        "validity": "DAY",
                        "securityId": str(pos.get("securityId") or ""),
                        "quantity": abs(net_qty),
                        "price": 0.0,
                        "triggerPrice": 0.0,
                    }
                    r_fb = await self._http_req(
                        "POST", f"{base}/orders", headers, json_body=fallback_payload
                    )
                    if r_fb.status_code < 400:
                        fallback_exits += 1
                    else:
                        errors.append(
                            f"Fallback MARKET exit failed for {pos.get('securityId')}: HTTP {r_fb.status_code}"
                        )
        except httpx.HTTPError as exc:
            errors.append(f"Fallback positions check error: {exc}")

        return KillSwitchTriggerResponse(
            kill_switch_active=True,
            cancelled_orders=cancelled_orders,
            exited_positions=exited_positions,
            fallback_exits=fallback_exits,
            errors=errors,
            triggered_at=now_utc,
            reason=reason,
        )

    async def unlock_kill_switch(
        self, session: AsyncSession, confirmation_text: str
    ) -> RiskStateResponse:
        if confirmation_text.strip().upper() not in ("UNLOCK", "CONFIRM UNLOCK"):
            raise RiskLimitError(
                'Confirmation mismatch: type "UNLOCK" to disengage the Daily Kill Switch.'
            )
        self.daily_kill_switch_active = False
        self.kill_switch_reason = None
        self.kill_switch_engaged_at = None
        await self._sync_row(session)
        return await self.get_state(session)

    async def evaluate_mtm_and_enforce(
        self,
        session: AsyncSession,
        net_mtm_inr: float,
        env: Literal["SANDBOX", "LIVE"] | None = None,
    ) -> KillSwitchTriggerResponse | None:
        self.last_net_mtm_inr = net_mtm_inr
        if self.daily_kill_switch_active or self.daily_max_loss_inr <= 0:
            return None
        if net_mtm_inr <= -self.daily_max_loss_inr:
            reason = (
                f"Daily max loss breached: ₹{net_mtm_inr:,.2f} <= -₹{self.daily_max_loss_inr:,.2f}"
            )
            logger.critical("RISK BREAKER TRIGGERED: %s", reason)
            return await self.trigger_kill_switch(session=session, reason=reason, env=env)
        return None

