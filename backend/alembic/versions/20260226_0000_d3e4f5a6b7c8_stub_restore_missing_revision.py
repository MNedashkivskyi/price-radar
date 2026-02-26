"""stub: restore missing revision referenced by deployed DB

The production database's alembic_version table points to d3e4f5a6b7c8,
but the migration file was deleted from the repo. This no-op stub restores
the revision so Alembic can locate it and the migration chain is intact.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-02-26 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No-op: this stub exists solely to satisfy the alembic_version pointer
    # in the deployed database. The original migration was removed from the
    # repo but had already been applied.
    pass


def downgrade() -> None:
    pass
