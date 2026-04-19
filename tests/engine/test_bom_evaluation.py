"""
Tests for BOM evaluation logic: inclusion/exclusion, OR/AND logic,
bom_type filtering, line totals, commercial total, empty version.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import (
    BOMItem,
    BOMItemRule,
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
def setup_bom_scenario(db_session: Session):
    """
    Scenario for BOM evaluation testing.

    Fields:
    - color (dropdown): RED, BLUE
    - material (dropdown): WOOD, METAL

    BOM items:
    - Frame (TECHNICAL, unconditional)
    - Paint (COMMERCIAL, conditional: color == RED)
    - Coating TECHNICAL (TECHNICAL, conditional: material == METAL)
    - Coating COMMERCIAL (COMMERCIAL, conditional: material == METAL)
    - Screws (COMMERCIAL, unconditional)
    """
    entity = Entity(name="BOM Test Product", description="BOM evaluation tests")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    f_color = Field(
        entity_version_id=version.id,
        name="color",
        label="Color",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=1,
        sequence=0,
    )
    f_material = Field(
        entity_version_id=version.id,
        name="material",
        label="Material",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=1,
        sequence=1,
    )
    db_session.add_all([f_color, f_material])
    db_session.commit()

    from app.models.domain import Value

    v_red = Value(field_id=f_color.id, value="RED", label="Red")
    v_blue = Value(field_id=f_color.id, value="BLUE", label="Blue")
    v_wood = Value(field_id=f_material.id, value="WOOD", label="Wood")
    v_metal = Value(field_id=f_material.id, value="METAL", label="Metal")
    db_session.add_all([v_red, v_blue, v_wood, v_metal])
    db_session.commit()

    # BOM items
    bom_frame = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="FRM-001",
        quantity=Decimal("1"),
        sequence=1,
    )
    bom_paint = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="PNT-RED",
        quantity=Decimal("1"),
        sequence=2,
    )
    bom_coating_tech = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="CTG-MTL",
        quantity=Decimal("2"),
        sequence=3,
    )
    bom_coating_comm = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="CTG-MTL",
        quantity=Decimal("2"),
        sequence=4,
    )
    bom_screws = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="SCR-100",
        quantity=Decimal("4"),
        sequence=5,
    )
    db_session.add_all([bom_frame, bom_paint, bom_coating_tech, bom_coating_comm, bom_screws])
    db_session.commit()

    # BOM item rules
    # Paint included only if color == RED
    rule_paint = BOMItemRule(
        bom_item_id=bom_paint.id,
        entity_version_id=version.id,
        conditions={"criteria": [{"field_id": f_color.id, "operator": "EQUALS", "value": "RED"}]},
        description="Include paint for red color",
    )
    # Coating included only if material == METAL (both technical and commercial)
    rule_coating_tech = BOMItemRule(
        bom_item_id=bom_coating_tech.id,
        entity_version_id=version.id,
        conditions={"criteria": [{"field_id": f_material.id, "operator": "EQUALS", "value": "METAL"}]},
        description="Include coating (technical) for metal",
    )
    rule_coating_comm = BOMItemRule(
        bom_item_id=bom_coating_comm.id,
        entity_version_id=version.id,
        conditions={"criteria": [{"field_id": f_material.id, "operator": "EQUALS", "value": "METAL"}]},
        description="Include coating (commercial) for metal",
    )
    db_session.add_all([rule_paint, rule_coating_tech, rule_coating_comm])
    db_session.commit()

    # Price list for commercial items
    pl = create_price_list_with_items(
        db_session,
        {
            "PNT-RED": Decimal("25.00"),
            "CTG-MTL": Decimal("15.00"),
            "SCR-100": Decimal("3.50"),
        },
    )

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "price_list_id": pl.id,
        "fields": {"color": f_color.id, "material": f_material.id},
        "bom_items": {
            "frame": bom_frame.id,
            "paint": bom_paint.id,
            "coating_tech": bom_coating_tech.id,
            "coating_comm": bom_coating_comm.id,
            "screws": bom_screws.id,
        },
    }


class TestBOMInclusion:
    """BOM item inclusion and exclusion logic."""

    def test_bom_item_no_rules_always_included(self, db_session, setup_bom_scenario):
        """BOM item with zero rules is present in output."""
        data = setup_bom_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[],
            ),
        )

        assert response.bom is not None
        technical_ids = [item.bom_item_id for item in response.bom.technical]
        commercial_ids = [item.bom_item_id for item in response.bom.commercial]
        # Frame (TECHNICAL, no rules) is always included
        assert data["bom_items"]["frame"] in technical_ids
        # Screws (COMMERCIAL, no rules) is always included
        assert data["bom_items"]["screws"] in commercial_ids

    def test_bom_item_single_rule_passes(self, db_session, setup_bom_scenario):
        """Item included when its one rule's conditions are met."""
        data = setup_bom_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["color"], value="RED")],
            ),
        )

        assert response.bom is not None
        commercial_ids = [item.bom_item_id for item in response.bom.commercial]
        assert data["bom_items"]["paint"] in commercial_ids

    def test_bom_item_single_rule_fails(self, db_session, setup_bom_scenario):
        """Item excluded when its one rule's conditions are not met."""
        data = setup_bom_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["color"], value="BLUE")],
            ),
        )

        assert response.bom is not None
        commercial_ids = [item.bom_item_id for item in response.bom.commercial]
        assert data["bom_items"]["paint"] not in commercial_ids

    def test_bom_item_multiple_rules_or_logic(self, db_session):
        """Item included if any one of multiple rules passes (OR logic)."""
        entity = Entity(name="BOM OR Test", description="OR logic")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        f_size = Field(
            entity_version_id=version.id,
            name="size",
            label="Size",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        db_session.add(f_size)
        db_session.commit()

        bom_item = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="OR-001",
            quantity=Decimal("1"),
            sequence=1,
        )
        db_session.add(bom_item)
        db_session.commit()

        # Two rules: size == LARGE OR size == MEDIUM
        rule1 = BOMItemRule(
            bom_item_id=bom_item.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_size.id, "operator": "EQUALS", "value": "LARGE"}]},
        )
        rule2 = BOMItemRule(
            bom_item_id=bom_item.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_size.id, "operator": "EQUALS", "value": "MEDIUM"}]},
        )
        db_session.add_all([rule1, rule2])
        db_session.commit()

        service = RuleEngineService()

        # MEDIUM matches rule2
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[FieldInputState(field_id=f_size.id, value="MEDIUM")],
            ),
        )
        assert response.bom is not None
        assert any(item.bom_item_id == bom_item.id for item in response.bom.technical)

    def test_bom_item_multiple_rules_all_fail(self, db_session):
        """Item excluded when all rules fail."""
        entity = Entity(name="BOM All Fail Test", description="All fail")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        f_size = Field(
            entity_version_id=version.id,
            name="size",
            label="Size",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        db_session.add(f_size)
        db_session.commit()

        bom_item = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="FAIL-001",
            quantity=Decimal("1"),
            sequence=1,
        )
        db_session.add(bom_item)
        db_session.commit()

        rule1 = BOMItemRule(
            bom_item_id=bom_item.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_size.id, "operator": "EQUALS", "value": "LARGE"}]},
        )
        rule2 = BOMItemRule(
            bom_item_id=bom_item.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_size.id, "operator": "EQUALS", "value": "MEDIUM"}]},
        )
        db_session.add_all([rule1, rule2])
        db_session.commit()

        service = RuleEngineService()

        # SMALL matches neither
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[FieldInputState(field_id=f_size.id, value="SMALL")],
            ),
        )
        assert response.bom is None or not any(item.bom_item_id == bom_item.id for item in response.bom.technical)

    def test_bom_item_criteria_and_logic(self, db_session):
        """All criteria within a single rule must pass (AND logic)."""
        entity = Entity(name="BOM AND Test", description="AND logic")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        f_color = Field(
            entity_version_id=version.id,
            name="color",
            label="Color",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        f_size = Field(
            entity_version_id=version.id,
            name="size",
            label="Size",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=1,
        )
        db_session.add_all([f_color, f_size])
        db_session.commit()

        bom_item = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="AND-001",
            quantity=Decimal("1"),
            sequence=1,
        )
        db_session.add(bom_item)
        db_session.commit()

        # Single rule with two criteria: color == RED AND size == LARGE
        rule = BOMItemRule(
            bom_item_id=bom_item.id,
            entity_version_id=version.id,
            conditions={
                "criteria": [
                    {"field_id": f_color.id, "operator": "EQUALS", "value": "RED"},
                    {"field_id": f_size.id, "operator": "EQUALS", "value": "LARGE"},
                ]
            },
        )
        db_session.add(rule)
        db_session.commit()

        service = RuleEngineService()

        # Only color matches — should be excluded
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[
                    FieldInputState(field_id=f_color.id, value="RED"),
                    FieldInputState(field_id=f_size.id, value="SMALL"),
                ],
            ),
        )
        assert response.bom is None or not any(item.bom_item_id == bom_item.id for item in response.bom.technical)

        # Both match — should be included
        response2 = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[
                    FieldInputState(field_id=f_color.id, value="RED"),
                    FieldInputState(field_id=f_size.id, value="LARGE"),
                ],
            ),
        )
        assert response2.bom is not None
        assert any(item.bom_item_id == bom_item.id for item in response2.bom.technical)


