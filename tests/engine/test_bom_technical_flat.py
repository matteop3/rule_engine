"""
Tests for `BOMOutput.technical_flat`: the alphabetically sorted, cascade-aggregated
view of the technical BOM.

Covers the empty case, single-level (flat == tree quantities), multi-level cascade
arithmetic, cross-branch aggregation of repeated parts, alphabetic ordering,
interaction with `quantity_from_field_id` and the hidden-field fallback to the
static quantity, and snapshot capture at finalization.
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

# ============================================================
# HELPERS
# ============================================================


@pytest.fixture(scope="function")
def published_version(db_session: Session) -> EntityVersion:
    entity = Entity(name="Technical Flat Test", description="technical_flat tests")
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


def _add_bom_item(
    db: Session,
    *,
    version: EntityVersion,
    part_number: str,
    quantity: Decimal,
    sequence: int,
    parent_bom_item_id: int | None = None,
    bom_type: BOMType = BOMType.TECHNICAL,
    quantity_from_field_id: int | None = None,
) -> BOMItem:
    bom = BOMItem(
        entity_version_id=version.id,
        bom_type=bom_type.value,
        part_number=part_number,
        quantity=quantity,
        sequence=sequence,
        parent_bom_item_id=parent_bom_item_id,
        quantity_from_field_id=quantity_from_field_id,
    )
    db.add(bom)
    db.commit()
    db.refresh(bom)
    return bom


def _calculate(db: Session, version: EntityVersion, current_state: list | None = None):
    service = RuleEngineService()
    return service.calculate_state(
        db,
        CalculationRequest(
            entity_id=version.entity_id,
            current_state=current_state or [],
        ),
    )


def _flat_dict(flat) -> dict[str, Decimal]:
    return {row.part_number: row.total_quantity for row in flat}


# ============================================================
# Empty / single-level
# ============================================================


def test_empty_technical_tree_yields_empty_flat(db_session: Session, published_version: EntityVersion):
    """A version with only COMMERCIAL items has an empty technical tree and empty flat."""
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="COMM-ONLY",
        quantity=Decimal("1"),
        sequence=1,
        bom_type=BOMType.COMMERCIAL,
    )

    response = _calculate(db_session, published_version)
    assert response.bom is not None
    assert response.bom.technical == []
    assert response.bom.technical_flat == []


def test_single_level_tree_flat_equals_tree_quantities(db_session: Session, published_version: EntityVersion):
    _add_bom_item(db_session, version=published_version, part_number="BOLT", quantity=Decimal("4"), sequence=1)
    _add_bom_item(db_session, version=published_version, part_number="NUT", quantity=Decimal("4"), sequence=2)

    response = _calculate(db_session, published_version)
    flat = _flat_dict(response.bom.technical_flat)
    assert flat == {"BOLT": Decimal("4"), "NUT": Decimal("4")}


# ============================================================
# Multi-level cascade
# ============================================================


def test_multi_level_cascade_arithmetic(db_session: Session, published_version: EntityVersion):
    """A(qty=2) → B(qty=4) yields flat [A: 2, B: 8]."""
    a = _add_bom_item(db_session, version=published_version, part_number="A", quantity=Decimal("2"), sequence=1)
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="B",
        quantity=Decimal("4"),
        sequence=2,
        parent_bom_item_id=a.id,
    )

    response = _calculate(db_session, published_version)
    flat = _flat_dict(response.bom.technical_flat)
    assert flat == {"A": Decimal("2"), "B": Decimal("8")}


def test_three_level_cascade_arithmetic(db_session: Session, published_version: EntityVersion):
    """A(qty=2) → B(qty=3) → C(qty=5) yields flat [A:2, B:6, C:30]."""
    a = _add_bom_item(db_session, version=published_version, part_number="A", quantity=Decimal("2"), sequence=1)
    b = _add_bom_item(
        db_session,
        version=published_version,
        part_number="B",
        quantity=Decimal("3"),
        sequence=2,
        parent_bom_item_id=a.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="C",
        quantity=Decimal("5"),
        sequence=3,
        parent_bom_item_id=b.id,
    )

    response = _calculate(db_session, published_version)
    flat = _flat_dict(response.bom.technical_flat)
    assert flat == {"A": Decimal("2"), "B": Decimal("6"), "C": Decimal("30")}


def test_same_part_in_multiple_branches_aggregates_with_cascade(db_session: Session, published_version: EntityVersion):
    """LEFT(qty=2)→SHARED(qty=3) and RIGHT(qty=4)→SHARED(qty=5): SHARED=2*3+4*5=26."""
    left = _add_bom_item(db_session, version=published_version, part_number="LEFT", quantity=Decimal("2"), sequence=1)
    right = _add_bom_item(db_session, version=published_version, part_number="RIGHT", quantity=Decimal("4"), sequence=2)
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="SHARED",
        quantity=Decimal("3"),
        sequence=3,
        parent_bom_item_id=left.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="SHARED",
        quantity=Decimal("5"),
        sequence=4,
        parent_bom_item_id=right.id,
    )

    response = _calculate(db_session, published_version)
    flat = _flat_dict(response.bom.technical_flat)
    assert flat == {
        "LEFT": Decimal("2"),
        "RIGHT": Decimal("4"),
        "SHARED": Decimal("26"),
    }


def test_flat_alphabetically_sorted_regardless_of_input_order(db_session: Session, published_version: EntityVersion):
    _add_bom_item(db_session, version=published_version, part_number="ZULU", quantity=Decimal("1"), sequence=10)
    _add_bom_item(db_session, version=published_version, part_number="ALPHA", quantity=Decimal("1"), sequence=1)
    _add_bom_item(db_session, version=published_version, part_number="MIKE", quantity=Decimal("1"), sequence=5)

    response = _calculate(db_session, published_version)
    parts = [row.part_number for row in response.bom.technical_flat]
    assert parts == ["ALPHA", "MIKE", "ZULU"]


def test_flat_carries_catalog_metadata(db_session: Session, published_version: EntityVersion):
    from tests.fixtures.catalog_items import create_catalog_item

    create_catalog_item(
        db_session,
        "WIDGET-01",
        description="Standard widget",
        category="Widgets",
        unit_of_measure="EA",
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="WIDGET-01",
        quantity=Decimal("3"),
        sequence=1,
    )

    response = _calculate(db_session, published_version)
    assert len(response.bom.technical_flat) == 1
    row = response.bom.technical_flat[0]
    assert row.part_number == "WIDGET-01"
    assert row.description == "Standard widget"
    assert row.category == "Widgets"
    assert row.unit_of_measure == "EA"
    assert row.total_quantity == Decimal("3")


# ============================================================
# Interaction with quantity_from_field_id
# ============================================================


def test_field_driven_root_quantity_propagates_through_cascade(db_session: Session, published_version: EntityVersion):
    """Resolved field quantity at the root cascades into descendants' totals."""
    qty_field = Field(
        entity_version_id=published_version.id,
        name="qty",
        label="Quantity",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=0,
    )
    db_session.add(qty_field)
    db_session.commit()

    a = _add_bom_item(
        db_session,
        version=published_version,
        part_number="A",
        quantity=Decimal("1"),
        sequence=1,
        quantity_from_field_id=qty_field.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="B",
        quantity=Decimal("4"),
        sequence=2,
        parent_bom_item_id=a.id,
    )

    response = _calculate(
        db_session,
        published_version,
        current_state=[FieldInputState(field_id=qty_field.id, value="3")],
    )
    flat = _flat_dict(response.bom.technical_flat)
    # A's resolved quantity is 3 (from field), B's static is 4 → flat: A=3, B=12.
    assert flat == {"A": Decimal("3"), "B": Decimal("12")}


