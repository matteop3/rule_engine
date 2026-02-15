"""
End-to-End Integration Tests.

Tests complete flows across multiple routers:
- Entity creation → Version → Fields → Values → Rules → Engine

These tests validate that all components work together correctly
in real-world scenarios.
"""

from fastapi.testclient import TestClient

# ============================================================
# COMPLETE ENTITY LIFECYCLE TESTS
# ============================================================


class TestCascadeOperations:
    """Tests cascade behavior across entities."""

    def test_delete_draft_version_removes_all_children(self, client: TestClient, admin_headers, db_session):
        """
        E2E: Delete DRAFT version → Verify all fields, values deleted.
        Note: Rules require valid conditions, so we test with fields/values only.
        """
        # Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Cascade Delete Test", "description": "Test cascade delete"},
            headers=admin_headers,
        )
        entity_id = entity_resp.json()["id"]

        # Create Version
        version_resp = client.post(
            "/versions/", json={"entity_id": entity_id, "changelog": "To be deleted"}, headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Add field
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "test_field",
                "label": "Test Field",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1,
            },
            headers=admin_headers,
        )
        field_id = field_resp.json()["id"]

        # Add value
        value_resp = client.post(
            "/values/",
            json={"field_id": field_id, "value": "TEST", "label": "Test", "is_default": True},
            headers=admin_headers,
        )
        value_id = value_resp.json()["id"]

        # Verify all exist
        assert client.get(f"/fields/{field_id}", headers=admin_headers).status_code == 200
        assert client.get(f"/values/{value_id}", headers=admin_headers).status_code == 200

        # Delete version
        delete_resp = client.delete(f"/versions/{version_id}", headers=admin_headers)
        assert delete_resp.status_code == 204

        # Verify cascade delete
        assert client.get(f"/versions/{version_id}", headers=admin_headers).status_code == 404
        assert client.get(f"/fields/{field_id}", headers=admin_headers).status_code == 404
        assert client.get(f"/values/{value_id}", headers=admin_headers).status_code == 404

    def test_entity_delete_requires_versions_deleted_first(self, client: TestClient, admin_headers):
        """
        E2E: Entity with versions cannot be deleted directly.
        Must delete versions first, then entity.
        """
        # Create Entity
        entity_resp = client.post(
            "/entities/", json={"name": "Delete Order Test", "description": "Test delete order"}, headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create version
        v1_resp = client.post("/versions/", json={"entity_id": entity_id, "changelog": "V1"}, headers=admin_headers)
        v1_id = v1_resp.json()["id"]

        # Add field to V1
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "field",
                "label": "Field",
                "data_type": "string",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1,
            },
            headers=admin_headers,
        )
        field_id = field_resp.json()["id"]

        # Try to delete entity with version - should fail with 409
        delete_entity_resp = client.delete(f"/entities/{entity_id}", headers=admin_headers)
        assert delete_entity_resp.status_code == 409
        assert "version" in delete_entity_resp.json()["detail"].lower()

        # Entity still exists
        assert client.get(f"/entities/{entity_id}", headers=admin_headers).status_code == 200

        # Delete version first (DRAFT can be deleted)
        delete_version_resp = client.delete(f"/versions/{v1_id}", headers=admin_headers)
        assert delete_version_resp.status_code == 204

        # Now entity can be deleted
        delete_entity_resp2 = client.delete(f"/entities/{entity_id}", headers=admin_headers)
        assert delete_entity_resp2.status_code == 204

        # Verify entity is gone
        assert client.get(f"/entities/{entity_id}", headers=admin_headers).status_code == 404


# ============================================================
# ROLE-BASED ACCESS CONTROL E2E TESTS
# ============================================================
