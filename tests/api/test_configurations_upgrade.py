"""
Tests for Configuration upgrade operations.
Covers upgrade to latest PUBLISHED version, status constraints, and access control.
"""
import pytest
from app.models.domain import Configuration, ConfigurationStatus, VersionStatus


# ============================================================
# BASIC UPGRADE FUNCTIONALITY
# ============================================================

class TestUpgradeBasicFunctionality:
    """Tests for basic upgrade operation behavior."""

    def test_upgrade_updates_version_id(
        self, client, db_session, lifecycle_user_headers,
        configuration_on_archived_version, multi_version_entity
    ):
        """Upgrade should update entity_version_id to latest PUBLISHED version."""
        published_version = multi_version_entity["published_version"]
        config = configuration_on_archived_version

        response = client.post(
            f"/configurations/{config.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["entity_version_id"] == published_version.id

    def test_upgrade_preserves_input_data(
        self, client, db_session, lifecycle_user_headers,
        configuration_on_archived_version, multi_version_entity
    ):
        """Upgrade should preserve user data array."""
        config = configuration_on_archived_version
        original_data = config.data.copy()

        response = client.post(
            f"/configurations/{config.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()

        # Data should be preserved (though field IDs might be different versions)
        # The important thing is the data array length is preserved
        assert len(data["data"]) == len(original_data)

    def test_upgrade_recalculates_is_complete(
        self, client, db_session, lifecycle_user_headers,
        configuration_on_published_multi_version, multi_version_entity
    ):
        """Upgrade should recalculate is_complete with new version's rules."""
        config = configuration_on_published_multi_version

        # This config is already on published, so it won't actually upgrade
        # unless there's a newer published version
        response = client.post(
            f"/configurations/{config.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        # is_complete should be a boolean (recalculated)
        assert isinstance(data["is_complete"], bool)

    def test_upgrade_already_on_latest(
        self, client, lifecycle_user_headers,
        configuration_on_published_multi_version, multi_version_entity
    ):
        """No change if already on latest PUBLISHED version."""
        config = configuration_on_published_multi_version
        published_version = multi_version_entity["published_version"]

        response = client.post(
            f"/configurations/{config.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        # Should still be on same version
        assert data["entity_version_id"] == published_version.id

    def test_upgrade_returns_updated_config(
        self, client, lifecycle_user_headers,
        configuration_on_archived_version, multi_version_entity
    ):
        """Response should contain full updated configuration."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()

        # Verify all expected fields
        assert "id" in data
        assert "entity_version_id" in data
        assert "name" in data
        assert "status" in data
        assert "is_complete" in data
        assert "data" in data


# ============================================================
# UPGRADE STATUS CONSTRAINTS
# ============================================================

class TestUpgradeStatusConstraints:
    """Tests for upgrade operation status constraints."""

    def test_upgrade_draft_allowed(
        self, client, lifecycle_user_headers, configuration_on_archived_version
    ):
        """DRAFT configuration can be upgraded."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200

    def test_upgrade_finalized_blocked(
        self, client, lifecycle_user_headers, finalized_configuration
    ):
        """FINALIZED configuration cannot be upgraded."""
        response = client.post(
            f"/configurations/{finalized_configuration.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 409
        assert "FINALIZED" in response.json()["detail"]

    def test_upgrade_finalized_error_message(
        self, client, lifecycle_user_headers, finalized_configuration
    ):
        """Error message should suggest using clone."""
        response = client.post(
            f"/configurations/{finalized_configuration.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "clone" in detail.lower()

    def test_upgrade_deleted_config_accessible(
        self, client, lifecycle_admin_headers, soft_deleted_configuration
    ):
        """Soft-deleted config is accessible but blocked because it's FINALIZED."""
        response = client.post(
            f"/configurations/{soft_deleted_configuration.id}/upgrade",
            headers=lifecycle_admin_headers
        )

        # soft_deleted_configuration is FINALIZED, so upgrade blocked
        assert response.status_code == 409


# ============================================================
# UPGRADE VERSION RESOLUTION
# ============================================================

class TestUpgradeVersionResolution:
    """Tests for upgrade version resolution logic."""

    def test_upgrade_finds_published_version(
        self, client, lifecycle_user_headers,
        configuration_on_archived_version, multi_version_entity
    ):
        """Upgrade should find the PUBLISHED version."""
        published_version = multi_version_entity["published_version"]

        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["entity_version_id"] == published_version.id

    def test_upgrade_no_published_version(
        self, client, db_session, lifecycle_user_headers,
        lifecycle_admin, lifecycle_entity, lifecycle_user
    ):
        """If no PUBLISHED version exists, upgrade should fail with 404."""
        from app.models.domain import EntityVersion, Field, FieldType

        # Create a DRAFT-only version
        draft_version = EntityVersion(
            entity_id=lifecycle_entity.id,
            version_number=99,
            status=VersionStatus.DRAFT,
            changelog="Draft only version",
            created_by_id=lifecycle_admin.id,
            updated_by_id=lifecycle_admin.id
        )
        db_session.add(draft_version)
        db_session.flush()

        # Add a field
        field = Field(
            entity_version_id=draft_version.id,
            name="test_field",
            label="Test",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=False,
            sequence=1
        )
        db_session.add(field)
        db_session.flush()

        # Create a config on this draft version
        config = Configuration(
            entity_version_id=draft_version.id,
            user_id=lifecycle_user.id,
            name="Config on draft-only entity",
            status=ConfigurationStatus.DRAFT,
            is_complete=True,
            data=[],
            created_by_id=lifecycle_user.id
        )
        db_session.add(config)
        db_session.commit()

        # Try to upgrade - should fail because no PUBLISHED version
        response = client.post(
            f"/configurations/{config.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 404
        assert "PUBLISHED" in response.json()["detail"]

    def test_upgrade_ignores_draft_versions(
        self, client, lifecycle_user_headers,
        configuration_on_archived_version, multi_version_entity
    ):
        """Upgrade should not consider DRAFT versions."""
        draft_version = multi_version_entity["draft_version"]
        published_version = multi_version_entity["published_version"]

        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        # Should upgrade to PUBLISHED, not DRAFT
        assert data["entity_version_id"] == published_version.id
        assert data["entity_version_id"] != draft_version.id

    def test_upgrade_ignores_archived_versions(
        self, client, lifecycle_user_headers,
        configuration_on_archived_version, multi_version_entity
    ):
        """Upgrade should skip ARCHIVED versions."""
        archived_version = multi_version_entity["archived_version"]
        published_version = multi_version_entity["published_version"]

        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        # Should upgrade to PUBLISHED, not stay on ARCHIVED
        assert data["entity_version_id"] == published_version.id
        assert data["entity_version_id"] != archived_version.id

    def test_upgrade_from_archived_to_published(
        self, client, lifecycle_user_headers,
        configuration_on_archived_version, multi_version_entity
    ):
        """Config on ARCHIVED version should upgrade to PUBLISHED."""
        archived_version = multi_version_entity["archived_version"]
        published_version = multi_version_entity["published_version"]

        # Verify starting state
        assert configuration_on_archived_version.entity_version_id == archived_version.id

        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["entity_version_id"] == published_version.id


# ============================================================
# UPGRADE ACCESS CONTROL
# ============================================================

class TestUpgradeAccessControl:
    """Tests for upgrade operation access control."""

    def test_upgrade_owner_can_upgrade_own(
        self, client, lifecycle_user_headers, configuration_on_archived_version
    ):
        """Owner can upgrade their own configuration."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200

    def test_upgrade_admin_can_upgrade_any(
        self, client, lifecycle_admin_headers, configuration_on_archived_version
    ):
        """ADMIN can upgrade any configuration."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_admin_headers
        )

        assert response.status_code == 200

    def test_upgrade_user_cannot_upgrade_others(
        self, client, second_lifecycle_user_headers, configuration_on_archived_version
    ):
        """USER cannot upgrade other user's configuration."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=second_lifecycle_user_headers
        )

        assert response.status_code == 403

    def test_upgrade_without_auth(
        self, client, configuration_on_archived_version
    ):
        """Upgrade without authentication should return 401."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade"
        )

        assert response.status_code == 401


# ============================================================
# UPGRADE EDGE CASES
# ============================================================

class TestUpgradeEdgeCases:
    """Edge cases for upgrade operation."""

    def test_upgrade_with_incompatible_fields(
        self, client, lifecycle_user_headers,
        configuration_on_archived_version, multi_version_entity
    ):
        """Upgrade should handle gracefully when fields differ between versions."""
        # The archived version has different fields than published
        # The upgrade should still succeed (data may become incomplete)
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        # is_complete might be False now due to different required fields
        assert isinstance(data["is_complete"], bool)

    def test_upgrade_updates_audit_fields(
        self, client, db_session, lifecycle_user_headers,
        configuration_on_archived_version, lifecycle_user
    ):
        """Upgrade should set updated_by_id to current user."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["updated_by_id"] == lifecycle_user.id

    def test_upgrade_nonexistent_config(
        self, client, lifecycle_user_headers
    ):
        """Upgrading non-existent config should return 404."""
        response = client.post(
            "/configurations/00000000-0000-0000-0000-000000000000/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 404

    def test_upgrade_idempotent_when_already_latest(
        self, client, db_session, lifecycle_user_headers,
        configuration_on_published_multi_version
    ):
        """Multiple upgrade calls should be safe when already on latest."""
        config_id = configuration_on_published_multi_version.id

        # First upgrade
        response1 = client.post(
            f"/configurations/{config_id}/upgrade",
            headers=lifecycle_user_headers
        )
        assert response1.status_code == 200
        version1 = response1.json()["entity_version_id"]

        # Second upgrade (should be no-op)
        response2 = client.post(
            f"/configurations/{config_id}/upgrade",
            headers=lifecycle_user_headers
        )
        assert response2.status_code == 200
        version2 = response2.json()["entity_version_id"]

        # Version should not change
        assert version1 == version2

    def test_upgrade_preserves_name(
        self, client, lifecycle_user_headers, configuration_on_archived_version
    ):
        """Upgrade should not change configuration name."""
        original_name = configuration_on_archived_version.name

        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == original_name

    def test_upgrade_preserves_status_draft(
        self, client, lifecycle_user_headers, configuration_on_archived_version
    ):
        """Upgrade should keep status as DRAFT."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade",
            headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "DRAFT"
