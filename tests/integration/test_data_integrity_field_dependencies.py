"""
Data Integrity Tests.

Tests for referential integrity across the data model:
- Field → Rule dependencies
- Value → Rule dependencies
- Cascade delete behavior
- Clone ID remapping integrity
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    FieldType, RuleType, VersionStatus
)


# ============================================================
# FIELD → RULE DEPENDENCY TESTS
# ============================================================

class TestFieldRuleDependencies:
    """Tests for field dependencies in rules."""

    def test_cannot_delete_field_used_as_rule_target(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Cannot delete a field that is the target_field_id of a rule.
        """
        # Create version with field and rule
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Test",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(version)
        db_session.flush()

        target_field = Field(
            entity_version_id=version.id,
            name="target_field",
            label="Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True,
            is_required=False,
            sequence=1
        )
        source_field = Field(
            entity_version_id=version.id,
            name="source_field",
            label="Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            is_required=True,
            sequence=2
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        rule = Rule(
            entity_version_id=version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.MANDATORY.value,
            description="Test rule",
            conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        )
        db_session.add(rule)
        db_session.commit()

        # Try to delete target field - should fail due to rule dependency
        delete_resp = client.delete(f"/fields/{target_field.id}", headers=admin_headers)

        # Expect 409 Conflict or similar error
        assert delete_resp.status_code in [400, 409]
        assert "rule" in delete_resp.json()["detail"].lower() or "depend" in delete_resp.json()["detail"].lower()

    def test_cannot_delete_field_used_in_rule_condition(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Cannot delete a field that is referenced in rule conditions.
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Test",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(version)
        db_session.flush()

        target_field = Field(
            entity_version_id=version.id,
            name="target",
            label="Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True,
            is_required=False,
            sequence=1
        )
        condition_field = Field(
            entity_version_id=version.id,
            name="condition",
            label="Condition",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            is_required=True,
            sequence=2
        )
        db_session.add_all([target_field, condition_field])
        db_session.flush()

        # Rule uses condition_field in its criteria
        rule = Rule(
            entity_version_id=version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.VISIBILITY.value,
            description="Test rule",
            conditions={"criteria": [{"field_id": condition_field.id, "operator": "EQUALS", "value": 100}]}
        )
        db_session.add(rule)
        db_session.commit()

        # Try to delete condition field - should fail
        delete_resp = client.delete(f"/fields/{condition_field.id}", headers=admin_headers)

        assert delete_resp.status_code in [400, 409]

    def test_can_delete_field_after_removing_dependent_rules(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Can delete field after removing all dependent rules.
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Test",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(version)
        db_session.flush()

        field = Field(
            entity_version_id=version.id,
            name="deletable",
            label="Deletable",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=1
        )
        db_session.add(field)
        db_session.flush()

        rule = Rule(
            entity_version_id=version.id,
            target_field_id=field.id,
            rule_type=RuleType.VALIDATION.value,
            description="Will be deleted",
            conditions={"criteria": []}
        )
        db_session.add(rule)
        db_session.commit()

        rule_id = rule.id
        field_id = field.id

        # First delete the rule
        delete_rule_resp = client.delete(f"/rules/{rule_id}", headers=admin_headers)
        assert delete_rule_resp.status_code == 204

        # Now we can delete the field
        delete_field_resp = client.delete(f"/fields/{field_id}", headers=admin_headers)
        assert delete_field_resp.status_code == 204


# ============================================================
# VALUE → RULE DEPENDENCY TESTS
# ============================================================

