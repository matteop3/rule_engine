"""
Test suite for Fields API endpoints.

Tests the full CRUD lifecycle for Field management including:
- RBAC enforcement (admin/author only)
- DRAFT-only modification policy
- is_free_value state transitions
- Guardrails for deletion (Values, Rules dependencies)

Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Field, Value, Rule, RuleType, FieldType


# ============================================================
# LIST FIELDS TESTS (GET /fields/)
# ============================================================

class TestListFields:
    """Tests for GET /fields/ endpoint."""

    def test_admin_can_list_fields(self, client: TestClient, admin_headers, draft_field):
        """Test that admin can list fields for a version."""
        response = client.get(
            f"/fields/?entity_version_id={draft_field.entity_version_id}",
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert any(f["id"] == draft_field.id for f in data)

    def test_author_can_list_fields(self, client: TestClient, author_headers, draft_field):
        """Test that author can list fields."""
        response = client.get(
            f"/fields/?entity_version_id={draft_field.entity_version_id}",
            headers=author_headers
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_regular_user_cannot_list_fields(self, client: TestClient, user_headers, draft_field):
        """Test that regular user cannot list fields (403)."""
        response = client.get(
            f"/fields/?entity_version_id={draft_field.entity_version_id}",
            headers=user_headers
        )

        assert response.status_code == 403

    def test_unauthenticated_cannot_list_fields(self, client: TestClient, draft_field):
        """Test that unauthenticated request returns 401."""
        response = client.get(f"/fields/?entity_version_id={draft_field.entity_version_id}")

        assert response.status_code == 401

    def test_list_fields_ordered_by_step_and_sequence(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that fields are ordered by step and sequence."""
        # Create fields with different step/sequence
        fields_data = [
            (2, 1, "step2_seq1"),
            (1, 2, "step1_seq2"),
            (1, 1, "step1_seq1"),
            (2, 2, "step2_seq2"),
        ]
        for step, seq, name in fields_data:
            field = Field(
                entity_version_id=draft_version.id,
                name=name,
                label=name,
                data_type=FieldType.STRING.value,
                is_free_value=True,
                step=step,
                sequence=seq
            )
            db_session.add(field)
        db_session.commit()

        response = client.get(
            f"/fields/?entity_version_id={draft_version.id}",
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        # Expected order: step1_seq1, step1_seq2, step2_seq1, step2_seq2
        names = [f["name"] for f in data]
        assert names == ["step1_seq1", "step1_seq2", "step2_seq1", "step2_seq2"]

    def test_list_fields_pagination(self, client: TestClient, admin_headers, db_session, draft_version):
        """Test pagination parameters work correctly."""
        # Create 5 fields
        for i in range(5):
            field = Field(
                entity_version_id=draft_version.id,
                name=f"paginated_field_{i}",
                label=f"Field {i}",
                data_type=FieldType.STRING.value,
                is_free_value=True,
                step=1,
                sequence=i
            )
            db_session.add(field)
        db_session.commit()

        response = client.get(
            f"/fields/?entity_version_id={draft_version.id}&limit=2",
            headers=admin_headers
        )

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_fields_limit_over_100_rejected(self, client: TestClient, admin_headers, draft_field):
        """Test that limit > 100 is rejected with 422."""
        response = client.get(
            f"/fields/?entity_version_id={draft_field.entity_version_id}&limit=200",
            headers=admin_headers
        )

        assert response.status_code == 422


# ============================================================
# READ FIELD TESTS (GET /fields/{field_id})
# ============================================================

class TestReadField:
    """Tests for GET /fields/{field_id} endpoint."""

    def test_admin_can_read_field(self, client: TestClient, admin_headers, draft_field):
        """Test that admin can read field by ID."""
        response = client.get(f"/fields/{draft_field.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == draft_field.id
        assert data["name"] == "test_field"

    def test_author_can_read_field(self, client: TestClient, author_headers, draft_field):
        """Test that author can read field by ID."""
        response = client.get(f"/fields/{draft_field.id}", headers=author_headers)

        assert response.status_code == 200
        assert response.json()["id"] == draft_field.id

    def test_regular_user_cannot_read_field(self, client: TestClient, user_headers, draft_field):
        """Test that regular user cannot read fields (403)."""
        response = client.get(f"/fields/{draft_field.id}", headers=user_headers)

        assert response.status_code == 403

    def test_read_nonexistent_field_returns_404(self, client: TestClient, admin_headers):
        """Test that reading non-existent field returns 404."""
        response = client.get("/fields/99999", headers=admin_headers)

        assert response.status_code == 404

    def test_unauthenticated_cannot_read_field(self, client: TestClient, draft_field):
        """Test that unauthenticated request returns 401."""
        response = client.get(f"/fields/{draft_field.id}")

        assert response.status_code == 401


# ============================================================
# CREATE FIELD TESTS (POST /fields/)
# ============================================================

class TestCreateField:
    """Tests for POST /fields/ endpoint."""

    def test_admin_can_create_field(self, client: TestClient, admin_headers, draft_version):
        """Test that admin can create a field in DRAFT version."""
        payload = {
            "entity_version_id": draft_version.id,
            "name": "new_field",
            "label": "New Field",
            "data_type": "string",
            "is_free_value": True,
            "is_required": False
        }

        response = client.post("/fields/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "new_field"
        assert data["is_free_value"] is True
        assert "id" in data

    def test_author_can_create_field(self, client: TestClient, author_headers, draft_version):
        """Test that author can create a field."""
        payload = {
            "entity_version_id": draft_version.id,
            "name": "author_field",
            "label": "Author Field",
            "data_type": "number",
            "is_free_value": True
        }

        response = client.post("/fields/", json=payload, headers=author_headers)

        assert response.status_code == 201
        assert response.json()["name"] == "author_field"

    def test_regular_user_cannot_create_field(self, client: TestClient, user_headers, draft_version):
        """Test that regular user cannot create fields (403)."""
        payload = {
            "entity_version_id": draft_version.id,
            "name": "forbidden_field",
            "label": "Forbidden",
            "data_type": "string",
            "is_free_value": True
        }

        response = client.post("/fields/", json=payload, headers=user_headers)

        assert response.status_code == 403

    def test_unauthenticated_cannot_create_field(self, client: TestClient, draft_version):
        """Test that unauthenticated request returns 401."""
        payload = {
            "entity_version_id": draft_version.id,
            "name": "anon_field",
            "label": "Anonymous",
            "data_type": "string",
            "is_free_value": True
        }

        response = client.post("/fields/", json=payload)

        assert response.status_code == 401

    def test_cannot_create_field_in_published_version(
        self, client: TestClient, admin_headers, published_version
    ):
        """
        Test DRAFT-only policy: cannot create field in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        payload = {
            "entity_version_id": published_version.id,
            "name": "should_fail",
            "label": "Should Fail",
            "data_type": "string",
            "is_free_value": True
        }

        response = client.post("/fields/", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_create_field_in_archived_version(
        self, client: TestClient, admin_headers, archived_version
    ):
        """
        Test DRAFT-only policy: cannot create field in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        payload = {
            "entity_version_id": archived_version.id,
            "name": "should_fail",
            "label": "Should Fail",
            "data_type": "string",
            "is_free_value": True
        }

        response = client.post("/fields/", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_set_default_value_on_non_free_field(
        self, client: TestClient, admin_headers, draft_version
    ):
        """
        Test is_free_value constraint: default_value only allowed for free fields.
        This is a CRITICAL business rule.
        """
        payload = {
            "entity_version_id": draft_version.id,
            "name": "bad_default",
            "label": "Bad Default",
            "data_type": "string",
            "is_free_value": False,
            "default_value": "should_fail"  # Not allowed for non-free fields
        }

        response = client.post("/fields/", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "default_value" in response.json()["detail"].lower()

    def test_can_set_default_value_on_free_field(
        self, client: TestClient, admin_headers, draft_version
    ):
        """Test that default_value IS allowed for free-value fields."""
        payload = {
            "entity_version_id": draft_version.id,
            "name": "good_default",
            "label": "Good Default",
            "data_type": "string",
            "is_free_value": True,
            "default_value": "allowed"
        }

        response = client.post("/fields/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["default_value"] == "allowed"

    def test_create_field_for_nonexistent_version(self, client: TestClient, admin_headers):
        """Test that creating field for non-existent version fails."""
        payload = {
            "entity_version_id": 99999,
            "name": "ghost_field",
            "label": "Ghost Field",
            "data_type": "string",
            "is_free_value": True
        }

        response = client.post("/fields/", json=payload, headers=admin_headers)

        assert response.status_code == 404

    def test_create_field_all_data_types(self, client: TestClient, admin_headers, draft_version):
        """Test that all valid data types can be used."""
        data_types = ["string", "number", "boolean", "date"]

        for dtype in data_types:
            payload = {
                "entity_version_id": draft_version.id,
                "name": f"field_{dtype}",
                "label": f"Field {dtype}",
                "data_type": dtype,
                "is_free_value": True
            }

            response = client.post("/fields/", json=payload, headers=admin_headers)
            assert response.status_code == 201, f"Failed for data_type: {dtype}"


# ============================================================
# UPDATE FIELD TESTS (PUT /fields/{field_id})
# ============================================================

class TestUpdateField:
    """Tests for PUT /fields/{field_id} endpoint."""

    def test_admin_can_update_field(self, client: TestClient, admin_headers, draft_field):
        """Test that admin can update a field in DRAFT version."""
        payload = {
            "name": "updated_field",
            "label": "Updated Field",
            "data_type": "string",
            "is_free_value": False,
            "is_required": True
        }

        response = client.patch(
            f"/fields/{draft_field.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "updated_field"
        assert data["label"] == "Updated Field"

    def test_author_can_update_field(self, client: TestClient, author_headers, draft_field):
        """Test that author can update a field."""
        payload = {
            "name": "author_update",
            "label": "Author Update",
            "data_type": "string",
            "is_free_value": False
        }

        response = client.patch(
            f"/fields/{draft_field.id}",
            json=payload,
            headers=author_headers
        )

        assert response.status_code == 200
        assert response.json()["name"] == "author_update"

    def test_regular_user_cannot_update_field(self, client: TestClient, user_headers, draft_field):
        """Test that regular user cannot update fields (403)."""
        payload = {
            "name": "user_update",
            "label": "User Update",
            "data_type": "string",
            "is_free_value": False
        }

        response = client.patch(
            f"/fields/{draft_field.id}",
            json=payload,
            headers=user_headers
        )

        assert response.status_code == 403

    def test_cannot_update_field_in_published_version(
        self, client: TestClient, admin_headers, published_field
    ):
        """
        Test DRAFT-only policy: cannot update field in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        payload = {
            "name": "should_fail",
            "label": "Should Fail",
            "data_type": "string",
            "is_free_value": False
        }

        response = client.patch(
            f"/fields/{published_field.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_update_field_in_archived_version(
        self, client: TestClient, admin_headers, archived_field
    ):
        """
        Test DRAFT-only policy: cannot update field in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        payload = {
            "name": "should_fail",
            "label": "Should Fail",
            "data_type": "string",
            "is_free_value": False
        }

        response = client.patch(
            f"/fields/{archived_field.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_change_non_free_to_free_with_values(
        self, client: TestClient, admin_headers, field_with_values
    ):
        """
        Test state transition: cannot change is_free_value False->True if Values exist.
        This is a CRITICAL business rule.
        """
        field = field_with_values["field"]
        payload = {
            "name": field.name,
            "label": field.label,
            "data_type": field.data_type,
            "is_free_value": True  # Try to change from False to True
        }

        response = client.patch(
            f"/fields/{field.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 409
        assert "values" in response.json()["detail"].lower()

    def test_can_change_free_to_non_free(
        self, client: TestClient, admin_headers, free_field
    ):
        """Test state transition: can change is_free_value True->False."""
        payload = {
            "name": free_field.name,
            "label": free_field.label,
            "data_type": free_field.data_type,
            "is_free_value": False  # Change from True to False
        }

        response = client.patch(
            f"/fields/{free_field.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["is_free_value"] is False
        # default_value should be cleared
        assert response.json()["default_value"] is None

    def test_cannot_set_default_when_switching_to_non_free(
        self, client: TestClient, admin_headers, free_field
    ):
        """Test that default_value cannot be set when switching to non-free."""
        payload = {
            "name": free_field.name,
            "label": free_field.label,
            "data_type": free_field.data_type,
            "is_free_value": False,
            "default_value": "not_allowed"  # Should fail
        }

        response = client.patch(
            f"/fields/{free_field.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 400

    def test_update_nonexistent_field_returns_404(self, client: TestClient, admin_headers):
        """Test that updating non-existent field returns 404."""
        payload = {
            "name": "ghost",
            "label": "Ghost",
            "data_type": "string",
            "is_free_value": True
        }

        response = client.patch("/fields/99999", json=payload, headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# DELETE FIELD TESTS (DELETE /fields/{field_id})
# ============================================================

class TestDeleteField:
    """Tests for DELETE /fields/{field_id} endpoint."""

    def test_admin_can_delete_empty_field(self, client: TestClient, admin_headers, draft_field):
        """Test that admin can delete a field without dependencies."""
        response = client.delete(f"/fields/{draft_field.id}", headers=admin_headers)

        assert response.status_code == 204

    def test_author_can_delete_field(self, client: TestClient, author_headers, free_field):
        """Test that author can delete a field."""
        response = client.delete(f"/fields/{free_field.id}", headers=author_headers)

        assert response.status_code == 204

    def test_regular_user_cannot_delete_field(self, client: TestClient, user_headers, draft_field):
        """Test that regular user cannot delete fields (403)."""
        response = client.delete(f"/fields/{draft_field.id}", headers=user_headers)

        assert response.status_code == 403

    def test_cannot_delete_field_in_published_version(
        self, client: TestClient, admin_headers, published_field
    ):
        """
        Test DRAFT-only policy: cannot delete field in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        response = client.delete(f"/fields/{published_field.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_delete_field_in_archived_version(
        self, client: TestClient, admin_headers, archived_field
    ):
        """
        Test DRAFT-only policy: cannot delete field in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        response = client.delete(f"/fields/{archived_field.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_delete_field_with_values(
        self, client: TestClient, admin_headers, field_with_values
    ):
        """
        Test guardrail: cannot delete field that has associated Values.
        This is a CRITICAL business rule.
        """
        field = field_with_values["field"]

        response = client.delete(f"/fields/{field.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "values" in response.json()["detail"].lower()

    def test_cannot_delete_field_targeted_by_rule(
        self, client: TestClient, admin_headers, field_as_rule_target
    ):
        """
        Test guardrail: cannot delete field that is target of a Rule.
        This is a CRITICAL business rule.
        """
        target_field = field_as_rule_target["target_field"]

        response = client.delete(f"/fields/{target_field.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "rule" in response.json()["detail"].lower()

    def test_cannot_delete_field_used_in_rule_conditions(
        self, client: TestClient, admin_headers, field_as_rule_target
    ):
        """
        Test guardrail: cannot delete field used in Rule conditions JSON.
        This is a CRITICAL business rule - deep scan of conditions.
        """
        condition_field = field_as_rule_target["condition_field"]

        response = client.delete(f"/fields/{condition_field.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "condition" in response.json()["detail"].lower() or "rule" in response.json()["detail"].lower()

    def test_delete_nonexistent_field_returns_404(self, client: TestClient, admin_headers):
        """Test that deleting non-existent field returns 404."""
        response = client.delete("/fields/99999", headers=admin_headers)

        assert response.status_code == 404

    def test_unauthenticated_cannot_delete_field(self, client: TestClient, draft_field):
        """Test that unauthenticated request returns 401."""
        response = client.delete(f"/fields/{draft_field.id}")

        assert response.status_code == 401


# ============================================================
# STATE TRANSITION TESTS
# ============================================================

class TestFieldStateTransitions:
    """Tests for is_free_value state transitions."""

    def test_can_change_non_free_to_free_without_values(
        self, client: TestClient, admin_headers, draft_field
    ):
        """Test that non-free field without values CAN become free."""
        payload = {
            "name": draft_field.name,
            "label": draft_field.label,
            "data_type": draft_field.data_type,
            "is_free_value": True
        }

        response = client.patch(
            f"/fields/{draft_field.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["is_free_value"] is True

    def test_free_field_can_have_default_updated(
        self, client: TestClient, admin_headers, free_field
    ):
        """Test that free field default_value can be updated."""
        payload = {
            "name": free_field.name,
            "label": free_field.label,
            "data_type": free_field.data_type,
            "is_free_value": True,
            "default_value": "new_default"
        }

        response = client.patch(
            f"/fields/{free_field.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["default_value"] == "new_default"


# ============================================================
# EDGE CASES
# ============================================================

class TestFieldEdgeCases:
    """Edge case and boundary tests for Field API."""

    def test_field_name_with_special_characters(
        self, client: TestClient, admin_headers, draft_version
    ):
        """Test that field names with underscores are handled."""
        payload = {
            "entity_version_id": draft_version.id,
            "name": "field_with_underscores_123",
            "label": "Field With Special Chars",
            "data_type": "string",
            "is_free_value": True
        }

        response = client.post("/fields/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["name"] == "field_with_underscores_123"

    def test_field_with_step_and_sequence(
        self, client: TestClient, admin_headers, draft_version
    ):
        """Test that step and sequence are properly set."""
        payload = {
            "entity_version_id": draft_version.id,
            "name": "sequenced_field",
            "label": "Sequenced Field",
            "data_type": "number",
            "is_free_value": True,
            "step": 3,
            "sequence": 5
        }

        response = client.post("/fields/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["step"] == 3
        assert data["sequence"] == 5

    def test_empty_list_for_version_without_fields(
        self, client: TestClient, admin_headers, draft_version
    ):
        """Test listing fields for version with no fields returns empty list."""
        response = client.get(
            f"/fields/?entity_version_id={draft_version.id}",
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json() == []
