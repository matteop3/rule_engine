"""
Test suite for Values API endpoints.

Tests the full CRUD lifecycle for Value management including:
- RBAC enforcement (admin/author only)
- DRAFT-only modification policy
- Free-field restriction (no values for free fields)
- Cross-version movement restrictions
- Guardrails for deletion (Rules dependencies)

Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Field, Value, Rule, RuleType, FieldType


# ============================================================
# LIST VALUES TESTS (GET /values/)
# ============================================================

class TestListValues:
    """Tests for GET /values/ endpoint."""

    def test_admin_can_list_values(self, client: TestClient, admin_headers, draft_value):
        """Test that admin can list values."""
        response = client.get(
            f"/values/?field_id={draft_value.field_id}",
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_author_can_list_values(self, client: TestClient, author_headers, draft_value):
        """Test that author can list values."""
        response = client.get(
            f"/values/?field_id={draft_value.field_id}",
            headers=author_headers
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_regular_user_cannot_list_values(self, client: TestClient, user_headers, draft_value):
        """Test that regular user cannot list values (403)."""
        response = client.get(
            f"/values/?field_id={draft_value.field_id}",
            headers=user_headers
        )

        assert response.status_code == 403

    def test_unauthenticated_cannot_list_values(self, client: TestClient, draft_value):
        """Test that unauthenticated request returns 401."""
        response = client.get(f"/values/?field_id={draft_value.field_id}")

        assert response.status_code == 401

    def test_list_values_without_filter(self, client: TestClient, admin_headers, field_with_values):
        """Test that listing without filter returns all accessible values."""
        response = client.get("/values/", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should contain at least the values from fixture
        assert len(data) >= 3

    def test_list_values_pagination(self, client: TestClient, admin_headers, field_with_values):
        """Test pagination parameters work correctly."""
        response = client.get("/values/?limit=2", headers=admin_headers)

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_values_skip(self, client: TestClient, admin_headers, field_with_values):
        """Test skip parameter works correctly."""
        response_all = client.get("/values/", headers=admin_headers)
        response_skip = client.get("/values/?skip=1", headers=admin_headers)

        assert response_all.status_code == 200
        assert response_skip.status_code == 200
        assert len(response_skip.json()) == len(response_all.json()) - 1

    def test_list_values_limit_capped_at_100(self, client: TestClient, admin_headers, draft_value):
        """Test that limit is capped at 100."""
        response = client.get("/values/?limit=200", headers=admin_headers)

        assert response.status_code == 200
        assert len(response.json()) <= 100


# ============================================================
# READ VALUE TESTS (GET /values/{value_id})
# ============================================================

class TestReadValue:
    """Tests for GET /values/{value_id} endpoint."""

    def test_admin_can_read_value(self, client: TestClient, admin_headers, draft_value):
        """Test that admin can read value by ID."""
        response = client.get(f"/values/{draft_value.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == draft_value.id
        assert data["value"] == "TEST_VALUE"

    def test_author_can_read_value(self, client: TestClient, author_headers, draft_value):
        """Test that author can read value by ID."""
        response = client.get(f"/values/{draft_value.id}", headers=author_headers)

        assert response.status_code == 200
        assert response.json()["id"] == draft_value.id

    def test_regular_user_cannot_read_value(self, client: TestClient, user_headers, draft_value):
        """Test that regular user cannot read values (403)."""
        response = client.get(f"/values/{draft_value.id}", headers=user_headers)

        assert response.status_code == 403

    def test_read_nonexistent_value_returns_404(self, client: TestClient, admin_headers):
        """Test that reading non-existent value returns 404."""
        response = client.get("/values/99999", headers=admin_headers)

        assert response.status_code == 404

    def test_unauthenticated_cannot_read_value(self, client: TestClient, draft_value):
        """Test that unauthenticated request returns 401."""
        response = client.get(f"/values/{draft_value.id}")

        assert response.status_code == 401


# ============================================================
# CREATE VALUE TESTS (POST /values/)
# ============================================================

class TestCreateValue:
    """Tests for POST /values/ endpoint."""

    def test_admin_can_create_value(self, client: TestClient, admin_headers, draft_field):
        """Test that admin can create a value for a non-free field."""
        payload = {
            "field_id": draft_field.id,
            "value": "NEW_VALUE",
            "label": "New Value",
            "is_default": False
        }

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["value"] == "NEW_VALUE"
        assert data["field_id"] == draft_field.id
        assert "id" in data

    def test_author_can_create_value(self, client: TestClient, author_headers, draft_field):
        """Test that author can create a value."""
        payload = {
            "field_id": draft_field.id,
            "value": "AUTHOR_VALUE",
            "label": "Author Value"
        }

        response = client.post("/values/", json=payload, headers=author_headers)

        assert response.status_code == 201
        assert response.json()["value"] == "AUTHOR_VALUE"

    def test_regular_user_cannot_create_value(self, client: TestClient, user_headers, draft_field):
        """Test that regular user cannot create values (403)."""
        payload = {
            "field_id": draft_field.id,
            "value": "USER_VALUE",
            "label": "User Value"
        }

        response = client.post("/values/", json=payload, headers=user_headers)

        assert response.status_code == 403

    def test_unauthenticated_cannot_create_value(self, client: TestClient, draft_field):
        """Test that unauthenticated request returns 401."""
        payload = {
            "field_id": draft_field.id,
            "value": "ANON_VALUE",
            "label": "Anonymous Value"
        }

        response = client.post("/values/", json=payload)

        assert response.status_code == 401

    def test_cannot_create_value_for_free_field(
        self, client: TestClient, admin_headers, free_field
    ):
        """
        Test free-field restriction: cannot create Value for is_free_value=True field.
        This is a CRITICAL business rule.
        """
        payload = {
            "field_id": free_field.id,
            "value": "SHOULD_FAIL",
            "label": "Should Fail"
        }

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "free" in response.json()["detail"].lower()

    def test_cannot_create_value_in_published_version(
        self, client: TestClient, admin_headers, published_field
    ):
        """
        Test DRAFT-only policy: cannot create value for field in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        payload = {
            "field_id": published_field.id,
            "value": "SHOULD_FAIL",
            "label": "Should Fail"
        }

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_create_value_for_nonexistent_field(self, client: TestClient, admin_headers):
        """Test that creating value for non-existent field fails."""
        payload = {
            "field_id": 99999,
            "value": "GHOST_VALUE",
            "label": "Ghost Value"
        }

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 404

    def test_create_value_with_is_default(self, client: TestClient, admin_headers, draft_field):
        """Test that is_default flag is properly set."""
        payload = {
            "field_id": draft_field.id,
            "value": "DEFAULT_VALUE",
            "label": "Default Value",
            "is_default": True
        }

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["is_default"] is True


