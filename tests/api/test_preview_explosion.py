"""
Test suite for `GET /catalog-items/{part_number}/preview-explosion`.

Covers RBAC, the leaf-only case, single- and multi-level templates,
diamond aggregation in the flat list, suppression behavior, the operational
limits (HTTP 413), OBSOLETE rejection (HTTP 409), 404 on unknown part, and
the catalog metadata join on both `tree` and `flat`.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import CatalogItemStatus, EngineeringTemplateItem
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


# ============================================================
# RBAC
# ============================================================


class TestPreviewExplosionRBAC:
    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 200),
        ],
    )
    def test_rbac_any_authenticated(
        self,
        client: TestClient,
        db_session,
        headers_fixture,
        expected_status,
        request,
    ):
        create_catalog_item(db_session, "PART-A")
        headers = request.getfixturevalue(headers_fixture)
        response = client.get("/catalog-items/PART-A/preview-explosion", headers=headers)
        assert response.status_code == expected_status

    def test_unauthenticated_rejected(self, client: TestClient, db_session):
        create_catalog_item(db_session, "PART-A")
        response = client.get("/catalog-items/PART-A/preview-explosion")
        assert response.status_code == 401


# ============================================================
# 404
# ============================================================


def test_preview_unknown_part_returns_404(client: TestClient, admin_headers):
    response = client.get("/catalog-items/GHOST/preview-explosion", headers=admin_headers)
    assert response.status_code == 404


# ============================================================
# Leaf-only / no template
# ============================================================


def test_preview_leaf_only_returns_root_with_empty_flat(client: TestClient, admin_headers, db_session):
    create_catalog_item(db_session, "BOLT-01", description="Single bolt", category="Fasteners")

    response = client.get("/catalog-items/BOLT-01/preview-explosion", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_nodes"] == 1
    assert body["max_depth_reached"] == 0
    assert body["flat"] == []

    assert len(body["tree"]) == 1
    root = body["tree"][0]
    assert root["part_number"] == "BOLT-01"
    assert Decimal(root["quantity"]) == Decimal("1")
    assert root["children"] == []
    assert root["description"] == "Single bolt"
    assert root["category"] == "Fasteners"
    assert root["unit_of_measure"] == "PC"


# ============================================================
# Single-level template
# ============================================================


def test_preview_single_level_returns_correct_tree_and_flat(client: TestClient, admin_headers, db_session):
    create_catalog_item(db_session, "KIT", description="Kit assembly")
    create_catalog_item(db_session, "BOLT", description="Bolt M6")
    create_catalog_item(db_session, "NUT", description="Nut M6")
    db_session.add_all(
        [
            EngineeringTemplateItem(
                parent_part_number="KIT",
                child_part_number="BOLT",
                quantity=Decimal("4"),
                sequence=0,
            ),
            EngineeringTemplateItem(
                parent_part_number="KIT",
                child_part_number="NUT",
                quantity=Decimal("4"),
                sequence=1,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/catalog-items/KIT/preview-explosion", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_nodes"] == 3
    assert body["max_depth_reached"] == 1

    root = body["tree"][0]
    children = [(c["part_number"], Decimal(c["quantity"])) for c in root["children"]]
    assert children == [("BOLT", Decimal("4")), ("NUT", Decimal("4"))]

    flat = {row["part_number"]: Decimal(row["total_quantity"]) for row in body["flat"]}
    assert flat == {"BOLT": Decimal("4"), "NUT": Decimal("4")}


# ============================================================
# Multi-level cascade in flat list
# ============================================================


def test_preview_multi_level_cascade_arithmetic_in_flat(client: TestClient, admin_headers, db_session):
    """A→B×2 with B→C×3: flat shows B=2, C=6 (cascade)."""
    _add_template_edge(db_session, "A", "B", quantity=Decimal("2"))
    _add_template_edge(db_session, "B", "C", quantity=Decimal("3"))

    response = client.get("/catalog-items/A/preview-explosion", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_nodes"] == 3
    assert body["max_depth_reached"] == 2

    flat = {row["part_number"]: Decimal(row["total_quantity"]) for row in body["flat"]}
    assert flat == {"B": Decimal("2"), "C": Decimal("6")}


def test_preview_flat_alphabetically_sorted(client: TestClient, admin_headers, db_session):
    _add_template_edge(db_session, "ROOT", "ZULU", quantity=Decimal("1"))
    _add_template_edge(db_session, "ROOT", "ALPHA", quantity=Decimal("1"))
    _add_template_edge(db_session, "ROOT", "MIKE", quantity=Decimal("1"))

    response = client.get("/catalog-items/ROOT/preview-explosion", headers=admin_headers)
    assert response.status_code == 200
    parts = [row["part_number"] for row in response.json()["flat"]]
    assert parts == ["ALPHA", "MIKE", "ZULU"]


def test_preview_diamond_aggregates_shared_part_in_flat(client: TestClient, admin_headers, db_session):
    """SHARED appears via two branches with different quantities; flat sums them."""
    _add_template_edge(db_session, "ROOT", "LEFT", quantity=Decimal("1"))
    _add_template_edge(db_session, "ROOT", "RIGHT", quantity=Decimal("1"))
    _add_template_edge(db_session, "LEFT", "SHARED", quantity=Decimal("2"))
    _add_template_edge(db_session, "RIGHT", "SHARED", quantity=Decimal("3"))

    response = client.get("/catalog-items/ROOT/preview-explosion", headers=admin_headers)
    assert response.status_code == 200
    flat = {row["part_number"]: Decimal(row["total_quantity"]) for row in response.json()["flat"]}
    assert flat == {
        "LEFT": Decimal("1"),
        "RIGHT": Decimal("1"),
        "SHARED": Decimal("5"),
    }


# ============================================================
# Suppression
# ============================================================


def test_preview_suppress_child_explosion_makes_leaf(client: TestClient, admin_headers, db_session):
    _add_template_edge(
        db_session,
        "ASSY",
        "SUB",
        quantity=Decimal("1"),
        suppress_child_explosion=True,
    )
    _add_template_edge(db_session, "SUB", "DEEP", quantity=Decimal("99"))

    response = client.get("/catalog-items/ASSY/preview-explosion", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_nodes"] == 2
    assert body["max_depth_reached"] == 1

    sub = body["tree"][0]["children"][0]
    assert sub["part_number"] == "SUB"
    assert sub["suppress_auto_explode"] is True
    assert sub["children"] == []

    flat = {row["part_number"]: Decimal(row["total_quantity"]) for row in body["flat"]}
    assert flat == {"SUB": Decimal("1")}


# ============================================================
# Limits
# ============================================================


def test_preview_node_limit_returns_413(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    admin_headers,
    db_session,
):
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_NODES", 2)
    _add_template_edge(db_session, "KIT", "BOLT")
    _add_template_edge(db_session, "KIT", "NUT")

    response = client.get("/catalog-items/KIT/preview-explosion", headers=admin_headers)
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["limit"] == "nodes"
    assert detail["max"] == 2
    assert detail["reached"] >= 3


def test_preview_depth_limit_returns_413(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    admin_headers,
    db_session,
):
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_DEPTH", 2)
    monkeypatch.setattr(settings, "MAX_BOM_EXPLOSION_NODES", 100)

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

    response = client.get("/catalog-items/P0/preview-explosion", headers=admin_headers)
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert detail["limit"] == "depth"
    assert detail["max"] == 2


# ============================================================
# OBSOLETE
# ============================================================


def test_preview_obsolete_descendant_returns_409_with_payload(client: TestClient, admin_headers, db_session):
    create_catalog_item(db_session, "ASSY")
    create_catalog_item(db_session, "OLD", status=CatalogItemStatus.OBSOLETE)
    db_session.add(
        EngineeringTemplateItem(
            parent_part_number="ASSY",
            child_part_number="OLD",
            quantity=Decimal("1"),
        )
    )
    db_session.commit()

    response = client.get("/catalog-items/ASSY/preview-explosion", headers=admin_headers)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["obsolete_parts"] == ["OLD"]
    assert "OBSOLETE" in detail["message"]


def test_preview_obsolete_root_returns_409(client: TestClient, admin_headers, db_session):
    create_catalog_item(db_session, "OLD-ROOT", status=CatalogItemStatus.OBSOLETE)
    response = client.get("/catalog-items/OLD-ROOT/preview-explosion", headers=admin_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["obsolete_parts"] == ["OLD-ROOT"]


# ============================================================
# Catalog metadata join
# ============================================================


def test_preview_metadata_joined_on_tree_and_flat(client: TestClient, admin_headers, db_session):
    create_catalog_item(
        db_session,
        "KIT",
        description="Kit assembly",
        category="Assemblies",
        unit_of_measure="EA",
    )
    create_catalog_item(
        db_session,
        "BOLT",
        description="Hex bolt",
        category="Fasteners",
        unit_of_measure="PC",
    )
    db_session.add(
        EngineeringTemplateItem(
            parent_part_number="KIT",
            child_part_number="BOLT",
            quantity=Decimal("4"),
        )
    )
    db_session.commit()

    response = client.get("/catalog-items/KIT/preview-explosion", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()

    root = body["tree"][0]
    assert root["description"] == "Kit assembly"
    assert root["category"] == "Assemblies"
    assert root["unit_of_measure"] == "EA"

    bolt_tree = root["children"][0]
    assert bolt_tree["description"] == "Hex bolt"
    assert bolt_tree["category"] == "Fasteners"
    assert bolt_tree["unit_of_measure"] == "PC"

    bolt_flat = body["flat"][0]
    assert bolt_flat["part_number"] == "BOLT"
    assert bolt_flat["description"] == "Hex bolt"
    assert bolt_flat["category"] == "Fasteners"
    assert bolt_flat["unit_of_measure"] == "PC"


def test_preview_does_not_persist_anything(client: TestClient, admin_headers, db_session):
    """Preview is a dry run: no BOMItem rows are created."""
    from app.models.domain import BOMItem

    _add_template_edge(db_session, "KIT", "BOLT", quantity=Decimal("4"))

    response = client.get("/catalog-items/KIT/preview-explosion", headers=admin_headers)
    assert response.status_code == 200
    assert db_session.query(BOMItem).count() == 0
