"""DhanHQ v2.5 Live & Sandbox ExecutionProvider with Margin-Safe Basket Ordering & Super Orders."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar import IST, get_instrument_spec, round_to_tick, to_ist
from app.core.contracts import parse_contract_id
from app.db.models import LiveOrderModel
from app.providers.base import MarketDataProvider
from app.providers.virtual_broker import KillSwitchEngagedError
from app.schemas.domain import (
    BatchOrderRequest,
    BrokerOrderRecordSchema,
    BrokerPositionRecordSchema,
    BrokerReconcileResponse,
    ExecutionResultSchema,
    FundLimitResponse,
    OrderFillSchema,
    OrderLegInstruction,
)
from app.services.dhan_auth import DhanAuthError, DhanTokenManager
from app.services.dhan_scrip_master import DhanScripMaster

if TYPE_CHECKING:
    from app.services.risk_guard import RiskGuardService

DHAN_LIVE_BASE = "https://api.dhan.co/v2"
DHAN_SANDBOX_BASE = "https://sandbox.dhan.co/v2"


class HedgeExecutionAbortedError(RuntimeError):
    """Raised when BUY hedge legs fail/reject, aborting subsequent SELL legs."""


class DhanBrokerError(RuntimeError):
    """Raised when Dhan Trading API rejects an order or request."""


def resolve_dhan_env(trading_mode: str) -> Literal["SANDBOX", "LIVE"]:
    if trading_mode in ("DHAN_LIVE", "LIVE"):
        return "LIVE"
    return "SANDBOX"


def base_url_for_env(env: Literal["SANDBOX", "LIVE"]) -> str:
    return DHAN_LIVE_BASE if env == "LIVE" else DHAN_SANDBOX_BASE


def _normalize_fill_status(
    raw_status: str | None,
) -> Literal["PENDING", "TRANSIT", "TRADED", "FILLED", "REJECTED", "CANCELLED"]:
    up = (raw_status or "PENDING").strip().upper()
    if up in ("TRADED", "COMPLETE", "COMPLETED", "FILLED"):
        return "TRADED"
    if up in ("REJECTED", "FAILED"):
        return "REJECTED"
    if up in ("CANCELLED", "CANCELED"):
        return "CANCELLED"
    if up == "TRANSIT":
        return "TRANSIT"
    return "PENDING"


class DhanExecutionProvider:
    """ExecutionProvider calling DhanHQ v2.5 Sandbox/Live Trading APIs with RiskGuard + slicing."""

    def __init__(
        self,
        token_manager: DhanTokenManager,
        scrip_master: DhanScripMaster,
        market_provider: MarketDataProvider,
        risk_guard: RiskGuardService | None = None,
        http_client: httpx.AsyncClient | None = None,
        poll_timeout_s: float = 3.0,
        poll_interval_s: float = 0.2,
    ) -> None:
        self._tokens = token_manager
        self._scrip = scrip_master
        self._market = market_provider
        self._risk_guard = risk_guard
        self._http_client = http_client
        self._poll_timeout_s = poll_timeout_s
        self._poll_interval_s = poll_interval_s

    def _auth_headers(self) -> tuple[str, dict[str, str]]:
        cid = self._tokens.client_id
        tok = self._tokens.access_token
        if not cid or not tok or self._tokens.token_expired:
            raise DhanAuthError(
                "Valid DhanHQ Client ID & Access Token required for Sandbox/Live execution."
            )
        return cid, {
            "access-token": tok,
            "client-id": cid,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
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

    async def fetch_fund_limits(self, env: Literal["SANDBOX", "LIVE"]) -> FundLimitResponse:
        _, headers = self._auth_headers()
        base = base_url_for_env(env)
        resp = await self._request("GET", f"{base}/fundlimit", headers)
        if resp.status_code >= 400:
            raise DhanBrokerError(f"Dhan /v2/fundlimit HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        # Dhan API historically uses spelling 'availabelBalance' as well as 'availableBalance'
        avail = float(data.get("availabelBalance") or data.get("availableBalance") or 0.0)
        utilized = float(data.get("utilizedAmount") or 0.0)
        collateral = float(data.get("collateralAmount") or 0.0)
        return FundLimitResponse(
            available_balance=avail,
            utilized_amount=utilized,
            collateral_amount=collateral,
            environment=env,
            source="dhan_api",
        )

    async def fetch_orders(self, env: Literal["SANDBOX", "LIVE"]) -> list[BrokerOrderRecordSchema]:
        _, headers = self._auth_headers()
        base = base_url_for_env(env)
        orders: list[BrokerOrderRecordSchema] = []

        for endpoint, is_super in ((f"{base}/orders", False), (f"{base}/super/orders", True)):
            try:
                resp = await self._request("GET", endpoint, headers)
            except httpx.HTTPError:
                continue
            if resp.status_code >= 400:
                continue
            payload = resp.json()
            items = payload if isinstance(payload, list) else payload.get("data", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or not item.get("orderId"):
                    continue
                orders.append(
                    BrokerOrderRecordSchema(
                        order_id=str(item.get("orderId")),
                        correlation_id=item.get("correlationId"),
                        order_status=str(item.get("orderStatus") or "PENDING"),
                        transaction_type=str(item.get("transactionType") or "BUY"),
                        exchange_segment=str(item.get("exchangeSegment") or "NSE_FNO"),
                        security_id=str(item.get("securityId") or ""),
                        trading_symbol=item.get("tradingSymbol"),
                        product_type=item.get("productType"),
                        order_type=item.get("orderType"),
                        quantity=int(item.get("quantity") or 0),
                        filled_qty=int(item.get("filledQty") or 0),
                        price=float(item.get("price") or 0.0),
                        average_traded_price=float(
                            item.get("averageTradedPrice") or item.get("tradedPrice") or 0.0
                        ),
                        is_super_order=is_super or bool(item.get("targetPrice")),
                        oms_error_description=item.get("omsErrorDescription"),
                        create_time=item.get("createTime"),
                    )
                )
        return orders

    async def fetch_positions(
        self, env: Literal["SANDBOX", "LIVE"]
    ) -> list[BrokerPositionRecordSchema]:
        _, headers = self._auth_headers()
        base = base_url_for_env(env)
        resp = await self._request("GET", f"{base}/positions", headers)
        if resp.status_code >= 400:
            raise DhanBrokerError(f"Dhan /v2/positions HTTP {resp.status_code}: {resp.text}")
        payload = resp.json()
        items = payload if isinstance(payload, list) else payload.get("data", [])
        positions: list[BrokerPositionRecordSchema] = []
        if not isinstance(items, list):
            return positions
        for item in items:
            if not isinstance(item, dict):
                continue
            positions.append(
                BrokerPositionRecordSchema(
                    trading_symbol=str(item.get("tradingSymbol") or item.get("securityId") or ""),
                    exchange_segment=str(item.get("exchangeSegment") or "NSE_FNO"),
                    security_id=str(item.get("securityId") or ""),
                    product_type=str(item.get("productType") or "MARGIN"),
                    net_qty=int(item.get("netQty") or 0),
                    buy_avg=float(item.get("buyAvg") or 0.0),
                    sell_avg=float(item.get("sellAvg") or 0.0),
                    realized_profit=float(item.get("realizedProfit") or 0.0),
                    unrealized_profit=float(item.get("unrealizedProfit") or 0.0),
                    multiplier=int(item.get("multiplier") or 1),
                )
            )
        return positions

    async def reconcile_orders(
        self, session: AsyncSession, env: Literal["SANDBOX", "LIVE"]
    ) -> BrokerReconcileResponse:
        orders = await self.fetch_orders(env)
        positions = await self.fetch_positions(env)
        by_broker_id = {o.order_id: o for o in orders}

        updated_count = 0
        if by_broker_id:
            stmt = select(LiveOrderModel).where(
                LiveOrderModel.broker_order_id.in_(list(by_broker_id.keys()))
            )
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                b = by_broker_id.get(row.broker_order_id or "")
                if b is None:
                    continue
                norm = _normalize_fill_status(b.order_status)
                changed = False
                if row.status != norm:
                    row.status = norm
                    changed = True
                if b.average_traded_price > 0:
                    avg_px = Decimal(f"{b.average_traded_price:.2f}")
                    if row.fill_price != avg_px:
                        row.fill_price = avg_px
                        changed = True
                if b.oms_error_description and row.oms_error != b.oms_error_description:
                    row.oms_error = b.oms_error_description
                    changed = True
                if changed:
                    updated_count += 1
            if updated_count > 0:
                await session.commit()

        return BrokerReconcileResponse(
            environment=env,
            updated_orders=updated_count,
            orders=orders,
            positions=positions,
        )

    async def _poll_until_traded(
        self,
        base: str,
        headers: dict[str, str],
        broker_order_id: str,
        initial_status: str,
    ) -> tuple[str, float, str | None]:
        """Poll Dhan GET /orders/{orderId} up to poll_timeout_s for hedge fill confirmation."""
        norm = _normalize_fill_status(initial_status)
        if norm in ("TRADED", "REJECTED", "CANCELLED"):
            return norm, 0.0, None

        deadline = asyncio.get_running_loop().time() + self._poll_timeout_s
        last_status = norm
        last_avg = 0.0
        last_err: str | None = None

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(self._poll_interval_s)
            try:
                resp = await self._request("GET", f"{base}/orders/{broker_order_id}", headers)
            except httpx.HTTPError as exc:
                last_err = str(exc)
                continue
            if resp.status_code >= 400:
                continue
            data = resp.json()
            if isinstance(data, list) and data:
                data = data[0]
            if not isinstance(data, dict):
                continue
            last_status = _normalize_fill_status(data.get("orderStatus"))
            last_avg = float(data.get("averageTradedPrice") or data.get("tradedPrice") or 0.0)
            last_err = data.get("omsErrorDescription")
            if last_status in ("TRADED", "REJECTED", "CANCELLED"):
                return last_status, last_avg, last_err

        return last_status, last_avg, last_err or "Hedge order confirmation timed out before TRADED"

    async def _dispatch_single_slice(
        self,
        base: str,
        client_id: str,
        headers: dict[str, str],
        instr: OrderLegInstruction,
        exchange_segment: str,
        security_id: str,
        slice_qty: int,
        snapped_px: Decimal,
        order_type: str,
        product_type: str,
        correlation_id: str,
        await_traded: bool,
    ) -> tuple[str, str | None, Decimal, str | None, bool]:
        """Dispatch either POST /v2/orders or POST /v2/super/orders for a slice."""
        is_super = instr.target_price is not None or instr.stop_loss_price is not None
        payload: dict[str, Any] = {
            "dhanClientId": client_id,
            "correlationId": correlation_id,
            "transactionType": instr.side,
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "validity": "DAY",
            "securityId": security_id,
            "quantity": slice_qty,
            "disclosedQuantity": 0,
            "price": 0.0 if order_type == "MARKET" else float(snapped_px),
            "triggerPrice": 0.0,
            "afterMarketOrder": False,
        }
        if is_super:
            if instr.target_price is not None:
                payload["targetPrice"] = float(instr.target_price)
            if instr.stop_loss_price is not None:
                payload["stopLossPrice"] = float(instr.stop_loss_price)
            if instr.trailing_jump is not None:
                payload["trailingJump"] = float(instr.trailing_jump)
            endpoint = f"{base}/super/orders"
        else:
            endpoint = f"{base}/orders"

        resp = await self._request("POST", endpoint, headers, json_body=payload)
        if resp.status_code >= 400:
            detail = resp.text
            return "REJECTED", None, snapped_px, f"Dhan HTTP {resp.status_code}: {detail}", is_super

        data = resp.json()
        broker_order_id = str(data.get("orderId") or "") or None
        raw_status = str(data.get("orderStatus") or "PENDING")
        oms_err = data.get("omsErrorDescription")
        norm_status = _normalize_fill_status(raw_status)
        fill_px = snapped_px
        avg_traded = float(data.get("averageTradedPrice") or 0.0)
        if avg_traded > 0:
            fill_px = Decimal(f"{avg_traded:.2f}")

        if await_traded and broker_order_id and norm_status not in ("TRADED", "REJECTED", "CANCELLED"):
            polled_status, polled_avg, polled_err = await self._poll_until_traded(
                base, headers, broker_order_id, raw_status
            )
            norm_status = polled_status
            if polled_avg > 0:
                fill_px = Decimal(f"{polled_avg:.2f}")
            if polled_err:
                oms_err = polled_err

        return norm_status, broker_order_id, fill_px, oms_err, is_super

    async def execute_orders(
        self,
        session: AsyncSession,
        req: BatchOrderRequest,
        idempotency_key: UUID,
    ) -> ExecutionResultSchema:
        # 1. Pre-dispatch Postgres idempotency check (zero HTTP calls on replay)
        existing_stmt = select(LiveOrderModel).where(
            LiveOrderModel.idempotency_key == idempotency_key
        )
        existing_root = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing_root is not None:
            cached = existing_root.metadata_json.get("cached_result")
            if cached is not None:
                parsed = ExecutionResultSchema.model_validate(cached)
                return parsed.model_copy(update={"deduplicated": True})

        env = resolve_dhan_env(req.trading_mode)
        base = base_url_for_env(env)
        client_id, headers = self._auth_headers()

        # 2. Enforce RiskGuard BEFORE dispatching any order to Dhan
        if self._risk_guard is not None:
            await self._risk_guard.validate_pre_trade(
                session=session,
                req=req,
                env=env,
                fund_fetcher=self.fetch_fund_limits,
            )

        await self._scrip.ensure_loaded()
        eval_dt = to_ist(req.as_of) if req.as_of is not None else datetime.now(IST)
        contract_ids = [leg.contract_id for leg in req.legs]
        quotes = await self._market.get_contract_quotes(contract_ids, as_of=eval_dt)

        # 3. Margin-Safe Basket Ordering: BUY (hedge) legs strictly execute before SELL (short) legs
        buy_indexed = [(i, leg) for i, leg in enumerate(req.legs) if leg.side == "BUY"]
        sell_indexed = [(i, leg) for i, leg in enumerate(req.legs) if leg.side == "SELL"]
        ordered_pairs = buy_indexed + sell_indexed
        has_buy_hedges = len(buy_indexed) > 0

        fills: list[OrderFillSchema] = []
        root_row: LiveOrderModel | None = None
        first_root_assigned = False

        for instr_idx, instr in ordered_pairs:
            parsed_cid = parse_contract_id(instr.contract_id)
            spec = get_instrument_spec(parsed_cid.symbol, parsed_cid.expiry or eval_dt)
            lot_size = instr.lot_size or spec.lot_size
            total_qty = instr.lots * lot_size

            mapped = self._scrip.to_dhan(instr.contract_id)
            if mapped is None:
                raise DhanBrokerError(
                    f"Contract {instr.contract_id} not found in Dhan Scrip Master."
                )
            exchange_segment, security_id = mapped

            effective_order_type = instr.order_type or req.order_type or "LIMIT"
            effective_product = instr.product_type or req.product_type or "MARGIN"
            buffer_ticks = req.limit_buffer_ticks if req.limit_buffer_ticks is not None else 2

            if instr.limit_price is not None:
                raw_px = float(instr.limit_price)
            elif instr.contract_id in quotes:
                q = quotes[instr.contract_id]
                base_px = (
                    q.ask
                    if instr.side == "BUY" and q.ask > 0
                    else (q.bid if instr.side == "SELL" and q.bid > 0 else q.ltp)
                )
                buf = buffer_ticks * spec.tick_size
                raw_px = base_px + buf if instr.side == "BUY" else max(spec.tick_size, base_px - buf)
            else:
                raise DhanBrokerError(f"Unable to resolve live quote for {instr.contract_id}")

            snapped_px = Decimal(f"{round_to_tick(max(spec.tick_size, raw_px), spec.tick_size):.2f}")
            max_lots_per_slice = max(1, spec.freeze_qty // lot_size)
            needs_slicing = req.slice_if_frozen and total_qty > spec.freeze_qty
            chunks: list[int] = []
            if needs_slicing:
                rem = instr.lots
                while rem > 0:
                    take = min(rem, max_lots_per_slice)
                    chunks.append(take)
                    rem -= take
            else:
                chunks = [instr.lots]

            is_buy_hedge = instr.side == "BUY"
            is_super = instr.target_price is not None or instr.stop_loss_price is not None

            parent_id: uuid.UUID | None = None
            if len(chunks) > 1:
                parent_key = (
                    idempotency_key
                    if not first_root_assigned
                    else uuid.uuid5(idempotency_key, f"leg:{instr_idx}:parent")
                )
                first_root_assigned = True
                parent_row = LiveOrderModel(
                    strategy_id=req.strategy_id,
                    idempotency_key=parent_key,
                    parent_order_id=req.parent_order_id,
                    slice_index=0,
                    total_slices=len(chunks),
                    trading_mode=req.trading_mode,
                    environment=env,
                    contract_id=instr.contract_id,
                    exchange_segment=exchange_segment,
                    security_id=security_id,
                    side=instr.side,
                    action=req.action,
                    product_type=effective_product,
                    order_type=effective_order_type,
                    is_super_order=is_super,
                    lots=instr.lots,
                    quantity=total_qty,
                    limit_price=snapped_px,
                    fill_price=snapped_px,
                    target_price=instr.target_price,
                    stop_loss_price=instr.stop_loss_price,
                    trailing_jump=instr.trailing_jump,
                    status="PENDING",
                    metadata_json={
                        "is_parent": True,
                        "batch_idempotency_key": str(idempotency_key),
                        "leg_id": instr.leg_id,
                    },
                    executed_at=eval_dt,
                )
                session.add(parent_row)
                await session.flush()
                parent_id = parent_row.id
                if root_row is None:
                    root_row = parent_row

            slice_statuses: list[str] = []
            for s_idx, slice_lots in enumerate(chunks, start=1):
                slice_qty = slice_lots * lot_size
                corr_id = f"{str(idempotency_key)[:8]}-{instr_idx}-{s_idx}"
                if len(chunks) == 1 and not first_root_assigned:
                    row_key = idempotency_key
                    first_root_assigned = True
                else:
                    row_key = uuid.uuid5(idempotency_key, f"leg:{instr_idx}:slice:{s_idx}")

                status_str, broker_oid, fill_px, oms_err, super_used = (
                    await self._dispatch_single_slice(
                        base=base,
                        client_id=client_id,
                        headers=headers,
                        instr=instr,
                        exchange_segment=exchange_segment,
                        security_id=security_id,
                        slice_qty=slice_qty,
                        snapped_px=snapped_px,
                        order_type=effective_order_type,
                        product_type=effective_product,
                        correlation_id=corr_id,
                        await_traded=(is_buy_hedge and len(sell_indexed) > 0),
                    )
                )
                slice_statuses.append(status_str)

                child_row = LiveOrderModel(
                    strategy_id=req.strategy_id,
                    idempotency_key=row_key,
                    parent_order_id=parent_id or req.parent_order_id,
                    slice_index=s_idx if len(chunks) > 1 else 0,
                    total_slices=len(chunks),
                    trading_mode=req.trading_mode,
                    environment=env,
                    contract_id=instr.contract_id,
                    exchange_segment=exchange_segment,
                    security_id=security_id,
                    side=instr.side,
                    action=req.action,
                    product_type=effective_product,
                    order_type=effective_order_type,
                    is_super_order=super_used,
                    lots=slice_lots,
                    quantity=slice_qty,
                    limit_price=snapped_px,
                    fill_price=fill_px,
                    target_price=instr.target_price,
                    stop_loss_price=instr.stop_loss_price,
                    trailing_jump=instr.trailing_jump,
                    broker_order_id=broker_oid,
                    correlation_id=corr_id,
                    status=status_str,
                    oms_error=oms_err,
                    metadata_json={
                        "is_parent": False,
                        "batch_idempotency_key": str(idempotency_key),
                        "leg_id": instr.leg_id,
                    },
                    executed_at=eval_dt,
                )
                session.add(child_row)
                await session.flush()
                if root_row is None:
                    root_row = child_row

                fills.append(
                    OrderFillSchema(
                        order_id=child_row.id,
                        parent_order_id=child_row.parent_order_id,
                        slice_index=child_row.slice_index,
                        total_slices=len(chunks),
                        is_parent=False,
                        contract_id=instr.contract_id,
                        side=instr.side,
                        action=req.action,
                        lots=slice_lots,
                        quantity=slice_qty,
                        fill_price=fill_px,
                        status=_normalize_fill_status(status_str),
                        broker_order_id=broker_oid,
                        is_super_order=super_used,
                        oms_error=oms_err,
                        executed_at=eval_dt,
                    )
                )

                # Margin-safe hedge abort: if ANY BUY hedge leg fails when SELL legs remain, stop immediately
                if (
                    is_buy_hedge
                    and has_buy_hedges
                    and len(sell_indexed) > 0
                    and status_str != "TRADED"
                ):
                    await session.commit()
                    raise HedgeExecutionAbortedError(
                        f"BUY hedge {instr.contract_id} did not fill (status={status_str}"
                        f"{f', oms={oms_err}' if oms_err else ''}); SELL legs aborted for margin safety."
                    )

            if parent_id is not None:
                p_row = await session.get(LiveOrderModel, parent_id)
                if p_row is not None:
                    p_row.status = "TRADED" if all(s == "TRADED" for s in slice_statuses) else slice_statuses[-1]

        result = ExecutionResultSchema(
            idempotency_key=idempotency_key,
            deduplicated=False,
            trading_mode=req.trading_mode,
            action=req.action,
            realized_pnl_delta=Decimal("0.00"),
            fills=fills,
        )
        if root_row is not None:
            meta = dict(root_row.metadata_json)
            meta["cached_result"] = result.model_dump(mode="json")
            root_row.metadata_json = meta

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            re_existing = (await session.execute(existing_stmt)).scalar_one_or_none()
            if re_existing is not None and "cached_result" in re_existing.metadata_json:
                parsed = ExecutionResultSchema.model_validate(
                    re_existing.metadata_json["cached_result"]
                )
                return parsed.model_copy(update={"deduplicated": True})
            raise

        return result


class CompositeExecutionProvider:
    """Routes SIMULATOR/PAPER_LIVE to VirtualSimulatorBroker and DHAN_* to DhanExecutionProvider."""

    def __init__(
        self,
        virtual_broker: Any,
        dhan_broker: DhanExecutionProvider,
        risk_guard: RiskGuardService | None = None,
    ) -> None:
        self._virtual = virtual_broker
        self._dhan = dhan_broker
        self._risk_guard = risk_guard

    async def execute_orders(
        self,
        session: AsyncSession,
        req: BatchOrderRequest,
        idempotency_key: UUID,
    ) -> ExecutionResultSchema:
        if req.trading_mode in ("DHAN_SANDBOX", "SANDBOX", "DHAN_LIVE", "LIVE"):
            return await self._dhan.execute_orders(session, req, idempotency_key)
        if self._risk_guard is not None and self._risk_guard.daily_kill_switch_active:
            # Also enforce global emergency kill switch on simulator/paper orders when active
            raise KillSwitchEngagedError(
                "Execution blocked: Daily Kill Switch is active. Unlock manually to resume."
            )
        return await self._virtual.execute_orders(session, req, idempotency_key)
