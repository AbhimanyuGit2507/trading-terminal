"""Add broker_credentials table for persisted Dhan daily tokens.

Revision ID: 0003_broker_credentials
Revises: 0002_strategy_closed_legs
Create Date: 2026-11-25 01:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_broker_credentials"
down_revision: str | Sequence[str] | None = "0002_strategy_closed_legs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "broker_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("broker", sa.String(length=24), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("account_name", sa.String(length=120), nullable=True),
        sa.Column("ucc", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broker_credentials")),
        sa.UniqueConstraint("broker", name=op.f("uq_broker_credentials_broker")),
    )


def downgrade() -> None:
    op.drop_table("broker_credentials")
