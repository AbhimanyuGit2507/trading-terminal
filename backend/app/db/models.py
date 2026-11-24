"""PostgreSQL ORM models for strategies and idempotent virtual/live orders."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

JSON_VARIANT = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrategyModel(Base):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="builder")
    legs_json: Mapped[list[dict]] = mapped_column(JSON_VARIANT, nullable=False, default=list)
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00")
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    orders: Mapped[list[VirtualOrderModel]] = relationship(
        back_populates="strategy",
        cascade="save-update, merge",
    )


class VirtualOrderModel(Base):
    __tablename__ = "virtual_orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("strategies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, unique=True
    )
    parent_order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("virtual_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    slice_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_slices: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trading_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="SIMULATOR")
    contract_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    lots: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fill_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="FILLED")
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    strategy: Mapped[StrategyModel | None] = relationship(back_populates="orders")
    child_orders: Mapped[list[VirtualOrderModel]] = relationship(
        remote_side=[id],
        uselist=True,
    )
