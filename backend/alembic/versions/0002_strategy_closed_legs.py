"""Add closed_legs_json and metadata_json to strategies.

Revision ID: 0002_strategy_closed_legs
Revises: 0001_initial_schema
Create Date: 2026-11-25 01:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_strategy_closed_legs"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
    op.add_column(
        "strategies",
        sa.Column(
            "closed_legs_json",
            json_type,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "strategies",
        sa.Column(
            "metadata_json",
            json_type,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("strategies", "metadata_json")
    op.drop_column("strategies", "closed_legs_json")