# ============================================================
# UPDATE VALUE TESTS (PATCH /values/{value_id})
# ============================================================

class TestUpdateValue:
    """Tests for PATCH /values/{value_id} endpoint."""

    def test_admin_can_update_value(self, client: TestClient, admin_headers, draft_value):
        """Test that admin can update a value in DRAFT version."""
        payload = {
            "value": "UPDATED_VALUE",
            "label": "Updated Value"
        }

        response = client.patch(
            f"/values/{draft_value.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == "UPDATED_VALUE"
        assert data["label"] == "Updated Value"

    def test_author_can_update_value(self, client: TestClient, author_headers, draft_value):
        """Test that author can update a value."""
        payload = {"label": "Author Updated"}

        response = client.patch(
            f"/values/{draft_value.id}",
            json=payload,
            headers=author_headers
        )

        assert response.status_code == 200
        assert response.json()["label"] == "Author Updated"

    def test_regular_user_cannot_update_value(self, client: TestClient, user_headers, draft_value):
        """Test that regular user cannot update values (403)."""
        payload = {"label": "User Updated"}

        response = client.patch(
            f"/values/{draft_value.id}",
            json=payload,
            headers=user_headers
        )

        assert response.status_code == 403

    def test_cannot_update_value_in_published_version(
        self, client: TestClient, admin_headers, db_session, published_field
    ):
        """
        Test DRAFT-only policy: cannot update value in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        # Create a value for the published field
        value = Value(
            field_id=published_field.id,
            value="PUB_VALUE",
            label="Published Value"
        )
        db_session.add(value)
        db_session.commit()

        payload = {"label": "Should Fail"}

        response = client.patch(
            f"/values/{value.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_move_value_to_different_version(
        self, client: TestClient, admin_headers, db_session, draft_value, second_entity, admin_user
    ):
        """
        Test cross-version restriction: cannot move value to field in different version.
        This is a CRITICAL business rule.
        """
        from app.models.domain import EntityVersion, VersionStatus

        # Create another version with a field
        other_version = EntityVersion(
            entity_id=second_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Other version",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(other_version)
        db_session.flush()

        other_field = Field(
            entity_version_id=other_version.id,
            name="other_field",
            label="Other Field",
            data_type=FieldType.STRING.value,
            is_free_value=False
        )
        db_session.add(other_field)
        db_session.commit()

        # Try to move value to field in different version
        payload = {"field_id": other_field.id}

        response = client.patch(
            f"/values/{draft_value.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 400
        assert "version" in response.json()["detail"].lower()

    def test_cannot_move_value_to_free_field(
        self, client: TestClient, admin_headers, draft_value, free_field
    ):
        """
        Test free-field restriction: cannot move value to a free-value field.
        This is a CRITICAL business rule.
        """
        payload = {"field_id": free_field.id}

        response = client.patch(
            f"/values/{draft_value.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 400
        assert "free" in response.json()["detail"].lower()

    def test_can_move_value_within_same_version(
        self, client: TestClient, admin_headers, db_session, draft_value, draft_version
    ):
        """Test that value CAN be moved to another field in the same version."""
        # Create another field in the same version
        another_field = Field(
            entity_version_id=draft_version.id,
            name="another_field",
            label="Another Field",
            data_type=FieldType.STRING.value,
            is_free_value=False
        )
        db_session.add(another_field)
        db_session.commit()

        payload = {"field_id": another_field.id}

        response = client.patch(
            f"/values/{draft_value.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["field_id"] == another_field.id

    def test_update_is_default_flag(self, client: TestClient, admin_headers, draft_value):
        """Test that is_default flag can be updated."""
        payload = {"is_default": True}

        response = client.patch(
            f"/values/{draft_value.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["is_default"] is True

    def test_empty_update_handled(self, client: TestClient, admin_headers, draft_value):
        """Test that empty update payload is handled gracefully."""
        response = client.patch(
            f"/values/{draft_value.id}",
            json={},
            headers=admin_headers
        )

        assert response.status_code == 200

    def test_update_nonexistent_value_returns_404(self, client: TestClient, admin_headers):
        """Test that updating non-existent value returns 404."""
        payload = {"label": "Ghost"}

        response = client.patch("/values/99999", json=payload, headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# DELETE VALUE TESTS (DELETE /values/{value_id})
# ============================================================

class TestDeleteValue:
    """Tests for DELETE /values/{value_id} endpoint."""

    def test_admin_can_delete_value(self, client: TestClient, admin_headers, draft_value):
        """Test that admin can delete a value without dependencies."""
        response = client.delete(f"/values/{draft_value.id}", headers=admin_headers)

        assert response.status_code == 204

    def test_author_can_delete_value(
        self, client: TestClient, author_headers, db_session, draft_field
    ):
        """Test that author can delete a value."""
        value = Value(field_id=draft_field.id, value="TO_DELETE", label="To Delete")
        db_session.add(value)
        db_session.commit()

        response = client.delete(f"/values/{value.id}", headers=author_headers)

        assert response.status_code == 204

    def test_regular_user_cannot_delete_value(self, client: TestClient, user_headers, draft_value):
        """Test that regular user cannot delete values (403)."""
        response = client.delete(f"/values/{draft_value.id}", headers=user_headers)

        assert response.status_code == 403

    def test_cannot_delete_value_in_published_version(
        self, client: TestClient, admin_headers, db_session, published_field
    ):
        """
        Test DRAFT-only policy: cannot delete value in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        value = Value(
            field_id=published_field.id,
            value="PUB_VALUE",
            label="Published Value"
        )
        db_session.add(value)
        db_session.commit()

        response = client.delete(f"/values/{value.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_delete_value_targeted_by_rule(
        self, client: TestClient, admin_headers, value_in_rule_target
    ):
        """
        Test guardrail: cannot delete value that is explicit target of a Rule.
        This is a CRITICAL business rule.
        """
        value = value_in_rule_target["value"]

        response = client.delete(f"/values/{value.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "rule" in response.json()["detail"].lower()

    def test_cannot_delete_value_used_in_rule_conditions(
        self, client: TestClient, admin_headers, value_in_rule_condition
    ):
        """
        Test guardrail: cannot delete value used in Rule conditions JSON.
        This is a CRITICAL business rule - deep scan of conditions.
        """
        condition_value = value_in_rule_condition["condition_value"]

        response = client.delete(f"/values/{condition_value.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "rule" in response.json()["detail"].lower() or "condition" in response.json()["detail"].lower()

    def test_delete_nonexistent_value_returns_404(self, client: TestClient, admin_headers):
        """Test that deleting non-existent value returns 404."""
        response = client.delete("/values/99999", headers=admin_headers)

        assert response.status_code == 404

    def test_unauthenticated_cannot_delete_value(self, client: TestClient, draft_value):
        """Test that unauthenticated request returns 401."""
        response = client.delete(f"/values/{draft_value.id}")

        assert response.status_code == 401


# ============================================================
# OWNERSHIP AND INTEGRITY TESTS
# ============================================================

class TestValueOwnership:
    """Tests for value ownership and data integrity."""

    def test_value_belongs_to_correct_field(self, client: TestClient, admin_headers, draft_value):
        """Test that value correctly references its parent field."""
        response = client.get(f"/values/{draft_value.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["field_id"] == draft_value.field_id

    def test_multiple_values_for_same_field(
        self, client: TestClient, admin_headers, draft_field
    ):
        """Test that a field can have multiple values."""
        values = ["VALUE_1", "VALUE_2", "VALUE_3"]

        for val in values:
            payload = {
                "field_id": draft_field.id,
                "value": val,
                "label": f"Label {val}"
            }
            response = client.post("/values/", json=payload, headers=admin_headers)
            assert response.status_code == 201

        # Verify all values exist
        list_response = client.get(
            f"/values/?field_id={draft_field.id}",
            headers=admin_headers
        )
        assert len(list_response.json()) == 3


# ============================================================
# EDGE CASES
# ============================================================

class TestValueEdgeCases:
    """Edge case and boundary tests for Value API."""

    def test_value_with_special_characters(
        self, client: TestClient, admin_headers, draft_field
    ):
        """Test that value strings with special characters are handled."""
        payload = {
            "field_id": draft_field.id,
            "value": "SPECIAL_VALUE-123",
            "label": "Value with dashes & underscores"
        }

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["value"] == "SPECIAL_VALUE-123"

    def test_value_with_long_label(self, client: TestClient, admin_headers, draft_field):
        """Test that long labels are handled."""
        payload = {
            "field_id": draft_field.id,
            "value": "LONG",
            "label": "A" * 200
        }

        response = client.post("/values/", json=payload, headers=admin_headers)

        # Should either succeed or return validation error
        assert response.status_code in [201, 422]

    def test_empty_list_for_field_without_values(
        self, client: TestClient, admin_headers, draft_field
    ):
        """Test listing values for field with no values returns empty list."""
        response = client.get(
            f"/values/?field_id={draft_field.id}",
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_only_one_default_value_recommended(
        self, client: TestClient, admin_headers, draft_field
    ):
        """Test behavior when multiple values are marked as default."""
        # Create first default value
        payload1 = {
            "field_id": draft_field.id,
            "value": "DEFAULT_1",
            "label": "Default 1",
            "is_default": True
        }
        resp1 = client.post("/values/", json=payload1, headers=admin_headers)
        assert resp1.status_code == 201

        # Create second default value (may succeed - business logic may allow it)
        payload2 = {
            "field_id": draft_field.id,
            "value": "DEFAULT_2",
            "label": "Default 2",
            "is_default": True
        }
        resp2 = client.post("/values/", json=payload2, headers=admin_headers)
        # Document current behavior - may succeed or fail
        assert resp2.status_code in [201, 400]
