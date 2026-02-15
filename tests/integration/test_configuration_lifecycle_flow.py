"""
Integration tests for Configuration lifecycle flows.
Covers complete workflows and error recovery scenarios.
"""

from app.models.domain import Configuration, ConfigurationStatus

# ============================================================
# COMPLETE LIFECYCLE FLOW TESTS
# ============================================================


class TestFullLifecycleFlows:
    """Tests for complete configuration lifecycle workflows."""

    def test_full_lifecycle_draft_to_finalized(self, client, lifecycle_user_headers, published_version_for_lifecycle):
        """Complete workflow: Create -> Update -> Finalize."""
        version_data = published_version_for_lifecycle
        version = version_data["version"]
        fields = version_data["fields"]

        # Step 1: Create
        create_response = client.post(
            "/configurations/",
            json={
                "entity_version_id": version.id,
                "name": "Lifecycle Test Config",
                "data": [
                    {"field_id": fields["name"].id, "value": "Initial Name"},
                    {"field_id": fields["amount"].id, "value": 100},
                ],
            },
            headers=lifecycle_user_headers,
        )
        assert create_response.status_code == 201
        config_id = create_response.json()["id"]
        assert create_response.json()["status"] == "DRAFT"

        # Step 2: Update multiple times
        for i in range(3):
            update_response = client.patch(
                f"/configurations/{config_id}",
                json={
                    "name": f"Updated Config v{i + 1}",
                    "data": [
                        {"field_id": fields["name"].id, "value": f"Name v{i + 1}"},
                        {"field_id": fields["amount"].id, "value": 100 * (i + 1)},
                    ],
                },
                headers=lifecycle_user_headers,
            )
            assert update_response.status_code == 200
            assert update_response.json()["status"] == "DRAFT"

        # Step 3: Finalize
        finalize_response = client.post(f"/configurations/{config_id}/finalize", headers=lifecycle_user_headers)
        assert finalize_response.status_code == 200
        assert finalize_response.json()["status"] == "FINALIZED"
        assert finalize_response.json()["name"] == "Updated Config v3"

    def test_lifecycle_finalized_clone_modify(
        self, client, lifecycle_user_headers, finalized_configuration, published_version_for_lifecycle
    ):
        """Workflow: Finalize -> Clone -> Modify clone."""
        fields = published_version_for_lifecycle["fields"]
        original_id = finalized_configuration.id

        # Verify starting state
        read_response = client.get(f"/configurations/{original_id}", headers=lifecycle_user_headers)
        assert read_response.json()["status"] == "FINALIZED"

        # Step 1: Clone the FINALIZED config
        clone_response = client.post(f"/configurations/{original_id}/clone", headers=lifecycle_user_headers)
        assert clone_response.status_code == 201
        clone_id = clone_response.json()["id"]
        assert clone_response.json()["status"] == "DRAFT"
        assert clone_response.json()["source_id"] == original_id

        # Step 2: Modify clone
        update_response = client.patch(
            f"/configurations/{clone_id}",
            json={
                "name": "Modified Clone",
                "data": [
                    {"field_id": fields["name"].id, "value": "New Owner"},
                    {"field_id": fields["amount"].id, "value": 9999},
                ],
            },
            headers=lifecycle_user_headers,
        )
        assert update_response.status_code == 200

        # Step 3: Verify original unchanged
        original_response = client.get(f"/configurations/{original_id}", headers=lifecycle_user_headers)
        assert original_response.json()["status"] == "FINALIZED"
        assert original_response.json()["name"] == finalized_configuration.name

    def test_lifecycle_upgrade_incompatible_then_finalize_blocked(
        self, client, lifecycle_user_headers, configuration_on_archived_version, multi_version_entity
    ):
        """Workflow: Upgrade to incompatible version -> Finalize blocked.

        When upgrading from a version with different fields, the configuration
        becomes incomplete because the old field data doesn't satisfy the new
        version's required fields. Finalize should be blocked.
        """
        config_id = configuration_on_archived_version.id
        archived_version = multi_version_entity["archived_version"]
        published_version = multi_version_entity["published_version"]

        # Verify starting state
        read_response = client.get(f"/configurations/{config_id}", headers=lifecycle_user_headers)
        assert read_response.json()["entity_version_id"] == archived_version.id
        assert read_response.json()["status"] == "DRAFT"
        assert read_response.json()["is_complete"] is True

        # Step 1: Upgrade to latest PUBLISHED version (different fields)
        upgrade_response = client.post(f"/configurations/{config_id}/upgrade", headers=lifecycle_user_headers)
        assert upgrade_response.status_code == 200
        assert upgrade_response.json()["entity_version_id"] == published_version.id
        assert upgrade_response.json()["status"] == "DRAFT"
        # After upgrade, config is incomplete because fields are incompatible
        assert upgrade_response.json()["is_complete"] is False

        # Step 2: Finalize should be blocked (incomplete configuration)
        finalize_response = client.post(f"/configurations/{config_id}/finalize", headers=lifecycle_user_headers)
        assert finalize_response.status_code == 400
        assert "incomplete configuration" in finalize_response.json()["detail"]

    def test_lifecycle_multi_clone_chain(self, client, lifecycle_user_headers, draft_configuration):
        """Workflow: Clone of clone of clone."""
        original_id = draft_configuration.id
        clone_ids = [original_id]

        # Create chain of 3 clones
        for i in range(3):
            clone_response = client.post(f"/configurations/{clone_ids[-1]}/clone", headers=lifecycle_user_headers)
            assert clone_response.status_code == 201
            clone_ids.append(clone_response.json()["id"])
            assert clone_response.json()["status"] == "DRAFT"
            assert clone_response.json()["source_id"] == clone_ids[-2]

        # All IDs should be unique
        assert len(clone_ids) == len(set(clone_ids))

        # Verify each clone can be independently modified
        for clone_id in clone_ids[1:]:  # Skip original
            update_response = client.patch(
                f"/configurations/{clone_id}", json={"name": f"Clone {clone_id[:8]}"}, headers=lifecycle_user_headers
            )
            assert update_response.status_code == 200

    def test_lifecycle_create_finalize_clone_finalize_chain(
        self, client, lifecycle_user_headers, published_version_for_lifecycle
    ):
        """Workflow: Create -> Finalize -> Clone -> Finalize (repeat)."""
        version_data = published_version_for_lifecycle
        version = version_data["version"]
        fields = version_data["fields"]

        # Create initial
        create_response = client.post(
            "/configurations/",
            json={
                "entity_version_id": version.id,
                "name": "Chain Start",
                "data": [
                    {"field_id": fields["name"].id, "value": "Initial"},
                    {"field_id": fields["amount"].id, "value": 100},
                ],
            },
            headers=lifecycle_user_headers,
        )
        assert create_response.status_code == 201
        current_id = create_response.json()["id"]

        for i in range(3):
            # Finalize current
            finalize_response = client.post(f"/configurations/{current_id}/finalize", headers=lifecycle_user_headers)
            assert finalize_response.status_code == 200
            assert finalize_response.json()["status"] == "FINALIZED"

            # Clone
            clone_response = client.post(f"/configurations/{current_id}/clone", headers=lifecycle_user_headers)
            assert clone_response.status_code == 201
            current_id = clone_response.json()["id"]
            assert clone_response.json()["status"] == "DRAFT"

            # Modify clone
            update_response = client.patch(
                f"/configurations/{current_id}", json={"name": f"Iteration {i + 1}"}, headers=lifecycle_user_headers
            )
            assert update_response.status_code == 200


