"""
Test suite for Catalog Items API endpoints.

Covers CRUD happy paths, duplicate detection, missing-field validation,
the immutable-`part_number` invariant on PATCH, and RBAC.
"""

import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models.domain import (
    BOMItem,
    BOMType,
    CatalogItem,
    CatalogItemStatus,
    EntityVersion,
    PriceList,
    PriceListItem,
)
from tests.fixtures.catalog_items import create_catalog_item

# ============================================================
# LIST (GET /catalog-items/)
# ============================================================


class TestListCatalogItems:
    """Tests for GET /catalog-items/."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 200),
        ],
    )
    def test_list_rbac(self, client: TestClient, headers_fixture, expected_status, request):
        """Reads are allowed for any authenticated user, including USER."""
        headers = request.getfixturevalue(headers_fixture)
        response = client.get("/catalog-items/", headers=headers)
        assert response.status_code == expected_status

    def test_list_unauthenticated_rejected(self, client: TestClient):
        response = client.get("/catalog-items/")
        assert response.status_code == 401

    def test_list_sorted_by_part_number(self, client: TestClient, admin_headers, db_session):
        """List is ordered by part_number ASC."""
        for pn in ["ZULU-01", "ALPHA-01", "MIKE-01"]:
            create_catalog_item(db_session, pn)

        response = client.get("/catalog-items/", headers=admin_headers)
        assert response.status_code == 200
        pns = [c["part_number"] for c in response.json()]
        assert pns == sorted(pns)

    def test_list_filter_by_status(self, client: TestClient, admin_headers, db_session):
        """The `status` query param filters by lifecycle state."""
        create_catalog_item(db_session, "ACTIVE-01", status=CatalogItemStatus.ACTIVE)
        create_catalog_item(db_session, "OBSOLETE-01", status=CatalogItemStatus.OBSOLETE)

        response = client.get("/catalog-items/?status=ACTIVE", headers=admin_headers)
        assert response.status_code == 200
        pns = {c["part_number"] for c in response.json()}
        assert "ACTIVE-01" in pns
        assert "OBSOLETE-01" not in pns

        response = client.get("/catalog-items/?status=OBSOLETE", headers=admin_headers)
        assert response.status_code == 200
        pns = {c["part_number"] for c in response.json()}
        assert "OBSOLETE-01" in pns
        assert "ACTIVE-01" not in pns

    def test_list_pagination(self, client: TestClient, admin_headers, db_session):
        """`skip` and `limit` paginate the result set."""
        for i in range(5):
            create_catalog_item(db_session, f"PAGE-{i:02d}")

        response = client.get("/catalog-items/?limit=2", headers=admin_headers)
        assert response.status_code == 200
        assert len(response.json()) == 2

        response = client.get("/catalog-items/?skip=2&limit=2", headers=admin_headers)
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_invalid_status_rejected(self, client: TestClient, admin_headers):
        response = client.get("/catalog-items/?status=BANANA", headers=admin_headers)
        assert response.status_code == 422


# ============================================================
# READ BY ID (GET /catalog-items/{id})
# ============================================================


class TestReadCatalogItem:
    """Tests for GET /catalog-items/{id}."""

    def test_read(self, client: TestClient, admin_headers, db_session):
        item = create_catalog_item(
            db_session,
            "READ-01",
            description="Readable widget",
            category="Widgets",
        )
        response = client.get(f"/catalog-items/{item.id}", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == item.id
        assert body["part_number"] == "READ-01"
        assert body["description"] == "Readable widget"
        assert body["category"] == "Widgets"
        assert body["unit_of_measure"] == "PC"
        assert body["status"] == "ACTIVE"

    def test_read_not_found(self, client: TestClient, admin_headers):
        response = client.get("/catalog-items/999999", headers=admin_headers)
        assert response.status_code == 404

    def test_read_user_allowed(self, client: TestClient, user_headers, db_session):
        item = create_catalog_item(db_session, "USER-READ")
        response = client.get(f"/catalog-items/{item.id}", headers=user_headers)
        assert response.status_code == 200

    def test_read_unauthenticated_rejected(self, client: TestClient, db_session):
        item = create_catalog_item(db_session, "ANON-READ")
        response = client.get(f"/catalog-items/{item.id}")
        assert response.status_code == 401


# ============================================================
# READ BY PART NUMBER (GET /catalog-items/by-part-number/{part_number})
# ============================================================


class TestReadCatalogItemByPartNumber:
    """Tests for GET /catalog-items/by-part-number/{part_number}."""

    def test_read_by_part_number(self, client: TestClient, admin_headers, db_session):
        create_catalog_item(db_session, "LOOKUP-01", description="Lookup part")
        response = client.get("/catalog-items/by-part-number/LOOKUP-01", headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["part_number"] == "LOOKUP-01"
        assert body["description"] == "Lookup part"

    def test_read_by_part_number_not_found(self, client: TestClient, admin_headers):
        response = client.get("/catalog-items/by-part-number/DOES-NOT-EXIST", headers=admin_headers)
        assert response.status_code == 404

    def test_read_by_part_number_user_allowed(self, client: TestClient, user_headers, db_session):
        create_catalog_item(db_session, "USER-LOOKUP")
        response = client.get("/catalog-items/by-part-number/USER-LOOKUP", headers=user_headers)
        assert response.status_code == 200


# ============================================================
# CREATE (POST /catalog-items/)
# ============================================================


class TestCreateCatalogItem:
    """Tests for POST /catalog-items/."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 201),
            ("author_headers", 201),
            ("user_headers", 403),
        ],
    )
    def test_create_rbac(self, client: TestClient, headers_fixture, expected_status, request):
        headers = request.getfixturevalue(headers_fixture)
        payload = {
            "part_number": f"CREATE-{headers_fixture}",
            "description": "RBAC create",
        }
        response = client.post("/catalog-items/", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_create_success(self, client: TestClient, admin_headers):
        payload = {
            "part_number": "BOLT-M8",
            "description": "Bolt M8 zinc-plated",
            "unit_of_measure": "PC",
            "category": "Fasteners",
            "notes": "Standard DIN 933",
        }
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 201
        body = response.json()
        assert body["part_number"] == "BOLT-M8"
        assert body["description"] == "Bolt M8 zinc-plated"
        assert body["unit_of_measure"] == "PC"
        assert body["category"] == "Fasteners"
        assert body["notes"] == "Standard DIN 933"
        assert body["status"] == "ACTIVE"
        assert "id" in body

    def test_create_defaults_unit_of_measure_to_pc(self, client: TestClient, admin_headers):
        """`unit_of_measure` defaults to `'PC'` when omitted."""
        payload = {"part_number": "DEFAULT-UOM", "description": "With default UoM"}
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 201
        assert response.json()["unit_of_measure"] == "PC"

    def test_create_defaults_status_to_active(self, client: TestClient, admin_headers):
        """`status` defaults to ACTIVE when omitted."""
        payload = {"part_number": "DEFAULT-STATUS", "description": "Defaults status"}
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 201
        assert response.json()["status"] == "ACTIVE"

    def test_create_with_status_obsolete(self, client: TestClient, admin_headers):
        """A part can be created in OBSOLETE state (e.g. imported-but-dead)."""
        payload = {
            "part_number": "DEAD-01",
            "description": "Born obsolete",
            "status": "OBSOLETE",
        }
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 201
        assert response.json()["status"] == "OBSOLETE"

    def test_create_duplicate_part_number_rejected(self, client: TestClient, admin_headers, db_session):
        """Duplicate `part_number` → 409."""
        create_catalog_item(db_session, "DUP-01")

        payload = {"part_number": "DUP-01", "description": "Second entry"}
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_create_missing_part_number_rejected(self, client: TestClient, admin_headers):
        payload = {"description": "Missing key"}
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 422

    def test_create_missing_description_rejected(self, client: TestClient, admin_headers):
        payload = {"part_number": "NO-DESC"}
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 422

    def test_create_empty_part_number_rejected(self, client: TestClient, admin_headers):
        payload = {"part_number": "", "description": "Empty key"}
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 422

    def test_create_empty_description_rejected(self, client: TestClient, admin_headers):
        payload = {"part_number": "EMPTY-DESC", "description": ""}
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 422

    def test_create_invalid_status_rejected(self, client: TestClient, admin_headers):
        payload = {
            "part_number": "BAD-STATUS",
            "description": "Bad status",
            "status": "DEPRECATED",
        }
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 422

    def test_create_part_number_max_length_enforced(self, client: TestClient, admin_headers):
        payload = {
            "part_number": "X" * 101,
            "description": "Too long",
        }
        response = client.post("/catalog-items/", json=payload, headers=admin_headers)
        assert response.status_code == 422


# ============================================================
# UPDATE (PATCH /catalog-items/{id})
# ============================================================


class TestUpdateCatalogItem:
    """Tests for PATCH /catalog-items/{id}."""

    @pytest.fixture
    def item(self, db_session) -> CatalogItem:
        return create_catalog_item(
            db_session,
            "PATCH-ME",
            description="Original description",
            category="Original",
        )

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_update_rbac(self, client: TestClient, headers_fixture, expected_status, request, item):
        headers = request.getfixturevalue(headers_fixture)
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"description": "changed"},
            headers=headers,
        )
        assert response.status_code == expected_status

    def test_update_description(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"description": "Updated description"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["description"] == "Updated description"

    def test_update_category(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"category": "Reclassified"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["category"] == "Reclassified"

    def test_update_unit_of_measure(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"unit_of_measure": "KG"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["unit_of_measure"] == "KG"

    def test_update_status_active_to_obsolete(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"status": "OBSOLETE"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "OBSOLETE"

    def test_update_status_obsolete_to_active(self, client: TestClient, admin_headers, db_session):
        """An OBSOLETE catalog item can be reactivated ("oops, we needed it")."""
        item = create_catalog_item(db_session, "REVIVE-01", status=CatalogItemStatus.OBSOLETE)
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"status": "ACTIVE"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ACTIVE"

    def test_update_notes(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"notes": "Supplier: Acme"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["notes"] == "Supplier: Acme"

    def test_update_part_number_in_payload_rejected(self, client: TestClient, admin_headers, item):
        """The immutable-`part_number` invariant is enforced at the schema layer."""
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"part_number": "RENAMED"},
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        detail_text = str(body["detail"])
        assert "part_number cannot be modified" in detail_text

    def test_update_part_number_rejected_even_when_same_value(self, client: TestClient, admin_headers, item):
        """The rejection is syntactic — sending `part_number` at all is an error."""
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"part_number": item.part_number},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_update_part_number_with_other_fields_rejected(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"part_number": "RENAMED", "description": "New desc"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_update_empty_payload_returns_unchanged(self, client: TestClient, admin_headers, item):
        response = client.patch(f"/catalog-items/{item.id}", json={}, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["id"] == item.id
        assert response.json()["description"] == "Original description"

    def test_update_not_found(self, client: TestClient, admin_headers):
        response = client.patch(
            "/catalog-items/999999",
            json={"description": "ghost"},
            headers=admin_headers,
        )
        assert response.status_code == 404

    def test_update_invalid_status_rejected(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"status": "DEPRECATED"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_update_empty_description_rejected(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/catalog-items/{item.id}",
            json={"description": ""},
            headers=admin_headers,
        )
        assert response.status_code == 422


# ============================================================
# DELETE (DELETE /catalog-items/{id})
# ============================================================


class TestDeleteCatalogItem:
    """Tests for DELETE /catalog-items/{id}."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 204),
            ("author_headers", 204),
            ("user_headers", 403),
        ],
    )
    def test_delete_rbac(self, client: TestClient, headers_fixture, expected_status, request, db_session):
        item = create_catalog_item(db_session, f"DEL-{headers_fixture}")
        headers = request.getfixturevalue(headers_fixture)
        response = client.delete(f"/catalog-items/{item.id}", headers=headers)
        assert response.status_code == expected_status

    def test_delete_unreferenced(self, client: TestClient, admin_headers, db_session):
        item = create_catalog_item(db_session, "GONE-01")
        response = client.delete(f"/catalog-items/{item.id}", headers=admin_headers)
        assert response.status_code == 204

        lookup = db_session.query(CatalogItem).filter(CatalogItem.id == item.id).first()
        assert lookup is None

    def test_delete_not_found(self, client: TestClient, admin_headers):
        response = client.delete("/catalog-items/999999", headers=admin_headers)
        assert response.status_code == 404

    def test_delete_blocked_by_bom_item_reference(
        self,
        client: TestClient,
        admin_headers,
        db_session,
        draft_version: EntityVersion,
        strict_catalog_validation,
    ):
        catalog = create_catalog_item(db_session, "BOM-REF-DEL")

        bom = BOMItem(
            entity_version_id=draft_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="BOM-REF-DEL",
            quantity=Decimal("1"),
        )
        db_session.add(bom)
        db_session.commit()

        response = client.delete(f"/catalog-items/{catalog.id}", headers=admin_headers)
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Catalog item 'BOM-REF-DEL' cannot be deleted: referenced by 1 BOM item(s) and 0 price list item(s)"
        )

    def test_delete_blocked_by_price_list_item_reference(
        self,
        client: TestClient,
        admin_headers,
        db_session,
        strict_catalog_validation,
    ):
        catalog = create_catalog_item(db_session, "PLI-REF-DEL")

        price_list = PriceList(
            name="Ref Delete PL",
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(price_list)
        db_session.flush()

        pli = PriceListItem(
            price_list_id=price_list.id,
            part_number="PLI-REF-DEL",
            unit_price=Decimal("10.00"),
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(pli)
        db_session.commit()

        response = client.delete(f"/catalog-items/{catalog.id}", headers=admin_headers)
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Catalog item 'PLI-REF-DEL' cannot be deleted: referenced by 0 BOM item(s) and 1 price list item(s)"
        )

    def test_delete_blocked_by_both_references(
        self,
        client: TestClient,
        admin_headers,
        db_session,
        draft_version: EntityVersion,
        strict_catalog_validation,
    ):
        catalog = create_catalog_item(db_session, "BOTH-REF-DEL")

        bom = BOMItem(
            entity_version_id=draft_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="BOTH-REF-DEL",
            quantity=Decimal("1"),
        )
        price_list = PriceList(
            name="Both Ref PL",
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add_all([bom, price_list])
        db_session.flush()

        pli = PriceListItem(
            price_list_id=price_list.id,
            part_number="BOTH-REF-DEL",
            unit_price=Decimal("10.00"),
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(pli)
        db_session.commit()

        response = client.delete(f"/catalog-items/{catalog.id}", headers=admin_headers)
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Catalog item 'BOTH-REF-DEL' cannot be deleted: referenced by 1 BOM item(s) and 1 price list item(s)"
        )
