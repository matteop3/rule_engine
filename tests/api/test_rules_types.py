"""
Test suite for Rules API endpoints.

Tests the full CRUD lifecycle for Rule management including:
- RBAC enforcement (admin/author only)
- DRAFT-only modification policy
- Target field/value ownership validation
- Version immutability on updates

Each test is atomic and independent.
"""

from fastapi.testclient import TestClient

from app.models.domain import Field, FieldType, Value

# ============================================================
# RULE TYPE SPECIFIC TESTS
# ============================================================


class TestRuleTypes:
    """Tests for specific rule type behaviors."""

    def test_validation_rule_with_error_message(self, client: TestClient, admin_headers, db_session, draft_version):
        """Test that validation rules can have error messages."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="validation_target",
            label="Validation Target",
            data_type=FieldType.DATE.value,
            is_free_value=True,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="validation_source",
            label="Validation Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "validation",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
            "error_message": "Validation failed",
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["error_message"] == "Validation failed"

    def test_availability_rule_with_value_target(self, client: TestClient, admin_headers, rule_with_value_target):
        """Test that availability rules can target specific values."""
        rule = rule_with_value_target["rule"]

        response = client.get(f"/rules/{rule.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["rule_type"] == "availability"
        assert data["target_value_id"] is not None


# ============================================================
# CALCULATION RULE TESTS
# ============================================================


class TestCalculationRuleType:
    """Tests for CALCULATION rule type API behavior."""

    def test_create_calculation_rule_with_set_value(self, client: TestClient, admin_headers, db_session, draft_version):
        """Test that CALCULATION rule can be created with set_value on a free-value field."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_target",
            label="Calc Target",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_source",
            label="Calc Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "calculation",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "trigger"}]},
            "set_value": "forced_result",
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["rule_type"] == "calculation"
        assert data["set_value"] == "forced_result"

    def test_calculation_requires_set_value(self, client: TestClient, admin_headers, db_session, draft_version):
        """Test that CALCULATION rule without set_value is rejected (422)."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_no_sv",
            label="Calc No SetValue",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_no_sv_src",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "calculation",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
            # No set_value
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_calculation_rejects_target_value_id(self, client: TestClient, admin_headers, db_session, draft_version):
        """Test that CALCULATION rule with target_value_id is rejected (422)."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_tvi",
            label="Calc TVI",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_tvi_src",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        val = Value(field_id=target_field.id, value="VAL1", label="Val 1")
        db_session.add(val)
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "target_value_id": val.id,
            "rule_type": "calculation",
            "set_value": "VAL1",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_calculation_rejects_error_message(self, client: TestClient, admin_headers, db_session, draft_version):
        """Test that CALCULATION rule with error_message is rejected (422)."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_em",
            label="Calc EM",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_em_src",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "calculation",
            "set_value": "forced",
            "error_message": "should not be here",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_set_value_rejected_for_non_calculation_types(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that set_value is rejected for non-CALCULATION rule types (422)."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="non_calc_sv",
            label="Non Calc SV",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="non_calc_sv_src",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "visibility",
            "set_value": "should_fail",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_set_value_validated_against_field_values_non_free(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that set_value must match a defined Value for non-free fields (400)."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_val_check",
            label="Calc Val Check",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_val_check_src",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        val = Value(field_id=target_field.id, value="ALLOWED", label="Allowed")
        db_session.add(val)
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "calculation",
            "set_value": "NOT_ALLOWED",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "set_value" in response.json()["detail"].lower()

    def test_set_value_accepted_for_free_field(self, client: TestClient, admin_headers, db_session, draft_version):
        """Test that any set_value is accepted for free-value fields."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_free_sv",
            label="Calc Free SV",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_free_sv_src",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "calculation",
            "set_value": "any_arbitrary_value",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["set_value"] == "any_arbitrary_value"

    def test_set_value_valid_for_non_free_field(self, client: TestClient, admin_headers, db_session, draft_version):
        """Test that a valid set_value is accepted for non-free fields."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="calc_valid_sv",
            label="Calc Valid SV",
            data_type=FieldType.STRING.value,
            is_free_value=False,
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="calc_valid_sv_src",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        val = Value(field_id=target_field.id, value="VALID_VALUE", label="Valid")
        db_session.add(val)
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "calculation",
            "set_value": "VALID_VALUE",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": "x"}]},
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["set_value"] == "VALID_VALUE"


# ============================================================
# EDGE CASES
# ============================================================
