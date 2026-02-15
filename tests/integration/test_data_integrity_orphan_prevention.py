"""
Data Integrity Tests.

Tests for referential integrity across the data model:
- Field → Rule dependencies
- Value → Rule dependencies
- Cascade delete behavior
- Clone ID remapping integrity
"""

from fastapi.testclient import TestClient

from app.models.domain import EntityVersion, Field, FieldType, VersionStatus

# ============================================================
# FIELD → RULE DEPENDENCY TESTS
# ============================================================


class TestOrphanPrevention:
    """Tests to ensure no orphaned data is created."""

    def test_field_cannot_reference_nonexistent_version(self, client: TestClient, admin_headers):
        """
        Integrity: Cannot create field for non-existent version.
        """
        resp = client.post(
            "/fields/",
            json={
                "entity_version_id": 99999,
                "name": "orphan",
                "label": "Orphan",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 1,
            },
            headers=admin_headers,
        )

        assert resp.status_code == 404

    def test_value_cannot_reference_nonexistent_field(self, client: TestClient, admin_headers):
        """
        Integrity: Cannot create value for non-existent field.
        """
        resp = client.post(
            "/values/",
            json={"field_id": 99999, "value": "ORPHAN", "label": "Orphan", "is_default": True},
            headers=admin_headers,
        )

        assert resp.status_code == 404

    def test_rule_cannot_reference_nonexistent_target_field(self, client: TestClient, admin_headers, draft_version):
        """
        Integrity: Cannot create rule with non-existent target_field_id.
        """
        resp = client.post(
            "/rules/",
            json={
                "entity_version_id": draft_version.id,
                "target_field_id": 99999,
                "rule_type": "validation",
                "description": "Orphan rule",
                "conditions": {"criteria": []},
            },
            headers=admin_headers,
        )

        # 400/404 for business logic errors, 422 for Pydantic validation errors
        assert resp.status_code in [400, 404, 422]

    def test_rule_cannot_reference_field_from_different_version(
        self, client: TestClient, admin_headers, db_session, test_entity, second_entity, admin_user
    ):
        """
        Integrity: Rule cannot reference a field from a different version.
        """
        # Version 1 with its field
        v1 = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="V1",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(v1)
        db_session.flush()

        v1_field = Field(
            entity_version_id=v1.id,
            name="v1_field",
            label="V1 Field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=1,
        )
        db_session.add(v1_field)
        db_session.flush()

        # Version 2 on different entity
        v2 = EntityVersion(
            entity_id=second_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="V2",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(v2)
        db_session.commit()

        # Try to create rule in V2 referencing V1's field
        resp = client.post(
            "/rules/",
            json={
                "entity_version_id": v2.id,
                "target_field_id": v1_field.id,  # Wrong version!
                "rule_type": "validation",
                "description": "Cross-version rule",
                "conditions": {"criteria": []},
            },
            headers=admin_headers,
        )

        # Should fail - field doesn't belong to this version
        # 400 for business logic, 422 for validation
        assert resp.status_code in [400, 422]


# ============================================================
# DATA CONSISTENCY AFTER OPERATIONS
# ============================================================
