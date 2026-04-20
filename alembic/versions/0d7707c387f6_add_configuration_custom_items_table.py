"""add configuration_custom_items table

Revision ID: 0d7707c387f6
Revises: e7e71e4e3229
Create Date: 2026-04-19 20:33:52.171817

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0d7707c387f6"
down_revision: str | Sequence[str] | None = "e7e71e4e3229"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "configuration_custom_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("configuration_id", sa.String(length=36), nullable=False),
        sa.Column("custom_key", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("unit_of_measure", sa.String(length=20), nullable=True),
        sa.Column("sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Timestamp when record was created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when record was last updated",
        ),
        sa.Column(
            "created_by_id",
            sa.String(length=36),
            nullable=True,
            comment="ID of user who created this record",
        ),
        sa.Column(
            "updated_by_id",
            sa.String(length=36),
            nullable=True,
            comment="ID of user who last updated this record",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_cci_quantity_positive"),
        sa.CheckConstraint("unit_price >= 0", name="ck_cci_unit_price_nonnegative"),
        sa.ForeignKeyConstraint(["configuration_id"], ["configurations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("custom_key", name="uq_cci_custom_key"),
    )
    op.create_index("ix_cci_configuration", "configuration_custom_items", ["configuration_id"], unique=False)
    op.create_index(
        op.f("ix_configuration_custom_items_id"),
        "configuration_custom_items",
        ["id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_configuration_custom_items_id"), table_name="configuration_custom_items")
    op.drop_index("ix_cci_configuration", table_name="configuration_custom_items")
    op.drop_table("configuration_custom_items")
