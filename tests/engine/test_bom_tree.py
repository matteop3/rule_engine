"""
Tests for BOM tree pruning: parent/child cascade, three-level nesting,
sibling independence, sequence ordering, nested totals.

Hierarchy is for TECHNICAL items only. COMMERCIAL items are always root-level.
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
def setup_bom_tree_scenario(db_session: Session):
    """
    Scenario for BOM tree pruning testing.

    Fields:
    - toggle (STRING, free value): controls parent inclusion

    BOM tree (TECHNICAL — hierarchy):
    - Assembly A (conditional: toggle == ON)
      - Sub A1 (unconditional)
        - Part A1a (unconditional)
      - Sub A2 (unconditional)
    - Assembly B (unconditional)
      - Sub B1 (unconditional)
    """
    entity = Entity(name="BOM Tree Test", description="Tree pruning")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    f_toggle = Field(
        entity_version_id=version.id,
        name="toggle",
        label="Toggle",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        step=1,
        sequence=0,
    )
    db_session.add(f_toggle)
    db_session.commit()

    # Root: Assembly A (conditional)
    asm_a = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="ASM-A",
        description="Assembly A",
        quantity=Decimal("1"),
        sequence=1,
    )
    db_session.add(asm_a)
    db_session.commit()

    # Children of Assembly A
    sub_a1 = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="SUB-A1",
        description="Sub-assembly A1",
        parent_bom_item_id=asm_a.id,
        quantity=Decimal("2"),
        sequence=2,
    )
    sub_a2 = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="SUB-A2",
        description="Sub-assembly A2",
        parent_bom_item_id=asm_a.id,
        quantity=Decimal("1"),
        sequence=3,
    )
    db_session.add_all([sub_a1, sub_a2])
    db_session.commit()

    # Grandchild of Assembly A → Sub A1
    part_a1a = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="PRT-A1A",
        description="Part A1a",
        parent_bom_item_id=sub_a1.id,
        quantity=Decimal("4"),
        sequence=4,
    )
    db_session.add(part_a1a)
    db_session.commit()

    # Root: Assembly B (unconditional)
    asm_b = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="ASM-B",
        description="Assembly B",
        quantity=Decimal("1"),
        sequence=5,
    )
    db_session.add(asm_b)
    db_session.commit()

    sub_b1 = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="SUB-B1",
        description="Sub-assembly B1",
        parent_bom_item_id=asm_b.id,
        quantity=Decimal("1"),
        sequence=6,
    )
    db_session.add(sub_b1)
    db_session.commit()

    # Rule: Assembly A included only if toggle == ON
    rule_asm_a = BOMItemRule(
        bom_item_id=asm_a.id,
        entity_version_id=version.id,
        conditions={"criteria": [{"field_id": f_toggle.id, "operator": "EQUALS", "value": "ON"}]},
    )
    db_session.add(rule_asm_a)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {"toggle": f_toggle.id},
        "bom_items": {
            "asm_a": asm_a.id,
            "sub_a1": sub_a1.id,
            "sub_a2": sub_a2.id,
            "part_a1a": part_a1a.id,
            "asm_b": asm_b.id,
            "sub_b1": sub_b1.id,
        },
    }


def _collect_all_ids(items):
    """Recursively collect all bom_item_ids from a list of BOMLineItems."""
    ids = set()
    for item in items:
        ids.add(item.bom_item_id)
        ids.update(_collect_all_ids(item.children))
    return ids


class TestBOMTreePruning:
    """Tree pruning and nesting logic (TECHNICAL items only)."""

    def test_nested_items_parent_included(self, db_session, setup_bom_tree_scenario):
        """Parent included → children evaluated normally."""
        data = setup_bom_tree_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["toggle"], value="ON")],
            ),
        )

        assert response.bom is not None
        all_ids = _collect_all_ids(response.bom.technical)
        assert data["bom_items"]["asm_a"] in all_ids
        assert data["bom_items"]["sub_a1"] in all_ids
        assert data["bom_items"]["sub_a2"] in all_ids
        assert data["bom_items"]["part_a1a"] in all_ids

    def test_nested_items_parent_excluded(self, db_session, setup_bom_tree_scenario):
        """Parent excluded → entire subtree excluded."""
        data = setup_bom_tree_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["toggle"], value="OFF")],
            ),
        )

        assert response.bom is not None
        all_ids = _collect_all_ids(response.bom.technical)
        assert data["bom_items"]["asm_a"] not in all_ids
        assert data["bom_items"]["sub_a1"] not in all_ids
        assert data["bom_items"]["sub_a2"] not in all_ids
        assert data["bom_items"]["part_a1a"] not in all_ids

    def test_three_level_nesting(self, db_session, setup_bom_tree_scenario):
        """Grandparent → Parent → Child cascade works."""
        data = setup_bom_tree_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["toggle"], value="ON")],
            ),
        )

        assert response.bom is not None
        # Find Assembly A root
        asm_a = next(i for i in response.bom.technical if i.bom_item_id == data["bom_items"]["asm_a"])
        # Sub A1 is a child of Assembly A
        sub_a1 = next(c for c in asm_a.children if c.bom_item_id == data["bom_items"]["sub_a1"])
        # Part A1a is a child of Sub A1
        part_a1a = next(c for c in sub_a1.children if c.bom_item_id == data["bom_items"]["part_a1a"])
        assert part_a1a.part_number == "PRT-A1A"

    def test_sibling_independence(self, db_session, setup_bom_tree_scenario):
        """Excluding one sibling does not affect others."""
        data = setup_bom_tree_scenario
        service = RuleEngineService()

        # Assembly A excluded, Assembly B remains
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["toggle"], value="OFF")],
            ),
        )

        assert response.bom is not None
        all_ids = _collect_all_ids(response.bom.technical)
        assert data["bom_items"]["asm_b"] in all_ids
        assert data["bom_items"]["sub_b1"] in all_ids

    def test_child_excluded_independently(self, db_session):
        """Child's own conditions can exclude it even if parent is included."""
        entity = Entity(name="BOM Child Exclusion", description="Child exclusion")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        f_opt = Field(
            entity_version_id=version.id,
            name="option",
            label="Option",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        db_session.add(f_opt)
        db_session.commit()

        # Parent (unconditional)
        parent = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PARENT",
            quantity=Decimal("1"),
            sequence=1,
        )
        db_session.add(parent)
        db_session.commit()

        # Child (conditional: option == YES)
        child = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="CHILD",
            parent_bom_item_id=parent.id,
            quantity=Decimal("1"),
            sequence=2,
        )
        db_session.add(child)
        db_session.commit()

        rule_child = BOMItemRule(
            bom_item_id=child.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_opt.id, "operator": "EQUALS", "value": "YES"}]},
        )
        db_session.add(rule_child)
        db_session.commit()

        service = RuleEngineService()

        # Option != YES — parent included, child excluded
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[FieldInputState(field_id=f_opt.id, value="NO")],
            ),
        )

        assert response.bom is not None
        parent_item = next(i for i in response.bom.technical if i.bom_item_id == parent.id)
        assert len(parent_item.children) == 0

    def test_sequence_ordering_among_siblings(self, db_session, setup_bom_tree_scenario):
        """Items ordered by `sequence` within each level."""
        data = setup_bom_tree_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["toggle"], value="ON")],
            ),
        )

        assert response.bom is not None
        # Root-level technical items should be ordered by sequence
        root_ids = [i.bom_item_id for i in response.bom.technical]
        assert root_ids.index(data["bom_items"]["asm_a"]) < root_ids.index(data["bom_items"]["asm_b"])

        # Children of Assembly A ordered by sequence
        asm_a = next(i for i in response.bom.technical if i.bom_item_id == data["bom_items"]["asm_a"])
        child_ids = [c.bom_item_id for c in asm_a.children]
        assert child_ids.index(data["bom_items"]["sub_a1"]) < child_ids.index(data["bom_items"]["sub_a2"])

    def test_nested_technical_no_pricing(self, db_session, setup_bom_tree_scenario):
        """TECHNICAL tree items have no pricing (unit_price and line_total are null)."""
        data = setup_bom_tree_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["toggle"], value="ON")],
            ),
        )

        assert response.bom is not None
        all_items = []

        def collect(items):
            for item in items:
                all_items.append(item)
                collect(item.children)

        collect(response.bom.technical)
        for item in all_items:
            assert item.unit_price is None
            assert item.line_total is None
