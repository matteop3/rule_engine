"""
Tests for BOM quantity resolution: static quantity, field reference,
null fallback, zero/negative exclusion, decimal support, hidden field fallback.
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
    Rule,
    RuleType,
    VersionStatus,
)
from app.schemas.engine import CalculationRequest, FieldInputState
from app.services.rule_engine import RuleEngineService
from tests.fixtures.price_lists import create_price_list_with_items


@pytest.fixture(scope="function")
def setup_bom_quantity_scenario(db_session: Session):
    """
    Scenario for BOM quantity resolution testing.

    Fields:
    - qty_field (NUMBER, free value): drives dynamic quantity
    """
    entity = Entity(name="BOM Qty Test", description="Quantity resolution")
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

    # BOM item with static quantity
    bom_static = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="STATIC-001",
        quantity=Decimal("5"),
        sequence=1,
    )
    # BOM item with quantity_from_field_id
    bom_dynamic = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="DYN-001",
        quantity=Decimal("3"),
        quantity_from_field_id=f_qty.id,
        sequence=2,
    )
    db_session.add_all([bom_static, bom_dynamic])
    db_session.commit()

    pl = create_price_list_with_items(
        db_session,
        {"STATIC-001": Decimal("10.00"), "DYN-001": Decimal("10.00")},
    )

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "price_list_id": pl.id,
        "fields": {"qty": f_qty.id},
        "bom_items": {"static": bom_static.id, "dynamic": bom_dynamic.id},
    }


class TestBOMQuantityResolution:
    """Quantity resolution logic for BOM items."""

    def test_static_quantity(self, db_session, setup_bom_quantity_scenario):
        """Uses `quantity` when `quantity_from_field_id` is null."""
        data = setup_bom_quantity_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                price_list_id=data["price_list_id"],
                current_state=[],
            ),
        )

        assert response.bom is not None
        static_item = next(i for i in response.bom.commercial if i.bom_item_id == data["bom_items"]["static"])
        assert static_item.quantity == Decimal("5")
        assert static_item.line_total == Decimal("50.00")

    def test_quantity_from_field_valid(self, db_session, setup_bom_quantity_scenario):
        """Reads quantity from referenced numeric field."""
        data = setup_bom_quantity_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                price_list_id=data["price_list_id"],
                current_state=[FieldInputState(field_id=data["fields"]["qty"], value=7)],
            ),
        )

        assert response.bom is not None
        dynamic_item = next(i for i in response.bom.commercial if i.bom_item_id == data["bom_items"]["dynamic"])
        assert dynamic_item.quantity == Decimal("7")
        assert dynamic_item.line_total == Decimal("70.00")

    def test_quantity_from_field_null_fallback(self, db_session, setup_bom_quantity_scenario):
        """Falls back to static when field value is null."""
        data = setup_bom_quantity_scenario
        service = RuleEngineService()

        # No value provided for qty field
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                price_list_id=data["price_list_id"],
                current_state=[],
            ),
        )

        assert response.bom is not None
        dynamic_item = next(i for i in response.bom.commercial if i.bom_item_id == data["bom_items"]["dynamic"])
        assert dynamic_item.quantity == Decimal("3")  # Falls back to static quantity

    def test_quantity_from_field_zero_excludes(self, db_session, setup_bom_quantity_scenario):
        """Item excluded when field value is 0."""
        data = setup_bom_quantity_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                price_list_id=data["price_list_id"],
                current_state=[FieldInputState(field_id=data["fields"]["qty"], value=0)],
            ),
        )

        assert response.bom is not None
        dynamic_ids = [i.bom_item_id for i in response.bom.commercial]
        assert data["bom_items"]["dynamic"] not in dynamic_ids

    def test_quantity_from_field_negative_excludes(self, db_session, setup_bom_quantity_scenario):
        """Item excluded when field value is negative."""
        data = setup_bom_quantity_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                price_list_id=data["price_list_id"],
                current_state=[FieldInputState(field_id=data["fields"]["qty"], value=-3)],
            ),
        )

        assert response.bom is not None
        dynamic_ids = [i.bom_item_id for i in response.bom.commercial]
        assert data["bom_items"]["dynamic"] not in dynamic_ids

    def test_quantity_from_field_decimal(self, db_session, setup_bom_quantity_scenario):
        """Decimal field values are supported."""
        data = setup_bom_quantity_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                price_list_id=data["price_list_id"],
                current_state=[FieldInputState(field_id=data["fields"]["qty"], value=2.5)],
            ),
        )

        assert response.bom is not None
        dynamic_item = next(i for i in response.bom.commercial if i.bom_item_id == data["bom_items"]["dynamic"])
        assert dynamic_item.quantity == Decimal("2.5")
        assert dynamic_item.line_total == Decimal("25.00")

    def test_quantity_from_hidden_field_fallback(self, db_session):
        """Falls back to static when referenced field is hidden."""
        entity = Entity(name="BOM Hidden Qty", description="Hidden field fallback")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        f_trigger = Field(
            entity_version_id=version.id,
            name="trigger",
            label="Trigger",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        f_qty = Field(
            entity_version_id=version.id,
            name="qty_field",
            label="Quantity Field",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            step=2,
            sequence=0,
        )
        db_session.add_all([f_trigger, f_qty])
        db_session.commit()

        # Visibility rule: qty_field hidden if trigger == "HIDE"
        rule_hide_qty = Rule(
            entity_version_id=version.id,
            target_field_id=f_qty.id,
            rule_type=RuleType.VISIBILITY.value,
            conditions={"criteria": [{"field_id": f_trigger.id, "operator": "NOT_EQUALS", "value": "HIDE"}]},
        )
        db_session.add(rule_hide_qty)
        db_session.commit()

        bom_dynamic = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="DYN-001",
            quantity=Decimal("3"),
            quantity_from_field_id=f_qty.id,
            sequence=1,
        )
        db_session.add(bom_dynamic)
        db_session.commit()

        service = RuleEngineService()

        # Set trigger to "HIDE" so qty_field becomes hidden
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[
                    FieldInputState(field_id=f_trigger.id, value="HIDE"),
                    FieldInputState(field_id=f_qty.id, value=99),
                ],
            ),
        )

        assert response.bom is not None
        dynamic_item = next(i for i in response.bom.commercial if i.bom_item_id == bom_dynamic.id)
        # Falls back to static quantity because field is hidden
        assert dynamic_item.quantity == Decimal("3")
