"""
Unit tests for `explode` and `materialize` in the engineering template
service. Covers single-level and multi-level templates, the
`suppress_child_explosion` propagation, depth and node-count limits,
OBSOLETE rejection, and idempotency of repeated materialization calls.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import (
    BOMItem,
    BOMType,
    CatalogItemStatus,
    EngineeringTemplateItem,
    EntityVersion,
)
from app.services.engineering_template import (
    ExplosionContainsObsoletePartsError,
    ExplosionLimitExceededError,
    explode,
    materialize,
)
from tests.fixtures.catalog_items import create_catalog_item, ensure_catalog_entry

# ============================================================
# HELPERS
# ============================================================


def _add_template_edge(
    db: Session,
    parent: str,
    child: str,
    *,
    quantity: Decimal = Decimal("1"),
    sequence: int = 0,
    suppress_child_explosion: bool = False,
) -> EngineeringTemplateItem:
    ensure_catalog_entry(db, parent)
    ensure_catalog_entry(db, child)
    edge = EngineeringTemplateItem(
        parent_part_number=parent,
        child_part_number=child,
        quantity=quantity,
        sequence=sequence,
        suppress_child_explosion=suppress_child_explosion,
    )
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


def _build_chain(db: Session, length: int, prefix: str = "P") -> list[str]:
    """Create a deep chain P0 -> P1 -> ... -> P{length-1} (length-1 edges)."""
    parts = [f"{prefix}{i}" for i in range(length)]
    for part in parts:
        ensure_catalog_entry(db, part)
    for parent, child in zip(parts, parts[1:], strict=False):
        edge = EngineeringTemplateItem(
            parent_part_number=parent,
            child_part_number=child,
            quantity=Decimal("1"),
        )
        db.add(edge)
    db.commit()
    return parts


# ============================================================
# explode
# ============================================================


def test_explode_leaf_part_returns_single_root(db_session: Session) -> None:
    create_catalog_item(db_session, "LEAF")

    result = explode(db_session, "LEAF")

    assert result.tree.part_number == "LEAF"
    assert result.tree.quantity == Decimal("1")
    assert result.tree.sequence == 0
    assert result.tree.suppress_auto_explode is False
    assert result.tree.children == []
    assert result.total_nodes == 1
    assert result.max_depth_reached == 0


def test_explode_single_level_template(db_session: Session) -> None:
    _add_template_edge(db_session, "KIT", "BOLT", quantity=Decimal("4"), sequence=0)
    _add_template_edge(db_session, "KIT", "NUT", quantity=Decimal("4"), sequence=1)

    result = explode(db_session, "KIT")

    assert result.tree.part_number == "KIT"
    assert [c.part_number for c in result.tree.children] == ["BOLT", "NUT"]
    assert [c.quantity for c in result.tree.children] == [Decimal("4"), Decimal("4")]
    assert result.total_nodes == 3
    assert result.max_depth_reached == 1


def test_explode_multi_level_recursion(db_session: Session) -> None:
    _add_template_edge(db_session, "ASSY", "SUB", quantity=Decimal("2"))
    _add_template_edge(db_session, "SUB", "BOLT", quantity=Decimal("3"))
    _add_template_edge(db_session, "BOLT", "WASHER", quantity=Decimal("1"))

    result = explode(db_session, "ASSY")

    assert result.total_nodes == 4
    assert result.max_depth_reached == 3

    sub = result.tree.children[0]
    assert sub.part_number == "SUB"
    assert sub.quantity == Decimal("2")

    bolt = sub.children[0]
    assert bolt.part_number == "BOLT"
    assert bolt.quantity == Decimal("3")

    washer = bolt.children[0]
    assert washer.part_number == "WASHER"
    assert washer.children == []


def test_explode_children_ordered_by_sequence(db_session: Session) -> None:
    _add_template_edge(db_session, "KIT", "PART-Z", sequence=2)
    _add_template_edge(db_session, "KIT", "PART-A", sequence=0)
    _add_template_edge(db_session, "KIT", "PART-M", sequence=1)

    result = explode(db_session, "KIT")

    assert [c.part_number for c in result.tree.children] == ["PART-A", "PART-M", "PART-Z"]


def test_explode_suppress_child_explosion_makes_leaf(db_session: Session) -> None:
    """A child with suppress_child_explosion=True is a leaf even if it has its own template."""
    _add_template_edge(db_session, "ASSY", "SUB", quantity=Decimal("1"), suppress_child_explosion=True)
    # SUB has its own template that should NOT be visited.
    _add_template_edge(db_session, "SUB", "DEEP", quantity=Decimal("9"))

    result = explode(db_session, "ASSY")

    sub = result.tree.children[0]
    assert sub.part_number == "SUB"
    assert sub.suppress_auto_explode is True
    assert sub.children == []
    assert result.total_nodes == 2
    assert result.max_depth_reached == 1


def test_explode_diamond_visits_shared_part_twice(db_session: Session) -> None:
    """A part reachable through multiple branches appears once per branch (no dedup)."""
    _add_template_edge(db_session, "ROOT", "LEFT")
    _add_template_edge(db_session, "ROOT", "RIGHT")
    _add_template_edge(db_session, "LEFT", "SHARED", quantity=Decimal("2"))
    _add_template_edge(db_session, "RIGHT", "SHARED", quantity=Decimal("3"))

    result = explode(db_session, "ROOT")

    left, right = result.tree.children
    assert [c.part_number for c in left.children] == ["SHARED"]
    assert [c.part_number for c in right.children] == ["SHARED"]
    assert left.children[0].quantity == Decimal("2")
    assert right.children[0].quantity == Decimal("3")
    assert result.total_nodes == 5  # ROOT + LEFT + RIGHT + 2x SHARED


# ============================================================
# explode — limits
# ============================================================


def test_explode_depth_limit_raises_with_payload(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_DEPTH", 3)
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_NODES", 1000)

    _build_chain(db_session, length=5)  # P0..P4 -> depth 4 from root

    with pytest.raises(ExplosionLimitExceededError) as exc:
        explode(db_session, "P0")

    assert exc.value.limit_name == "depth"
    assert exc.value.max_value == 3
    assert exc.value.reached == 4


def test_explode_node_count_limit_raises_with_payload(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_DEPTH", 100)
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_NODES", 3)

    # 5 children under one root = 6 total nodes > 3
    ensure_catalog_entry(db_session, "ROOT")
    for i in range(5):
        _add_template_edge(db_session, "ROOT", f"C{i}", sequence=i)

    with pytest.raises(ExplosionLimitExceededError) as exc:
        explode(db_session, "ROOT")

    assert exc.value.limit_name == "nodes"
    assert exc.value.max_value == 3
    assert exc.value.reached == 4


def test_explode_within_limits_succeeds(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> None:
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_DEPTH", 2)
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_NODES", 5)

    _add_template_edge(db_session, "ROOT", "LEAF1")
    _add_template_edge(db_session, "ROOT", "LEAF2")

    result = explode(db_session, "ROOT")
    assert result.total_nodes == 3
    assert result.max_depth_reached == 1


# ============================================================
# explode — OBSOLETE rejection
# ============================================================


def test_explode_root_obsolete_raises(db_session: Session) -> None:
    create_catalog_item(db_session, "OLD-ROOT", status=CatalogItemStatus.OBSOLETE)

    with pytest.raises(ExplosionContainsObsoletePartsError) as exc:
        explode(db_session, "OLD-ROOT")

    assert exc.value.obsolete_parts == ["OLD-ROOT"]


def test_explode_descendant_obsolete_raises(db_session: Session) -> None:
    create_catalog_item(db_session, "ASSY")
    create_catalog_item(db_session, "OLD-CHILD", status=CatalogItemStatus.OBSOLETE)
    db_session.add(
        EngineeringTemplateItem(
            parent_part_number="ASSY",
            child_part_number="OLD-CHILD",
            quantity=Decimal("1"),
        )
    )
    db_session.commit()

    with pytest.raises(ExplosionContainsObsoletePartsError) as exc:
        explode(db_session, "ASSY")

    assert exc.value.obsolete_parts == ["OLD-CHILD"]


def test_explode_collects_all_obsolete_parts(db_session: Session) -> None:
    """Every OBSOLETE part across the expansion is enumerated, not just the first."""
    create_catalog_item(db_session, "ASSY")
    create_catalog_item(db_session, "OBS-1", status=CatalogItemStatus.OBSOLETE)
    create_catalog_item(db_session, "GOOD")
    create_catalog_item(db_session, "OBS-2", status=CatalogItemStatus.OBSOLETE)
    db_session.add_all(
        [
            EngineeringTemplateItem(
                parent_part_number="ASSY", child_part_number="OBS-1", quantity=Decimal("1"), sequence=0
            ),
            EngineeringTemplateItem(
                parent_part_number="ASSY", child_part_number="GOOD", quantity=Decimal("1"), sequence=1
            ),
            EngineeringTemplateItem(parent_part_number="GOOD", child_part_number="OBS-2", quantity=Decimal("1")),
        ]
    )
    db_session.commit()

    with pytest.raises(ExplosionContainsObsoletePartsError) as exc:
        explode(db_session, "ASSY")

    assert sorted(exc.value.obsolete_parts) == ["OBS-1", "OBS-2"]


def test_explode_obsolete_part_dedup_in_listing(db_session: Session) -> None:
    """A single OBSOLETE part appearing in multiple branches is listed once."""
    create_catalog_item(db_session, "ROOT")
    create_catalog_item(db_session, "LEFT")
    create_catalog_item(db_session, "RIGHT")
    create_catalog_item(db_session, "OLD", status=CatalogItemStatus.OBSOLETE)
    db_session.add_all(
        [
            EngineeringTemplateItem(
                parent_part_number="ROOT", child_part_number="LEFT", quantity=Decimal("1"), sequence=0
            ),
            EngineeringTemplateItem(
                parent_part_number="ROOT", child_part_number="RIGHT", quantity=Decimal("1"), sequence=1
            ),
            EngineeringTemplateItem(parent_part_number="LEFT", child_part_number="OLD", quantity=Decimal("1")),
            EngineeringTemplateItem(parent_part_number="RIGHT", child_part_number="OLD", quantity=Decimal("1")),
        ]
    )
    db_session.commit()

    with pytest.raises(ExplosionContainsObsoletePartsError) as exc:
        explode(db_session, "ROOT")

    assert exc.value.obsolete_parts == ["OLD"]


# ============================================================
# materialize
# ============================================================


def test_materialize_single_level_template(db_session: Session, draft_version: EntityVersion) -> None:
    _add_template_edge(db_session, "KIT", "BOLT", quantity=Decimal("4"), sequence=0)
    _add_template_edge(db_session, "KIT", "NUT", quantity=Decimal("4"), sequence=1)

    root = materialize(
        db_session,
        entity_version_id=draft_version.id,
        root_part_number="KIT",
        parent_bom_item_id=None,
        root_quantity=Decimal("2"),
        root_quantity_from_field_id=None,
        root_sequence=10,
        root_suppress_auto_explode=False,
    )
    db_session.commit()

    assert root.part_number == "KIT"
    assert root.quantity == Decimal("2")
    assert root.sequence == 10
    assert root.bom_type == BOMType.TECHNICAL.value
    assert root.parent_bom_item_id is None
    assert root.suppress_auto_explode is False

    children = db_session.query(BOMItem).filter(BOMItem.parent_bom_item_id == root.id).order_by(BOMItem.sequence).all()
    assert [c.part_number for c in children] == ["BOLT", "NUT"]
    assert [c.quantity for c in children] == [Decimal("4"), Decimal("4")]
    assert all(c.bom_type == BOMType.TECHNICAL.value for c in children)
    assert all(c.suppress_auto_explode is False for c in children)


def test_materialize_multi_level_recursion(db_session: Session, draft_version: EntityVersion) -> None:
    _add_template_edge(db_session, "ASSY", "SUB", quantity=Decimal("2"))
    _add_template_edge(db_session, "SUB", "BOLT", quantity=Decimal("3"))
    _add_template_edge(db_session, "BOLT", "WASHER", quantity=Decimal("1"))

    root = materialize(
        db_session,
        entity_version_id=draft_version.id,
        root_part_number="ASSY",
        parent_bom_item_id=None,
        root_quantity=Decimal("1"),
        root_quantity_from_field_id=None,
        root_sequence=0,
        root_suppress_auto_explode=False,
    )
    db_session.commit()

    all_items = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft_version.id).all()
    assert len(all_items) == 4

    by_part = {item.part_number: item for item in all_items}
    assert by_part["ASSY"].parent_bom_item_id is None
    assert by_part["SUB"].parent_bom_item_id == by_part["ASSY"].id
    assert by_part["BOLT"].parent_bom_item_id == by_part["SUB"].id
    assert by_part["WASHER"].parent_bom_item_id == by_part["BOLT"].id

    # Stoichiometric per-edge quantities (Section 8.2): no cascade multiplication here.
    assert by_part["SUB"].quantity == Decimal("2")
    assert by_part["BOLT"].quantity == Decimal("3")
    assert by_part["WASHER"].quantity == Decimal("1")
    assert root.id == by_part["ASSY"].id


def test_materialize_propagates_suppress_child_explosion(db_session: Session, draft_version: EntityVersion) -> None:
    """A template edge with suppress_child_explosion makes the child a suppressed leaf."""
    _add_template_edge(
        db_session,
        "ASSY",
        "SUB",
        quantity=Decimal("1"),
        suppress_child_explosion=True,
    )
    _add_template_edge(db_session, "SUB", "DEEP", quantity=Decimal("99"))

    materialize(
        db_session,
        entity_version_id=draft_version.id,
        root_part_number="ASSY",
        parent_bom_item_id=None,
        root_quantity=Decimal("1"),
        root_quantity_from_field_id=None,
        root_sequence=0,
        root_suppress_auto_explode=False,
    )
    db_session.commit()

    sub = (
        db_session.query(BOMItem)
        .filter(BOMItem.entity_version_id == draft_version.id, BOMItem.part_number == "SUB")
        .one()
    )
    assert sub.suppress_auto_explode is True

    deep_count = (
        db_session.query(BOMItem)
        .filter(BOMItem.entity_version_id == draft_version.id, BOMItem.part_number == "DEEP")
        .count()
    )
    assert deep_count == 0


def test_materialize_root_quantity_from_field_is_persisted(
    db_session: Session, draft_version: EntityVersion, draft_field
) -> None:
    _add_template_edge(db_session, "KIT", "BOLT", quantity=Decimal("1"))

    root = materialize(
        db_session,
        entity_version_id=draft_version.id,
        root_part_number="KIT",
        parent_bom_item_id=None,
        root_quantity=Decimal("1"),
        root_quantity_from_field_id=draft_field.id,
        root_sequence=0,
        root_suppress_auto_explode=False,
    )
    db_session.commit()

    assert root.quantity_from_field_id == draft_field.id

    bolt = (
        db_session.query(BOMItem)
        .filter(BOMItem.entity_version_id == draft_version.id, BOMItem.part_number == "BOLT")
        .one()
    )
    assert bolt.quantity_from_field_id is None


def test_materialize_under_existing_parent(db_session: Session, draft_version: EntityVersion) -> None:
    """Setting parent_bom_item_id nests the new sub-tree under an existing BOMItem."""
    create_catalog_item(db_session, "TOP")
    parent = BOMItem(
        entity_version_id=draft_version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="TOP",
        quantity=Decimal("1"),
    )
    db_session.add(parent)
    db_session.commit()

    _add_template_edge(db_session, "KIT", "BOLT")

    root = materialize(
        db_session,
        entity_version_id=draft_version.id,
        root_part_number="KIT",
        parent_bom_item_id=parent.id,
        root_quantity=Decimal("1"),
        root_quantity_from_field_id=None,
        root_sequence=0,
        root_suppress_auto_explode=False,
    )
    db_session.commit()

    assert root.parent_bom_item_id == parent.id


def test_materialize_idempotency_creates_parallel_subtrees(db_session: Session, draft_version: EntityVersion) -> None:
    """Calling materialize twice yields two independent sub-trees; no automatic dedup."""
    _add_template_edge(db_session, "KIT", "BOLT", quantity=Decimal("4"))

    root_a = materialize(
        db_session,
        entity_version_id=draft_version.id,
        root_part_number="KIT",
        parent_bom_item_id=None,
        root_quantity=Decimal("1"),
        root_quantity_from_field_id=None,
        root_sequence=0,
        root_suppress_auto_explode=False,
    )
    root_b = materialize(
        db_session,
        entity_version_id=draft_version.id,
        root_part_number="KIT",
        parent_bom_item_id=None,
        root_quantity=Decimal("1"),
        root_quantity_from_field_id=None,
        root_sequence=1,
        root_suppress_auto_explode=False,
    )
    db_session.commit()

    assert root_a.id != root_b.id
    kits = (
        db_session.query(BOMItem)
        .filter(BOMItem.entity_version_id == draft_version.id, BOMItem.part_number == "KIT")
        .count()
    )
    bolts = (
        db_session.query(BOMItem)
        .filter(BOMItem.entity_version_id == draft_version.id, BOMItem.part_number == "BOLT")
        .count()
    )
    assert kits == 2
    assert bolts == 2


def test_materialize_obsolete_descendant_inserts_nothing(db_session: Session, draft_version: EntityVersion) -> None:
    """If the explosion contains an OBSOLETE part, no BOMItem rows are persisted."""
    create_catalog_item(db_session, "ASSY")
    create_catalog_item(db_session, "OBS", status=CatalogItemStatus.OBSOLETE)
    db_session.add(
        EngineeringTemplateItem(
            parent_part_number="ASSY",
            child_part_number="OBS",
            quantity=Decimal("1"),
        )
    )
    db_session.commit()

    with pytest.raises(ExplosionContainsObsoletePartsError):
        materialize(
            db_session,
            entity_version_id=draft_version.id,
            root_part_number="ASSY",
            parent_bom_item_id=None,
            root_quantity=Decimal("1"),
            root_quantity_from_field_id=None,
            root_sequence=0,
            root_suppress_auto_explode=False,
        )

    db_session.rollback()
    count = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft_version.id).count()
    assert count == 0


def test_materialize_node_limit_inserts_nothing(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    draft_version: EntityVersion,
) -> None:
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_NODES", 2)

    _add_template_edge(db_session, "KIT", "BOLT")
    _add_template_edge(db_session, "KIT", "NUT")

    with pytest.raises(ExplosionLimitExceededError) as exc:
        materialize(
            db_session,
            entity_version_id=draft_version.id,
            root_part_number="KIT",
            parent_bom_item_id=None,
            root_quantity=Decimal("1"),
            root_quantity_from_field_id=None,
            root_sequence=0,
            root_suppress_auto_explode=False,
        )

    assert exc.value.limit_name == "nodes"

    db_session.rollback()
    count = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft_version.id).count()
    assert count == 0
