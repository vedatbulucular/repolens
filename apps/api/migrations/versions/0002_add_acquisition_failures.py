"""Add safe acquisition failure and processing ownership fields.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add Stage 2 acquisition failure and idempotency metadata."""
    op.add_column("analyses", sa.Column("error_code", sa.String(length=64), nullable=True))
    op.add_column(
        "analyses",
        sa.Column("processing_token", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Remove Stage 2 acquisition metadata."""
    op.drop_column("analyses", "processing_token")
    op.drop_column("analyses", "error_code")
