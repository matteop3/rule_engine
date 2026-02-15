"""
Tests for Configuration state transition matrix.
Covers all valid and invalid state transitions between DRAFT and FINALIZED.
"""

from app.models.domain import Configuration, ConfigurationStatus

# ============================================================
# DRAFT -> DRAFT TRANSITIONS
# ============================================================


class TestDraftToDraftTransitions:
    """Tests for transitions that keep configuration in DRAFT status."""

    def test_draft_update_stays_draft(self, client, lifecycle_user_headers, draft_configuration):
        """UPDATE on DRAFT keeps status as DRAFT."""
        response = client.patch(
            f"/configurations/{draft_configuration.id}", json={"name": "Updated Name"}, headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        assert response.json()["status"] == "DRAFT"

    def test_draft_upgrade_stays_draft(self, client, lifecycle_user_headers, configuration_on_archived_version):
        """UPGRADE on DRAFT keeps status as DRAFT."""
        response = client.post(
            f"/configurations/{configuration_on_archived_version.id}/upgrade", headers=lifecycle_user_headers
        )

        assert response.status_code == 200
        assert response.json()["status"] == "DRAFT"


# ============================================================
# DRAFT -> FINALIZED TRANSITIONS
# ============================================================


class TestDraftToFinalizedTransitions:
    """Tests for transitions from DRAFT to FINALIZED."""

    def test_draft_finalize_to_finalized(self, client, lifecycle_user_headers, draft_configuration):
        """FINALIZE on DRAFT transitions to FINALIZED."""
        response = client.post(f"/configurations/{draft_configuration.id}/finalize", headers=lifecycle_user_headers)

        assert response.status_code == 200
        assert response.json()["status"] == "FINALIZED"


# ============================================================
# DRAFT -> DELETED TRANSITIONS
# ============================================================


class TestDraftToDeletedTransitions:
    """Tests for deletion transitions from DRAFT."""

    def test_draft_delete_hard_delete(self, client, db_session, lifecycle_user_headers, draft_configuration):
        """DELETE on DRAFT performs hard delete."""
        config_id = draft_configuration.id

        response = client.delete(f"/configurations/{config_id}", headers=lifecycle_user_headers)

        assert response.status_code == 204

        # Verify hard delete - record should not exist
        config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
        assert config is None


# ============================================================
# FINALIZED -> FINALIZED BLOCKED TRANSITIONS
# ============================================================


class TestFinalizedToFinalizedBlockedTransitions:
    """Tests for operations blocked on FINALIZED configurations."""

    def test_finalized_update_blocked(self, client, lifecycle_user_headers, finalized_configuration):
        """UPDATE on FINALIZED returns HTTP 409."""
        response = client.patch(
            f"/configurations/{finalized_configuration.id}",
            json={"name": "Attempted Update"},
            headers=lifecycle_user_headers,
        )

        assert response.status_code == 409
        assert "FINALIZED" in response.json()["detail"]

    def test_finalized_upgrade_blocked(self, client, lifecycle_user_headers, finalized_configuration):
        """UPGRADE on FINALIZED returns HTTP 409."""
        response = client.post(f"/configurations/{finalized_configuration.id}/upgrade", headers=lifecycle_user_headers)

        assert response.status_code == 409
        assert "FINALIZED" in response.json()["detail"]

    def test_finalized_finalize_blocked(self, client, lifecycle_user_headers, finalized_configuration):
        """FINALIZE on FINALIZED returns HTTP 409."""
        response = client.post(f"/configurations/{finalized_configuration.id}/finalize", headers=lifecycle_user_headers)

        assert response.status_code == 409
        assert "already FINALIZED" in response.json()["detail"]


# ============================================================
# FINALIZED -> SOFT DELETED TRANSITIONS
# ============================================================


class TestFinalizedToSoftDeletedTransitions:
    """Tests for soft delete transitions from FINALIZED."""

    def test_finalized_delete_admin_soft_delete(
        self, client, db_session, lifecycle_admin_headers, admin_owned_finalized_configuration
    ):
        """DELETE by ADMIN on FINALIZED performs soft delete."""
        config_id = admin_owned_finalized_configuration.id

        response = client.delete(f"/configurations/{config_id}", headers=lifecycle_admin_headers)

        assert response.status_code == 204

        # Verify soft delete - record exists with is_deleted=True
        db_session.expire_all()
        config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
        assert config is not None
        assert config.is_deleted is True
        assert config.status == ConfigurationStatus.FINALIZED

    def test_finalized_delete_user_denied(self, client, lifecycle_user_headers, finalized_configuration):
        """DELETE by USER on FINALIZED returns HTTP 403."""
        response = client.delete(f"/configurations/{finalized_configuration.id}", headers=lifecycle_user_headers)

        assert response.status_code == 403


# ============================================================
# CLONE TRANSITIONS (ANY -> DRAFT)
# ============================================================


class TestCloneTransitions:
    """Tests for clone transitions which always result in DRAFT."""

    def test_clone_draft_creates_draft(self, client, lifecycle_user_headers, draft_configuration):
        """CLONE of DRAFT creates new DRAFT configuration."""
        response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        assert response.json()["status"] == "DRAFT"
        assert response.json()["id"] != draft_configuration.id

    def test_clone_finalized_creates_draft(self, client, lifecycle_user_headers, finalized_configuration):
        """CLONE of FINALIZED creates new DRAFT configuration."""
        response = client.post(f"/configurations/{finalized_configuration.id}/clone", headers=lifecycle_user_headers)

        assert response.status_code == 201
        assert response.json()["status"] == "DRAFT"
        assert response.json()["id"] != finalized_configuration.id


# ============================================================
# STATE TRANSITION MATRIX COMPREHENSIVE TESTS
# ============================================================


class TestStateTransitionMatrix:
    """
    Comprehensive state transition matrix tests.

    Matrix:
    | From State | Operation | Expected Result |
    |------------|-----------|-----------------|
    | DRAFT      | UPDATE    | DRAFT (allowed) |
    | DRAFT      | UPGRADE   | DRAFT (allowed) |
    | DRAFT      | FINALIZE  | FINALIZED       |
    | DRAFT      | DELETE    | Hard delete     |
    | DRAFT      | CLONE     | New DRAFT       |
    | FINALIZED  | UPDATE    | HTTP 409        |
    | FINALIZED  | UPGRADE   | HTTP 409        |
    | FINALIZED  | FINALIZE  | HTTP 409        |
    | FINALIZED  | DELETE    | Soft/Denied     |
    | FINALIZED  | CLONE     | New DRAFT       |
    """

    def test_all_draft_operations(
        self, client, db_session, lifecycle_user_headers, published_version_for_lifecycle, lifecycle_user
    ):
        """Test all operations from DRAFT state."""
        version_data = published_version_for_lifecycle
        version = version_data["version"]
        fields = version_data["fields"]

        # Create fresh DRAFT for each operation
        def create_draft():
            config = Configuration(
                entity_version_id=version.id,
                user_id=lifecycle_user.id,
                name="Matrix Test Config",
                status=ConfigurationStatus.DRAFT,
                is_complete=True,
                data=[
                    {"field_id": fields["name"].id, "value": "Test"},
                    {"field_id": fields["amount"].id, "value": 100},
                ],
                created_by_id=lifecycle_user.id,
            )
            db_session.add(config)
            db_session.commit()
            db_session.refresh(config)
            return config

        # UPDATE: DRAFT -> DRAFT
        config1 = create_draft()
        update_resp = client.patch(
            f"/configurations/{config1.id}", json={"name": "Updated"}, headers=lifecycle_user_headers
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "DRAFT"

        # FINALIZE: DRAFT -> FINALIZED
        config2 = create_draft()
        finalize_resp = client.post(f"/configurations/{config2.id}/finalize", headers=lifecycle_user_headers)
        assert finalize_resp.status_code == 200
        assert finalize_resp.json()["status"] == "FINALIZED"

        # DELETE: DRAFT -> (removed)
        config3 = create_draft()
        config3_id = config3.id
        delete_resp = client.delete(f"/configurations/{config3_id}", headers=lifecycle_user_headers)
        assert delete_resp.status_code == 204
        db_session.expire_all()
        assert db_session.query(Configuration).filter(Configuration.id == config3_id).first() is None

        # CLONE: DRAFT -> new DRAFT
        config4 = create_draft()
        clone_resp = client.post(f"/configurations/{config4.id}/clone", headers=lifecycle_user_headers)
        assert clone_resp.status_code == 201
        assert clone_resp.json()["status"] == "DRAFT"
        assert clone_resp.json()["id"] != config4.id

    def test_all_finalized_operations(
        self,
        client,
        db_session,
        lifecycle_user_headers,
        lifecycle_admin_headers,
        published_version_for_lifecycle,
        lifecycle_user,
        lifecycle_admin,
    ):
        """Test all operations from FINALIZED state."""
        version_data = published_version_for_lifecycle
        version = version_data["version"]
        fields = version_data["fields"]

        def create_finalized(owner_id):
            config = Configuration(
                entity_version_id=version.id,
                user_id=owner_id,
                name="Finalized Matrix Test",
                status=ConfigurationStatus.FINALIZED,
                is_complete=True,
                data=[
                    {"field_id": fields["name"].id, "value": "Test"},
                    {"field_id": fields["amount"].id, "value": 100},
                ],
                created_by_id=owner_id,
                updated_by_id=owner_id,
            )
            db_session.add(config)
            db_session.commit()
            db_session.refresh(config)
            return config

        # UPDATE: FINALIZED -> HTTP 409
        config1 = create_finalized(lifecycle_user.id)
        update_resp = client.patch(
            f"/configurations/{config1.id}", json={"name": "Attempted"}, headers=lifecycle_user_headers
        )
        assert update_resp.status_code == 409

        # UPGRADE: FINALIZED -> HTTP 409
        config2 = create_finalized(lifecycle_user.id)
        upgrade_resp = client.post(f"/configurations/{config2.id}/upgrade", headers=lifecycle_user_headers)
        assert upgrade_resp.status_code == 409

        # FINALIZE: FINALIZED -> HTTP 409
        config3 = create_finalized(lifecycle_user.id)
        finalize_resp = client.post(f"/configurations/{config3.id}/finalize", headers=lifecycle_user_headers)
        assert finalize_resp.status_code == 409

        # DELETE by USER: FINALIZED -> HTTP 403
        config4 = create_finalized(lifecycle_user.id)
        delete_user_resp = client.delete(f"/configurations/{config4.id}", headers=lifecycle_user_headers)
        assert delete_user_resp.status_code == 403

        # DELETE by ADMIN: FINALIZED -> soft delete
        config5 = create_finalized(lifecycle_admin.id)
        config5_id = config5.id
        delete_admin_resp = client.delete(f"/configurations/{config5_id}", headers=lifecycle_admin_headers)
        assert delete_admin_resp.status_code == 204
        db_session.expire_all()
        soft_deleted = db_session.query(Configuration).filter(Configuration.id == config5_id).first()
        assert soft_deleted is not None
        assert soft_deleted.is_deleted is True

        # CLONE: FINALIZED -> new DRAFT
        config6 = create_finalized(lifecycle_user.id)
        clone_resp = client.post(f"/configurations/{config6.id}/clone", headers=lifecycle_user_headers)
        assert clone_resp.status_code == 201
        assert clone_resp.json()["status"] == "DRAFT"


# ============================================================
# EDGE CASES AND INVALID TRANSITIONS
# ============================================================


class TestInvalidTransitions:
    """Tests for edge cases and error handling in transitions."""

    def test_cannot_manually_set_status_to_finalized_via_update(
        self, client, lifecycle_user_headers, draft_configuration
    ):
        """Status cannot be changed to FINALIZED via PATCH."""
        response = client.patch(
            f"/configurations/{draft_configuration.id}", json={"status": "FINALIZED"}, headers=lifecycle_user_headers
        )

        # Update should succeed but status should remain DRAFT
        # (status field is not in update schema)
        assert response.status_code == 200
        assert response.json()["status"] == "DRAFT"

    def test_cannot_manually_set_status_to_draft_via_update(
        self, client, lifecycle_user_headers, finalized_configuration
    ):
        """Cannot revert FINALIZED to DRAFT via PATCH."""
        response = client.patch(
            f"/configurations/{finalized_configuration.id}", json={"status": "DRAFT"}, headers=lifecycle_user_headers
        )

        # Update blocked because config is FINALIZED
        assert response.status_code == 409

    def test_transition_sequence_draft_finalize_clone_update(
        self, client, lifecycle_user_headers, draft_configuration, published_version_for_lifecycle
    ):
        """Test sequence: DRAFT -> finalize -> FINALIZED -> clone -> DRAFT -> update."""
        fields = published_version_for_lifecycle["fields"]

        # Start with DRAFT
        assert draft_configuration.status == ConfigurationStatus.DRAFT

        # Finalize
        finalize_resp = client.post(
            f"/configurations/{draft_configuration.id}/finalize", headers=lifecycle_user_headers
        )
        assert finalize_resp.status_code == 200
        assert finalize_resp.json()["status"] == "FINALIZED"

        # Clone (creates new DRAFT)
        clone_resp = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)
        assert clone_resp.status_code == 201
        clone_id = clone_resp.json()["id"]
        assert clone_resp.json()["status"] == "DRAFT"

        # Update clone
        update_resp = client.patch(
            f"/configurations/{clone_id}",
            json={
                "name": "Cloned and Updated",
                "data": [
                    {"field_id": fields["name"].id, "value": "New Value"},
                    {"field_id": fields["amount"].id, "value": 9999},
                ],
            },
            headers=lifecycle_user_headers,
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Cloned and Updated"
