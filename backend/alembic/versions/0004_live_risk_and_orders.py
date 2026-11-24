"""Add live_orders and risk_config tables for Phase 4 live execution & kill switch.

Revision ID: 0004_live_risk_and_orders
Revises: 0003_broker_credentials
Create Date: 2026-11-25 02:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_live_risk_and_orders"
down_revision: str | Sequence[str] | None = "0003_broker_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("parent_order_id", sa.Uuid(), nullable=True),
        sa.Column("slice_index", sa.Integer(), nullable=False),
        sa.Column("total_slices", sa.Integer(), nullable=False),
        sa.Column("trading_mode", sa.String(length=24), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("contract_id", sa.String(length=64), nullable=False),
        sa.Column("exchange_segment", sa.String(length=16), nullable=False),
        sa.Column("security_id", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("product_type", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("is_super_order", sa.Boolean(), nullable=False),
        sa.Column("lots", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("fill_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("target_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("stop_loss_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("trailing_jump", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("oms_error", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_order_id"],
            ["live_orders.id"],
            name=op.f("fk_live_orders_parent_order_id_live_orders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_live_orders_strategy_id_strategies"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_live_orders")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_live_orders_idempotency_key")),
    )
    op.create_index(op.f("ix_live_orders_broker_order_id"), "live_orders", ["broker_order_id"])
    op.create_index(op.f("ix_live_orders_contract_id"), "live_orders", ["contract_id"])
    op.create_index(op.f("ix_live_orders_parent_order_id"), "live_orders", ["parent_order_id"])
    op.create_index(op.f("ix_live_orders_strategy_id"), "live_orders", ["strategy_id"])

    op.create_table(
        "risk_config",
        sa.Column("id", sa.String(length=24), nullable=False),
        sa.Column("active_execution_mode", sa.String(length=24), nullable=False),
        sa.Column("daily_kill_switch_active", sa.Boolean(), nullable=False),
        sa.Column("kill_switch_reason", sa.Text(), nullable=True),
        sa.Column("kill_switch_engaged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_max_loss_inr", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("max_lots_per_order", sa.Integer(), nullable=False),
        sa.Column("max_open_lots", sa.Integer(), nullable=False),
        sa.Column("max_daily_trades", sa.Integer(), nullable=False),
        sa.Column("product_type", sa.String(length=16), nullable=False),
        sa.Column("limit_buffer_ticks", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_config")),
    )


def downgrade() -> None:
    op.drop_table("risk_config")
    op.drop_index(op.f("ix_live_orders_strategy_id"), table_name="live_orders")
    op.drop_index(op.f("ix_live_orders_parent_order_id"), table_name="live_orders")
    op.drop_index(op.f("ix_live_orders_contract_id"), table_name="live_orders")
    op.drop_index(op.f("ix_live_orders_broker_order_id"), table_name="live_orders")
    op.drop_table("live_orders")