class TestBOMTypeFiltering:
    """BOM type classification into technical and commercial lists."""

    def test_bom_type_technical_in_technical_list(self, db_session, setup_bom_scenario):
        """TECHNICAL item appears only in `bom.technical`."""
        data = setup_bom_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[],
            ),
        )

        assert response.bom is not None
        technical_ids = [item.bom_item_id for item in response.bom.technical]
        commercial_ids = [item.bom_item_id for item in response.bom.commercial]
        assert data["bom_items"]["frame"] in technical_ids
        assert data["bom_items"]["frame"] not in commercial_ids

    def test_bom_type_commercial_in_commercial_list(self, db_session, setup_bom_scenario):
        """COMMERCIAL item appears in `bom.commercial` only."""
        data = setup_bom_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[],
            ),
        )

        assert response.bom is not None
        technical_ids = [item.bom_item_id for item in response.bom.technical]
        commercial_ids = [item.bom_item_id for item in response.bom.commercial]
        assert data["bom_items"]["screws"] in commercial_ids
        assert data["bom_items"]["screws"] not in technical_ids

    def test_same_part_separate_technical_and_commercial(self, db_session, setup_bom_scenario):
        """Same part_number modeled as separate TECHNICAL and COMMERCIAL items appears in both lists."""
        data = setup_bom_scenario
        service = RuleEngineService()

        # Include coating by selecting METAL
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["material"], value="METAL")],
            ),
        )

        assert response.bom is not None
        technical_ids = [item.bom_item_id for item in response.bom.technical]
        commercial_ids = [item.bom_item_id for item in response.bom.commercial]
        assert data["bom_items"]["coating_tech"] in technical_ids
        assert data["bom_items"]["coating_comm"] in commercial_ids
        # Each appears only in its own list
        assert data["bom_items"]["coating_tech"] not in commercial_ids
        assert data["bom_items"]["coating_comm"] not in technical_ids


