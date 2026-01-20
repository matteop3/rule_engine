"""
Tests for Configuration finalize operations.
Covers finalize functionality, idempotency, constraints, and access control.
"""
import pytest
from app.models.domain import Configuration, ConfigurationStatus


# ============================================================
# BASIC FINALIZE FUNCTIONALITY
# ============================================================

class TestFinalizeBasicFunctionality:
    """Tests for basic finalize operation behavior."""

    def test_finalize_changes_status(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """Finalize should change status to FINALIZED."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "FINALIZED"

    def test_finalize_returns_updated_config(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """Response should contain full configuration with new status."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all expected fields
        assert data["id"] == draft_configuration.id
        assert data["status"] == "FINALIZED"
        assert "entity_version_id" in data
        assert "name" in data
        assert "is_complete" in data
        assert "data" in data

    def test_finalize_preserves_all_data(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """Finalize should not alter any data."""
        original_data = draft_configuration.data.copy()
        original_name = draft_configuration.name

        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()

        # Data should be identical
        assert data["name"] == original_name
        assert len(data["data"]) == len(original_data)
        for orig, final in zip(original_data, data["data"]):
            assert orig["field_id"] == final["field_id"]
            assert orig["value"] == final["value"]

    def test_finalize_preserves_version(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """Finalize should not change entity_version_id."""
        original_version_id = draft_configuration.entity_version_id

        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["entity_version_id"] == original_version_id

    def test_finalize_preserves_is_complete(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """Finalize should preserve is_complete flag."""
        original_is_complete = draft_configuration.is_complete

        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_complete"] == original_is_complete


# ============================================================
# FINALIZE IDEMPOTENCY AND CONSTRAINTS
# ============================================================

class TestFinalizeIdempotencyAndConstraints:
    """Tests for finalize idempotency and constraint handling."""

    def test_finalize_already_finalized(
        self, client, lifecycle_user_headers, finalized_configuration
    ):
        """Cannot finalize an already FINALIZED configuration."""
        response = client.post(
            f"/configurations/{finalized_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 409
        assert "already FINALIZED" in response.json()["detail"]

    def test_finalize_deleted_config_accessible_but_finalized(
        self, client, lifecycle_admin_headers, soft_deleted_configuration
    ):
        """Soft-deleted config is accessible but already FINALIZED."""
        response = client.post(
            f"/configurations/{soft_deleted_configuration.id}/finalize",
            headers=lifecycle_admin_headers
        )

        # soft_deleted_configuration is already FINALIZED
        assert response.status_code == 409

    def test_finalize_updates_audit_fields(
        self, client, db_session, lifecycle_user_headers,
        draft_configuration, lifecycle_user
    ):
        """Finalize should set updated_by_id to current user."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated_by_id"] == lifecycle_user.id

    def test_finalize_sets_updated_at(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """Finalize should update the updated_at timestamp."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated_at"] is not None


# ============================================================
# FINALIZE ACCESS CONTROL
# ============================================================

class TestFinalizeAccessControl:
    """Tests for finalize operation access control."""

    def test_finalize_owner_can_finalize(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """Owner can finalize their own configuration."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200

    def test_finalize_admin_can_finalize_any(
        self, client, lifecycle_admin_headers, draft_configuration
    ):
        """ADMIN can finalize any configuration."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_admin_headers
        )

        assert response.status_code == 200

    def test_finalize_user_cannot_finalize_others(
        self, client, second_lifecycle_user_headers, draft_configuration
    ):
        """USER cannot finalize other user's configuration."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=second_lifecycle_user_headers
        )

        assert response.status_code == 403

    def test_finalize_author_cannot_finalize_others(
        self, client, lifecycle_author_headers, draft_configuration
    ):
        """AUTHOR cannot finalize other user's configuration."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_author_headers
        )

        assert response.status_code == 403

    def test_finalize_without_auth(
        self, client, draft_configuration
    ):
        """Finalize without authentication should return 401."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize"
        )

        assert response.status_code == 401


# ============================================================
# FINALIZE EDGE CASES
# ============================================================

class TestFinalizeEdgeCases:
    """Edge cases for finalize operation."""

    def test_finalize_nonexistent_config(
        self, client, lifecycle_user_headers
    ):
        """Finalizing non-existent config should return 404."""
        response = client.post(
            "/configurations/00000000-0000-0000-0000-000000000000/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 404

    def test_finalize_with_incomplete_config_rejected(
        self, client, lifecycle_user_headers, configuration_with_empty_data
    ):
        """Cannot finalize incomplete configuration (is_complete=False)."""
        # Empty data likely means is_complete=False
        response = client.post(
            f"/configurations/{configuration_with_empty_data.id}/finalize",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 400
        assert "incomplete configuration" in response.json()["detail"]

    def test_finalize_then_update_blocked(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """After finalize, updates should be blocked."""
        # First finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

        # Then try to update
        update_response = client.patch(
            f"/configurations/{draft_configuration.id}",
            json={"name": "Attempted Update"},
            headers=lifecycle_user_headers
        )

        assert update_response.status_code == 409

    def test_finalize_then_upgrade_blocked(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """After finalize, upgrade should be blocked."""
        # First finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

        # Then try to upgrade
        upgrade_response = client.post(
            f"/configurations/{draft_configuration.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert upgrade_response.status_code == 409

    def test_finalize_then_clone_allowed(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """After finalize, clone should still work."""
        # First finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

        # Then clone
        clone_response = client.post(
            f"/configurations/{draft_configuration.id}/clone",
            headers=lifecycle_user_headers
        )

        assert clone_response.status_code == 201
        assert clone_response.json()["status"] == "DRAFT"

    def test_finalize_then_delete_blocked_for_user(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """After finalize, USER cannot delete."""
        # First finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

        # Then try to delete
        delete_response = client.delete(
            f"/configurations/{draft_configuration.id}",
            headers=lifecycle_user_headers
        )

        assert delete_response.status_code == 403

    def test_finalize_then_read_allowed(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """After finalize, read should still work."""
        # First finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

        # Then read
        read_response = client.get(
            f"/configurations/{draft_configuration.id}",
            headers=lifecycle_user_headers
        )

        assert read_response.status_code == 200
        assert read_response.json()["status"] == "FINALIZED"

    def test_finalize_persists_to_database(
        self, client, db_session, lifecycle_user_headers, draft_configuration
    ):
        """Finalize status should be persisted to database."""
        response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )
        assert response.status_code == 200

        # Refresh from database
        db_session.expire_all()
        config = db_session.query(Configuration).filter(
            Configuration.id == draft_configuration.id
        ).first()

        assert config.status == ConfigurationStatus.FINALIZED


# ============================================================
# FINALIZE WORKFLOW TESTS
# ============================================================

class TestFinalizeWorkflows:
    """Workflow tests involving finalize operation."""

    def test_create_update_finalize_workflow(
        self, client, lifecycle_user_headers, published_version_for_lifecycle
    ):
        """Complete workflow: create -> update -> finalize."""
        version_data = published_version_for_lifecycle
        version = version_data["version"]
        fields = version_data["fields"]

        # Create
        create_response = client.post(
            "/configurations/",
            json={
                "entity_version_id": version.id,
                "name": "Workflow Config",
                "data": [
                    {"field_id": fields["name"].id, "value": "Initial"},
                    {"field_id": fields["amount"].id, "value": 100}
                ]
            },
            headers=lifecycle_user_headers
        )
        assert create_response.status_code == 201
        config_id = create_response.json()["id"]

        # Update
        update_response = client.patch(
            f"/configurations/{config_id}",
            json={"name": "Updated Workflow Config"},
            headers=lifecycle_user_headers
        )
        assert update_response.status_code == 200

        # Finalize
        finalize_response = client.post(
            f"/configurations/{config_id}/finalize",
            headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200
        assert finalize_response.json()["status"] == "FINALIZED"
        assert finalize_response.json()["name"] == "Updated Workflow Config"

    def test_finalize_clone_modify_workflow(
        self, client, lifecycle_user_headers,
        draft_configuration, published_version_for_lifecycle
    ):
        """Workflow: finalize -> clone -> modify clone."""
        fields = published_version_for_lifecycle["fields"]

        # Finalize original
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize",
            headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

        # Clone
        clone_response = client.post(
            f"/configurations/{draft_configuration.id}/clone",
            headers=lifecycle_user_headers
        )
        assert clone_response.status_code == 201
        clone_id = clone_response.json()["id"]

        # Modify clone
        update_response = client.patch(
            f"/configurations/{clone_id}",
            json={
                "name": "Modified Clone",
                "data": [
                    {"field_id": fields["name"].id, "value": "New Value"},
                    {"field_id": fields["amount"].id, "value": 9999}
                ]
            },
            headers=lifecycle_user_headers
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Modified Clone"

        # Original should remain unchanged
        original_response = client.get(
            f"/configurations/{draft_configuration.id}",
            headers=lifecycle_user_headers
        )
        assert original_response.status_code == 200
        assert original_response.json()["status"] == "FINALIZED"
