"""
Data Integrity Tests.

Tests for referential integrity across the data model:
- Field → Rule dependencies
- Value → Rule dependencies
- Cascade delete behavior
- Clone ID remapping integrity
"""

from fastapi.testclient import TestClient

from app.models.domain import EntityVersion, Field, FieldType, Rule, RuleType, Value, VersionStatus

# ============================================================
# FIELD → RULE DEPENDENCY TESTS
# ============================================================


class TestValueRuleDependencies:
    """Tests for value dependencies in rules."""

    def test_cannot_delete_value_used_as_rule_target(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Cannot delete a value that is the target_value_id of a rule.
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Test",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(version)
        db_session.flush()

        field = Field(
            entity_version_id=version.id,
            name="dropdown",
            label="Dropdown",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_required=True,
            sequence=1,
        )
        condition_field = Field(
            entity_version_id=version.id,
            name="condition",
            label="Condition",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=2,
        )
        db_session.add_all([field, condition_field])
        db_session.flush()

        value = Value(field_id=field.id, value="TARGET", label="Target", is_default=True)
        other_value = Value(field_id=field.id, value="OTHER", label="Other", is_default=False)
        db_session.add_all([value, other_value])
        db_session.flush()

        # AVAILABILITY rule targeting specific value
        rule = Rule(
            entity_version_id=version.id,
            target_field_id=field.id,
            target_value_id=value.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="Value availability rule",
            conditions={"criteria": [{"field_id": condition_field.id, "operator": "EQUALS", "value": "YES"}]},
        )
        db_session.add(rule)
        db_session.commit()

        # Try to delete the targeted value - should fail
        delete_resp = client.delete(f"/values/{value.id}", headers=admin_headers)

        assert delete_resp.status_code in [400, 409]

    def test_cannot_delete_value_used_in_rule_condition(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Cannot delete a value that is referenced in rule conditions (value_id).
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Test",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(version)
        db_session.flush()

        source_field = Field(
            entity_version_id=version.id,
            name="source",
            label="Source",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_required=True,
            sequence=1,
        )
        target_field = Field(
            entity_version_id=version.id,
            name="target",
            label="Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True,
            is_required=False,
            sequence=2,
        )
        db_session.add_all([source_field, target_field])
        db_session.flush()

        condition_value = Value(field_id=source_field.id, value="TRIGGER", label="Trigger", is_default=True)
        db_session.add(condition_value)
        db_session.flush()

        # Rule uses condition_value.id in its criteria
        rule = Rule(
            entity_version_id=version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.VISIBILITY.value,
            description="Condition uses value_id",
            conditions={
                "criteria": [
                    {
                        "field_id": source_field.id,
                        "value_id": condition_value.id,
                        "operator": "EQUALS",
                        "value": "TRIGGER",
                    }
                ]
            },
        )
        db_session.add(rule)
        db_session.commit()

        # Try to delete the condition value - should fail
        delete_resp = client.delete(f"/values/{condition_value.id}", headers=admin_headers)

        assert delete_resp.status_code in [400, 409]


# ============================================================
# CLONE ID REMAPPING INTEGRITY TESTS
# ============================================================
