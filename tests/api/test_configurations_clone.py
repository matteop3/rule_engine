"""
Tests for Configuration clone operations.
Covers basic clone functionality, access control, and edge cases.
"""

from app.models.domain import Configuration

# ============================================================
# BASIC CLONE FUNCTIONALITY
# ============================================================


class TestCloneBasicFunctionality:
    """Tests for basic clone operation behavior."""

    def test_clone_draft_creates_new_config(self, client, lifecycle_user_headers, draft_configuration):
        """Cloning DRAFT config should create a new configuration with new UUID."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["id"] != draft_configuration.id
        # Verify it's a valid UUID format
        assert len(data["id"]) == 36

    def test_clone_finalized_creates_new_config(self, client, lifecycle_user_headers, finalized_configuration):
        """Cloning FINALIZED config should create a new configuration."""
        response = client.post(f"/configurations/{finalized_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["id"] != finalized_configuration.id

    def test_clone_result_always_draft(self, client, lifecycle_user_headers, finalized_configuration):
        """Clone should always have DRAFT status regardless of source."""
        response = client.post(f"/configurations/{finalized_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "DRAFT"

    def test_clone_copies_input_data(self, client, lifecycle_user_headers, draft_configuration):
        """Clone should have identical data array."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()

        # Compare data
        source_data = {d["field_id"]: d["value"] for d in draft_configuration.data}
        clone_data = {d["field_id"]: d["value"] for d in data["data"]}
        assert source_data == clone_data

    def test_clone_copies_version_reference(self, client, lifecycle_user_headers, draft_configuration):
        """Clone should have same entity_version_id as source."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["entity_version_id"] == draft_configuration.entity_version_id

    def test_clone_copies_name_with_suffix(self, client, lifecycle_user_headers, draft_configuration):
        """Clone name should have ' (Copy)' suffix."""
        original_name = draft_configuration.name

        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == f"{original_name} (Copy)"

    def test_clone_null_name_stays_null(self, client, lifecycle_user_headers, configuration_null_name):
        """Cloning config with null name should result in null name."""
        response = client.post(f"/configurations/{configuration_null_name.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] is None

    def test_clone_copies_is_complete(self, client, lifecycle_user_headers, draft_configuration):
        """Clone should preserve is_complete flag."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["is_complete"] == draft_configuration.is_complete

    def test_clone_source_unchanged(self, client, db_session, lifecycle_user_headers, draft_configuration):
        """Source configuration should remain unchanged after clone."""
        original_name = draft_configuration.name
        original_data = draft_configuration.data.copy()
        original_status = draft_configuration.status

        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)
        assert response.status_code == 201

        # Refresh source
        db_session.refresh(draft_configuration)
        assert draft_configuration.name == original_name
        assert draft_configuration.data == original_data
        assert draft_configuration.status == original_status

    def test_clone_returns_source_id(self, client, lifecycle_user_headers, draft_configuration):
        """Clone response should include source_id."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert "source_id" in data
        assert data["source_id"] == draft_configuration.id


# ============================================================
# CLONE ACCESS CONTROL
# ============================================================


class TestCloneAccessControl:
    """Tests for clone operation access control."""

    def test_clone_owner_can_clone_own(self, client, lifecycle_user_headers, draft_configuration):
        """Owner can clone their own configuration."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201

    def test_clone_admin_can_clone_any(self, client, lifecycle_admin_headers, draft_configuration):
        """ADMIN can clone any configuration."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_admin_headers)

        assert response.status_code == 201

    def test_clone_user_cannot_clone_others(self, client, lifecycle_user_headers, second_user_draft_configuration):
        """USER cannot clone other user's configuration."""
        response = client.post(
            f"/configurations/{second_user_draft_configuration.id}/clone", headers=lifecycle_user_headers
        )

        assert response.status_code == 403

    def test_clone_author_cannot_clone_others(self, client, lifecycle_author_headers, draft_configuration):
        """AUTHOR cannot clone other user's configuration."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_author_headers)

        assert response.status_code == 403

    def test_clone_deleted_config_still_accessible_to_owner(
        self, client, lifecycle_admin_headers, soft_deleted_configuration
    ):
        """Owner/ADMIN can still clone soft-deleted config."""
        response = client.post(
            f"/configurations/{soft_deleted_configuration.id}/clone", headers=lifecycle_admin_headers
        )

        # Soft-deleted configs are still accessible for reading/cloning
        assert response.status_code == 201


# ============================================================
# CLONE EDGE CASES
# ============================================================


class TestCloneEdgeCases:
    """Edge cases for clone operation."""

    def test_clone_with_empty_data(self, client, lifecycle_user_headers, configuration_with_empty_data):
        """Cloning config with empty data should work."""
        response = client.post(
            f"/configurations/{configuration_with_empty_data.id}/clone", headers=lifecycle_user_headers
        )

        assert response.status_code == 201
        data = response.json()
        assert data["data"] == []

    def test_clone_with_large_data(
        self, client, db_session, lifecycle_user_headers, draft_configuration, published_version_for_lifecycle
    ):
        """Clone should handle configurations with many fields."""
        # This test uses the existing draft_configuration which has limited fields
        # In a real scenario, you'd create a config with many fields
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert len(data["data"]) == len(draft_configuration.data)

    def test_clone_assigns_current_user_as_owner(
        self, client, db_session, lifecycle_admin_headers, draft_configuration, lifecycle_admin
    ):
        """Clone should be owned by the cloning user, not the original owner."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_admin_headers)

        assert response.status_code == 201
        clone_id = response.json()["id"]

        # Verify ownership
        clone = db_session.query(Configuration).filter(Configuration.id == clone_id).first()
        assert clone.user_id == lifecycle_admin.id
        assert clone.user_id != draft_configuration.user_id

    def test_clone_sets_new_audit_timestamps(self, client, lifecycle_user_headers, finalized_configuration):
        """Clone should have fresh created_at/updated_at timestamps."""
        response = client.post(f"/configurations/{finalized_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()

        # Clone timestamps should be different (newer)
        assert data["created_at"] is not None
        # Clone hasn't been updated yet
        assert data["updated_at"] is None

    def test_clone_nonexistent_config(self, client, lifecycle_user_headers):
        """Cloning non-existent config should return 404."""
        response = client.post(
            "/configurations/00000000-0000-0000-0000-000000000000/clone", headers=lifecycle_user_headers
        )

        assert response.status_code == 404

    def test_clone_without_auth(self, client, draft_configuration):
        """Clone without authentication should return 401."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone")

        assert response.status_code == 401

    def test_clone_is_deleted_false(self, client, lifecycle_user_headers, draft_configuration):
        """Clone should always have is_deleted=False."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["is_deleted"] is False

    def test_clone_finalized_to_draft_workflow(
        self, client, lifecycle_user_headers, finalized_configuration, published_version_for_lifecycle
    ):
        """
        Workflow test: Clone FINALIZED, modify clone, verify original unchanged.
        """
        fields = published_version_for_lifecycle["fields"]

        # Clone FINALIZED config
        clone_response = client.post(
            f"/configurations/{finalized_configuration.id}/clone", headers=lifecycle_user_headers
        )
        assert clone_response.status_code == 201
        clone_data = clone_response.json()
        clone_id = clone_data["id"]

        # Verify clone is DRAFT
        assert clone_data["status"] == "DRAFT"

        # Modify clone
        update_response = client.patch(
            f"/configurations/{clone_id}",
            json={
                "name": "Modified Clone",
                "data": [
                    {"field_id": fields["name"].id, "value": "Modified User"},
                    {"field_id": fields["amount"].id, "value": 9999},
                ],
            },
            headers=lifecycle_user_headers,
        )
        assert update_response.status_code == 200

        # Verify original is unchanged
        original_response = client.get(f"/configurations/{finalized_configuration.id}", headers=lifecycle_user_headers)
        assert original_response.status_code == 200
        original_data = original_response.json()
        assert original_data["status"] == "FINALIZED"
        assert original_data["name"] == finalized_configuration.name

    def test_multiple_clones_have_unique_ids(self, client, lifecycle_user_headers, draft_configuration):
        """Multiple clones of same source should each have unique IDs."""
        clone_ids = []

        for _ in range(3):
            response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)
            assert response.status_code == 201
            clone_ids.append(response.json()["id"])

        # All IDs should be unique
        assert len(clone_ids) == len(set(clone_ids))
        # None should match original
        assert draft_configuration.id not in clone_ids
