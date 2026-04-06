"""
Tests for BOM line aggregation by (part_number, parent_bom_item_id, bom_type).
Items sharing the same key are merged into a single output line with summed quantity.
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


@pytest.fixture(scope="function")
def setup_aggregation_scenario(db_session: Session):
    """
    Scenario for BOM aggregation testing.

    Fields:
    - color (dropdown): RED, BLUE
    - size (dropdown): SMALL, LARGE

    BOM items (all root-level, COMMERCIAL, same part_number "BLT-10"):
    - bolt_a: qty 2, unit_price 5.00, seq 1, conditional: color == RED
    - bolt_b: qty 3, unit_price 5.00, seq 2, conditional: size == LARGE

    BOM items (unique parts):
    - frame: TECHNICAL, part_number "FRM-01", qty 1, seq 3, unconditional
    - paint: COMMERCIAL, part_number "PNT-01", qty 1, unit_price 10.00, seq 4, unconditional
    """
    entity = Entity(name="Aggregation Test Product", description="Aggregation tests")
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
    f_size = Field(
        entity_version_id=version.id,
        name="size",
        label="Size",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=1,
        sequence=1,
    )
    db_session.add_all([f_color, f_size])
    db_session.commit()

    from app.models.domain import Value

    for field, vals in [
        (f_color, [("RED", "Red"), ("BLUE", "Blue")]),
        (f_size, [("SMALL", "Small"), ("LARGE", "Large")]),
    ]:
        for v, lbl in vals:
            db_session.add(Value(field_id=field.id, value=v, label=lbl))
    db_session.commit()

    # Two BOM items with same part_number "BLT-10" (root-level, COMMERCIAL)
    bolt_a = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="BLT-10",
        description="Bolt pack (color rule)",
        category="Fasteners",
        unit_of_measure="pcs",
        quantity=Decimal("2"),
        unit_price=Decimal("5.00"),
        sequence=1,
    )
    bolt_b = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="BLT-10",
        description="Bolt pack (size rule)",
        category="Fasteners alt",
        unit_of_measure="box",
        quantity=Decimal("3"),
        unit_price=Decimal("7.00"),
        sequence=2,
    )
    frame = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="FRM-01",
        description="Main frame",
        quantity=Decimal("1"),
        sequence=3,
    )
    paint = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="PNT-01",
        description="Paint",
        quantity=Decimal("1"),
        unit_price=Decimal("10.00"),
        sequence=4,
    )
    db_session.add_all([bolt_a, bolt_b, frame, paint])
    db_session.commit()

    # Rules: bolt_a included when color == RED, bolt_b included when size == LARGE
    rule_a = BOMItemRule(
        bom_item_id=bolt_a.id,
        entity_version_id=version.id,
        conditions={"criteria": [{"field_id": f_color.id, "operator": "EQUALS", "value": "RED"}]},
        description="Include bolts for red color",
    )
    rule_b = BOMItemRule(
        bom_item_id=bolt_b.id,
        entity_version_id=version.id,
        conditions={"criteria": [{"field_id": f_size.id, "operator": "EQUALS", "value": "LARGE"}]},
        description="Include bolts for large size",
    )
    db_session.add_all([rule_a, rule_b])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {"color": f_color.id, "size": f_size.id},
        "bom_items": {
            "bolt_a": bolt_a.id,
            "bolt_b": bolt_b.id,
            "frame": frame.id,
            "paint": paint.id,
        },
    }


class TestBOMAggregation:
    """BOM line aggregation by (part_number, parent_bom_item_id, bom_type)."""

    def test_same_part_same_parent_aggregated(self, db_session, setup_aggregation_scenario):
        """Two items with same part_number, parent, and bom_type produce one output line with summed quantity."""
        data = setup_aggregation_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[
                    FieldInputState(field_id=data["fields"]["color"], value="RED"),
                    FieldInputState(field_id=data["fields"]["size"], value="LARGE"),
                ],
            ),
        )

        assert response.bom is not None
        bolt_lines = [item for item in response.bom.commercial if item.part_number == "BLT-10"]
        # Aggregated into one line
        assert len(bolt_lines) == 1
        # Summed quantity: 2 + 3 = 5
        assert bolt_lines[0].quantity == Decimal("5")

    def test_same_part_different_parents_not_aggregated(self, db_session):
        """Same part_number under different parents produces separate lines (TECHNICAL hierarchy)."""
        entity = Entity(name="Agg Parent Test", description="Different parents")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        parent_a = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="ASM-A",
            description="Assembly A",
            quantity=Decimal("1"),
            sequence=1,
        )
        parent_b = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="ASM-B",
            description="Assembly B",
            quantity=Decimal("1"),
            sequence=2,
        )
        db_session.add_all([parent_a, parent_b])
        db_session.commit()

        child_a = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="BLT-10",
            description="Bolt under A",
            quantity=Decimal("2"),
            sequence=3,
            parent_bom_item_id=parent_a.id,
        )
        child_b = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="BLT-10",
            description="Bolt under B",
            quantity=Decimal("3"),
            sequence=4,
            parent_bom_item_id=parent_b.id,
        )
        db_session.add_all([child_a, child_b])
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        # Collect BLT-10 lines from all technical items (they are children)
        bolt_lines = []
        for root in response.bom.technical:
            for child in root.children:
                if child.part_number == "BLT-10":
                    bolt_lines.append(child)
        # Not aggregated — different parents
        assert len(bolt_lines) == 2
        quantities = sorted([line.quantity for line in bolt_lines])
        assert quantities == [Decimal("2"), Decimal("3")]

    def test_same_part_different_types_not_aggregated(self, db_session):
        """Same part_number with different bom_type produces separate lines."""
        entity = Entity(name="Agg Type Test", description="Different types")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        # Same part_number, one TECHNICAL and one COMMERCIAL (root-level)
        tech_item = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="MTR-01",
            description="Motor (technical)",
            quantity=Decimal("2"),
            sequence=1,
        )
        comm_item = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="MTR-01",
            description="Motor (commercial)",
            quantity=Decimal("3"),
            unit_price=Decimal("50.00"),
            sequence=2,
        )
        db_session.add_all([tech_item, comm_item])
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        # TECHNICAL list has MTR-01 with qty 2
        tech_motors = [i for i in response.bom.technical if i.part_number == "MTR-01"]
        assert len(tech_motors) == 1
        assert tech_motors[0].quantity == Decimal("2")
        # COMMERCIAL list has MTR-01 with qty 3
        comm_motors = [i for i in response.bom.commercial if i.part_number == "MTR-01"]
        assert len(comm_motors) == 1
        assert comm_motors[0].quantity == Decimal("3")

    def test_aggregated_line_total(self, db_session, setup_aggregation_scenario):
        """line_total = aggregated quantity x unit_price."""
        data = setup_aggregation_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[
                    FieldInputState(field_id=data["fields"]["color"], value="RED"),
                    FieldInputState(field_id=data["fields"]["size"], value="LARGE"),
                ],
            ),
        )

        assert response.bom is not None
        bolt_lines = [item for item in response.bom.commercial if item.part_number == "BLT-10"]
        assert len(bolt_lines) == 1
        # line_total = 5 x 5.00 = 25.00
        assert bolt_lines[0].line_total == Decimal("25.00")

    def test_aggregated_commercial_total(self, db_session, setup_aggregation_scenario):
        """commercial_total reflects aggregated quantities."""
        data = setup_aggregation_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[
                    FieldInputState(field_id=data["fields"]["color"], value="RED"),
                    FieldInputState(field_id=data["fields"]["size"], value="LARGE"),
                ],
            ),
        )

        assert response.bom is not None
        # BLT-10: 5 x 5.00 = 25.00, PNT-01: 1 x 10.00 = 10.00 -> total = 35.00
        assert response.bom.commercial_total == Decimal("35.00")

    def test_aggregation_preserves_first_item_metadata(self, db_session, setup_aggregation_scenario):
        """description, category, unit_of_measure come from the first item by sequence."""
        data = setup_aggregation_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[
                    FieldInputState(field_id=data["fields"]["color"], value="RED"),
                    FieldInputState(field_id=data["fields"]["size"], value="LARGE"),
                ],
            ),
        )

        assert response.bom is not None
        bolt_lines = [item for item in response.bom.commercial if item.part_number == "BLT-10"]
        assert len(bolt_lines) == 1
        bolt = bolt_lines[0]
        # First item (bolt_a, seq=1) metadata
        assert bolt.bom_item_id == data["bom_items"]["bolt_a"]
        assert bolt.description == "Bolt pack (color rule)"
        assert bolt.category == "Fasteners"
        assert bolt.unit_of_measure == "pcs"
        assert bolt.unit_price == Decimal("5.00")

    def test_three_items_same_part_aggregated(self, db_session):
        """Three items with same key aggregate into one line."""
        entity = Entity(name="Agg Three Test", description="Three-way aggregation")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        items = []
        for i, qty in enumerate([Decimal("1"), Decimal("2"), Decimal("3")], start=1):
            items.append(
                BOMItem(
                    entity_version_id=version.id,
                    bom_type=BOMType.COMMERCIAL.value,
                    part_number="NUT-05",
                    description=f"Nut batch {i}",
                    quantity=qty,
                    unit_price=Decimal("2.00"),
                    sequence=i,
                )
            )
        db_session.add_all(items)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        nut_lines = [item for item in response.bom.commercial if item.part_number == "NUT-05"]
        assert len(nut_lines) == 1
        # 1 + 2 + 3 = 6
        assert nut_lines[0].quantity == Decimal("6")
        assert nut_lines[0].line_total == Decimal("12.00")

    def test_no_aggregation_when_unique_parts(self, db_session, setup_aggregation_scenario):
        """Items with distinct part_number remain separate (baseline)."""
        data = setup_aggregation_scenario
        service = RuleEngineService()

        # Only bolt_a included (color=RED), bolt_b excluded (size!=LARGE)
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[
                    FieldInputState(field_id=data["fields"]["color"], value="RED"),
                    FieldInputState(field_id=data["fields"]["size"], value="SMALL"),
                ],
            ),
        )

        assert response.bom is not None
        commercial_parts = [item.part_number for item in response.bom.commercial]
        # BLT-10 (only bolt_a), PNT-01 — each appears once, no aggregation needed
        assert commercial_parts.count("BLT-10") == 1
        assert commercial_parts.count("PNT-01") == 1
        # BLT-10 keeps its original quantity (no summing)
        bolt = [item for item in response.bom.commercial if item.part_number == "BLT-10"][0]
        assert bolt.quantity == Decimal("2")
