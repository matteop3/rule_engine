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

from app.models.domain import Field, FieldType, Rule, RuleType, Value

# ============================================================
# LIST VALUES TESTS (GET /values/)
# ============================================================


class TestListValues:
    """Tests for GET /values/ endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
            (None, 401),
        ],
    )
    def test_list_values_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_value):
        """RBAC: admin/author can list values, user gets 403, unauthenticated gets 401."""
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.get(f"/values/?field_id={draft_value.field_id}", headers=headers)
        assert response.status_code == expected_status

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

    def test_list_values_limit_over_100_rejected(self, client: TestClient, admin_headers, draft_value):
        """Test that limit > 100 is rejected with 422."""
        response = client.get("/values/?limit=200", headers=admin_headers)

        assert response.status_code == 422


# ============================================================
# READ VALUE TESTS (GET /values/{value_id})
# ============================================================


class TestReadValue:
    """Tests for GET /values/{value_id} endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
            (None, 401),
        ],
    )
    def test_read_value_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_value):
        """RBAC: admin/author can read value, user gets 403, unauthenticated gets 401."""
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.get(f"/values/{draft_value.id}", headers=headers)
        assert response.status_code == expected_status

    def test_read_nonexistent_value_returns_404(self, client: TestClient, admin_headers):
        """Test that reading non-existent value returns 404."""
        response = client.get("/values/99999", headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# CREATE VALUE TESTS (POST /values/)
# ============================================================


class TestCreateValue:
    """Tests for POST /values/ endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 201),
            ("author_headers", 201),
            ("user_headers", 403),
            (None, 401),
        ],
    )
    def test_create_value_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_field):
        """RBAC: admin/author can create values, user gets 403, unauthenticated gets 401."""
        payload = {"field_id": draft_field.id, "value": "RBAC_VALUE", "label": "RBAC Value"}
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.post("/values/", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_cannot_create_value_for_free_field(self, client: TestClient, admin_headers, free_field):
        """
        Test free-field restriction: cannot create Value for is_free_value=True field.
        This is a CRITICAL business rule.
        """
        payload = {"field_id": free_field.id, "value": "SHOULD_FAIL", "label": "Should Fail"}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "free" in response.json()["detail"].lower()

    def test_cannot_create_value_in_published_version(self, client: TestClient, admin_headers, published_field):
        """
        Test DRAFT-only policy: cannot create value for field in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        payload = {"field_id": published_field.id, "value": "SHOULD_FAIL", "label": "Should Fail"}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_create_value_in_archived_version(self, client: TestClient, admin_headers, archived_field):
        """
        Test DRAFT-only policy: cannot create value for field in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        payload = {"field_id": archived_field.id, "value": "SHOULD_FAIL", "label": "Should Fail"}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_create_value_for_nonexistent_field(self, client: TestClient, admin_headers):
        """Test that creating value for non-existent field fails."""
        payload = {"field_id": 99999, "value": "GHOST_VALUE", "label": "Ghost Value"}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 404

    def test_create_value_with_is_default(self, client: TestClient, admin_headers, draft_field):
        """Test that is_default flag is properly set."""
        payload = {"field_id": draft_field.id, "value": "DEFAULT_VALUE", "label": "Default Value", "is_default": True}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["is_default"] is True


# ============================================================
# UPDATE VALUE TESTS (PATCH /values/{value_id})
# ============================================================


class TestUpdateValue:
    """Tests for PATCH /values/{value_id} endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_update_value_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_value):
        """RBAC: admin/author can update values, user gets 403."""
        payload = {"label": "RBAC Updated"}
        headers = request.getfixturevalue(headers_fixture)
        response = client.patch(f"/values/{draft_value.id}", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_cannot_update_value_in_published_version(
        self, client: TestClient, admin_headers, db_session, published_field
    ):
        """
        Test DRAFT-only policy: cannot update value in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        # Create a value for the published field
        value = Value(field_id=published_field.id, value="PUB_VALUE", label="Published Value")
        db_session.add(value)
        db_session.commit()

        payload = {"label": "Should Fail"}

        response = client.patch(f"/values/{value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_update_value_in_archived_version(
        self, client: TestClient, admin_headers, db_session, archived_field
    ):
        """
        Test DRAFT-only policy: cannot update value in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        # Create a value for the archived field
        value = Value(field_id=archived_field.id, value="ARCH_VALUE", label="Archived Value")
        db_session.add(value)
        db_session.commit()

        payload = {"label": "Should Fail"}

        response = client.patch(f"/values/{value.id}", json=payload, headers=admin_headers)

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
            updated_by_id=admin_user.id,
        )
        db_session.add(other_version)
        db_session.flush()

        other_field = Field(
            entity_version_id=other_version.id,
            name="other_field",
            label="Other Field",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        db_session.add(other_field)
        db_session.commit()

        # Try to move value to field in different version
        payload = {"field_id": other_field.id}

        response = client.patch(f"/values/{draft_value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "version" in response.json()["detail"].lower()

    def test_cannot_move_value_to_free_field(self, client: TestClient, admin_headers, draft_value, free_field):
        """
        Test free-field restriction: cannot move value to a free-value field.
        This is a CRITICAL business rule.
        """
        payload = {"field_id": free_field.id}

        response = client.patch(f"/values/{draft_value.id}", json=payload, headers=admin_headers)

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
            is_free_value=False,
        )
        db_session.add(another_field)
        db_session.commit()

        payload = {"field_id": another_field.id}

        response = client.patch(f"/values/{draft_value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["field_id"] == another_field.id

    def test_update_is_default_flag(self, client: TestClient, admin_headers, draft_value):
        """Test that is_default flag can be updated."""
        payload = {"is_default": True}

        response = client.patch(f"/values/{draft_value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["is_default"] is True

    def test_empty_update_handled(self, client: TestClient, admin_headers, draft_value):
        """Test that empty update payload is handled gracefully."""
        response = client.patch(f"/values/{draft_value.id}", json={}, headers=admin_headers)

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

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 204),
            ("author_headers", 204),
            ("user_headers", 403),
            (None, 401),
        ],
    )
    def test_delete_value_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_value):
        """RBAC: admin/author can delete values, user gets 403, unauthenticated gets 401."""
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.delete(f"/values/{draft_value.id}", headers=headers)
        assert response.status_code == expected_status

    def test_cannot_delete_value_in_published_version(
        self, client: TestClient, admin_headers, db_session, published_field
    ):
        """
        Test DRAFT-only policy: cannot delete value in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        value = Value(field_id=published_field.id, value="PUB_VALUE", label="Published Value")
        db_session.add(value)
        db_session.commit()

        response = client.delete(f"/values/{value.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_delete_value_in_archived_version(
        self, client: TestClient, admin_headers, db_session, archived_field
    ):
        """
        Test DRAFT-only policy: cannot delete value in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        value = Value(field_id=archived_field.id, value="ARCH_VALUE", label="Archived Value")
        db_session.add(value)
        db_session.commit()

        response = client.delete(f"/values/{value.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_delete_value_targeted_by_rule(self, client: TestClient, admin_headers, value_in_rule_target):
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

    def test_multiple_values_for_same_field(self, client: TestClient, admin_headers, draft_field):
        """Test that a field can have multiple values."""
        values = ["VALUE_1", "VALUE_2", "VALUE_3"]

        for val in values:
            payload = {"field_id": draft_field.id, "value": val, "label": f"Label {val}"}
            response = client.post("/values/", json=payload, headers=admin_headers)
            assert response.status_code == 201

        # Verify all values exist
        list_response = client.get(f"/values/?field_id={draft_field.id}", headers=admin_headers)
        assert len(list_response.json()) == 3


# ============================================================
# CALCULATION VALUE INTEGRITY TESTS
# ============================================================


class TestValueCalculationIntegrity:
    """Tests for CALCULATION rule guards on Value delete/update."""

    def test_delete_value_blocked_by_calculation_set_value(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """
        Test that deleting a Value referenced by a CALCULATION rule's set_value is blocked.
        This is a CRITICAL business rule.
        """
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_del_target",
            label="Calc Del Target",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_del_source",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        # Create values for target field
        val_referenced = Value(field_id=target_field.id, value="REFERENCED", label="Referenced")
        val_other = Value(field_id=target_field.id, value="OTHER", label="Other")
        db_session.add_all([val_referenced, val_other])
        db_session.flush()

        # Create CALCULATION rule that sets "REFERENCED"
        calc_rule = Rule(
            entity_version_id=draft_version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.CALCULATION.value,
            set_value="REFERENCED",
            conditions={"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        )
        db_session.add(calc_rule)
        db_session.commit()

        # Try to delete the referenced value → should fail
        response = client.delete(f"/values/{val_referenced.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "calculation" in response.json()["detail"].lower()

    def test_delete_value_allowed_when_no_calculation_references(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that deleting a Value not referenced by CALCULATION rules works."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_del_ok",
            label="Calc Del OK",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        db_session.add(target_field)
        db_session.flush()

        val = Value(field_id=target_field.id, value="NO_REF", label="No Ref")
        db_session.add(val)
        db_session.commit()

        response = client.delete(f"/values/{val.id}", headers=admin_headers)

        assert response.status_code == 204

    def test_update_value_string_blocked_by_calculation_set_value(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """
        Test that updating a Value.value string referenced by CALCULATION set_value is blocked.
        This is a CRITICAL business rule.
        """
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_upd_target",
            label="Calc Upd Target",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_upd_source",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        val = Value(field_id=target_field.id, value="CALC_REF", label="Calc Ref")
        db_session.add(val)
        db_session.flush()

        calc_rule = Rule(
            entity_version_id=draft_version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.CALCULATION.value,
            set_value="CALC_REF",
            conditions={"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        )
        db_session.add(calc_rule)
        db_session.commit()

        # Try to change the value string → should fail
        payload = {"value": "CHANGED"}

        response = client.patch(f"/values/{val.id}", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "calculation" in response.json()["detail"].lower()

    def test_update_value_string_allowed_when_no_calculation_references(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that updating Value.value works when no CALCULATION rules reference it."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_upd_ok",
            label="Calc Upd OK",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        db_session.add(target_field)
        db_session.flush()

        val = Value(field_id=target_field.id, value="OLD_VAL", label="Old Val")
        db_session.add(val)
        db_session.commit()

        payload = {"value": "NEW_VAL"}

        response = client.patch(f"/values/{val.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["value"] == "NEW_VAL"

    def test_update_value_label_allowed_even_with_calculation_reference(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that updating label (not value string) is allowed even with CALCULATION ref."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_label_upd",
            label="Calc Label Upd",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_label_src",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        val = Value(field_id=target_field.id, value="STABLE", label="Old Label")
        db_session.add(val)
        db_session.flush()

        calc_rule = Rule(
            entity_version_id=draft_version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.CALCULATION.value,
            set_value="STABLE",
            conditions={"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        )
        db_session.add(calc_rule)
        db_session.commit()

        # Update only the label → should succeed (value string unchanged)
        payload = {"label": "New Label"}

        response = client.patch(f"/values/{val.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["label"] == "New Label"


# ============================================================
# EDGE CASES
# ============================================================


class TestValueEdgeCases:
    """Edge case and boundary tests for Value API."""

    def test_value_with_special_characters(self, client: TestClient, admin_headers, draft_field):
        """Test that value strings with special characters are handled."""
        payload = {"field_id": draft_field.id, "value": "SPECIAL_VALUE-123", "label": "Value with dashes & underscores"}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["value"] == "SPECIAL_VALUE-123"

    def test_value_with_long_label(self, client: TestClient, admin_headers, draft_field):
        """Test that long labels are handled."""
        payload = {"field_id": draft_field.id, "value": "LONG", "label": "A" * 200}

        response = client.post("/values/", json=payload, headers=admin_headers)

        # Should either succeed or return validation error
        assert response.status_code in [201, 422]

    def test_empty_list_for_field_without_values(self, client: TestClient, admin_headers, draft_field):
        """Test listing values for field with no values returns empty list."""
        response = client.get(f"/values/?field_id={draft_field.id}", headers=admin_headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_only_one_default_value_recommended(self, client: TestClient, admin_headers, draft_field):
        """Test behavior when multiple values are marked as default."""
        # Create first default value
        payload1 = {"field_id": draft_field.id, "value": "DEFAULT_1", "label": "Default 1", "is_default": True}
        resp1 = client.post("/values/", json=payload1, headers=admin_headers)
        assert resp1.status_code == 201

        # Create second default value (may succeed - business logic may allow it)
        payload2 = {"field_id": draft_field.id, "value": "DEFAULT_2", "label": "Default 2", "is_default": True}
        resp2 = client.post("/values/", json=payload2, headers=admin_headers)
        # Document current behavior - may succeed or fail
        assert resp2.status_code in [201, 400]


# ============================================================
# SKU MODIFIER CRUD TESTS
# ============================================================


class TestValueSKUModifier:
    """Tests for Value sku_modifier attribute CRUD operations."""

    def test_create_value_with_sku_modifier(self, client: TestClient, admin_headers, draft_field):
        """Test that value can be created with sku_modifier."""
        payload = {"field_id": draft_field.id, "value": "INTEL_I7", "label": "Intel Core i7", "sku_modifier": "I7"}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["value"] == "INTEL_I7"
        assert data["sku_modifier"] == "I7"

    def test_create_value_without_sku_modifier(self, client: TestClient, admin_headers, draft_field):
        """Test that sku_modifier is optional on value creation."""
        payload = {"field_id": draft_field.id, "value": "NO_SKU", "label": "No SKU Modifier"}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["value"] == "NO_SKU"
        assert data["sku_modifier"] is None

    def test_update_value_sku_modifier(self, client: TestClient, admin_headers, draft_value):
        """Test that sku_modifier can be updated on a value in DRAFT version."""
        payload = {"sku_modifier": "NEW_MOD"}

        response = client.patch(f"/values/{draft_value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["sku_modifier"] == "NEW_MOD"

    def test_update_value_with_other_fields_and_sku_modifier(self, client: TestClient, admin_headers, draft_value):
        """Test that sku_modifier can be updated together with other fields."""
        payload = {"label": "Updated Label", "sku_modifier": "UPD"}

        response = client.patch(f"/values/{draft_value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["label"] == "Updated Label"
        assert data["sku_modifier"] == "UPD"

    def test_clear_sku_modifier(self, client: TestClient, admin_headers, db_session, draft_field):
        """Test that sku_modifier can be cleared (set to null)."""
        # Create value with sku_modifier
        value = Value(field_id=draft_field.id, value="WITH_MOD", label="With Modifier", sku_modifier="MOD")
        db_session.add(value)
        db_session.commit()

        # Clear sku_modifier
        payload = {"sku_modifier": None}
        response = client.patch(f"/values/{value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["sku_modifier"] is None

    def test_cannot_update_sku_modifier_on_published_value(
        self, client: TestClient, admin_headers, db_session, published_field
    ):
        """
        Test DRAFT-only policy: sku_modifier cannot be updated on PUBLISHED version.
        This is a CRITICAL business rule.
        """
        # Create value in published version
        value = Value(field_id=published_field.id, value="PUB_VALUE", label="Published Value", sku_modifier="PUB")
        db_session.add(value)
        db_session.commit()

        payload = {"sku_modifier": "SHOULD_FAIL"}

        response = client.patch(f"/values/{value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_read_value_includes_sku_modifier(self, client: TestClient, admin_headers, db_session, draft_field):
        """Test that reading a value includes sku_modifier in response."""
        value = Value(field_id=draft_field.id, value="READ_TEST", label="Read Test", sku_modifier="RT")
        db_session.add(value)
        db_session.commit()

        response = client.get(f"/values/{value.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["value"] == "READ_TEST"
        assert data["sku_modifier"] == "RT"

    def test_list_values_includes_sku_modifier(self, client: TestClient, admin_headers, db_session, draft_field):
        """Test that listing values includes sku_modifier for each value."""
        # Create values with different sku_modifiers
        v1 = Value(field_id=draft_field.id, value="V1", label="Value 1", sku_modifier="M1")
        v2 = Value(field_id=draft_field.id, value="V2", label="Value 2", sku_modifier="M2")
        v3 = Value(field_id=draft_field.id, value="V3", label="Value 3", sku_modifier=None)
        db_session.add_all([v1, v2, v3])
        db_session.commit()

        response = client.get(f"/values/?field_id={draft_field.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

        # Verify each has correct sku_modifier
        values_by_value = {v["value"]: v for v in data}
        assert values_by_value["V1"]["sku_modifier"] == "M1"
        assert values_by_value["V2"]["sku_modifier"] == "M2"
        assert values_by_value["V3"]["sku_modifier"] is None

    def test_move_value_with_sku_modifier_within_version(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that moving value between fields in same version preserves sku_modifier."""
        # Create two fields in same version
        field1 = Field(
            entity_version_id=draft_version.id,
            name="field1",
            label="Field 1",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        field2 = Field(
            entity_version_id=draft_version.id,
            name="field2",
            label="Field 2",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        db_session.add_all([field1, field2])
        db_session.commit()

        # Create value with sku_modifier in field1
        value = Value(field_id=field1.id, value="MOVE_ME", label="Move Me", sku_modifier="MV")
        db_session.add(value)
        db_session.commit()

        # Move to field2
        payload = {"field_id": field2.id}
        response = client.patch(f"/values/{value.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["field_id"] == field2.id
        assert data["sku_modifier"] == "MV"  # Preserved

    def test_sku_modifier_with_special_characters(self, client: TestClient, admin_headers, draft_field):
        """Test that sku_modifier can contain special characters."""
        payload = {"field_id": draft_field.id, "value": "SPECIAL", "label": "Special Chars", "sku_modifier": "X-L_32"}

        response = client.post("/values/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["sku_modifier"] == "X-L_32"

    def test_sku_modifier_max_length(self, client: TestClient, admin_headers, draft_field):
        """Test sku_modifier with long string (boundary test)."""
        long_modifier = "A" * 50  # Test with 50 characters
        payload = {
            "field_id": draft_field.id,
            "value": "LONG_MOD",
            "label": "Long Modifier",
            "sku_modifier": long_modifier,
        }

        response = client.post("/values/", json=payload, headers=admin_headers)

        # Should either succeed or return validation error
        assert response.status_code in [201, 422]
        if response.status_code == 201:
            assert response.json()["sku_modifier"] == long_modifier
