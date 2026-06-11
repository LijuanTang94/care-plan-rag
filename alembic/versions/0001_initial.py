"""initial schema: patients / providers / orders / care_plans

Revision ID: 0001
Revises:
Create Date: 2026-06-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("first_name", sa.String, nullable=False),
        sa.Column("last_name", sa.String, nullable=False),
        sa.Column("mrn", sa.String, nullable=False),
        sa.Column("dob", sa.String, nullable=False, server_default=""),
    )
    op.create_index("ix_patients_mrn", "patients", ["mrn"], unique=True)

    op.create_table(
        "providers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("npi", sa.String, nullable=False),
    )
    op.create_index("ix_providers_npi", "providers", ["npi"], unique=True)

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("provider_id", sa.Integer, sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("medication_name", sa.String, nullable=False),
        sa.Column("primary_diagnosis", sa.String, nullable=False),
        sa.Column("patient_records", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "care_plans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("order_id", sa.Integer, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
    )


def downgrade() -> None:
    op.drop_table("care_plans")
    op.drop_table("orders")
    op.drop_index("ix_providers_npi", table_name="providers")
    op.drop_table("providers")
    op.drop_index("ix_patients_mrn", table_name="patients")
    op.drop_table("patients")
