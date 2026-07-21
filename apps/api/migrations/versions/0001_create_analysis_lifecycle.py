"""Create repository and analysis lifecycle tables.

Revision ID: 0001
Revises:
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

analysis_status = postgresql.ENUM(
    "queued",
    "processing",
    "completed",
    "failed",
    name="analysis_status",
    create_type=False,
)


def upgrade() -> None:
    """Create the Stage 1 persistence schema."""
    analysis_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_url", sa.String(length=512), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repositories_canonical_url",
        "repositories",
        ["canonical_url"],
        unique=True,
    )
    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("status", analysis_status, nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analyses_repository_id", "analyses", ["repository_id"])
    op.create_index("ix_analyses_status", "analyses", ["status"])


def downgrade() -> None:
    """Remove the Stage 1 persistence schema."""
    op.drop_index("ix_analyses_status", table_name="analyses")
    op.drop_index("ix_analyses_repository_id", table_name="analyses")
    op.drop_table("analyses")
    op.drop_index("ix_repositories_canonical_url", table_name="repositories")
    op.drop_table("repositories")
    analysis_status.drop(op.get_bind(), checkfirst=True)
