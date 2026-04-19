"""add catalog_items table

Revision ID: 7d3a8c5f2e14
Revises: 8fda6a3544e3
Create Date: 2026-04-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d3a8c5f2e14"
down_revision: str | Sequence[str] | None = "8fda6a3544e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("part_number", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit_of_measure", sa.String(length=20), server_default="PC", nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("part_number", name="uq_catalog_items_part_number"),
    )
    op.create_index(op.f("ix_catalog_items_id"), "catalog_items", ["id"], unique=False)
    op.create_index(op.f("ix_catalog_items_part_number"), "catalog_items", ["part_number"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_catalog_items_part_number"), table_name="catalog_items")
    op.drop_index(op.f("ix_catalog_items_id"), table_name="catalog_items")
    op.drop_table("catalog_items")
