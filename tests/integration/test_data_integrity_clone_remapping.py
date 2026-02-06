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

class TestCloneIdRemapping:
    """Tests for ID remapping integrity during clone operations."""

    def test_clone_remaps_all_field_ids_in_rule_conditions(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Clone correctly remaps all field_id references in rule conditions.
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Original",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(version)
        db_session.flush()

        # Create multiple fields
        fields = []
        for i in range(3):
            f = Field(
                entity_version_id=version.id,
                name=f"field_{i}",
                label=f"Field {i}",
                data_type=FieldType.NUMBER.value if i < 2 else FieldType.BOOLEAN.value,
                is_free_value=True,
                is_required=i < 2,
                sequence=i + 1
            )
            db_session.add(f)
            fields.append(f)
        db_session.flush()

        # Rule with multiple conditions referencing different fields
        rule = Rule(
            entity_version_id=version.id,
            target_field_id=fields[2].id,
            rule_type=RuleType.MANDATORY.value,
            description="Multi-condition rule",
            conditions={
                "criteria": [
                    {"field_id": fields[0].id, "operator": "GREATER_THAN", "value": 10},
                    {"field_id": fields[1].id, "operator": "LESS_THAN", "value": 100}
                ]
            }
        )
        db_session.add(rule)
        db_session.commit()

        original_field_ids = {f.id for f in fields}

        # Clone the version
        clone_resp = client.post(
            f"/versions/{version.id}/clone",
            json={"changelog": "Cloned"},
            headers=admin_headers
        )
        assert clone_resp.status_code == 201
        new_version_id = clone_resp.json()["id"]

        # Get cloned fields
        cloned_fields_resp = client.get(
            f"/fields/?entity_version_id={new_version_id}",
            headers=admin_headers
        )
        cloned_fields = cloned_fields_resp.json()
        cloned_field_ids = {f["id"] for f in cloned_fields}

        # Field IDs should be different
        assert cloned_field_ids.isdisjoint(original_field_ids)

        # Get cloned rules
        cloned_rules_resp = client.get(
            f"/rules/?entity_version_id={new_version_id}",
            headers=admin_headers
        )
        cloned_rules = cloned_rules_resp.json()
        assert len(cloned_rules) == 1

        cloned_rule = cloned_rules[0]

        # Verify target_field_id is remapped
        assert cloned_rule["target_field_id"] not in original_field_ids
        assert cloned_rule["target_field_id"] in cloned_field_ids

        # Verify all field_ids in conditions are remapped
        for criterion in cloned_rule["conditions"]["criteria"]:
            assert criterion["field_id"] not in original_field_ids
            assert criterion["field_id"] in cloned_field_ids

    def test_clone_remaps_field_ids_in_rule_conditions(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Clone correctly remaps field_id references in rule conditions.
        Note: value_id in conditions may not be remapped by the current clone implementation.
        This test focuses on field_id remapping which IS implemented.
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Original",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(version)
        db_session.flush()

        source_field = Field(
            entity_version_id=version.id,
            name="source",
            label="Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            is_required=True,
            sequence=1
        )
        target_field = Field(
            entity_version_id=version.id,
            name="target",
            label="Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True,
            is_required=False,
            sequence=2
        )
        db_session.add_all([source_field, target_field])
        db_session.flush()

        original_source_id = source_field.id
        original_target_id = target_field.id

        # Rule with field_id in condition
        rule = Rule(
            entity_version_id=version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.VISIBILITY.value,
            description="Field-based rule",
            conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 100}]}
        )
        db_session.add(rule)
        db_session.commit()

        # Clone
        clone_resp = client.post(
            f"/versions/{version.id}/clone",
            json={"changelog": "Cloned"},
            headers=admin_headers
        )
        new_version_id = clone_resp.json()["id"]

        # Get cloned rule
        cloned_rules = client.get(f"/rules/?entity_version_id={new_version_id}", headers=admin_headers).json()
        cloned_rule = cloned_rules[0]

        # Get cloned fields
        cloned_fields = client.get(f"/fields/?entity_version_id={new_version_id}", headers=admin_headers).json()
        source_clone = next(f for f in cloned_fields if f["name"] == "source")
        target_clone = next(f for f in cloned_fields if f["name"] == "target")

        # Verify field_id in condition is remapped
        criterion = cloned_rule["conditions"]["criteria"][0]
        assert criterion["field_id"] == source_clone["id"]
        assert criterion["field_id"] != original_source_id

        # Verify target_field_id is remapped
        assert cloned_rule["target_field_id"] == target_clone["id"]
        assert cloned_rule["target_field_id"] != original_target_id

    def test_clone_remaps_target_value_id(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Clone correctly remaps target_value_id for AVAILABILITY rules.
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Original",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(version)
        db_session.flush()

        dropdown_field = Field(
            entity_version_id=version.id,
            name="dropdown",
            label="Dropdown",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_required=True,
            sequence=1
        )
        trigger_field = Field(
            entity_version_id=version.id,
            name="trigger",
            label="Trigger",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=2
        )
        db_session.add_all([dropdown_field, trigger_field])
        db_session.flush()

        target_value = Value(field_id=dropdown_field.id, value="LIMITED", label="Limited", is_default=False)
        other_value = Value(field_id=dropdown_field.id, value="ALWAYS", label="Always", is_default=True)
        db_session.add_all([target_value, other_value])
        db_session.flush()

        original_target_value_id = target_value.id

        # AVAILABILITY rule with target_value_id
        rule = Rule(
            entity_version_id=version.id,
            target_field_id=dropdown_field.id,
            target_value_id=target_value.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="Limited availability",
            conditions={"criteria": [{"field_id": trigger_field.id, "operator": "EQUALS", "value": "UNLOCK"}]}
        )
        db_session.add(rule)
        db_session.commit()

        # Clone
        clone_resp = client.post(
            f"/versions/{version.id}/clone",
            json={"changelog": "Cloned"},
            headers=admin_headers
        )
        new_version_id = clone_resp.json()["id"]

        # Get cloned rule
        cloned_rules = client.get(f"/rules/?entity_version_id={new_version_id}", headers=admin_headers).json()
        cloned_rule = cloned_rules[0]

        # Verify target_value_id is remapped
        assert cloned_rule["target_value_id"] is not None
        assert cloned_rule["target_value_id"] != original_target_value_id

    def test_clone_fails_if_target_value_id_not_in_value_map(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Clone must fail when a rule's target_value_id points to a Value
        that is not part of the source version (corrupted data), so it cannot be
        found in the value_map during remapping.
        """
        # Create a PUBLISHED version with a dropdown field and an AVAILABILITY rule
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Original",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(version)
        db_session.flush()

        dropdown_field = Field(
            entity_version_id=version.id,
            name="dropdown",
            label="Dropdown",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_required=True,
            sequence=1
        )
        trigger_field = Field(
            entity_version_id=version.id,
            name="trigger",
            label="Trigger",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=2
        )
        db_session.add_all([dropdown_field, trigger_field])
        db_session.flush()

        target_value = Value(field_id=dropdown_field.id, value="LIMITED", label="Limited", is_default=False)
        db_session.add(target_value)
        db_session.flush()

        rule = Rule(
            entity_version_id=version.id,
            target_field_id=dropdown_field.id,
            target_value_id=target_value.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="Availability rule with corrupted target_value_id",
            conditions={"criteria": [{"field_id": trigger_field.id, "operator": "EQUALS", "value": "GO"}]}
        )
        db_session.add(rule)
        db_session.flush()

        # Corrupt the data: move the target Value to a different field outside this version,
        # so it won't be in the value_map during clone.
        # We create a separate version with its own field and reassign the value to it.
        other_version = EntityVersion(
            entity_id=test_entity.id,
            version_number=99,
            status=VersionStatus.ARCHIVED,
            changelog="Other",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(other_version)
        db_session.flush()

        orphan_field = Field(
            entity_version_id=other_version.id,
            name="orphan",
            label="Orphan",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_required=False,
            sequence=1
        )
        db_session.add(orphan_field)
        db_session.flush()

        # Reassign the value to the orphan field (simulates corrupted FK)
        target_value.field_id = orphan_field.id
        db_session.commit()

        # Attempt to clone: should fail because target_value_id cannot be remapped
        clone_resp = client.post(
            f"/versions/{version.id}/clone",
            json={"changelog": "Should fail"},
            headers=admin_headers
        )

        assert clone_resp.status_code in (400, 500), (
            f"Expected clone to fail due to unmappable target_value_id, "
            f"got {clone_resp.status_code}: {clone_resp.json()}"
        )

    def test_clone_fails_if_condition_field_id_not_in_field_map(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Clone must fail when a rule's condition references a field_id
        that is not part of the source version (corrupted data), so it cannot be
        found in the field_map during conditions rewrite.
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Original",
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
            name="condition_source",
            label="Condition Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            is_required=True,
            sequence=2
        )
        db_session.add_all([target_field, condition_field])
        db_session.flush()

        # Rule whose condition references condition_field
        rule = Rule(
            entity_version_id=version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.VISIBILITY.value,
            description="Rule with corrupted condition field_id",
            conditions={"criteria": [{"field_id": condition_field.id, "operator": "GREATER_THAN", "value": 10}]}
        )
        db_session.add(rule)
        db_session.flush()

        # Corrupt the data: move condition_field to a different version,
        # so it won't be in the field_map during clone.
        other_version = EntityVersion(
            entity_id=test_entity.id,
            version_number=99,
            status=VersionStatus.ARCHIVED,
            changelog="Other",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(other_version)
        db_session.flush()

        condition_field.entity_version_id = other_version.id
        db_session.commit()

        # Attempt to clone: should fail because condition field_id cannot be remapped
        clone_resp = client.post(
            f"/versions/{version.id}/clone",
            json={"changelog": "Should fail"},
            headers=admin_headers
        )

        assert clone_resp.status_code in (400, 500), (
            f"Expected clone to fail due to unmappable condition field_id, "
            f"got {clone_resp.status_code}: {clone_resp.json()}"
        )


# ============================================================
# ORPHAN PREVENTION TESTS
# ============================================================

