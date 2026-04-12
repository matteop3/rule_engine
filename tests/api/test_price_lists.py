"""
Test suite for Price Lists API endpoints.

Covers CRUD, validation, valid_at filtering, delete protection, RBAC,
and bounding-box updates.
"""

import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models.domain import (
    Configuration,
    PriceList,
    PriceListItem,
)

# ============================================================
# LIST (GET /price-lists/)
# ============================================================


class TestListPriceLists:
    """Tests for GET /price-lists/."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_list_rbac(self, client: TestClient, headers_fixture, expected_status, request):
        headers = request.getfixturevalue(headers_fixture)
        response = client.get("/price-lists/", headers=headers)
        assert response.status_code == expected_status

    def test_list_default_is_today(self, client: TestClient, admin_headers, db_session):
        """valid_at defaults to today — only lists valid today are returned."""
        today = dt.date.today()
        valid_now = PriceList(
            name="Valid Now",
            valid_from=today - dt.timedelta(days=10),
            valid_to=today + dt.timedelta(days=10),
        )
        expired = PriceList(
            name="Expired",
            valid_from=today - dt.timedelta(days=60),
            valid_to=today - dt.timedelta(days=30),
        )
        future = PriceList(
            name="Future",
            valid_from=today + dt.timedelta(days=30),
            valid_to=today + dt.timedelta(days=60),
        )
        db_session.add_all([valid_now, expired, future])
        db_session.commit()

        response = client.get("/price-lists/", headers=admin_headers)
        assert response.status_code == 200
        names = [pl["name"] for pl in response.json()]
        assert "Valid Now" in names
        assert "Expired" not in names
        assert "Future" not in names

    def test_list_valid_at_filter(self, client: TestClient, admin_headers, db_session):
        """Custom valid_at filter returns lists valid at that date."""
        pl_2025 = PriceList(name="2025", valid_from=dt.date(2025, 1, 1), valid_to=dt.date(2025, 12, 31))
        pl_2026 = PriceList(name="2026", valid_from=dt.date(2026, 1, 1), valid_to=dt.date(2026, 12, 31))
        db_session.add_all([pl_2025, pl_2026])
        db_session.commit()

        response = client.get("/price-lists/?valid_at=2025-06-01", headers=admin_headers)
        assert response.status_code == 200
        names = [pl["name"] for pl in response.json()]
        assert "2025" in names
        assert "2026" not in names

    def test_list_sorted_by_name(self, client: TestClient, admin_headers, db_session):
        """List is ordered by name."""
        today = dt.date.today()
        for n in ["Zebra", "Alpha", "Mango"]:
            db_session.add(
                PriceList(
                    name=n,
                    valid_from=today - dt.timedelta(days=1),
                    valid_to=today + dt.timedelta(days=1),
                )
            )
        db_session.commit()

        response = client.get("/price-lists/", headers=admin_headers)
        assert response.status_code == 200
        names = [pl["name"] for pl in response.json()]
        assert names == sorted(names)


# ============================================================
# READ (GET /price-lists/{id})
# ============================================================


class TestReadPriceList:
    """Tests for GET /price-lists/{id}."""

    def test_read(self, client: TestClient, admin_headers, price_list):
        response = client.get(f"/price-lists/{price_list.id}", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["id"] == price_list.id
        assert response.json()["name"] == price_list.name

    def test_read_not_found(self, client: TestClient, admin_headers):
        response = client.get("/price-lists/999999", headers=admin_headers)
        assert response.status_code == 404

    def test_read_user_forbidden(self, client: TestClient, user_headers, price_list):
        response = client.get(f"/price-lists/{price_list.id}", headers=user_headers)
        assert response.status_code == 403


# ============================================================
# CREATE (POST /price-lists/)
# ============================================================


class TestCreatePriceList:
    """Tests for POST /price-lists/."""

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
            "name": f"PL {headers_fixture}",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
        }
        response = client.post("/price-lists/", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_create_success(self, client: TestClient, admin_headers):
        payload = {
            "name": "Spring 2026",
            "description": "Q2 pricing",
            "valid_from": "2026-04-01",
            "valid_to": "2026-06-30",
        }
        response = client.post("/price-lists/", json=payload, headers=admin_headers)
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Spring 2026"
        assert body["valid_from"] == "2026-04-01"
        assert body["valid_to"] == "2026-06-30"

    def test_create_invalid_dates(self, client: TestClient, admin_headers):
        """valid_from >= valid_to is rejected."""
        payload = {
            "name": "Bad Dates",
            "valid_from": "2026-12-31",
            "valid_to": "2026-01-01",
        }
        response = client.post("/price-lists/", json=payload, headers=admin_headers)
        assert response.status_code == 422

    def test_create_same_dates_rejected(self, client: TestClient, admin_headers):
        payload = {
            "name": "Same Dates",
            "valid_from": "2026-01-01",
            "valid_to": "2026-01-01",
        }
        response = client.post("/price-lists/", json=payload, headers=admin_headers)
        assert response.status_code == 422

    def test_create_duplicate_name_rejected(self, client: TestClient, admin_headers, price_list):
        """Duplicate name → 409."""
        payload = {
            "name": price_list.name,
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
        }
        response = client.post("/price-lists/", json=payload, headers=admin_headers)
        assert response.status_code == 409

    def test_create_empty_name_rejected(self, client: TestClient, admin_headers):
        payload = {
            "name": "",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
        }
        response = client.post("/price-lists/", json=payload, headers=admin_headers)
        assert response.status_code == 422

    def test_create_defaults_valid_to_far_future(self, client: TestClient, admin_headers):
        """valid_to defaults to 9999-12-31 when omitted."""
        payload = {"name": "Default End", "valid_from": "2026-01-01"}
        response = client.post("/price-lists/", json=payload, headers=admin_headers)
        assert response.status_code == 201
        assert response.json()["valid_to"] == "9999-12-31"


# ============================================================
# UPDATE (PATCH /price-lists/{id})
# ============================================================


class TestUpdatePriceList:
    """Tests for PATCH /price-lists/{id}."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_update_rbac(self, client: TestClient, headers_fixture, expected_status, request, price_list):
        headers = request.getfixturevalue(headers_fixture)
        response = client.patch(
            f"/price-lists/{price_list.id}",
            json={"description": "updated"},
            headers=headers,
        )
        assert response.status_code == expected_status

    def test_update_name(self, client: TestClient, admin_headers, price_list):
        response = client.patch(
            f"/price-lists/{price_list.id}",
            json={"name": "Renamed Price List"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Renamed Price List"

    def test_update_duplicate_name_rejected(self, client: TestClient, admin_headers, db_session, price_list):
        other = PriceList(
            name="Other Price List",
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(other)
        db_session.commit()

        response = client.patch(
            f"/price-lists/{price_list.id}",
            json={"name": "Other Price List"},
            headers=admin_headers,
        )
        assert response.status_code == 409

    def test_update_invalid_dates_both_rejected_by_schema(self, client: TestClient, admin_headers, price_list):
        """Inverted dates sent together are caught by the Pydantic schema → 422."""
        response = client.patch(
            f"/price-lists/{price_list.id}",
            json={"valid_from": "2030-01-01", "valid_to": "2025-01-01"},
            headers=admin_headers,
        )
        assert response.status_code == 422

    def test_update_single_date_flips_range_rejected_by_router(self, client: TestClient, admin_headers, db_session):
        """Sending only one date that makes merged range invalid is caught by the router → 400."""
        pl = PriceList(
            name="Flip Range PL",
            valid_from=dt.date(2025, 1, 1),
            valid_to=dt.date(2025, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()

        # New valid_from (2026) > existing valid_to (2025-12-31) → router 400
        response = client.patch(
            f"/price-lists/{pl.id}",
            json={"valid_from": "2026-06-01"},
            headers=admin_headers,
        )
        assert response.status_code == 400

    def test_update_narrow_dates_rejects_violating_items(
        self, client: TestClient, admin_headers, db_session, price_list
    ):
        """Cannot shrink dates if existing items fall outside the new range."""
        item = PriceListItem(
            price_list_id=price_list.id,
            part_number="PART-A",
            unit_price=Decimal("10.00"),
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(item)
        db_session.commit()

        response = client.patch(
            f"/price-lists/{price_list.id}",
            json={"valid_from": "2025-01-01", "valid_to": "2025-12-31"},
            headers=admin_headers,
        )
        assert response.status_code == 409

    def test_update_dates_allowed_when_items_fit(self, client: TestClient, admin_headers, db_session, price_list):
        """Dates can be narrowed if items still fit."""
        item = PriceListItem(
            price_list_id=price_list.id,
            part_number="PART-A",
            unit_price=Decimal("10.00"),
            valid_from=dt.date(2025, 6, 1),
            valid_to=dt.date(2025, 6, 30),
        )
        db_session.add(item)
        db_session.commit()

        response = client.patch(
            f"/price-lists/{price_list.id}",
            json={"valid_from": "2025-01-01", "valid_to": "2025-12-31"},
            headers=admin_headers,
        )
        assert response.status_code == 200

    def test_update_empty_payload_returns_unchanged(self, client: TestClient, admin_headers, price_list):
        response = client.patch(
            f"/price-lists/{price_list.id}",
            json={},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == price_list.id


# ============================================================
# DELETE (DELETE /price-lists/{id})
# ============================================================


class TestDeletePriceList:
    """Tests for DELETE /price-lists/{id}."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 204),
            ("author_headers", 204),
            ("user_headers", 403),
        ],
    )
    def test_delete_rbac(self, client: TestClient, headers_fixture, expected_status, request, db_session):
        pl = PriceList(
            name=f"Deletable {headers_fixture}",
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()
        headers = request.getfixturevalue(headers_fixture)
        response = client.delete(f"/price-lists/{pl.id}", headers=headers)
        assert response.status_code == expected_status

    def test_delete_unreferenced(self, client: TestClient, admin_headers, price_list):
        response = client.delete(f"/price-lists/{price_list.id}", headers=admin_headers)
        assert response.status_code == 204

    def test_delete_blocked_by_finalized_configuration(
        self,
        client: TestClient,
        lifecycle_admin_headers,
        db_session,
        finalized_configuration,
        lifecycle_price_list,
    ):
        """Cannot delete a price list referenced by any FINALIZED configuration."""
        response = client.delete(f"/price-lists/{lifecycle_price_list.id}", headers=lifecycle_admin_headers)
        assert response.status_code == 409

    def test_delete_allowed_with_only_draft_reference(
        self,
        client: TestClient,
        lifecycle_admin_headers,
        db_session,
        draft_configuration,
        lifecycle_price_list,
    ):
        """DRAFT references allow deletion (FK SET NULL)."""
        config_id = draft_configuration.id
        response = client.delete(f"/price-lists/{lifecycle_price_list.id}", headers=lifecycle_admin_headers)
        assert response.status_code == 204

        db_session.expire_all()
        config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
        assert config is not None
        assert config.price_list_id is None

    def test_delete_not_found(self, client: TestClient, admin_headers):
        response = client.delete("/price-lists/999999", headers=admin_headers)
        assert response.status_code == 404
