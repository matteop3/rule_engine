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
# EDGE CASES
# ============================================================

class TestRuleEdgeCases:
    """Edge case and boundary tests for Rule API."""

    def test_rule_description_optional(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that rule description is optional."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="no_desc_target",
            label="Target",
            data_type=FieldType.STRING.value,
            is_free_value=True
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="no_desc_source",
            label="Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "mandatory",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
            # No description
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201

    def test_multiple_rules_same_target(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that multiple rules can target the same field."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="multi_rule_target",
            label="Multi Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="multi_rule_source",
            label="Multi Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        # Create first rule
        payload1 = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "visibility",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        }
        resp1 = client.post("/rules/", json=payload1, headers=admin_headers)
        assert resp1.status_code == 201

        # Create second rule
        payload2 = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "mandatory",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "LESS_THAN", "value": 100}]}
        }
        resp2 = client.post("/rules/", json=payload2, headers=admin_headers)
        assert resp2.status_code == 201

        # Verify both exist
        list_response = client.get(
            f"/rules/?entity_version_id={draft_version.id}",
            headers=admin_headers
        )
        rules = [r for r in list_response.json() if r["target_field_id"] == target_field.id]
        assert len(rules) == 2

    def test_rule_with_multiple_criteria(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that rules can have multiple criteria (implicit AND)."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="multi_criteria_target",
            label="Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        source_field1 = Field(
            entity_version_id=draft_version.id,
            name="multi_criteria_source1",
            label="Source 1",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        source_field2 = Field(
            entity_version_id=draft_version.id,
            name="multi_criteria_source2",
            label="Source 2",
            data_type=FieldType.STRING.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field1, source_field2])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "mandatory",
            "conditions": {
                "criteria": [
                    {"field_id": source_field1.id, "operator": "GREATER_THAN", "value": 100},
                    {"field_id": source_field2.id, "operator": "EQUALS", "value": "ACTIVE"}
                ]
            }
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert len(data["conditions"]["criteria"]) == 2
