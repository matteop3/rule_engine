"""engineering template items and bom item suppress flag

Revision ID: 31116cc8a0f0
Revises: 0d7707c387f6
Create Date: 2026-04-26 11:52:58.802998

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "31116cc8a0f0"
down_revision: str | Sequence[str] | None = "0d7707c387f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "engineering_template_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parent_part_number", sa.String(length=100), nullable=False),
        sa.Column("child_part_number", sa.String(length=100), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "sequence",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Ordering among siblings within a template",
        ),
        sa.Column(
            "suppress_child_explosion",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="If true, the materialized child BOMItem is treated as a leaf",
        ),
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
        sa.CheckConstraint("parent_part_number <> child_part_number", name="ck_eti_no_self_loop"),
        sa.CheckConstraint("quantity > 0", name="ck_eti_quantity_positive"),
        sa.CheckConstraint("sequence >= 0", name="ck_eti_sequence_nonnegative"),
        sa.ForeignKeyConstraint(["child_part_number"], ["catalog_items.part_number"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_part_number"], ["catalog_items.part_number"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_part_number", "child_part_number", name="uq_eti_parent_child"),
    )
    op.create_index(
        op.f("ix_engineering_template_items_id"),
        "engineering_template_items",
        ["id"],
        unique=False,
    )
    op.create_index("ix_eti_child", "engineering_template_items", ["child_part_number"], unique=False)
    op.create_index("ix_eti_parent", "engineering_template_items", ["parent_part_number"], unique=False)
    op.add_column(
        "bom_items",
        sa.Column(
            "suppress_auto_explode",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="If true, future re-explode operations skip this row",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("bom_items", "suppress_auto_explode")
    op.drop_index("ix_eti_parent", table_name="engineering_template_items")
    op.drop_index("ix_eti_child", table_name="engineering_template_items")
    op.drop_index(op.f("ix_engineering_template_items_id"), table_name="engineering_template_items")
    op.drop_table("engineering_template_items")
