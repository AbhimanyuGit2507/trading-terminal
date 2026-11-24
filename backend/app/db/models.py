"""PostgreSQL ORM models for strategies and idempotent virtual/live orders."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
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
    closed_legs_json: Mapped[list[dict]] = mapped_column(JSON_VARIANT, nullable=False, default=list)
    realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0.00")
    )
    metadata_json: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
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


class BrokerCredentialModel(Base):
    __tablename__ = "broker_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broker: Mapped[str] = mapped_column(String(24), nullable=False, unique=True, default="DHAN")
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    account_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ucc: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class LiveOrderModel(Base):
    __tablename__ = "live_orders"

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
        ForeignKey("live_orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    slice_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_slices: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    trading_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="DHAN_SANDBOX")
    environment: Mapped[str] = mapped_column(String(16), nullable=False, default="SANDBOX")
    contract_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    exchange_segment: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE_FNO")
    security_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN_LEGS")
    product_type: Mapped[str] = mapped_column(String(16), nullable=False, default="MARGIN")
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="LIMIT")
    is_super_order: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lots: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fill_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    stop_loss_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    trailing_jump: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    oms_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class RiskConfigModel(Base):
    __tablename__ = "risk_config"

    id: Mapped[str] = mapped_column(String(24), primary_key=True, default="global")
    active_execution_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default="PAPER_LIVE"
    )
    daily_kill_switch_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kill_switch_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    kill_switch_engaged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    daily_max_loss_inr: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("25000.00")
    )
    max_lots_per_order: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    max_open_lots: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_daily_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    product_type: Mapped[str] = mapped_column(String(16), nullable=False, default="MARGIN")
    limit_buffer_ticks: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
