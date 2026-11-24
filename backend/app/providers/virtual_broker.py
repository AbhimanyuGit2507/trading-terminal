"""VirtualSimulatorBroker: idempotent, tick-snapped, freeze-sliced ExecutionProvider."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar import IST, get_instrument_spec, round_to_tick, to_ist
from app.core.config import get_settings
from app.core.contracts import parse_contract_id
from app.db.models import VirtualOrderModel
from app.providers.base import MarketDataProvider
from app.schemas.domain import (
    BatchOrderRequest,
    ExecutionResultSchema,
    OrderFillSchema,
)


class KillSwitchEngagedError(RuntimeError):
    """Raised when execution is attempted while kill switch is active."""


class TradingModeMismatchError(RuntimeError):
    """Raised when live/sandbox execution is requested under simulator mode."""


def _compute_realized_delta(
    action: str,
    order_side: str,
    qty: int,
    fill_price: Decimal,
    entry_price: Decimal | None,
) -> Decimal:
    if entry_price is None or action not in (
        "PARTIAL_EXIT",
        "SQUARE_OFF_ALL",
        "FLIP_SIDE",
        "SETTLED_AT_EXPIRY",
    ):
        return Decimal("0.00")
    # Order side is the closing order side:
    # BUY closes an existing SELL leg -> PnL = (entry - fill) * qty
    # SELL closes an existing BUY leg -> PnL = (fill - entry) * qty
    if order_side == "BUY":
        pnl = (entry_price - fill_price) * Decimal(qty)
    else:
        pnl = (fill_price - entry_price) * Decimal(qty)
    return pnl.quantize(Decimal("0.01"))


class VirtualSimulatorBroker:
    """Simulated ExecutionProvider backed by PostgreSQL virtual_orders ledger."""

    def __init__(self, market_provider: MarketDataProvider) -> None:
        self._market = market_provider

    async def execute_orders(
        self,
        session: AsyncSession,
        req: BatchOrderRequest,
        idempotency_key: UUID,
    ) -> ExecutionResultSchema:
        settings = get_settings()
        if settings.kill_switch_engaged:
            raise KillSwitchEngagedError("Execution blocked: global kill switch is engaged.")
        if req.trading_mode == "LIVE" and settings.trading_mode != "LIVE":
            raise TradingModeMismatchError(
                f"Cannot execute LIVE order when backend TRADING_MODE={settings.trading_mode}."
            )

        # 1. Idempotency check against Postgres unique index
        existing_stmt = select(VirtualOrderModel).where(
            VirtualOrderModel.idempotency_key == idempotency_key
        )
        existing_root = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing_root is not None:
            cached = existing_root.metadata_json.get("cached_result")
            if cached is not None:
                parsed = ExecutionResultSchema.model_validate(cached)
                return parsed.model_copy(update={"deduplicated": True})

        eval_dt = to_ist(req.as_of) if req.as_of is not None else datetime.now(IST)
        contract_ids = [leg.contract_id for leg in req.legs]
        quotes = await self._market.get_contract_quotes(contract_ids, as_of=eval_dt)

        fills: list[OrderFillSchema] = []
        total_realized_delta = Decimal("0.00")
        root_row: VirtualOrderModel | None = None

        for leg_idx, instr in enumerate(req.legs):
            parsed_cid = parse_contract_id(instr.contract_id)
            spec = get_instrument_spec(parsed_cid.symbol, parsed_cid.expiry or eval_dt)
            lot_size = instr.lot_size or spec.lot_size
            total_qty = instr.lots * lot_size

            if instr.limit_price is not None:
                raw_px = float(instr.limit_price)
            elif instr.contract_id in quotes:
                raw_px = quotes[instr.contract_id].ltp
            else:
                raise ValueError(f"Unable to resolve market quote for contract {instr.contract_id}")

            if req.action == "SETTLED_AT_EXPIRY" and raw_px <= 0.0:
                snapped_px = Decimal("0.00")
            else:
                snapped_px = Decimal(f"{round_to_tick(raw_px, spec.tick_size):.2f}")
            total_realized_delta += _compute_realized_delta(
                req.action, instr.side, total_qty, snapped_px, instr.entry_price
            )

            max_lots_per_slice = max(1, spec.freeze_qty // lot_size)
            needs_slicing = req.slice_if_frozen and total_qty > spec.freeze_qty

            if needs_slicing:
                chunks: list[int] = []
                remaining = instr.lots
                while remaining > 0:
                    take = min(remaining, max_lots_per_slice)
                    chunks.append(take)
                    remaining -= take

                parent_key = (
                    idempotency_key
                    if leg_idx == 0
                    else uuid.uuid5(idempotency_key, f"leg:{leg_idx}:parent")
                )
                parent_row = VirtualOrderModel(
                    strategy_id=req.strategy_id,
                    idempotency_key=parent_key,
                    parent_order_id=req.parent_order_id,
                    slice_index=0,
                    total_slices=len(chunks),
                    trading_mode=req.trading_mode,
                    contract_id=instr.contract_id,
                    side=instr.side,
                    action=req.action,
                    lots=instr.lots,
                    quantity=total_qty,
                    limit_price=instr.limit_price,
                    fill_price=snapped_px,
                    status="FILLED",
                    metadata_json={
                        "is_parent": True,
                        "batch_idempotency_key": str(idempotency_key),
                        "leg_id": instr.leg_id,
                    },
                    executed_at=eval_dt,
                )
                session.add(parent_row)
                await session.flush()
                if root_row is None:
                    root_row = parent_row

                fills.append(
                    OrderFillSchema(
                        order_id=parent_row.id,
                        parent_order_id=parent_row.parent_order_id,
                        slice_index=0,
                        total_slices=len(chunks),
                        is_parent=True,
                        contract_id=parent_row.contract_id,
                        side=instr.side,
                        action=req.action,
                        lots=parent_row.lots,
                        quantity=parent_row.quantity,
                        fill_price=snapped_px,
                        status="FILLED",
                        executed_at=eval_dt,
                    )
                )

                for s_idx, slice_lots in enumerate(chunks, start=1):
                    slice_qty = slice_lots * lot_size
                    child_key = uuid.uuid5(idempotency_key, f"leg:{leg_idx}:slice:{s_idx}")
                    child_row = VirtualOrderModel(
                        strategy_id=req.strategy_id,
                        idempotency_key=child_key,
                        parent_order_id=parent_row.id,
                        slice_index=s_idx,
                        total_slices=len(chunks),
                        trading_mode=req.trading_mode,
                        contract_id=instr.contract_id,
                        side=instr.side,
                        action=req.action,
                        lots=slice_lots,
                        quantity=slice_qty,
                        limit_price=instr.limit_price,
                        fill_price=snapped_px,
                        status="FILLED",
                        metadata_json={
                            "is_parent": False,
                            "batch_idempotency_key": str(idempotency_key),
                            "leg_id": instr.leg_id,
                        },
                        executed_at=eval_dt,
                    )
                    session.add(child_row)
                    await session.flush()
                    fills.append(
                        OrderFillSchema(
                            order_id=child_row.id,
                            parent_order_id=parent_row.id,
                            slice_index=s_idx,
                            total_slices=len(chunks),
                            is_parent=False,
                            contract_id=child_row.contract_id,
                            side=instr.side,
                            action=req.action,
                            lots=slice_lots,
                            quantity=slice_qty,
                            fill_price=snapped_px,
                            status="FILLED",
                            executed_at=eval_dt,
                        )
                    )
            else:
                row_key = (
                    idempotency_key
                    if leg_idx == 0
                    else uuid.uuid5(idempotency_key, f"leg:{leg_idx}:single")
                )
                order_row = VirtualOrderModel(
                    strategy_id=req.strategy_id,
                    idempotency_key=row_key,
                    parent_order_id=req.parent_order_id,
                    slice_index=0,
                    total_slices=1,
                    trading_mode=req.trading_mode,
                    contract_id=instr.contract_id,
                    side=instr.side,
                    action=req.action,
                    lots=instr.lots,
                    quantity=total_qty,
                    limit_price=instr.limit_price,
                    fill_price=snapped_px,
                    status="FILLED",
                    metadata_json={
                        "is_parent": False,
                        "batch_idempotency_key": str(idempotency_key),
                        "leg_id": instr.leg_id,
                    },
                    executed_at=eval_dt,
                )
                session.add(order_row)
                await session.flush()
                if root_row is None:
                    root_row = order_row
                fills.append(
                    OrderFillSchema(
                        order_id=order_row.id,
                        parent_order_id=order_row.parent_order_id,
                        slice_index=0,
                        total_slices=1,
                        is_parent=False,
                        contract_id=order_row.contract_id,
                        side=instr.side,
                        action=req.action,
                        lots=order_row.lots,
                        quantity=order_row.quantity,
                        fill_price=snapped_px,
                        status="FILLED",
                        executed_at=eval_dt,
                    )
                )

        result = ExecutionResultSchema(
            idempotency_key=idempotency_key,
            deduplicated=False,
            trading_mode=req.trading_mode,
            action=req.action,
            realized_pnl_delta=total_realized_delta.quantize(Decimal("0.01")),
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