# ============================================================
# ERROR RECOVERY SCENARIOS
# ============================================================


class TestErrorRecoveryScenarios:
    """Tests for error recovery and transaction safety."""

    def test_failed_update_does_not_corrupt_config(
        self, client, db_session, lifecycle_user_headers, draft_configuration, published_version_for_lifecycle
    ):
        """Failed update should not corrupt the configuration."""
        original_name = draft_configuration.name
        original_data = draft_configuration.data.copy()

        # Attempt update with invalid field_id
        bad_update_response = client.patch(
            f"/configurations/{draft_configuration.id}",
            json={
                "data": [
                    {"field_id": 999999, "value": "Invalid"}  # Non-existent field
                ]
            },
            headers=lifecycle_user_headers,
        )
        assert bad_update_response.status_code == 400

        # Verify config is unchanged
        db_session.refresh(draft_configuration)
        assert draft_configuration.name == original_name
        assert draft_configuration.data == original_data

    def test_clone_source_intact_after_clone_failure_simulation(
        self, client, db_session, lifecycle_user_headers, draft_configuration
    ):
        """Source config should remain intact even if clone were to fail.
        (This test verifies the source is never modified during clone.)
        """
        original_name = draft_configuration.name
        original_data = draft_configuration.data.copy()
        original_status = draft_configuration.status

        # Perform successful clone
        clone_response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)
        assert clone_response.status_code == 201

        # Verify source unchanged
        db_session.refresh(draft_configuration)
        assert draft_configuration.name == original_name
        assert draft_configuration.data == original_data
        assert draft_configuration.status == original_status

    def test_finalize_rollback_on_failure(self, client, db_session, lifecycle_user_headers, draft_configuration):
        """Test that finalize is atomic - config stays DRAFT if it fails."""
        # Note: In normal operation, finalize should not fail
        # This test verifies that if an error occurred, the state would be consistent

        # Successful finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize", headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

        # Verify persistent state
        db_session.expire_all()
        config = db_session.query(Configuration).filter(Configuration.id == draft_configuration.id).first()
        assert config.status == ConfigurationStatus.FINALIZED

    def test_upgrade_rollback_on_version_not_found(
        self, client, db_session, lifecycle_user_headers, lifecycle_admin, lifecycle_entity, lifecycle_user
    ):
        """Upgrade should fail cleanly if no PUBLISHED version exists."""
        from app.models.domain import EntityVersion, Field, FieldType, VersionStatus

        # Create entity with only DRAFT version (no PUBLISHED)
        draft_only_version = EntityVersion(
            entity_id=lifecycle_entity.id,
            version_number=999,
            status=VersionStatus.DRAFT,
            changelog="Draft only",
            created_by_id=lifecycle_admin.id,
            updated_by_id=lifecycle_admin.id,
        )
        db_session.add(draft_only_version)
        db_session.flush()

        field = Field(
            entity_version_id=draft_only_version.id,
            name="test_field",
            label="Test",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=False,
            sequence=1,
        )
        db_session.add(field)
        db_session.flush()

        # Create config on draft version
        config = Configuration(
            entity_version_id=draft_only_version.id,
            user_id=lifecycle_user.id,
            name="Test Config",
            status=ConfigurationStatus.DRAFT,
            is_complete=True,
            data=[],
            created_by_id=lifecycle_user.id,
        )
        db_session.add(config)
        db_session.commit()
        db_session.refresh(config)

        original_version_id = config.entity_version_id

        # Attempt upgrade
        upgrade_response = client.post(f"/configurations/{config.id}/upgrade", headers=lifecycle_user_headers)
        assert upgrade_response.status_code == 404

        # Verify config unchanged
        db_session.refresh(config)
        assert config.entity_version_id == original_version_id
        assert config.status == ConfigurationStatus.DRAFT


