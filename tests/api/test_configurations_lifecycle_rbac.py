"""
Tests for Configuration lifecycle RBAC (Role-Based Access Control).
Covers USER, AUTHOR, and ADMIN role permissions for lifecycle operations.
"""

from app.models.domain import Configuration, ConfigurationStatus

# ============================================================
# USER ROLE TESTS
# ============================================================


class TestUserRolePermissions:
    """Tests for USER role permissions on lifecycle operations."""

    def test_user_full_access_own_draft(
        self, client, lifecycle_user_headers, draft_configuration, published_version_for_lifecycle
    ):
        """USER has full access to own DRAFT configuration."""
        fields = published_version_for_lifecycle["fields"]

        # Read
        read_response = client.get(f"/configurations/{draft_configuration.id}", headers=lifecycle_user_headers)
        assert read_response.status_code == 200

        # Update
        update_response = client.patch(
            f"/configurations/{draft_configuration.id}",
            json={"name": "Updated by User"},
            headers=lifecycle_user_headers,
        )
        assert update_response.status_code == 200

        # Clone
        clone_response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)
        assert clone_response.status_code == 201

        # Finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize", headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

    def test_user_read_only_own_finalized(self, client, lifecycle_user_headers, finalized_configuration):
        """USER can only read own FINALIZED configuration, updates blocked."""
        # Read should work
        read_response = client.get(f"/configurations/{finalized_configuration.id}", headers=lifecycle_user_headers)
        assert read_response.status_code == 200

        # Update should be blocked
        update_response = client.patch(
            f"/configurations/{finalized_configuration.id}",
            json={"name": "Attempted Update"},
            headers=lifecycle_user_headers,
        )
        assert update_response.status_code == 409

    def test_user_can_clone_own_finalized(self, client, lifecycle_user_headers, finalized_configuration):
        """USER can clone own FINALIZED configuration."""
        response = client.post(f"/configurations/{finalized_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        assert response.json()["status"] == "DRAFT"

    def test_user_cannot_delete_finalized(self, client, lifecycle_user_headers, finalized_configuration):
        """USER cannot delete FINALIZED configuration."""
        response = client.delete(f"/configurations/{finalized_configuration.id}", headers=lifecycle_user_headers)

        assert response.status_code == 403

    def test_user_cannot_upgrade_finalized(self, client, lifecycle_user_headers, finalized_configuration):
        """USER cannot upgrade FINALIZED configuration."""
        response = client.post(f"/configurations/{finalized_configuration.id}/upgrade", headers=lifecycle_user_headers)

        assert response.status_code == 409

    def test_user_no_access_others_configs(self, client, lifecycle_user_headers, second_user_draft_configuration):
        """USER cannot access other user's configurations."""
        # Read
        read_response = client.get(
            f"/configurations/{second_user_draft_configuration.id}", headers=lifecycle_user_headers
        )
        assert read_response.status_code == 403

        # Update
        update_response = client.patch(
            f"/configurations/{second_user_draft_configuration.id}",
            json={"name": "Attempted"},
            headers=lifecycle_user_headers,
        )
        assert update_response.status_code == 403

        # Clone
        clone_response = client.post(
            f"/configurations/{second_user_draft_configuration.id}/clone", headers=lifecycle_user_headers
        )
        assert clone_response.status_code == 403

        # Finalize
        finalize_response = client.post(
            f"/configurations/{second_user_draft_configuration.id}/finalize", headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 403

        # Delete
        delete_response = client.delete(
            f"/configurations/{second_user_draft_configuration.id}", headers=lifecycle_user_headers
        )
        assert delete_response.status_code == 403

    def test_user_can_delete_own_draft(self, client, db_session, lifecycle_user_headers, draft_configuration):
        """USER can delete own DRAFT configuration."""
        config_id = draft_configuration.id

        response = client.delete(f"/configurations/{config_id}", headers=lifecycle_user_headers)

        assert response.status_code == 204

        # Verify hard delete
        config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
        assert config is None


# ============================================================
# AUTHOR ROLE TESTS
# ============================================================


class TestAuthorRolePermissions:
    """Tests for AUTHOR role permissions on lifecycle operations."""

    def test_author_same_restrictions_as_user(self, client, lifecycle_author_headers, draft_configuration):
        """AUTHOR has same config restrictions as USER for other's configs."""
        # Cannot access other user's config
        read_response = client.get(f"/configurations/{draft_configuration.id}", headers=lifecycle_author_headers)
        assert read_response.status_code == 403

    def test_author_full_access_own_draft(self, client, lifecycle_author_headers, author_owned_draft_configuration):
        """AUTHOR has full access to own DRAFT configuration."""
        # Read
        read_response = client.get(
            f"/configurations/{author_owned_draft_configuration.id}", headers=lifecycle_author_headers
        )
        assert read_response.status_code == 200

        # Update
        update_response = client.patch(
            f"/configurations/{author_owned_draft_configuration.id}",
            json={"name": "Updated by Author"},
            headers=lifecycle_author_headers,
        )
        assert update_response.status_code == 200

        # Clone
        clone_response = client.post(
            f"/configurations/{author_owned_draft_configuration.id}/clone", headers=lifecycle_author_headers
        )
        assert clone_response.status_code == 201

    def test_author_cannot_delete_finalized(
        self, client, db_session, lifecycle_author_headers, author_owned_draft_configuration
    ):
        """AUTHOR cannot delete FINALIZED configuration."""
        # First finalize
        author_owned_draft_configuration.status = ConfigurationStatus.FINALIZED
        db_session.commit()

        response = client.delete(
            f"/configurations/{author_owned_draft_configuration.id}", headers=lifecycle_author_headers
        )

        assert response.status_code == 403

    def test_author_can_finalize_own(self, client, lifecycle_author_headers, author_owned_draft_configuration):
        """AUTHOR can finalize own DRAFT configuration."""
        response = client.post(
            f"/configurations/{author_owned_draft_configuration.id}/finalize", headers=lifecycle_author_headers
        )

        assert response.status_code == 200
        assert response.json()["status"] == "FINALIZED"


# ============================================================
# ADMIN ROLE TESTS
# ============================================================


class TestAdminRolePermissions:
    """Tests for ADMIN role permissions on lifecycle operations."""

    def test_admin_can_access_all_configs(
        self, client, lifecycle_admin_headers, draft_configuration, second_user_draft_configuration
    ):
        """ADMIN can access all configurations regardless of owner."""
        # User's config
        response1 = client.get(f"/configurations/{draft_configuration.id}", headers=lifecycle_admin_headers)
        assert response1.status_code == 200

        # Second user's config
        response2 = client.get(f"/configurations/{second_user_draft_configuration.id}", headers=lifecycle_admin_headers)
        assert response2.status_code == 200

    def test_admin_can_soft_delete_finalized(
        self, client, db_session, lifecycle_admin_headers, admin_owned_finalized_configuration
    ):
        """ADMIN can soft-delete FINALIZED configuration."""
        config_id = admin_owned_finalized_configuration.id

        response = client.delete(f"/configurations/{config_id}", headers=lifecycle_admin_headers)

        assert response.status_code == 204

        # Verify soft delete
        db_session.expire_all()
        config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
        assert config is not None
        assert config.is_deleted is True

    def test_admin_cannot_modify_finalized_data(
        self, client, lifecycle_admin_headers, admin_owned_finalized_configuration
    ):
        """ADMIN cannot alter FINALIZED configuration's input data."""
        response = client.patch(
            f"/configurations/{admin_owned_finalized_configuration.id}",
            json={"name": "Admin attempted update"},
            headers=lifecycle_admin_headers,
        )

        assert response.status_code == 409

    def test_admin_can_clone_any_config(
        self, client, lifecycle_admin_headers, draft_configuration, finalized_configuration
    ):
        """ADMIN can clone any configuration."""
        # Clone user's draft
        response1 = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_admin_headers)
        assert response1.status_code == 201

        # Clone user's finalized
        response2 = client.post(f"/configurations/{finalized_configuration.id}/clone", headers=lifecycle_admin_headers)
        assert response2.status_code == 201

    def test_admin_can_view_deleted_configs(self, client, lifecycle_admin_headers, soft_deleted_configuration):
        """ADMIN can view soft-deleted configurations with include_deleted."""
        response = client.get("/configurations/?include_deleted=true", headers=lifecycle_admin_headers)

        assert response.status_code == 200
        config_ids = [c["id"] for c in response.json()]
        assert soft_deleted_configuration.id in config_ids

    def test_admin_can_finalize_any_config(self, client, lifecycle_admin_headers, draft_configuration):
        """ADMIN can finalize any DRAFT configuration."""
        response = client.post(f"/configurations/{draft_configuration.id}/finalize", headers=lifecycle_admin_headers)

        assert response.status_code == 200

    def test_admin_can_upgrade_any_config(self, client, lifecycle_admin_headers, configuration_on_archived_version):
        """ADMIN can upgrade any DRAFT configuration."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade", headers=lifecycle_admin_headers
        )

        assert response.status_code == 200


# ============================================================
# CROSS-ROLE INTERACTION TESTS
# ============================================================


class TestCrossRoleInteractions:
    """Tests for interactions between different roles."""

    def test_user_creates_admin_finalizes(
        self,
        client,
        db_session,
        lifecycle_user_headers,
        lifecycle_admin_headers,
        published_version_for_lifecycle,
        lifecycle_price_list,
    ):
        """Workflow: USER creates, ADMIN finalizes."""
        version_data = published_version_for_lifecycle
        version = version_data["version"]
        fields = version_data["fields"]

        # USER creates
        create_response = client.post(
            "/configurations/",
            json={
                "entity_version_id": version.id,
                "name": "User Created",
                "price_list_id": lifecycle_price_list.id,
                "data": [
                    {"field_id": fields["name"].id, "value": "Test"},
                    {"field_id": fields["amount"].id, "value": 100},
                ],
            },
            headers=lifecycle_user_headers,
        )
        assert create_response.status_code == 201
        config_id = create_response.json()["id"]

        # ADMIN finalizes
        finalize_response = client.post(f"/configurations/{config_id}/finalize", headers=lifecycle_admin_headers)
        assert finalize_response.status_code == 200
        assert finalize_response.json()["status"] == "FINALIZED"

    def test_author_creates_user_cannot_access(
        self,
        client,
        lifecycle_author_headers,
        lifecycle_user_headers,
        published_version_for_lifecycle,
        lifecycle_price_list,
    ):
        """AUTHOR's config is not accessible to USER."""
        version_data = published_version_for_lifecycle
        version = version_data["version"]
        fields = version_data["fields"]

        # AUTHOR creates
        create_response = client.post(
            "/configurations/",
            json={
                "entity_version_id": version.id,
                "name": "Author Created",
                "price_list_id": lifecycle_price_list.id,
                "data": [
                    {"field_id": fields["name"].id, "value": "Test"},
                    {"field_id": fields["amount"].id, "value": 100},
                ],
            },
            headers=lifecycle_author_headers,
        )
        assert create_response.status_code == 201
        config_id = create_response.json()["id"]

        # USER cannot access
        read_response = client.get(f"/configurations/{config_id}", headers=lifecycle_user_headers)
        assert read_response.status_code == 403

    def test_admin_soft_deletes_user_cannot_see(
        self,
        client,
        db_session,
        lifecycle_admin_headers,
        lifecycle_user_headers,
        admin_owned_finalized_configuration,
        lifecycle_user,
    ):
        """Soft-deleted by ADMIN is not visible to USER in list."""
        config_id = admin_owned_finalized_configuration.id

        # Make config owned by user for visibility test
        admin_owned_finalized_configuration.user_id = lifecycle_user.id
        db_session.commit()

        # ADMIN soft-deletes
        delete_response = client.delete(f"/configurations/{config_id}", headers=lifecycle_admin_headers)
        assert delete_response.status_code == 204

        # USER cannot see in list
        list_response = client.get("/configurations/", headers=lifecycle_user_headers)
        assert list_response.status_code == 200
        config_ids = [c["id"] for c in list_response.json()]
        assert config_id not in config_ids

    def test_user_creates_user2_cannot_modify(
        self, client, lifecycle_user_headers, second_lifecycle_user_headers, draft_configuration
    ):
        """One USER cannot modify another USER's configuration."""
        # Second user tries to update
        update_response = client.patch(
            f"/configurations/{draft_configuration.id}",
            json={"name": "Hijacked"},
            headers=second_lifecycle_user_headers,
        )
        assert update_response.status_code == 403

        # Second user tries to finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize", headers=second_lifecycle_user_headers
        )
        assert finalize_response.status_code == 403

        # Second user tries to delete
        delete_response = client.delete(
            f"/configurations/{draft_configuration.id}", headers=second_lifecycle_user_headers
        )
        assert delete_response.status_code == 403

    def test_list_shows_only_own_configs_for_user(
        self, client, lifecycle_user_headers, draft_configuration, second_user_draft_configuration
    ):
        """USER list should only show own configurations."""
        response = client.get("/configurations/", headers=lifecycle_user_headers)

        assert response.status_code == 200
        config_ids = [c["id"] for c in response.json()]

        # Own config should be visible
        assert draft_configuration.id in config_ids
        # Other user's config should not be visible
        assert second_user_draft_configuration.id not in config_ids

    def test_admin_list_shows_all_configs(
        self,
        client,
        lifecycle_admin_headers,
        draft_configuration,
        second_user_draft_configuration,
        admin_owned_draft_configuration,
    ):
        """ADMIN list shows all configurations."""
        response = client.get("/configurations/", headers=lifecycle_admin_headers)

        assert response.status_code == 200
        config_ids = [c["id"] for c in response.json()]

        # All configs should be visible
        assert draft_configuration.id in config_ids
        assert second_user_draft_configuration.id in config_ids
        assert admin_owned_draft_configuration.id in config_ids
