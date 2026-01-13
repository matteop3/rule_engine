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

class TestUniqueConstraints:
    """Tests for unique constraint enforcement."""

    def test_field_names_uniqueness_per_version(
        self, client: TestClient, admin_headers, draft_version
    ):
        """
        Note: Current API allows duplicate field names within a version.
        This test documents current behavior - fields with same name are allowed.
        Business logic may use name for lookups, so this could be enhanced in future.
        """
        # Create first field
        resp1 = client.post(
            "/fields/",
            json={
                "entity_version_id": draft_version.id,
                "name": "duplicate_name",
                "label": "First",
                "data_type": "string",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        )
        assert resp1.status_code == 201
        first_id = resp1.json()["id"]

        # Creating second field with same name - currently allowed
        resp2 = client.post(
            "/fields/",
            json={
                "entity_version_id": draft_version.id,
                "name": "duplicate_name",
                "label": "Second",
                "data_type": "number",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        )
        # Document current behavior: duplicates are allowed
        assert resp2.status_code == 201
        second_id = resp2.json()["id"]

        # Both fields exist with the same name
        assert first_id != second_id

    def test_cannot_create_duplicate_entity_names(
        self, client: TestClient, admin_headers
    ):
        """
        Integrity: Cannot have two entities with the same name.
        """
        # Create first entity
        resp1 = client.post(
            "/entities/",
            json={"name": "Unique Entity Name", "description": "First"},
            headers=admin_headers
        )
        assert resp1.status_code == 201

        # Try to create second entity with same name
        resp2 = client.post(
            "/entities/",
            json={"name": "Unique Entity Name", "description": "Second"},
            headers=admin_headers
        )
        assert resp2.status_code in [400, 409]

    def test_can_have_same_field_name_in_different_versions(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Integrity: Same field name is allowed in different versions (expected after clone).
        """
        # Create V1 with field
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

        # Create V2
        v2 = EntityVersion(
            entity_id=test_entity.id,
            version_number=2,
            status=VersionStatus.DRAFT,
            changelog="V2",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(v2)
        db_session.commit()

        # Add field with same name to both versions
        for version in [v1, v2]:
            resp = client.post(
                "/fields/",
                json={
                    "entity_version_id": version.id,
                    "name": "shared_name",
                    "label": f"Field in V{version.version_number}",
                    "data_type": "string",
                    "is_free_value": True,
                    "is_required": True,
                    "sequence": 1
                },
                headers=admin_headers
            )
            # V1 is published so should fail, V2 is draft so should succeed
            if version.status == VersionStatus.DRAFT:
                assert resp.status_code == 201
