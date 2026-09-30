"""care_plans.claimed_at: lease for the atomic claim

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: rows already stuck in "processing" have no claim time and are treated as expired.
    op.add_column("care_plans", sa.Column("claimed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("care_plans", "claimed_at")