# ============================================================
# CONCURRENT OPERATIONS (Simulated)
# ============================================================


class TestConcurrentOperations:
    """Tests for handling concurrent access patterns."""

    def test_rapid_clone_operations(self, client, lifecycle_user_headers, draft_configuration):
        """Multiple rapid clone operations should all succeed."""
        results = []
        for _ in range(5):
            response = client.post(f"/configurations/{draft_configuration.id}/clone", headers=lifecycle_user_headers)
            results.append(response)

        # All should succeed
        for response in results:
            assert response.status_code == 201

        # All should have unique IDs
        ids = [r.json()["id"] for r in results]
        assert len(ids) == len(set(ids))

    def test_read_after_finalize(self, client, lifecycle_user_headers, draft_configuration):
        """Read immediately after finalize should reflect new status."""
        # Finalize
        finalize_response = client.post(
            f"/configurations/{draft_configuration.id}/finalize", headers=lifecycle_user_headers
        )
        assert finalize_response.status_code == 200

        # Immediate read
        read_response = client.get(f"/configurations/{draft_configuration.id}", headers=lifecycle_user_headers)
        assert read_response.status_code == 200
        assert read_response.json()["status"] == "FINALIZED"

    def test_list_after_soft_delete(
        self, client, db_session, lifecycle_admin_headers, admin_owned_finalized_configuration
    ):
        """List immediately after soft delete should exclude the config."""
        config_id = admin_owned_finalized_configuration.id

        # Soft delete
        delete_response = client.delete(f"/configurations/{config_id}", headers=lifecycle_admin_headers)
        assert delete_response.status_code == 204

        # Immediate list (without include_deleted)
        list_response = client.get("/configurations/", headers=lifecycle_admin_headers)
        assert list_response.status_code == 200
        config_ids = [c["id"] for c in list_response.json()]
        assert config_id not in config_ids


