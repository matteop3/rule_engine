"""
Tests for BOM aggregation that re-parents children of merged sibling
representatives.

Scenario: two TECHNICAL siblings with the same `(part_number, parent,
bom_type)` get merged into one representative line. Their respective
children must follow the surviving representative and re-aggregate among
themselves so identical children fuse into a single line with summed
quantity. Without this re-parenting, orphaned children would surface as
spurious roots in the technical tree.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import (
    BOMItem,
    BOMType,
    Entity,
    EntityVersion,
    VersionStatus,
)
from app.schemas.engine import CalculationRequest
from app.services.rule_engine import RuleEngineService


@pytest.fixture(scope="function")
def published_version(db_session: Session) -> EntityVersion:
    entity = Entity(name="Sibling Merge Test", description="Sibling merge fix")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()
    return version


def _calculate(db: Session, version: EntityVersion):
    service = RuleEngineService()
    return service.calculate_state(
        db,
        CalculationRequest(entity_id=version.entity_id, current_state=[]),
    )


def _add_bom_item(
    db: Session,
    *,
    version: EntityVersion,
    part_number: str,
    quantity: Decimal,
    sequence: int,
    parent_bom_item_id: int | None = None,
    bom_type: BOMType = BOMType.TECHNICAL,
) -> BOMItem:
    bom = BOMItem(
        entity_version_id=version.id,
        bom_type=bom_type.value,
        part_number=part_number,
        quantity=quantity,
        sequence=sequence,
        parent_bom_item_id=parent_bom_item_id,
    )
    db.add(bom)
    db.commit()
    db.refresh(bom)
    return bom


def _flatten_technical(items, accumulator):
    for item in items:
        accumulator.append(item)
        _flatten_technical(item.children, accumulator)


# ============================================================
# Two TECHNICAL siblings, identical single child
# ============================================================


def test_two_siblings_with_identical_single_child(db_session: Session, published_version: EntityVersion):
    """ASSY-A appears twice; each has one BOLT child. Output: 1 ASSY (qty=2) → 1 BOLT (qty=2)."""
    a1 = _add_bom_item(db_session, version=published_version, part_number="ASSY-A", quantity=Decimal("1"), sequence=1)
    a2 = _add_bom_item(db_session, version=published_version, part_number="ASSY-A", quantity=Decimal("1"), sequence=2)
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="BOLT",
        quantity=Decimal("1"),
        sequence=3,
        parent_bom_item_id=a1.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="BOLT",
        quantity=Decimal("1"),
        sequence=4,
        parent_bom_item_id=a2.id,
    )

    response = _calculate(db_session, published_version)

    technical = response.bom.technical
    assert len(technical) == 1, f"Expected 1 technical root, got {len(technical)}"
    assy = technical[0]
    assert assy.part_number == "ASSY-A"
    assert assy.quantity == Decimal("2")
    assert len(assy.children) == 1
    bolt = assy.children[0]
    assert bolt.part_number == "BOLT"
    assert bolt.quantity == Decimal("2")
    assert bolt.children == []


# ============================================================
# Two TECHNICAL siblings, distinct single children
# ============================================================


def test_two_siblings_with_distinct_children(db_session: Session, published_version: EntityVersion):
    """ASSY-A appears twice; one has BOLT, the other NUT. Output: 1 ASSY (qty=2) with both children."""
    a1 = _add_bom_item(db_session, version=published_version, part_number="ASSY-A", quantity=Decimal("1"), sequence=1)
    a2 = _add_bom_item(db_session, version=published_version, part_number="ASSY-A", quantity=Decimal("1"), sequence=2)
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="BOLT",
        quantity=Decimal("3"),
        sequence=3,
        parent_bom_item_id=a1.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="NUT",
        quantity=Decimal("4"),
        sequence=4,
        parent_bom_item_id=a2.id,
    )

    response = _calculate(db_session, published_version)
    technical = response.bom.technical

    assert len(technical) == 1
    assy = technical[0]
    assert assy.part_number == "ASSY-A"
    assert assy.quantity == Decimal("2")

    children = sorted(assy.children, key=lambda c: c.part_number)
    assert [(c.part_number, c.quantity) for c in children] == [
        ("BOLT", Decimal("3")),
        ("NUT", Decimal("4")),
    ]
    assert all(c.children == [] for c in children)


# ============================================================
# Three siblings, mixed children
# ============================================================


def test_three_siblings_with_mixed_children(db_session: Session, published_version: EntityVersion):
    """Three ASSY-A siblings: two share a BOLT child, the third has a NUT."""
    a1 = _add_bom_item(db_session, version=published_version, part_number="ASSY-A", quantity=Decimal("1"), sequence=1)
    a2 = _add_bom_item(db_session, version=published_version, part_number="ASSY-A", quantity=Decimal("2"), sequence=2)
    a3 = _add_bom_item(db_session, version=published_version, part_number="ASSY-A", quantity=Decimal("3"), sequence=3)
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="BOLT",
        quantity=Decimal("5"),
        sequence=4,
        parent_bom_item_id=a1.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="BOLT",
        quantity=Decimal("7"),
        sequence=5,
        parent_bom_item_id=a2.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="NUT",
        quantity=Decimal("11"),
        sequence=6,
        parent_bom_item_id=a3.id,
    )

    response = _calculate(db_session, published_version)
    technical = response.bom.technical

    assert len(technical) == 1
    assy = technical[0]
    assert assy.part_number == "ASSY-A"
    assert assy.quantity == Decimal("6")

    children_by_part = {c.part_number: c for c in assy.children}
    assert set(children_by_part) == {"BOLT", "NUT"}
    assert children_by_part["BOLT"].quantity == Decimal("12")
    assert children_by_part["NUT"].quantity == Decimal("11")


# ============================================================
# Multi-level merging at depth ≥ 3
# ============================================================


def test_multi_level_merging_propagates_to_grandchildren(db_session: Session, published_version: EntityVersion):
    """
    Two ROOT siblings, each with a SUB child, each SUB has a LEAF.
    Top-level merge of ROOT siblings re-parents both SUBs under the surviving ROOT;
    second-level merge of the SUBs (same part_number) re-parents both LEAFs under
    the surviving SUB; and the LEAFs (same part_number) merge into one with
    summed quantities.
    """
    r1 = _add_bom_item(db_session, version=published_version, part_number="ROOT", quantity=Decimal("1"), sequence=1)
    r2 = _add_bom_item(db_session, version=published_version, part_number="ROOT", quantity=Decimal("1"), sequence=2)
    s1 = _add_bom_item(
        db_session,
        version=published_version,
        part_number="SUB",
        quantity=Decimal("1"),
        sequence=3,
        parent_bom_item_id=r1.id,
    )
    s2 = _add_bom_item(
        db_session,
        version=published_version,
        part_number="SUB",
        quantity=Decimal("1"),
        sequence=4,
        parent_bom_item_id=r2.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="LEAF",
        quantity=Decimal("2"),
        sequence=5,
        parent_bom_item_id=s1.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="LEAF",
        quantity=Decimal("3"),
        sequence=6,
        parent_bom_item_id=s2.id,
    )

    response = _calculate(db_session, published_version)
    technical = response.bom.technical

    assert len(technical) == 1
    root = technical[0]
    assert root.part_number == "ROOT"
    assert root.quantity == Decimal("2")

    assert len(root.children) == 1
    sub = root.children[0]
    assert sub.part_number == "SUB"
    assert sub.quantity == Decimal("2")

    assert len(sub.children) == 1
    leaf = sub.children[0]
    assert leaf.part_number == "LEAF"
    assert leaf.quantity == Decimal("5")
    assert leaf.children == []


# ============================================================
# Merged sibling does not orphan children
# ============================================================


def test_merged_siblings_do_not_orphan_children(db_session: Session, published_version: EntityVersion):
    """No spurious root entries appear: the merged siblings' children stay nested."""
    a1 = _add_bom_item(db_session, version=published_version, part_number="ASSY", quantity=Decimal("1"), sequence=1)
    a2 = _add_bom_item(db_session, version=published_version, part_number="ASSY", quantity=Decimal("1"), sequence=2)
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="BOLT",
        quantity=Decimal("1"),
        sequence=3,
        parent_bom_item_id=a1.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="WASHER",
        quantity=Decimal("1"),
        sequence=4,
        parent_bom_item_id=a2.id,
    )

    response = _calculate(db_session, published_version)
    technical = response.bom.technical

    root_part_numbers = [t.part_number for t in technical]
    assert root_part_numbers == ["ASSY"]

    all_lines: list = []
    _flatten_technical(technical, all_lines)
    parts_in_tree = sorted(line.part_number for line in all_lines)
    assert parts_in_tree == ["ASSY", "BOLT", "WASHER"]
