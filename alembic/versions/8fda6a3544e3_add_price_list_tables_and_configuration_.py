"""add price list tables and configuration pricing columns

Revision ID: 8fda6a3544e3
Revises: ede7b2b33ade
Create Date: 2026-04-09 00:23:24.715876

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8fda6a3544e3"
down_revision: str | Sequence[str] | None = "ede7b2b33ade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create price_lists table
    op.create_table(
        "price_lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), server_default="9999-12-31", nullable=False),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_price_lists_id"), "price_lists", ["id"], unique=False)

    # Create price_list_items table
    op.create_table(
        "price_list_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("price_list_id", sa.Integer(), nullable=False),
        sa.Column("part_number", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=False),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["price_list_id"], ["price_lists.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pli_lookup", "price_list_items", ["price_list_id", "part_number"], unique=False)
    op.create_index(op.f("ix_price_list_items_id"), "price_list_items", ["id"], unique=False)

    # Add pricing columns to configurations
    op.add_column(
        "configurations",
        sa.Column("price_list_id", sa.Integer(), nullable=True, comment="Price list used for this configuration"),
    )
    op.add_column(
        "configurations",
        sa.Column("price_date", sa.Date(), nullable=True, comment="Effective price date (set at finalization)"),
    )
    op.add_column(
        "configurations",
        sa.Column(
            "snapshot", sa.JSON(), nullable=True, comment="Full CalculationResponse snapshot for FINALIZED configs"
        ),
    )
    op.create_foreign_key(
        "fk_configurations_price_list_id",
        "configurations",
        "price_lists",
        ["price_list_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Remove unit_price from bom_items (pricing now handled by price list)
    op.drop_column("bom_items", "unit_price")


def downgrade() -> None:
    """Downgrade schema."""
    # Restore unit_price on bom_items
    op.add_column(
        "bom_items",
        sa.Column(
            "unit_price",
            sa.NUMERIC(precision=12, scale=4),
            nullable=True,
            comment="Required for COMMERCIAL, rejected for TECHNICAL",
        ),
    )

    # Remove pricing columns from configurations
    op.drop_constraint("fk_configurations_price_list_id", "configurations", type_="foreignkey")
    op.drop_column("configurations", "snapshot")
    op.drop_column("configurations", "price_date")
    op.drop_column("configurations", "price_list_id")

    # Drop price_list_items table
    op.drop_index(op.f("ix_price_list_items_id"), table_name="price_list_items")
    op.drop_index("ix_pli_lookup", table_name="price_list_items")
    op.drop_table("price_list_items")

    # Drop price_lists table
    op.drop_index(op.f("ix_price_lists_id"), table_name="price_lists")
    op.drop_table("price_lists")