def test_hidden_field_falls_back_to_static_quantity_in_flat(db_session: Session, published_version: EntityVersion):
    """A hidden NUMBER field returns no value; the static BOM quantity is used."""
    qty_field = Field(
        entity_version_id=published_version.id,
        name="qty",
        label="Quantity",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=False,
        is_hidden=True,
        step=1,
        sequence=0,
    )
    db_session.add(qty_field)
    db_session.commit()

    a = _add_bom_item(
        db_session,
        version=published_version,
        part_number="A",
        quantity=Decimal("7"),
        sequence=1,
        quantity_from_field_id=qty_field.id,
    )
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="B",
        quantity=Decimal("2"),
        sequence=2,
        parent_bom_item_id=a.id,
    )

    response = _calculate(db_session, published_version)
    flat = _flat_dict(response.bom.technical_flat)
    assert flat == {"A": Decimal("7"), "B": Decimal("14")}


# ============================================================
# Snapshot at finalization
# ============================================================


def test_finalized_snapshot_captures_technical_flat(
    db_session: Session,
    client,
    admin_headers,
    published_version: EntityVersion,
):
    """Finalizing a configuration freezes `technical_flat` into Configuration.snapshot."""
    import datetime as dt

    from app.models.domain import Configuration, PriceList

    a = _add_bom_item(db_session, version=published_version, part_number="ASSY", quantity=Decimal("2"), sequence=1)
    _add_bom_item(
        db_session,
        version=published_version,
        part_number="PART",
        quantity=Decimal("4"),
        sequence=2,
        parent_bom_item_id=a.id,
    )

    price_list = PriceList(
        name="Flat Snap PL",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(price_list)
    db_session.commit()

    create = client.post(
        "/configurations/",
        json={
            "entity_version_id": published_version.id,
            "name": "Flat Snap",
            "data": [],
            "price_list_id": price_list.id,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201
    config_id = create.json()["id"]

    finalize = client.post(f"/configurations/{config_id}/finalize", headers=admin_headers)
    assert finalize.status_code == 200

    db_session.expire_all()
    config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
    assert config.snapshot is not None
    assert "technical_flat" in config.snapshot["bom"]

    snap_flat_dict = {
        row["part_number"]: Decimal(str(row["total_quantity"])) for row in config.snapshot["bom"]["technical_flat"]
    }
    assert snap_flat_dict == {"ASSY": Decimal("2"), "PART": Decimal("8")}
