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

class TestDataConsistency:
    """Tests for data consistency after various operations."""

    def test_published_version_data_unchanged_after_clone_modifications(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Modifying cloned version doesn't affect original published version.
        """
        # Create and publish original
        original = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Original",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(original)
        db_session.flush()

        original_field = Field(
            entity_version_id=original.id,
            name="original_field",
            label="Original Label",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=1
        )
        db_session.add(original_field)
        db_session.commit()

        original_field_id = original_field.id

        # Clone
        clone_resp = client.post(
            f"/versions/{original.id}/clone",
            json={"changelog": "Clone"},
            headers=admin_headers
        )
        clone_id = clone_resp.json()["id"]

        # Get cloned field and modify it
        clone_fields = client.get(f"/fields/?entity_version_id={clone_id}", headers=admin_headers).json()
        clone_field_id = clone_fields[0]["id"]

        # Update cloned field
        client.put(
            f"/fields/{clone_field_id}",
            json={
                "entity_version_id": clone_id,
                "name": "modified_field",
                "label": "Modified Label",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 1
            },
            headers=admin_headers
        )

        # Verify original is unchanged
        original_check = client.get(f"/fields/{original_field_id}", headers=admin_headers).json()
        assert original_check["name"] == "original_field"
        assert original_check["label"] == "Original Label"
        assert original_check["is_required"] is True

    def test_version_isolation_engine_calculation(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Engine calculation uses only data from the specified version.
        """
        # Create V1 with specific rule
        v1 = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="V1",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(v1)
        db_session.flush()

        v1_field = Field(
            entity_version_id=v1.id,
            name="amount",
            label="Amount",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            is_required=True,
            sequence=1
        )
        v1_optional = Field(
            entity_version_id=v1.id,
            name="extra",
            label="Extra",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True,
            is_required=False,
            sequence=2
        )
        db_session.add_all([v1_field, v1_optional])
        db_session.flush()

        # V1 rule: Extra mandatory if amount > 100
        v1_rule = Rule(
            entity_version_id=v1.id,
            target_field_id=v1_optional.id,
            rule_type=RuleType.MANDATORY.value,
            description="V1: Extra if > 100",
            conditions={"criteria": [{"field_id": v1_field.id, "operator": "GREATER_THAN", "value": 100}]}
        )
        db_session.add(v1_rule)
        db_session.commit()

        # Calculate with V1 - amount 200 should trigger mandatory
        calc_v1 = client.post(
            "/engine/calculate",
            json={
                "entity_id": test_entity.id,
                "entity_version_id": v1.id,
                "current_state": [{"field_id": v1_field.id, "value": 200}]
            },
            headers=admin_headers
        ).json()

        v1_extra = next(f for f in calc_v1["fields"] if f["field_id"] == v1_optional.id)
        assert v1_extra["is_required"] is True

        # Archive V1 manually and create V2 with different rule
        db_session.refresh(v1)
        v1.status = VersionStatus.ARCHIVED

        v2 = EntityVersion(
            entity_id=test_entity.id,
            version_number=2,
            status=VersionStatus.PUBLISHED,
            changelog="V2",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(v2)
        db_session.flush()

        v2_field = Field(
            entity_version_id=v2.id,
            name="amount",
            label="Amount",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            is_required=True,
            sequence=1
        )
        v2_optional = Field(
            entity_version_id=v2.id,
            name="extra",
            label="Extra",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True,
            is_required=False,
            sequence=2
        )
        db_session.add_all([v2_field, v2_optional])
        db_session.flush()

        # V2 rule: Extra mandatory only if amount > 1000 (higher threshold)
        v2_rule = Rule(
            entity_version_id=v2.id,
            target_field_id=v2_optional.id,
            rule_type=RuleType.MANDATORY.value,
            description="V2: Extra if > 1000",
            conditions={"criteria": [{"field_id": v2_field.id, "operator": "GREATER_THAN", "value": 1000}]}
        )
        db_session.add(v2_rule)
        db_session.commit()

        # Calculate with V2 - amount 200 should NOT trigger mandatory
        calc_v2 = client.post(
            "/engine/calculate",
            json={
                "entity_id": test_entity.id,
                "entity_version_id": v2.id,
                "current_state": [{"field_id": v2_field.id, "value": 200}]
            },
            headers=admin_headers
        ).json()

        v2_extra = next(f for f in calc_v2["fields"] if f["field_id"] == v2_optional.id)
        assert v2_extra["is_required"] is False  # V2 threshold is 1000


# ============================================================
# UNIQUE CONSTRAINT TESTS
# ============================================================

