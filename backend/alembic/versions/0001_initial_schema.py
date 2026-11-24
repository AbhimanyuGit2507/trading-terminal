"""Initial schema for strategies and idempotent virtual orders.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-25 00:55:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")

    op.create_table(
        "strategies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("legs_json", json_type, nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategies")),
    )
    op.create_index(op.f("ix_strategies_symbol"), "strategies", ["symbol"], unique=False)

    op.create_table(
        "virtual_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("parent_order_id", sa.Uuid(), nullable=True),
        sa.Column("slice_index", sa.Integer(), nullable=False),
        sa.Column("total_slices", sa.Integer(), nullable=False),
        sa.Column("trading_mode", sa.String(length=16), nullable=False),
        sa.Column("contract_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("lots", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("fill_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_order_id"],
            ["virtual_orders.id"],
            name=op.f("fk_virtual_orders_parent_order_id_virtual_orders"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name=op.f("fk_virtual_orders_strategy_id_strategies"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_virtual_orders")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_virtual_orders_idempotency_key")),
    )
    op.create_index(
        op.f("ix_virtual_orders_contract_id"), "virtual_orders", ["contract_id"], unique=False
    )
    op.create_index(
        op.f("ix_virtual_orders_parent_order_id"),
        "virtual_orders",
        ["parent_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_virtual_orders_strategy_id"), "virtual_orders", ["strategy_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_virtual_orders_strategy_id"), table_name="virtual_orders")
    op.drop_index(op.f("ix_virtual_orders_parent_order_id"), table_name="virtual_orders")
    op.drop_index(op.f("ix_virtual_orders_contract_id"), table_name="virtual_orders")
    op.drop_table("virtual_orders")
    op.drop_index(op.f("ix_strategies_symbol"), table_name="strategies")
    op.drop_table("strategies")
