"""
End-to-End Integration Tests.

Tests complete flows across multiple routers:
- Entity creation → Version → Fields → Values → Rules → Engine

These tests validate that all components work together correctly
in real-world scenarios.
"""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    FieldType, RuleType, VersionStatus
)


# ============================================================
# COMPLETE ENTITY LIFECYCLE TESTS
# ============================================================

class TestRBACEndToEnd:
    """End-to-end tests for role-based access control."""

    def test_user_role_can_only_use_published_versions(
        self, client: TestClient, admin_headers, user_headers
    ):
        """
        E2E: USER role can only calculate on PUBLISHED versions.
        """
        # Admin creates entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "RBAC Test Entity", "description": "RBAC test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Draft"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Add field
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "test",
                "label": "Test",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 1
            },
            headers=admin_headers
        )
        field_id = field_resp.json()["id"]

        # USER tries to calculate on DRAFT - should fail
        calc_draft = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "entity_version_id": version_id,
                "current_state": []
            },
            headers=user_headers
        )
        assert calc_draft.status_code == 403

        # Admin publishes
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        # USER calculates on PUBLISHED - should succeed
        calc_published = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": []
            },
            headers=user_headers
        )
        assert calc_published.status_code == 200

    def test_author_can_preview_draft_via_engine(
        self, client: TestClient, admin_headers, author_headers
    ):
        """
        E2E: AUTHOR role can calculate on DRAFT versions for preview.
        """
        # Admin creates entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Author Preview Test", "description": "Author preview"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Author creates version (authors can create versions)
        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Author draft"},
            headers=author_headers
        )
        version_id = version_resp.json()["id"]

        # Author adds field
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "preview_field",
                "label": "Preview Field",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=author_headers
        )
        field_id = field_resp.json()["id"]

        # Author previews via engine
        calc_preview = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "entity_version_id": version_id,
                "current_state": [{"field_id": field_id, "value": 42}]
            },
            headers=author_headers
        )
        assert calc_preview.status_code == 200
        result = calc_preview.json()

        field_result = next(f for f in result["fields"] if f["field_id"] == field_id)
        assert field_result["current_value"] == 42


# ============================================================
# COMPLEX RULE INTERACTION TESTS
# ============================================================