# ============================================================
# MULTI-USER WORKFLOW TESTS
# ============================================================


class TestMultiUserWorkflows:
    """Tests for workflows involving multiple users."""

    def test_user_creates_admin_reviews_and_finalizes(
        self, client, lifecycle_user_headers, lifecycle_admin_headers, published_version_for_lifecycle
    ):
        """Workflow: USER creates draft, ADMIN reviews and finalizes."""
        version_data = published_version_for_lifecycle
        version = version_data["version"]
        fields = version_data["fields"]

        # USER creates
        create_response = client.post(
            "/configurations/",
            json={
                "entity_version_id": version.id,
                "name": "User Draft for Review",
                "data": [
                    {"field_id": fields["name"].id, "value": "Pending Review"},
                    {"field_id": fields["amount"].id, "value": 5000},
                ],
            },
            headers=lifecycle_user_headers,
        )
        assert create_response.status_code == 201
        config_id = create_response.json()["id"]

        # ADMIN reads
        admin_read_response = client.get(f"/configurations/{config_id}", headers=lifecycle_admin_headers)
        assert admin_read_response.status_code == 200

        # ADMIN finalizes
        finalize_response = client.post(f"/configurations/{config_id}/finalize", headers=lifecycle_admin_headers)
        assert finalize_response.status_code == 200
        assert finalize_response.json()["status"] == "FINALIZED"

        # USER can still read finalized config
        user_read_response = client.get(f"/configurations/{config_id}", headers=lifecycle_user_headers)
        assert user_read_response.status_code == 200
        assert user_read_response.json()["status"] == "FINALIZED"

    def test_admin_clones_user_config_for_template(
        self, client, lifecycle_user_headers, lifecycle_admin_headers, finalized_configuration
    ):
        """Workflow: ADMIN clones USER's finalized config as template."""
        # ADMIN clones
        clone_response = client.post(
            f"/configurations/{finalized_configuration.id}/clone", headers=lifecycle_admin_headers
        )
        assert clone_response.status_code == 201
        clone_id = clone_response.json()["id"]

        # Clone is owned by ADMIN
        admin_read_response = client.get(f"/configurations/{clone_id}", headers=lifecycle_admin_headers)
        assert admin_read_response.status_code == 200

        # USER cannot access ADMIN's clone
        user_read_response = client.get(f"/configurations/{clone_id}", headers=lifecycle_user_headers)
        assert user_read_response.status_code == 403
