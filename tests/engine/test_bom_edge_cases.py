"""
Tests for BOM numeric edge cases: precision limits, zero prices,
large quantities, decimal accumulation, and quantity-from-field boundaries.

Prices are resolved from price lists (not from BOM items).
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
from tests.fixtures.price_lists import create_price_list_with_items


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
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        pl = create_price_list_with_items(db_session, {"MAX-PRICE": Decimal("99999999.9999")}, name="Max Price PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], price_list_id=pl.id, current_state=[]),
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
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        pl = create_price_list_with_items(db_session, {"MAX-QTY": Decimal("1")}, name="Max Qty PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], price_list_id=pl.id, current_state=[]),
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
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        pl = create_price_list_with_items(db_session, {"SMALL-QTY": Decimal("10000.0000")}, name="Small Qty PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], price_list_id=pl.id, current_state=[]),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.line_total == Decimal("1.0000")


class TestZeroPrice:
    """Zero price on COMMERCIAL items via price list."""

    def test_zero_unit_price(self, db_session, setup_edge_case_entity):
        """Zero unit_price from price list produces line_total = 0."""
        data = setup_edge_case_entity

        bom = BOMItem(
            entity_version_id=data["version_id"],
            bom_type=BOMType.COMMERCIAL.value,
            part_number="FREE-ITEM",
            quantity=Decimal("5"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        pl = create_price_list_with_items(db_session, {"FREE-ITEM": Decimal("0.0000")}, name="Zero Price PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], price_list_id=pl.id, current_state=[]),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.line_total == Decimal("0.0000")


class TestAccumulationPrecision:
    """Decimal accumulation across many items (catches float conversion bugs)."""

    def test_twenty_items_accumulation(self, db_session, setup_edge_case_entity):
        """commercial_total for 20 items at 0.0001 each equals exactly 0.0020."""
        data = setup_edge_case_entity

        prices = {}
        for i in range(20):
            part = f"ACC-{i:03d}"
            bom = BOMItem(
                entity_version_id=data["version_id"],
                bom_type=BOMType.COMMERCIAL.value,
                part_number=part,
                quantity=Decimal("1"),
                sequence=i + 1,
            )
            db_session.add(bom)
            db_session.flush()
            prices[part] = Decimal("0.0001")
        db_session.commit()

        pl = create_price_list_with_items(db_session, prices, name="Accumulation PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], price_list_id=pl.id, current_state=[]),
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
                sequence=i + 1,
            )
            db_session.add(bom)
        db_session.commit()

        pl = create_price_list_with_items(db_session, {"AGG-LARGE": Decimal("1.0000")}, name="Agg Large PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(entity_id=data["entity_id"], price_list_id=pl.id, current_state=[]),
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
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        pl = create_price_list_with_items(db_session, {"QTY-LARGE": Decimal("1.0000")}, name="Qty Large PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                price_list_id=pl.id,
                current_state=[
                    FieldInputState(field_id=data["qty_field_id"], value=99999999.9999),
                ],
            ),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.quantity == Decimal("99999999.9999")
        assert item.line_total == Decimal("99999999.9999")
