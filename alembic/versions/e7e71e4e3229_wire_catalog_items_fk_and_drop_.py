"""wire catalog_items FK and drop redundant columns

Revision ID: e7e71e4e3229
Revises: 7d3a8c5f2e14
Create Date: 2026-04-18 10:56:59.466289

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7e71e4e3229"
down_revision: str | Sequence[str] | None = "7d3a8c5f2e14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Backfill catalog_items from distinct part_number values already present
    # on bom_items and price_list_items. description prefers the price list
    # value (more curated) and falls back to the BOM item value; category is
    # taken from the BOM item; unit_of_measure is taken from the BOM item
    # with 'PC' as fallback. status defaults to ACTIVE.
    op.execute(
        sa.text(
            """
            WITH pli_agg AS (
                SELECT part_number, MIN(description) AS description
                FROM price_list_items
                GROUP BY part_number
            ),
            bi_agg AS (
                SELECT
                    part_number,
                    MIN(description) AS description,
                    MIN(category) AS category,
                    MIN(unit_of_measure) AS unit_of_measure
                FROM bom_items
                GROUP BY part_number
            ),
            parts AS (
                SELECT part_number FROM pli_agg
                UNION
                SELECT part_number FROM bi_agg
            )
            INSERT INTO catalog_items
                (part_number, description, unit_of_measure, category, status, created_at)
            SELECT
                p.part_number,
                COALESCE(pli_agg.description, bi_agg.description, p.part_number) AS description,
                COALESCE(bi_agg.unit_of_measure, 'PC') AS unit_of_measure,
                bi_agg.category AS category,
                'ACTIVE' AS status,
                now() AS created_at
            FROM parts AS p
            LEFT JOIN pli_agg ON pli_agg.part_number = p.part_number
            LEFT JOIN bi_agg ON bi_agg.part_number = p.part_number
            WHERE p.part_number NOT IN (SELECT part_number FROM catalog_items)
            """
        )
    )

    op.create_foreign_key(
        "fk_bom_items_part_number",
        "bom_items",
        "catalog_items",
        ["part_number"],
        ["part_number"],
    )
    op.create_foreign_key(
        "fk_price_list_items_part_number",
        "price_list_items",
        "catalog_items",
        ["part_number"],
        ["part_number"],
    )

    op.drop_column("bom_items", "category")
    op.drop_column("bom_items", "description")
    op.drop_column("bom_items", "unit_of_measure")
    op.drop_column("price_list_items", "description")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "bom_items",
        sa.Column("description", sa.Text(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "bom_items",
        sa.Column(
            "category",
            sa.VARCHAR(length=100),
            autoincrement=False,
            nullable=True,
            comment="Grouping label (e.g., 'Chassis', 'Electronics')",
        ),
    )
    op.add_column(
        "bom_items",
        sa.Column(
            "unit_of_measure",
            sa.VARCHAR(length=20),
            autoincrement=False,
            nullable=True,
            comment="e.g., 'pcs', 'm', 'kg'",
        ),
    )
    op.add_column(
        "price_list_items",
        sa.Column("description", sa.Text(), autoincrement=False, nullable=True),
    )

    op.execute(
        sa.text(
            """
            UPDATE bom_items AS bi
            SET description = ci.description,
                category = ci.category,
                unit_of_measure = ci.unit_of_measure
            FROM catalog_items AS ci
            WHERE bi.part_number = ci.part_number
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE price_list_items AS pli
            SET description = ci.description
            FROM catalog_items AS ci
            WHERE pli.part_number = ci.part_number
            """
        )
    )

    op.drop_constraint("fk_price_list_items_part_number", "price_list_items", type_="foreignkey")
    op.drop_constraint("fk_bom_items_part_number", "bom_items", type_="foreignkey")
