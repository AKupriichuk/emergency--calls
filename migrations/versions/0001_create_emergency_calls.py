"""create emergency_calls table

Revision ID: 0001
Revises:
Create Date: 2026-10-11

"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emergency_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("call_number", sa.String(length=50), nullable=False),
        sa.Column("urgency_category", sa.SmallInteger(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=255), nullable=False),
    )
    op.create_index(
        "ix_emergency_calls_urgency_category",
        "emergency_calls",
        ["urgency_category"],
    )


def downgrade() -> None:
    op.drop_index("ix_emergency_calls_urgency_category", table_name="emergency_calls")
    op.drop_table("emergency_calls")