class TestBOMPricing:
    """BOM line total and commercial total calculations."""

    def test_bom_line_total_calculation(self, db_session, setup_bom_scenario):
        """`line_total = quantity × unit_price` for commercial items."""
        data = setup_bom_scenario
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
        screws = next(i for i in response.bom.commercial if i.bom_item_id == data["bom_items"]["screws"])
        # 4 × 3.50 = 14.00
        assert screws.line_total == Decimal("14.00")

    def test_bom_commercial_total(self, db_session, setup_bom_scenario):
        """`commercial_total` sums all commercial line totals."""
        data = setup_bom_scenario
        service = RuleEngineService()

        # Include coating (METAL) and paint (RED)
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                price_list_id=data["price_list_id"],
                current_state=[
                    FieldInputState(field_id=data["fields"]["color"], value="RED"),
                    FieldInputState(field_id=data["fields"]["material"], value="METAL"),
                ],
            ),
        )

        assert response.bom is not None
        # Paint: 1 × 25.00 = 25.00
        # Coating (commercial): 2 × 15.00 = 30.00
        # Screws: 4 × 3.50 = 14.00
        # Total: 69.00
        assert response.bom.commercial_total == Decimal("69.00")

    def test_bom_technical_no_pricing(self, db_session, setup_bom_scenario):
        """TECHNICAL items have `unit_price = null`, `line_total = null`."""
        data = setup_bom_scenario
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
        frame = next(i for i in response.bom.technical if i.bom_item_id == data["bom_items"]["frame"])
        assert frame.unit_price is None
        assert frame.line_total is None


class TestBOMEmpty:
    """Edge case: version with no BOM items."""

    def test_bom_empty_version(self, db_session):
        """Version with no BOM items → `bom` is null in response."""
        entity = Entity(name="Empty BOM", description="No BOM items")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[],
            ),
        )

        assert response.bom is None
