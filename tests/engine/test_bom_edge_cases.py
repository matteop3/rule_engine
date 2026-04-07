"""
Tests for BOM numeric edge cases: precision limits, zero prices,
large quantities, decimal accumulation, and quantity-from-field boundaries.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import (
    BOMItem,
    BOMType,
    Entity,
    EntityVersion,
    Field,
    FieldType,
    VersionStatus,
)
from app.schemas.engine import CalculationRequest, FieldInputState
from app.services.rule_engine import RuleEngineService


@pytest.fixture(scope="function")
def setup_edge_case_entity(db_session: Session):
    """
    Minimal entity with a PUBLISHED version for BOM edge case tests.

    Provides a NUMBER field (qty_field) for quantity-from-field tests.
    """
    entity = Entity(name="BOM Edge Cases", description="Numeric edge cases")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    f_qty = Field(
        entity_version_id=version.id,
        name="qty_field",
        label="Quantity Field",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        step=1,
        sequence=0,
    )
    db_session.add(f_qty)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "qty_field_id": f_qty.id,
    }


class TestDecimalPrecision:
    """Boundary value tests for Numeric(12,4) columns."""

    def test_max_unit_price(self, db_session, setup_edge_case_entity):
        """line_total is exact when unit_price is at the Numeric(12,4) maximum."""
        data = setup_edge_case_entity

        bom = BOMItem(
            entity_version_id=data["version_id"],
            bom_type=BOMType.COMMERCIAL.value,
            part_number="MAX-PRICE",
            quantity=Decimal("1"),
            unit_price=Decimal("99999999.9999"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], current_state=[]),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.line_total == Decimal("99999999.9999")

    def test_max_quantity(self, db_session, setup_edge_case_entity):
        """line_total is exact when quantity is at the Numeric(12,4) maximum."""
        data = setup_edge_case_entity

        bom = BOMItem(
            entity_version_id=data["version_id"],
            bom_type=BOMType.COMMERCIAL.value,
            part_number="MAX-QTY",
            quantity=Decimal("99999999.9999"),
            unit_price=Decimal("1"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], current_state=[]),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.line_total == Decimal("99999999.9999")

    def test_small_decimal_quantity(self, db_session, setup_edge_case_entity):
        """Minimum non-zero quantity (0.0001) produces correct line_total."""
        data = setup_edge_case_entity

        bom = BOMItem(
            entity_version_id=data["version_id"],
            bom_type=BOMType.COMMERCIAL.value,
            part_number="SMALL-QTY",
            quantity=Decimal("0.0001"),
            unit_price=Decimal("10000.0000"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], current_state=[]),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.line_total == Decimal("1.0000")


class TestZeroPrice:
    """Zero price on COMMERCIAL items."""

    def test_zero_unit_price(self, db_session, setup_edge_case_entity):
        """Zero unit_price is accepted and produces line_total = 0.
        Note: the CRUD router requires unit_price to be non-null for COMMERCIAL items
        but does not reject zero. This is intentional for promotional items.
        """
        data = setup_edge_case_entity

        bom = BOMItem(
            entity_version_id=data["version_id"],
            bom_type=BOMType.COMMERCIAL.value,
            part_number="FREE-ITEM",
            quantity=Decimal("5"),
            unit_price=Decimal("0.0000"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], current_state=[]),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.line_total == Decimal("0.0000")


class TestAccumulationPrecision:
    """Decimal accumulation across many items (catches float conversion bugs)."""

    def test_twenty_items_accumulation(self, db_session, setup_edge_case_entity):
        """commercial_total for 20 items at 0.0001 each equals exactly 0.0020."""
        data = setup_edge_case_entity

        bom_ids = []
        for i in range(20):
            bom = BOMItem(
                entity_version_id=data["version_id"],
                bom_type=BOMType.COMMERCIAL.value,
                part_number=f"ACC-{i:03d}",
                quantity=Decimal("1"),
                unit_price=Decimal("0.0001"),
                sequence=i + 1,
            )
            db_session.add(bom)
            db_session.flush()
            bom_ids.append(bom.id)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], current_state=[]),
        )

        assert response.bom is not None
        assert response.bom.commercial_total == Decimal("0.0020")


class TestAggregationLargeQuantities:
    """Aggregation of same-part-number items with large quantities."""

    def test_aggregate_large_quantities(self, db_session, setup_edge_case_entity):
        """Three items with same part_number aggregate to Numeric(12,4) max quantity."""
        data = setup_edge_case_entity

        for i in range(3):
            bom = BOMItem(
                entity_version_id=data["version_id"],
                bom_type=BOMType.COMMERCIAL.value,
                part_number="AGG-LARGE",
                quantity=Decimal("33333333.3333"),
                unit_price=Decimal("1.0000"),
                sequence=i + 1,
            )
            db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], current_state=[]),
        )

        assert response.bom is not None
        # After aggregation the three items merge into one
        agg_item = next(i for i in response.bom.commercial if i.part_number == "AGG-LARGE")
        assert agg_item.quantity == Decimal("99999999.9999")
        assert agg_item.line_total == Decimal("99999999.9999")


class TestQuantityFromFieldBoundaries:
    """Edge cases for quantity resolved from a field value."""

    def test_quantity_from_field_zero_excludes(self, db_session, setup_edge_case_entity):
        """Item excluded when quantity field value is 0."""
        data = setup_edge_case_entity

        bom = BOMItem(
            entity_version_id=data["version_id"],
            bom_type=BOMType.COMMERCIAL.value,
            part_number="QTY-ZERO",
            quantity=Decimal("1"),
            quantity_from_field_id=data["qty_field_id"],
            unit_price=Decimal("10.00"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["qty_field_id"], value=0)],
            ),
        )

        # Item should be excluded (zero quantity)
        if response.bom is not None:
            bom_ids = [i.bom_item_id for i in response.bom.commercial]
            assert bom.id not in bom_ids

    def test_quantity_from_field_negative_excludes(self, db_session, setup_edge_case_entity):
        """Item excluded when quantity field value is negative."""
        data = setup_edge_case_entity

        bom = BOMItem(
            entity_version_id=data["version_id"],
            bom_type=BOMType.COMMERCIAL.value,
            part_number="QTY-NEG",
            quantity=Decimal("1"),
            quantity_from_field_id=data["qty_field_id"],
            unit_price=Decimal("10.00"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["qty_field_id"], value=-5)],
            ),
        )

        # Item should be excluded (negative quantity)
        if response.bom is not None:
            bom_ids = [i.bom_item_id for i in response.bom.commercial]
            assert bom.id not in bom_ids

    def test_quantity_from_field_very_large(self, db_session, setup_edge_case_entity):
        """Item included with correct quantity when field value is very large."""
        data = setup_edge_case_entity

        bom = BOMItem(
            entity_version_id=data["version_id"],
            bom_type=BOMType.COMMERCIAL.value,
            part_number="QTY-LARGE",
            quantity=Decimal("1"),
            quantity_from_field_id=data["qty_field_id"],
            unit_price=Decimal("1.0000"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[
                    FieldInputState(field_id=data["qty_field_id"], value=99999999.9999),
                ],
            ),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.quantity == Decimal("99999999.9999")
        assert item.line_total == Decimal("99999999.9999")
