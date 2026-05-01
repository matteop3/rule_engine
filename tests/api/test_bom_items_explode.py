"""
Test suite for `POST /bom-items` with `explode_from_template=true`.

Covers happy-path materialization (single- and multi-level), the propagated
`suppress_child_explosion` opt-out, validation rejections (non-TECHNICAL
bom_type, missing template, OBSOLETE catalog entry, non-DRAFT version,
non-existent part), the operational limits (HTTP 413), RBAC, and the
unchanged behavior when the flag is `false`.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import (
    BOMItem,
    BOMType,
    CatalogItemStatus,
    EngineeringTemplateItem,
    EntityVersion,
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
    return edge


def _post_explode(
    client: TestClient,
    headers: dict,
    *,
    entity_version_id: int,
    part_number: str,
    quantity: str = "1",
    sequence: int = 0,
    bom_type: str = "TECHNICAL",
    parent_bom_item_id: int | None = None,
    quantity_from_field_id: int | None = None,
):
    payload: dict = {
        "entity_version_id": entity_version_id,
        "part_number": part_number,
        "bom_type": bom_type,
        "quantity": quantity,
        "sequence": sequence,
        "explode_from_template": True,
    }
    if parent_bom_item_id is not None:
        payload["parent_bom_item_id"] = parent_bom_item_id
    if quantity_from_field_id is not None:
        payload["quantity_from_field_id"] = quantity_from_field_id
    return client.post("/bom-items/", json=payload, headers=headers)


# ============================================================
# Happy path
# ============================================================


def test_explode_single_level_returns_nested_response(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    _add_template_edge(db_session, "KIT", "BOLT", quantity=Decimal("4"), sequence=0)
    _add_template_edge(db_session, "KIT", "NUT", quantity=Decimal("4"), sequence=1)

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="KIT",
        quantity="2",
        sequence=10,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["part_number"] == "KIT"
    assert Decimal(body["quantity"]) == Decimal("2")
    assert body["sequence"] == 10
    assert body["bom_type"] == "TECHNICAL"
    assert body["suppress_auto_explode"] is False

    children = body["children"]
    assert sorted(c["part_number"] for c in children) == ["BOLT", "NUT"]
    for c in children:
        assert Decimal(c["quantity"]) == Decimal("4")
        assert c["children"] == []
        assert c["bom_type"] == "TECHNICAL"


def test_explode_multi_level_returns_full_subtree(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    _add_template_edge(db_session, "ASSY", "SUB", quantity=Decimal("2"))
    _add_template_edge(db_session, "SUB", "BOLT", quantity=Decimal("3"))
    _add_template_edge(db_session, "BOLT", "WASHER", quantity=Decimal("1"))

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="ASSY",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["part_number"] == "ASSY"
    assert len(body["children"]) == 1

    sub = body["children"][0]
    assert sub["part_number"] == "SUB"
    bolt = sub["children"][0]
    assert bolt["part_number"] == "BOLT"
    washer = bolt["children"][0]
    assert washer["part_number"] == "WASHER"
    assert washer["children"] == []


def test_explode_persists_full_subtree_in_database(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    _add_template_edge(db_session, "KIT", "BOLT")
    _add_template_edge(db_session, "KIT", "NUT")

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="KIT",
    )
    assert response.status_code == 201

    rows = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft_version.id).all()
    assert sorted(r.part_number for r in rows) == ["BOLT", "KIT", "NUT"]


def test_explode_propagates_suppress_child_explosion(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    _add_template_edge(
        db_session,
        "ASSY",
        "SUB",
        quantity=Decimal("1"),
        suppress_child_explosion=True,
    )
    _add_template_edge(db_session, "SUB", "DEEP", quantity=Decimal("9"))

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="ASSY",
    )

    assert response.status_code == 201
    body = response.json()
    sub = body["children"][0]
    assert sub["part_number"] == "SUB"
    assert sub["suppress_auto_explode"] is True
    assert sub["children"] == []


def test_explode_under_existing_parent_bom_item(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
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

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="KIT",
        parent_bom_item_id=parent.id,
    )

    assert response.status_code == 201
    assert response.json()["parent_bom_item_id"] == parent.id


# ============================================================
# Validation rejections
# ============================================================


def test_explode_with_commercial_bom_type_returns_422(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    _add_template_edge(db_session, "KIT", "BOLT")

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="KIT",
        bom_type="COMMERCIAL",
    )

    assert response.status_code == 422
    assert "TECHNICAL" in response.json()["detail"]


def test_explode_part_without_template_returns_422(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    create_catalog_item(db_session, "LEAF-ONLY")

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="LEAF-ONLY",
    )

    assert response.status_code == 422
    assert "engineering template" in response.json()["detail"]


def test_explode_obsolete_root_returns_409(
    client: TestClient,
    admin_headers,
    db_session,
    draft_version: EntityVersion,
    strict_catalog_validation,
):
    """An OBSOLETE root is rejected by the existing catalog reference validator."""
    create_catalog_item(db_session, "OLD-KIT", status=CatalogItemStatus.OBSOLETE)
    create_catalog_item(db_session, "BOLT")
    db_session.add(
        EngineeringTemplateItem(
            parent_part_number="OLD-KIT",
            child_part_number="BOLT",
            quantity=Decimal("1"),
        )
    )
    db_session.commit()

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="OLD-KIT",
    )

    assert response.status_code == 409


def test_explode_obsolete_descendant_returns_409_with_payload(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    create_catalog_item(db_session, "ASSY")
    create_catalog_item(db_session, "OBS-1", status=CatalogItemStatus.OBSOLETE)
    create_catalog_item(db_session, "OBS-2", status=CatalogItemStatus.OBSOLETE)
    create_catalog_item(db_session, "GOOD")
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

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="ASSY",
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert sorted(detail["obsolete_parts"]) == ["OBS-1", "OBS-2"]
    assert "OBSOLETE" in detail["message"]

    persisted = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft_version.id).count()
    assert persisted == 0


def test_explode_node_limit_returns_413_with_payload(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    admin_headers,
    db_session,
    draft_version: EntityVersion,
):
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_NODES", 2)

    _add_template_edge(db_session, "KIT", "BOLT")
    _add_template_edge(db_session, "KIT", "NUT")

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="KIT",
    )

    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["limit"] == "nodes"
    assert detail["max"] == 2
    assert detail["reached"] >= 3

    persisted = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft_version.id).count()
    assert persisted == 0


def test_explode_depth_limit_returns_413_with_payload(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    admin_headers,
    db_session,
    draft_version: EntityVersion,
):
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_DEPTH", 2)
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_NODES", 100)

    # P0 -> P1 -> P2 -> P3 -> P4 (depth 4)
    parts = [f"P{i}" for i in range(5)]
    for p in parts:
        ensure_catalog_entry(db_session, p)
    for parent, child in zip(parts, parts[1:], strict=False):
        db_session.add(
            EngineeringTemplateItem(
                parent_part_number=parent,
                child_part_number=child,
                quantity=Decimal("1"),
            )
        )
    db_session.commit()

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="P0",
    )

    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["limit"] == "depth"
    assert detail["max"] == 2
    assert detail["reached"] >= 3


def test_explode_against_published_version_returns_409(
    client: TestClient,
    admin_headers,
    db_session,
    published_version: EntityVersion,
):
    _add_template_edge(db_session, "KIT", "BOLT")

    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=published_version.id,
        part_number="KIT",
    )
    assert response.status_code == 409


def test_explode_unknown_part_returns_409(
    client: TestClient,
    admin_headers,
    draft_version: EntityVersion,
    strict_catalog_validation,
):
    response = _post_explode(
        client,
        admin_headers,
        entity_version_id=draft_version.id,
        part_number="GHOST-PART",
    )
    assert response.status_code == 409


# ============================================================
# RBAC
# ============================================================


class TestExplodeRBAC:
    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 201),
            ("author_headers", 201),
            ("user_headers", 403),
        ],
    )
    def test_rbac(
        self,
        client: TestClient,
        db_session,
        draft_version: EntityVersion,
        headers_fixture,
        expected_status,
        request,
    ):
        _add_template_edge(db_session, "KIT", "BOLT")
        headers = request.getfixturevalue(headers_fixture)

        response = _post_explode(
            client,
            headers,
            entity_version_id=draft_version.id,
            part_number="KIT",
        )
        assert response.status_code == expected_status


# ============================================================
# Backward compatibility (flag absent or false)
# ============================================================


def test_create_without_flag_behaves_unchanged(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    """A regular POST without `explode_from_template` does not materialize children."""
    create_catalog_item(db_session, "PLAIN-PART")
    response = client.post(
        "/bom-items/",
        json={
            "entity_version_id": draft_version.id,
            "part_number": "PLAIN-PART",
            "bom_type": "TECHNICAL",
            "quantity": "1",
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["part_number"] == "PLAIN-PART"
    assert body["children"] == []

    rows = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft_version.id).count()
    assert rows == 1


def test_explode_false_behaves_unchanged_even_if_template_exists(
    client: TestClient, admin_headers, db_session, draft_version: EntityVersion
):
    """`explode_from_template=false` skips materialization regardless of template state."""
    _add_template_edge(db_session, "KIT", "BOLT")

    response = client.post(
        "/bom-items/",
        json={
            "entity_version_id": draft_version.id,
            "part_number": "KIT",
            "bom_type": "TECHNICAL",
            "quantity": "1",
            "explode_from_template": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["children"] == []

    rows = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft_version.id).all()
    assert [r.part_number for r in rows] == ["KIT"]
