"""
Test suite for `GET /catalog-items/{part_number}/usage`.

Covers RBAC, the empty-usage case, correct categorization across
`templates_as_parent`, `templates_as_child`, and `bom_items`, and 404 when
the part itself does not exist.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.domain import BOMItem, BOMType, EngineeringTemplateItem, EntityVersion
from tests.fixtures.catalog_items import create_catalog_item, ensure_catalog_entry


def _add_template_edge(
    db: Session,
    parent: str,
    child: str,
    *,
    quantity: Decimal = Decimal("1"),
    sequence: int = 0,
) -> EngineeringTemplateItem:
    ensure_catalog_entry(db, parent)
    ensure_catalog_entry(db, child)
    item = EngineeringTemplateItem(
        parent_part_number=parent,
        child_part_number=child,
        quantity=quantity,
        sequence=sequence,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _add_bom_item(db: Session, version: EntityVersion, part_number: str) -> BOMItem:
    ensure_catalog_entry(db, part_number)
    bom = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number=part_number,
        quantity=Decimal("1"),
    )
    db.add(bom)
    db.commit()
    db.refresh(bom)
    return bom


# ============================================================
# RBAC
# ============================================================


class TestCatalogItemUsageRBAC:
    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_rbac(self, client: TestClient, db_session, headers_fixture, expected_status, request):
        create_catalog_item(db_session, "PART-A")
        headers = request.getfixturevalue(headers_fixture)
        response = client.get("/catalog-items/PART-A/usage", headers=headers)
        assert response.status_code == expected_status

    def test_unauthenticated_rejected(self, client: TestClient, db_session):
        create_catalog_item(db_session, "PART-A")
        response = client.get("/catalog-items/PART-A/usage")
        assert response.status_code == 401


# ============================================================
# 404 / empty
# ============================================================


def test_usage_unknown_part_returns_404(client: TestClient, admin_headers):
    response = client.get("/catalog-items/GHOST/usage", headers=admin_headers)
    assert response.status_code == 404


def test_usage_empty_when_no_references(client: TestClient, admin_headers, db_session):
    create_catalog_item(db_session, "ISOLATED")
    response = client.get("/catalog-items/ISOLATED/usage", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["part_number"] == "ISOLATED"
    assert body["templates_as_parent"] == []
    assert body["templates_as_child"] == []
    assert body["bom_items"] == []


# ============================================================
# Categorization
# ============================================================


class TestCatalogItemUsageCategorization:
    def test_templates_as_parent_lists_only_outgoing_edges(self, client: TestClient, admin_headers, db_session):
        _add_template_edge(db_session, "KIT-A", "PART-X", sequence=2)
        _add_template_edge(db_session, "KIT-A", "PART-Y", sequence=1)
        _add_template_edge(db_session, "KIT-B", "KIT-A", sequence=0)

        response = client.get("/catalog-items/KIT-A/usage", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()

        children = [row["child_part_number"] for row in body["templates_as_parent"]]
        assert children == ["PART-Y", "PART-X"]

    def test_templates_as_child_lists_only_incoming_edges(self, client: TestClient, admin_headers, db_session):
        _add_template_edge(db_session, "KIT-A", "BOLT-01")
        _add_template_edge(db_session, "KIT-B", "BOLT-01")
        _add_template_edge(db_session, "KIT-A", "PART-X")

        response = client.get("/catalog-items/BOLT-01/usage", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()

        parents = sorted(row["parent_part_number"] for row in body["templates_as_child"])
        assert parents == ["KIT-A", "KIT-B"]
        assert body["templates_as_parent"] == []

    def test_bom_items_list_includes_entity_version_id(
        self, client: TestClient, admin_headers, db_session, draft_version: EntityVersion
    ):
        bom = _add_bom_item(db_session, draft_version, "WIDGET-01")

        response = client.get("/catalog-items/WIDGET-01/usage", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()

        assert body["bom_items"] == [{"bom_item_id": bom.id, "entity_version_id": draft_version.id}]

    def test_part_appearing_in_all_three_categories(
        self, client: TestClient, admin_headers, db_session, draft_version: EntityVersion
    ):
        # FOCUS plays parent of PART-X, child of KIT-A, and is referenced by a BOMItem.
        _add_template_edge(db_session, "FOCUS", "PART-X")
        _add_template_edge(db_session, "KIT-A", "FOCUS")
        bom = _add_bom_item(db_session, draft_version, "FOCUS")

        response = client.get("/catalog-items/FOCUS/usage", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()

        assert body["part_number"] == "FOCUS"
        assert [row["child_part_number"] for row in body["templates_as_parent"]] == ["PART-X"]
        assert [row["parent_part_number"] for row in body["templates_as_child"]] == ["KIT-A"]
        assert body["bom_items"] == [{"bom_item_id": bom.id, "entity_version_id": draft_version.id}]

    def test_part_isolated_from_unrelated_graph_data(
        self, client: TestClient, admin_headers, db_session, draft_version: EntityVersion
    ):
        # Set up a busy graph that does NOT touch PART-Z.
        _add_template_edge(db_session, "KIT-A", "PART-X")
        _add_template_edge(db_session, "KIT-A", "PART-Y")
        _add_bom_item(db_session, draft_version, "PART-X")
        ensure_catalog_entry(db_session, "PART-Z")

        response = client.get("/catalog-items/PART-Z/usage", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["templates_as_parent"] == []
        assert body["templates_as_child"] == []
        assert body["bom_items"] == []
