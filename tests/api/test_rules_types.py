"""
Test suite for Rules API endpoints.

Tests the full CRUD lifecycle for Rule management including:
- RBAC enforcement (admin/author only)
- DRAFT-only modification policy
- Target field/value ownership validation
- Version immutability on updates

Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Field, Value, Rule, RuleType, FieldType



# ============================================================
# RULE TYPE SPECIFIC TESTS
# ============================================================

class TestRuleTypes:
    """Tests for specific rule type behaviors."""

    def test_validation_rule_with_error_message(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that validation rules can have error messages."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="validation_target",
            label="Validation Target",
            data_type=FieldType.DATE.value,
            is_free_value=True
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="validation_source",
            label="Validation Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "validation",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
            "error_message": "Validation failed"
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["error_message"] == "Validation failed"

    def test_availability_rule_with_value_target(
        self, client: TestClient, admin_headers, rule_with_value_target
    ):
        """Test that availability rules can target specific values."""
        rule = rule_with_value_target["rule"]

        response = client.get(f"/rules/{rule.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["rule_type"] == "availability"
        assert data["target_value_id"] is not None


# ============================================================
# EDGE CASES
# ============================================================

