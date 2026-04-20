"""
Test suite for the nested ``/configurations/{id}/custom-items`` API.

Covers happy paths, server-generated key semantics, value validation,
DRAFT gating, ownership checks, and list ordering.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models.domain import ConfigurationCustomItem

# ============================================================
# HELPERS
# ============================================================


def _create_payload(**overrides) -> dict:
    """Build a valid create payload with sensible defaults."""
    payload = {
        "description": "Extra service line",
        "quantity": "2",
        "unit_price": "150.00",
        "unit_of_measure": "PC",
        "sequence": 0,
    }
    payload.update(overrides)
    return payload


def _post(client: TestClient, config_id: str, headers: dict, **overrides):
    return client.post(
        f"/configurations/{config_id}/custom-items/",
        json=_create_payload(**overrides),
        headers=headers,
    )


# ============================================================
# CREATE — HAPPY PATH + KEY GENERATION
# ============================================================


class TestCreateCustomItemHappyPath:
    def test_create_custom_item_success(self, client, lifecycle_user_headers, draft_configuration):
        response = _post(client, draft_configuration.id, lifecycle_user_headers)

        assert response.status_code == 201
        body = response.json()
        assert body["description"] == "Extra service line"
        assert Decimal(body["quantity"]) == Decimal("2")
        assert Decimal(body["unit_price"]) == Decimal("150.00")
        assert body["unit_of_measure"] == "PC"
        assert body["sequence"] == 0
        assert body["configuration_id"] == draft_configuration.id
        assert "id" in body

    def test_auto_generated_key_format(self, client, lifecycle_user_headers, draft_configuration):
        response = _post(client, draft_configuration.id, lifecycle_user_headers)

        assert response.status_code == 201
        custom_key = response.json()["custom_key"]
        assert custom_key.startswith("CUSTOM-")
        assert len(custom_key) == 15  # "CUSTOM-" (7) + 8 hex chars
        assert all(c in "0123456789abcdef" for c in custom_key[7:])

    def test_duplicate_creations_produce_distinct_keys(self, client, lifecycle_user_headers, draft_configuration):
        r1 = _post(client, draft_configuration.id, lifecycle_user_headers)
        r2 = _post(client, draft_configuration.id, lifecycle_user_headers)
        r3 = _post(client, draft_configuration.id, lifecycle_user_headers)

        for r in (r1, r2, r3):
            assert r.status_code == 201

        keys = {r.json()["custom_key"] for r in (r1, r2, r3)}
        assert len(keys) == 3

    def test_client_custom_key_is_ignored(self, client, lifecycle_user_headers, draft_configuration):
        payload = _create_payload()
        payload["custom_key"] = "CUSTOM-deadbeef"

        response = client.post(
            f"/configurations/{draft_configuration.id}/custom-items/",
            json=payload,
            headers=lifecycle_user_headers,
        )

        assert response.status_code == 201
        returned_key = response.json()["custom_key"]
        assert returned_key != "CUSTOM-deadbeef"
        assert returned_key.startswith("CUSTOM-")

    def test_create_with_zero_unit_price_is_accepted(self, client, lifecycle_user_headers, draft_configuration):
        response = _post(client, draft_configuration.id, lifecycle_user_headers, unit_price="0")

        assert response.status_code == 201
        assert Decimal(response.json()["unit_price"]) == Decimal("0")

    def test_create_without_optional_unit_of_measure(self, client, lifecycle_user_headers, draft_configuration):
        payload = _create_payload()
        del payload["unit_of_measure"]

        response = client.post(
            f"/configurations/{draft_configuration.id}/custom-items/",
            json=payload,
            headers=lifecycle_user_headers,
        )

        assert response.status_code == 201
        assert response.json()["unit_of_measure"] is None

    def test_create_persists_audit_fields(
        self, client, db_session, lifecycle_user, lifecycle_user_headers, draft_configuration
    ):
        response = _post(client, draft_configuration.id, lifecycle_user_headers)
        assert response.status_code == 201

        db_session.expire_all()
        item = (
            db_session.query(ConfigurationCustomItem).filter(ConfigurationCustomItem.id == response.json()["id"]).one()
        )
        assert item.created_by_id == lifecycle_user.id


# ============================================================
# CREATE — VALIDATION
# ============================================================


class TestCreateCustomItemValidation:
    @pytest.mark.parametrize("quantity", ["0", "-1", "-0.0001"])
    def test_non_positive_quantity_is_rejected(self, client, lifecycle_user_headers, draft_configuration, quantity):
        response = _post(client, draft_configuration.id, lifecycle_user_headers, quantity=quantity)
        assert response.status_code == 422

    @pytest.mark.parametrize("unit_price", ["-0.01", "-1", "-100"])
    def test_negative_unit_price_is_rejected(self, client, lifecycle_user_headers, draft_configuration, unit_price):
        response = _post(client, draft_configuration.id, lifecycle_user_headers, unit_price=unit_price)
        assert response.status_code == 422

    def test_missing_description_is_rejected(self, client, lifecycle_user_headers, draft_configuration):
        payload = _create_payload()
        del payload["description"]

        response = client.post(
            f"/configurations/{draft_configuration.id}/custom-items/",
            json=payload,
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("description", ["", "   ", "\t\n"])
    def test_empty_or_whitespace_description_is_rejected(
        self, client, lifecycle_user_headers, draft_configuration, description
    ):
        response = _post(client, draft_configuration.id, lifecycle_user_headers, description=description)
        assert response.status_code == 422

    def test_missing_quantity_is_rejected(self, client, lifecycle_user_headers, draft_configuration):
        payload = _create_payload()
        del payload["quantity"]

        response = client.post(
            f"/configurations/{draft_configuration.id}/custom-items/",
            json=payload,
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 422

    def test_missing_unit_price_is_rejected(self, client, lifecycle_user_headers, draft_configuration):
        payload = _create_payload()
        del payload["unit_price"]

        response = client.post(
            f"/configurations/{draft_configuration.id}/custom-items/",
            json=payload,
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 422


# ============================================================
# CREATE — DRAFT GATING AND OWNERSHIP
# ============================================================


class TestCreateCustomItemAccessControl:
    def test_create_on_finalized_returns_409(self, client, lifecycle_user_headers, finalized_configuration):
        response = _post(client, finalized_configuration.id, lifecycle_user_headers)
        assert response.status_code == 409

    def test_user_cannot_create_on_other_users_configuration(
        self, client, lifecycle_user_headers, second_user_draft_configuration
    ):
        response = _post(client, second_user_draft_configuration.id, lifecycle_user_headers)
        assert response.status_code == 403

    def test_admin_can_create_on_any_configuration(
        self, client, lifecycle_admin_headers, second_user_draft_configuration
    ):
        response = _post(client, second_user_draft_configuration.id, lifecycle_admin_headers)
        assert response.status_code == 201

    def test_owner_user_can_create(self, client, lifecycle_user_headers, draft_configuration):
        response = _post(client, draft_configuration.id, lifecycle_user_headers)
        assert response.status_code == 201

    def test_unauthenticated_is_rejected(self, client, draft_configuration):
        response = client.post(
            f"/configurations/{draft_configuration.id}/custom-items/",
            json=_create_payload(),
        )
        assert response.status_code == 401

    def test_create_on_missing_configuration_returns_404(self, client, lifecycle_user_headers):
        response = _post(client, "00000000-0000-0000-0000-000000000000", lifecycle_user_headers)
        assert response.status_code == 404


# ============================================================
# LIST
# ============================================================


class TestListCustomItems:
    def test_list_returns_items_ordered_by_sequence(self, client, lifecycle_user_headers, draft_configuration):
        r_last = _post(client, draft_configuration.id, lifecycle_user_headers, sequence=10)
        r_first = _post(client, draft_configuration.id, lifecycle_user_headers, sequence=0, description="First")
        r_mid = _post(client, draft_configuration.id, lifecycle_user_headers, sequence=5, description="Mid")

        for r in (r_first, r_mid, r_last):
            assert r.status_code == 201

        response = client.get(
            f"/configurations/{draft_configuration.id}/custom-items/",
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 200
        items = response.json()
        assert [i["sequence"] for i in items] == [0, 5, 10]

    def test_list_on_empty_configuration_returns_empty(self, client, lifecycle_user_headers, draft_configuration):
        response = client.get(
            f"/configurations/{draft_configuration.id}/custom-items/",
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_user_cannot_list_other_users_custom_items(
        self, client, lifecycle_user_headers, second_user_draft_configuration
    ):
        response = client.get(
            f"/configurations/{second_user_draft_configuration.id}/custom-items/",
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 403

    def test_admin_can_list_any_configuration(self, client, lifecycle_admin_headers, second_user_draft_configuration):
        response = client.get(
            f"/configurations/{second_user_draft_configuration.id}/custom-items/",
            headers=lifecycle_admin_headers,
        )
        assert response.status_code == 200

    def test_list_unauthenticated_is_rejected(self, client, draft_configuration):
        response = client.get(f"/configurations/{draft_configuration.id}/custom-items/")
        assert response.status_code == 401


# ============================================================
# UPDATE
# ============================================================


class TestUpdateCustomItem:
    def test_update_allowed_fields_on_draft(self, client, lifecycle_user_headers, draft_configuration):
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        response = client.patch(
            f"/configurations/{draft_configuration.id}/custom-items/{created['id']}",
            json={
                "description": "Updated description",
                "quantity": "5",
                "unit_price": "99.99",
                "unit_of_measure": "KG",
                "sequence": 3,
            },
            headers=lifecycle_user_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["description"] == "Updated description"
        assert Decimal(body["quantity"]) == Decimal("5")
        assert Decimal(body["unit_price"]) == Decimal("99.99")
        assert body["unit_of_measure"] == "KG"
        assert body["sequence"] == 3
        # Key is immutable
        assert body["custom_key"] == created["custom_key"]

    def test_partial_update_keeps_unchanged_fields(self, client, lifecycle_user_headers, draft_configuration):
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        response = client.patch(
            f"/configurations/{draft_configuration.id}/custom-items/{created['id']}",
            json={"description": "Only description changed"},
            headers=lifecycle_user_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["description"] == "Only description changed"
        assert Decimal(body["quantity"]) == Decimal(created["quantity"])
        assert Decimal(body["unit_price"]) == Decimal(created["unit_price"])

    def test_update_custom_key_rejected(self, client, lifecycle_user_headers, draft_configuration):
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        response = client.patch(
            f"/configurations/{draft_configuration.id}/custom-items/{created['id']}",
            json={"custom_key": "CUSTOM-deadbeef"},
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 422

    def test_update_with_invalid_quantity_rejected(self, client, lifecycle_user_headers, draft_configuration):
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        response = client.patch(
            f"/configurations/{draft_configuration.id}/custom-items/{created['id']}",
            json={"quantity": "0"},
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 422

    def test_update_with_negative_unit_price_rejected(self, client, lifecycle_user_headers, draft_configuration):
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        response = client.patch(
            f"/configurations/{draft_configuration.id}/custom-items/{created['id']}",
            json={"unit_price": "-1"},
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 422

    def test_update_with_empty_description_rejected(self, client, lifecycle_user_headers, draft_configuration):
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        response = client.patch(
            f"/configurations/{draft_configuration.id}/custom-items/{created['id']}",
            json={"description": "   "},
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 422

    def test_update_on_finalized_returns_409(
        self,
        client,
        db_session,
        lifecycle_admin_headers,
        admin_owned_draft_configuration,
        lifecycle_admin,
    ):
        """
        Create the item while DRAFT, then flip the configuration to
        FINALIZED by updating the row directly, and verify updates are
        blocked. Using admin_owned_draft_configuration keeps ownership
        consistent with the admin headers used here.
        """
        from app.models.domain import Configuration, ConfigurationStatus

        created = _post(client, admin_owned_draft_configuration.id, lifecycle_admin_headers).json()

        db_session.query(Configuration).filter(Configuration.id == admin_owned_draft_configuration.id).update(
            {"status": ConfigurationStatus.FINALIZED.value}
        )
        db_session.commit()

        response = client.patch(
            f"/configurations/{admin_owned_draft_configuration.id}/custom-items/{created['id']}",
            json={"description": "attempt"},
            headers=lifecycle_admin_headers,
        )
        assert response.status_code == 409

    def test_update_missing_item_returns_404(self, client, lifecycle_user_headers, draft_configuration):
        response = client.patch(
            f"/configurations/{draft_configuration.id}/custom-items/999999",
            json={"description": "ghost"},
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 404

    def test_update_on_other_users_custom_item_is_forbidden(
        self,
        client,
        lifecycle_user_headers,
        lifecycle_admin_headers,
        second_user_draft_configuration,
    ):
        # Admin seeds a custom item on the second user's configuration
        created = _post(client, second_user_draft_configuration.id, lifecycle_admin_headers).json()

        # First lifecycle_user is not the owner — 403
        response = client.patch(
            f"/configurations/{second_user_draft_configuration.id}/custom-items/{created['id']}",
            json={"description": "hostile edit"},
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 403

    def test_empty_update_returns_current_state(self, client, lifecycle_user_headers, draft_configuration):
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        response = client.patch(
            f"/configurations/{draft_configuration.id}/custom-items/{created['id']}",
            json={},
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == created["id"]


# ============================================================
# DELETE
# ============================================================


class TestDeleteCustomItem:
    def test_delete_on_draft_succeeds(self, client, lifecycle_user_headers, draft_configuration, db_session):
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        response = client.delete(
            f"/configurations/{draft_configuration.id}/custom-items/{created['id']}",
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 204

        db_session.expire_all()
        remaining = (
            db_session.query(ConfigurationCustomItem).filter(ConfigurationCustomItem.id == created["id"]).first()
        )
        assert remaining is None

    def test_delete_on_finalized_returns_409(
        self,
        client,
        db_session,
        lifecycle_admin_headers,
        admin_owned_draft_configuration,
    ):
        from app.models.domain import Configuration, ConfigurationStatus

        created = _post(client, admin_owned_draft_configuration.id, lifecycle_admin_headers).json()

        db_session.query(Configuration).filter(Configuration.id == admin_owned_draft_configuration.id).update(
            {"status": ConfigurationStatus.FINALIZED.value}
        )
        db_session.commit()

        response = client.delete(
            f"/configurations/{admin_owned_draft_configuration.id}/custom-items/{created['id']}",
            headers=lifecycle_admin_headers,
        )
        assert response.status_code == 409

    def test_delete_missing_item_returns_404(self, client, lifecycle_user_headers, draft_configuration):
        response = client.delete(
            f"/configurations/{draft_configuration.id}/custom-items/999999",
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 404

    def test_delete_on_other_users_configuration_is_forbidden(
        self,
        client,
        lifecycle_user_headers,
        lifecycle_admin_headers,
        second_user_draft_configuration,
    ):
        created = _post(client, second_user_draft_configuration.id, lifecycle_admin_headers).json()

        response = client.delete(
            f"/configurations/{second_user_draft_configuration.id}/custom-items/{created['id']}",
            headers=lifecycle_user_headers,
        )
        assert response.status_code == 403

    def test_delete_unauthenticated_is_rejected(self, client, draft_configuration):
        response = client.delete(
            f"/configurations/{draft_configuration.id}/custom-items/1",
        )
        assert response.status_code == 401

    def test_cascade_delete_on_configuration_delete(
        self, client, db_session, lifecycle_user_headers, draft_configuration
    ):
        """Deleting the parent DRAFT configuration cascades to its custom items."""
        created = _post(client, draft_configuration.id, lifecycle_user_headers).json()

        del_resp = client.delete(f"/configurations/{draft_configuration.id}", headers=lifecycle_user_headers)
        assert del_resp.status_code == 204

        db_session.expire_all()
        orphan = db_session.query(ConfigurationCustomItem).filter(ConfigurationCustomItem.id == created["id"]).first()
        assert orphan is None
