"""
Test suite for Price List Items API endpoints.

Covers CRUD, date defaulting, bounding box, overlap detection, price
validation, and RBAC.
"""

import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models.domain import PriceList, PriceListItem

# ============================================================
# LIST (GET /price-list-items/)
# ============================================================


class TestListPriceListItems:
    """Tests for GET /price-list-items/."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_list_rbac(self, client: TestClient, headers_fixture, expected_status, request, price_list):
        headers = request.getfixturevalue(headers_fixture)
        response = client.get(f"/price-list-items/?price_list_id={price_list.id}", headers=headers)
        assert response.status_code == expected_status

    def test_list_filters_by_price_list(self, client: TestClient, admin_headers, db_session):
        pl_a = PriceList(name="PL A", valid_from=dt.date(2020, 1, 1), valid_to=dt.date(9999, 12, 31))
        pl_b = PriceList(name="PL B", valid_from=dt.date(2020, 1, 1), valid_to=dt.date(9999, 12, 31))
        db_session.add_all([pl_a, pl_b])
        db_session.flush()

        db_session.add_all(
            [
                PriceListItem(
                    price_list_id=pl_a.id,
                    part_number="A-1",
                    unit_price=Decimal("10"),
                    valid_from=dt.date(2020, 1, 1),
                    valid_to=dt.date(9999, 12, 31),
                ),
                PriceListItem(
                    price_list_id=pl_b.id,
                    part_number="B-1",
                    unit_price=Decimal("20"),
                    valid_from=dt.date(2020, 1, 1),
                    valid_to=dt.date(9999, 12, 31),
                ),
            ]
        )
        db_session.commit()

        response = client.get(f"/price-list-items/?price_list_id={pl_a.id}", headers=admin_headers)
        assert response.status_code == 200
        parts = [i["part_number"] for i in response.json()]
        assert parts == ["A-1"]

    def test_list_unknown_price_list_404(self, client: TestClient, admin_headers):
        response = client.get("/price-list-items/?price_list_id=999999", headers=admin_headers)
        assert response.status_code == 404


# ============================================================
# READ (GET /price-list-items/{id})
# ============================================================


class TestReadPriceListItem:
    def test_read(self, client: TestClient, admin_headers, db_session, price_list):
        item = PriceListItem(
            price_list_id=price_list.id,
            part_number="READ-01",
            unit_price=Decimal("5.50"),
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(item)
        db_session.commit()

        response = client.get(f"/price-list-items/{item.id}", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["part_number"] == "READ-01"
        assert Decimal(response.json()["unit_price"]) == Decimal("5.50")

    def test_read_not_found(self, client: TestClient, admin_headers):
        response = client.get("/price-list-items/999999", headers=admin_headers)
        assert response.status_code == 404


# ============================================================
# CREATE (POST /price-list-items/)
# ============================================================


class TestCreatePriceListItem:
    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 201),
            ("author_headers", 201),
            ("user_headers", 403),
        ],
    )
    def test_create_rbac(self, client: TestClient, headers_fixture, expected_status, request, db_session):
        pl = PriceList(
            name=f"Create RBAC {headers_fixture}",
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()

        headers = request.getfixturevalue(headers_fixture)
        payload = {
            "price_list_id": pl.id,
            "part_number": f"RBAC-{headers_fixture}",
            "unit_price": "10.00",
        }
        response = client.post("/price-list-items/", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_create_success_defaults_dates_from_header(self, client: TestClient, admin_headers, price_list):
        """When dates are omitted, item inherits them from the parent price list."""
        payload = {
            "price_list_id": price_list.id,
            "part_number": "DEFAULT-DATES",
            "unit_price": "15.00",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 201
        body = response.json()
        assert body["valid_from"] == price_list.valid_from.isoformat()
        assert body["valid_to"] == price_list.valid_to.isoformat()

    def test_create_with_explicit_dates(self, client: TestClient, admin_headers, price_list):
        payload = {
            "price_list_id": price_list.id,
            "part_number": "EXPLICIT-DATES",
            "unit_price": "22.00",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 201
        body = response.json()
        assert body["valid_from"] == "2026-01-01"
        assert body["valid_to"] == "2026-12-31"

    def test_create_unknown_price_list(self, client: TestClient, admin_headers):
        payload = {
            "price_list_id": 999999,
            "part_number": "ORPHAN",
            "unit_price": "10.00",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 404

    def test_create_zero_price_rejected(self, client: TestClient, admin_headers, price_list):
        payload = {
            "price_list_id": price_list.id,
            "part_number": "ZERO",
            "unit_price": "0.00",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 400

    def test_create_negative_price_rejected(self, client: TestClient, admin_headers, price_list):
        payload = {
            "price_list_id": price_list.id,
            "part_number": "NEG",
            "unit_price": "-5.00",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 400

    def test_create_bounding_box_before_header_start(self, client: TestClient, admin_headers, db_session):
        pl = PriceList(
            name="Bounded PL",
            valid_from=dt.date(2026, 1, 1),
            valid_to=dt.date(2026, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()

        payload = {
            "price_list_id": pl.id,
            "part_number": "OUT-BEFORE",
            "unit_price": "10.00",
            "valid_from": "2025-06-01",
            "valid_to": "2026-06-01",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 400

    def test_create_bounding_box_after_header_end(self, client: TestClient, admin_headers, db_session):
        pl = PriceList(
            name="Bounded PL 2",
            valid_from=dt.date(2026, 1, 1),
            valid_to=dt.date(2026, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()

        payload = {
            "price_list_id": pl.id,
            "part_number": "OUT-AFTER",
            "unit_price": "10.00",
            "valid_from": "2026-06-01",
            "valid_to": "2027-06-01",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 400

    def test_create_overlap_same_part_rejected(self, client: TestClient, admin_headers, db_session, price_list):
        existing = PriceListItem(
            price_list_id=price_list.id,
            part_number="OVERLAP",
            unit_price=Decimal("10"),
            valid_from=dt.date(2025, 1, 1),
            valid_to=dt.date(2025, 12, 31),
        )
        db_session.add(existing)
        db_session.commit()

        payload = {
            "price_list_id": price_list.id,
            "part_number": "OVERLAP",
            "unit_price": "12.00",
            "valid_from": "2025-06-01",
            "valid_to": "2026-06-01",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 409

    def test_create_non_overlapping_same_part_allowed(self, client: TestClient, admin_headers, db_session, price_list):
        existing = PriceListItem(
            price_list_id=price_list.id,
            part_number="TEMPORAL",
            unit_price=Decimal("10"),
            valid_from=dt.date(2025, 1, 1),
            valid_to=dt.date(2025, 12, 31),
        )
        db_session.add(existing)
        db_session.commit()

        payload = {
            "price_list_id": price_list.id,
            "part_number": "TEMPORAL",
            "unit_price": "12.00",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 201

    def test_create_same_dates_different_part_allowed(self, client: TestClient, admin_headers, db_session, price_list):
        existing = PriceListItem(
            price_list_id=price_list.id,
            part_number="PART-A",
            unit_price=Decimal("10"),
            valid_from=dt.date(2025, 1, 1),
            valid_to=dt.date(2025, 12, 31),
        )
        db_session.add(existing)
        db_session.commit()

        payload = {
            "price_list_id": price_list.id,
            "part_number": "PART-B",
            "unit_price": "15.00",
            "valid_from": "2025-01-01",
            "valid_to": "2025-12-31",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 201

    def test_create_invalid_dates_rejected(self, client: TestClient, admin_headers, price_list):
        payload = {
            "price_list_id": price_list.id,
            "part_number": "BAD-DATES",
            "unit_price": "10.00",
            "valid_from": "2026-12-31",
            "valid_to": "2026-01-01",
        }
        response = client.post("/price-list-items/", json=payload, headers=admin_headers)
        assert response.status_code == 400


# ============================================================
# UPDATE (PATCH /price-list-items/{id})
# ============================================================


class TestUpdatePriceListItem:
    @pytest.fixture
    def item(self, db_session, price_list):
        item = PriceListItem(
            price_list_id=price_list.id,
            part_number="UPDATE-ME",
            unit_price=Decimal("10.00"),
            valid_from=dt.date(2025, 1, 1),
            valid_to=dt.date(2025, 12, 31),
        )
        db_session.add(item)
        db_session.commit()
        return item

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
            f"/price-list-items/{item.id}",
            json={"description": "updated"},
            headers=headers,
        )
        assert response.status_code == expected_status

    def test_update_price(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/price-list-items/{item.id}",
            json={"unit_price": "25.00"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert Decimal(response.json()["unit_price"]) == Decimal("25.00")

    def test_update_zero_price_rejected(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/price-list-items/{item.id}",
            json={"unit_price": "0.00"},
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_update_dates_within_bounds(self, client: TestClient, admin_headers, item):
        response = client.patch(
            f"/price-list-items/{item.id}",
            json={"valid_from": "2025-03-01", "valid_to": "2025-09-30"},
            headers=admin_headers,
        )
        assert response.status_code == 200

    def test_update_dates_outside_bounds(self, client: TestClient, admin_headers, item):
        """Cannot update dates outside parent bounding box."""
        response = client.patch(
            f"/price-list-items/{item.id}",
            json={"valid_from": "1999-01-01"},
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_update_empty_payload_returns_unchanged(self, client: TestClient, admin_headers, item):
        response = client.patch(f"/price-list-items/{item.id}", json={}, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["id"] == item.id

    def test_update_invalid_dates_both_rejected_by_schema(self, client: TestClient, admin_headers, item):
        """Inverted dates sent together are caught by the Pydantic schema → 422."""
        response = client.patch(
            f"/price-list-items/{item.id}",
            json={"valid_from": "2025-12-01", "valid_to": "2025-01-01"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_update_single_date_flips_range_rejected_by_router(self, client: TestClient, admin_headers, item):
        """Sending only one date that makes merged range invalid is caught by the router → 400."""
        # item.valid_to = 2025-12-31; new valid_from = 2026-01-01 → router 400
        response = client.patch(
            f"/price-list-items/{item.id}",
            json={"valid_from": "2026-01-01"},
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_update_overlap_with_sibling_rejected(
        self, client: TestClient, admin_headers, db_session, price_list, item
    ):
        sibling = PriceListItem(
            price_list_id=price_list.id,
            part_number=item.part_number,
            unit_price=Decimal("20.00"),
            valid_from=dt.date(2026, 1, 1),
            valid_to=dt.date(2026, 12, 31),
        )
        db_session.add(sibling)
        db_session.commit()

        response = client.patch(
            f"/price-list-items/{item.id}",
            json={"valid_from": "2025-06-01", "valid_to": "2026-06-01"},
            headers=admin_headers,
        )
        assert response.status_code == 409


# ============================================================
# DELETE (DELETE /price-list-items/{id})
# ============================================================


class TestDeletePriceListItem:
    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 204),
            ("author_headers", 204),
            ("user_headers", 403),
        ],
    )
    def test_delete_rbac(self, client: TestClient, headers_fixture, expected_status, request, db_session, price_list):
        item = PriceListItem(
            price_list_id=price_list.id,
            part_number=f"DEL-{headers_fixture}",
            unit_price=Decimal("10.00"),
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(item)
        db_session.commit()

        headers = request.getfixturevalue(headers_fixture)
        response = client.delete(f"/price-list-items/{item.id}", headers=headers)
        assert response.status_code == expected_status

    def test_delete_not_found(self, client: TestClient, admin_headers):
        response = client.delete("/price-list-items/999999", headers=admin_headers)
        assert response.status_code == 404
