"""
Test suite for the engineering template CRUD endpoints under
`/catalog-items/{part_number}/template`.

Covers happy-path CRUD for each verb, RBAC, cycle detection, UNIQUE
violations, the immutable-fields invariant on PATCH, list ordering, and
DELETE isolation between siblings.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.domain import EngineeringTemplateItem
from tests.fixtures.catalog_items import create_catalog_item, ensure_catalog_entry


def _post_template_item(
    db: Session,
    parent: str,
    child: str,
    *,
    quantity: Decimal = Decimal("1"),
    sequence: int = 0,
    suppress_child_explosion: bool = False,
) -> EngineeringTemplateItem:
    """Insert a template edge directly via ORM (used to set up scenarios)."""
    ensure_catalog_entry(db, parent)
    ensure_catalog_entry(db, child)
    item = EngineeringTemplateItem(
        parent_part_number=parent,
        child_part_number=child,
        quantity=quantity,
        sequence=sequence,
        suppress_child_explosion=suppress_child_explosion,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# ============================================================
# LIST (GET /catalog-items/{p}/template)
# ============================================================


class TestListTemplateItems:
    """Tests for GET /catalog-items/{part_number}/template."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 200),
        ],
    )
    def test_list_rbac(self, client: TestClient, db_session, headers_fixture, expected_status, request):
        create_catalog_item(db_session, "KIT-A")
        headers = request.getfixturevalue(headers_fixture)
        response = client.get("/catalog-items/KIT-A/template", headers=headers)
        assert response.status_code == expected_status

    def test_list_unauthenticated_rejected(self, client: TestClient, db_session):
        create_catalog_item(db_session, "KIT-A")
        response = client.get("/catalog-items/KIT-A/template")
        assert response.status_code == 401

    def test_list_empty_when_no_template(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")

        response = client.get("/catalog-items/KIT-A/template", headers=admin_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_list_returns_only_children_of_requested_parent(self, client: TestClient, admin_headers, db_session):
        _post_template_item(db_session, "KIT-A", "PART-X")
        _post_template_item(db_session, "KIT-B", "PART-Y")

        response = client.get("/catalog-items/KIT-A/template", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["parent_part_number"] == "KIT-A"
        assert body[0]["child_part_number"] == "PART-X"

    def test_list_ordered_by_sequence_then_part_number(self, client: TestClient, admin_headers, db_session):
        _post_template_item(db_session, "KIT-A", "PART-Z", sequence=5)
        _post_template_item(db_session, "KIT-A", "PART-A", sequence=1)
        _post_template_item(db_session, "KIT-A", "PART-M", sequence=1)

        response = client.get("/catalog-items/KIT-A/template", headers=admin_headers)
        assert response.status_code == 200
        children = [row["child_part_number"] for row in response.json()]
        assert children == ["PART-A", "PART-M", "PART-Z"]

    def test_list_unknown_parent_returns_404(self, client: TestClient, admin_headers):
        response = client.get("/catalog-items/GHOST/template", headers=admin_headers)
        assert response.status_code == 404


# ============================================================
# CREATE (POST /catalog-items/{p}/template/items)
# ============================================================


class TestCreateTemplateItem:
    """Tests for POST /catalog-items/{part_number}/template/items."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 201),
            ("author_headers", 201),
            ("user_headers", 403),
        ],
    )
    def test_create_rbac(self, client: TestClient, db_session, headers_fixture, expected_status, request):
        create_catalog_item(db_session, "KIT-A")
        create_catalog_item(db_session, "PART-X")
        headers = request.getfixturevalue(headers_fixture)

        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "PART-X", "quantity": "2", "sequence": 0},
            headers=headers,
        )
        assert response.status_code == expected_status

    def test_create_unauthenticated_rejected(self, client: TestClient, db_session):
        create_catalog_item(db_session, "KIT-A")
        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "PART-X", "quantity": "1"},
        )
        assert response.status_code == 401

    def test_create_success_returns_full_record(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        create_catalog_item(db_session, "PART-X")

        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={
                "child_part_number": "PART-X",
                "quantity": "3.5",
                "sequence": 7,
                "suppress_child_explosion": True,
            },
            headers=admin_headers,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["parent_part_number"] == "KIT-A"
        assert body["child_part_number"] == "PART-X"
        assert Decimal(body["quantity"]) == Decimal("3.5")
        assert body["sequence"] == 7
        assert body["suppress_child_explosion"] is True
        assert "id" in body
        assert "created_at" in body

    def test_create_defaults_sequence_and_suppress(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        create_catalog_item(db_session, "PART-X")

        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "PART-X", "quantity": "1"},
            headers=admin_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["sequence"] == 0
        assert body["suppress_child_explosion"] is False

    def test_create_unknown_parent_returns_404(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "PART-X")
        response = client.post(
            "/catalog-items/GHOST/template/items",
            json={"child_part_number": "PART-X", "quantity": "1"},
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_create_unknown_child_returns_409(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "GHOST", "quantity": "1"},
            headers=admin_headers,
        )
        assert response.status_code == 409
        assert "GHOST" in response.json()["detail"]

    def test_create_zero_quantity_rejected(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        create_catalog_item(db_session, "PART-X")
        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "PART-X", "quantity": "0"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_create_negative_quantity_rejected(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        create_catalog_item(db_session, "PART-X")
        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "PART-X", "quantity": "-1"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_create_negative_sequence_rejected(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        create_catalog_item(db_session, "PART-X")
        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "PART-X", "quantity": "1", "sequence": -1},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_create_duplicate_pair_returns_409(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        create_catalog_item(db_session, "PART-X")
        first = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "PART-X", "quantity": "1"},
            headers=admin_headers,
        )
        assert first.status_code == 201

        second = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "PART-X", "quantity": "5"},
            headers=admin_headers,
        )
        assert second.status_code == 409

    def test_create_self_loop_returns_409_with_cycle_path(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        response = client.post(
            "/catalog-items/KIT-A/template/items",
            json={"child_part_number": "KIT-A", "quantity": "1"},
            headers=admin_headers,
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["cycle_path"] == ["KIT-A", "KIT-A"]

    def test_create_two_node_cycle_returns_409_with_cycle_path(self, client: TestClient, admin_headers, db_session):
        _post_template_item(db_session, "A", "B")

        response = client.post(
            "/catalog-items/B/template/items",
            json={"child_part_number": "A", "quantity": "1"},
            headers=admin_headers,
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["cycle_path"] == ["B", "A", "B"]

    def test_create_three_node_cycle_returns_409_with_cycle_path(self, client: TestClient, admin_headers, db_session):
        _post_template_item(db_session, "A", "B")
        _post_template_item(db_session, "B", "C")

        response = client.post(
            "/catalog-items/C/template/items",
            json={"child_part_number": "A", "quantity": "1"},
            headers=admin_headers,
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["cycle_path"] == ["C", "A", "B", "C"]


# ============================================================
# UPDATE (PATCH /catalog-items/{p}/template/items/{id})
# ============================================================


class TestUpdateTemplateItem:
    """Tests for PATCH /catalog-items/{part_number}/template/items/{item_id}."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_update_rbac(self, client: TestClient, db_session, headers_fixture, expected_status, request):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        headers = request.getfixturevalue(headers_fixture)
        response = client.patch(
            f"/catalog-items/KIT-A/template/items/{item.id}",
            json={"quantity": "2"},
            headers=headers,
        )
        assert response.status_code == expected_status

    def test_update_quantity_sequence_and_flag(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X", quantity=Decimal("1"))
        response = client.patch(
            f"/catalog-items/KIT-A/template/items/{item.id}",
            json={"quantity": "4.25", "sequence": 9, "suppress_child_explosion": True},
            headers=admin_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["quantity"]) == Decimal("4.25")
        assert body["sequence"] == 9
        assert body["suppress_child_explosion"] is True

    def test_update_empty_payload_returns_existing_record(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X", quantity=Decimal("3"))
        response = client.patch(
            f"/catalog-items/KIT-A/template/items/{item.id}",
            json={},
            headers=admin_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert Decimal(body["quantity"]) == Decimal("3")

    def test_update_rejects_parent_part_number_change(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        ensure_catalog_entry(db_session, "KIT-B")
        response = client.patch(
            f"/catalog-items/KIT-A/template/items/{item.id}",
            json={"parent_part_number": "KIT-B"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_update_rejects_child_part_number_change(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        ensure_catalog_entry(db_session, "PART-Y")
        response = client.patch(
            f"/catalog-items/KIT-A/template/items/{item.id}",
            json={"child_part_number": "PART-Y"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_update_unknown_item_returns_404(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        response = client.patch(
            "/catalog-items/KIT-A/template/items/9999",
            json={"quantity": "2"},
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_update_item_under_wrong_parent_returns_404(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        create_catalog_item(db_session, "KIT-B")
        response = client.patch(
            f"/catalog-items/KIT-B/template/items/{item.id}",
            json={"quantity": "2"},
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_update_unknown_parent_returns_404(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        response = client.patch(
            f"/catalog-items/GHOST/template/items/{item.id}",
            json={"quantity": "2"},
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_update_zero_quantity_rejected(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        response = client.patch(
            f"/catalog-items/KIT-A/template/items/{item.id}",
            json={"quantity": "0"},
            headers=admin_headers,
        )
        assert response.status_code == 422


# ============================================================
# DELETE (DELETE /catalog-items/{p}/template/items/{id})
# ============================================================


class TestDeleteTemplateItem:
    """Tests for DELETE /catalog-items/{part_number}/template/items/{item_id}."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 204),
            ("author_headers", 204),
            ("user_headers", 403),
        ],
    )
    def test_delete_rbac(self, client: TestClient, db_session, headers_fixture, expected_status, request):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        headers = request.getfixturevalue(headers_fixture)
        response = client.delete(
            f"/catalog-items/KIT-A/template/items/{item.id}",
            headers=headers,
        )
        assert response.status_code == expected_status

    def test_delete_removes_only_target_sibling(self, client: TestClient, admin_headers, db_session):
        keep = _post_template_item(db_session, "KIT-A", "PART-X", sequence=1)
        target = _post_template_item(db_session, "KIT-A", "PART-Y", sequence=2)

        response = client.delete(
            f"/catalog-items/KIT-A/template/items/{target.id}",
            headers=admin_headers,
        )
        assert response.status_code == 204

        listing = client.get("/catalog-items/KIT-A/template", headers=admin_headers)
        assert listing.status_code == 200
        children = [row["id"] for row in listing.json()]
        assert children == [keep.id]

    def test_delete_unknown_item_returns_404(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "KIT-A")
        response = client.delete(
            "/catalog-items/KIT-A/template/items/9999",
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_delete_item_under_wrong_parent_returns_404(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        create_catalog_item(db_session, "KIT-B")
        response = client.delete(
            f"/catalog-items/KIT-B/template/items/{item.id}",
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_delete_unknown_parent_returns_404(self, client: TestClient, admin_headers, db_session):
        item = _post_template_item(db_session, "KIT-A", "PART-X")
        response = client.delete(
            f"/catalog-items/GHOST/template/items/{item.id}",
            headers=admin_headers,
        )
        assert response.status_code == 404
