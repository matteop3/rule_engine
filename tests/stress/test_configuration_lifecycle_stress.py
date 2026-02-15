"""
Configuration Lifecycle Stress Tests.

Tests for configuration lifecycle operations under stress conditions:
- Clone performance with many configurations
- Finalize bulk operations
- List filtering with large datasets
- Soft delete scan performance
"""

import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, get_password_hash
from app.models.domain import (
    Configuration,
    ConfigurationStatus,
    Entity,
    EntityVersion,
    Field,
    FieldType,
    User,
    UserRole,
    VersionStatus,
)

# ============================================================
# FIXTURES FOR STRESS TESTS
# ============================================================


@pytest.fixture(scope="function")
def stress_admin(db_session):
    """Creates an admin user for stress tests."""
    user = User(
        email="stress_admin@example.com",
        hashed_password=get_password_hash("AdminPassword123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def stress_admin_headers(stress_admin):
    """Auth headers for stress admin."""
    token = create_access_token(subject=stress_admin.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def stress_user(db_session):
    """Creates a regular user for stress tests."""
    user = User(
        email="stress_user@example.com",
        hashed_password=get_password_hash("UserPassword123!"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def stress_user_headers(stress_user):
    """Auth headers for stress user."""
    token = create_access_token(subject=stress_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def stress_entity_with_version(db_session, stress_admin):
    """Creates an entity with a published version for stress tests."""
    entity = Entity(
        name="Stress Test Entity",
        description="Entity for configuration stress testing",
        created_by_id=stress_admin.id,
        updated_by_id=stress_admin.id,
    )
    db_session.add(entity)
    db_session.flush()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        changelog="Published version for stress tests",
        published_at=datetime.now(UTC),
        created_by_id=stress_admin.id,
        updated_by_id=stress_admin.id,
    )
    db_session.add(version)
    db_session.flush()

    # Create fields
    field_name = Field(
        entity_version_id=version.id,
        name="name",
        label="Name",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=True,
        sequence=1,
    )
    field_amount = Field(
        entity_version_id=version.id,
        name="amount",
        label="Amount",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        sequence=2,
    )
    db_session.add_all([field_name, field_amount])
    db_session.commit()

    db_session.refresh(entity)
    db_session.refresh(version)
    db_session.refresh(field_name)
    db_session.refresh(field_amount)

    return {"entity": entity, "version": version, "fields": {"name": field_name, "amount": field_amount}}


@pytest.fixture(scope="function")
def base_draft_config(db_session, stress_user, stress_entity_with_version):
    """Creates a base DRAFT configuration for cloning tests."""
    version = stress_entity_with_version["version"]
    fields = stress_entity_with_version["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=stress_user.id,
        name="Base Config for Stress Test",
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        is_deleted=False,
        data=[
            {"field_id": fields["name"].id, "value": "Stress Test User"},
            {"field_id": fields["amount"].id, "value": 1000},
        ],
        created_by_id=stress_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


# ============================================================
# CLONE PERFORMANCE TESTS
# ============================================================


class TestClonePerformance:
    """Tests for clone operation performance."""

    def test_clone_100_configs_sequentially(
        self, client: TestClient, stress_user_headers, base_draft_config, stress_entity_with_version
    ):
        """
        Stress: Clone 100 configurations sequentially.
        Threshold: < 10 seconds
        """
        source_id = base_draft_config.id
        clone_ids = []

        start_time = time.time()

        for i in range(100):
            response = client.post(f"/configurations/{source_id}/clone", headers=stress_user_headers)
            assert response.status_code == 201, f"Clone {i + 1} failed: {response.text}"
            clone_ids.append(response.json()["id"])

        elapsed_time = time.time() - start_time

        # All clones should have unique IDs
        assert len(clone_ids) == 100
        assert len(set(clone_ids)) == 100

        # All clones should be DRAFT
        for clone_id in clone_ids[:5]:  # Sample check first 5
            response = client.get(f"/configurations/{clone_id}", headers=stress_user_headers)
            assert response.json()["status"] == "DRAFT"

        # Performance threshold
        assert elapsed_time < 10.0, f"Clone 100 configs took {elapsed_time:.2f}s, threshold is 10s"

    def test_clone_preserves_data_integrity_under_load(
        self, client: TestClient, stress_user_headers, base_draft_config, stress_entity_with_version
    ):
        """
        Stress: Verify data integrity across 50 rapid clones.
        """
        source_id = base_draft_config.id
        original_data = base_draft_config.data.copy()

        clone_ids = []
        for _ in range(50):
            response = client.post(f"/configurations/{source_id}/clone", headers=stress_user_headers)
            assert response.status_code == 201
            clone_ids.append(response.json()["id"])

        # Verify each clone has same data as original
        for clone_id in clone_ids:
            response = client.get(f"/configurations/{clone_id}", headers=stress_user_headers)
            clone_data = response.json()["data"]

            # Compare field values (field_ids may differ in structure but values should match)
            original_values = {item["field_id"]: item["value"] for item in original_data}
            clone_values = {item["field_id"]: item["value"] for item in clone_data}

            assert original_values == clone_values, f"Clone {clone_id} data mismatch"

    def test_clone_chain_performance(self, client: TestClient, stress_user_headers, base_draft_config):
        """
        Stress: Clone of clone chain (20 generations).
        Each clone is a clone of the previous one.
        """
        current_id = base_draft_config.id
        chain_ids = [current_id]

        start_time = time.time()

        for i in range(20):
            response = client.post(f"/configurations/{current_id}/clone", headers=stress_user_headers)
            assert response.status_code == 201, f"Clone generation {i + 1} failed"
            current_id = response.json()["id"]
            chain_ids.append(current_id)

        elapsed_time = time.time() - start_time

        # Verify chain
        assert len(chain_ids) == 21  # Original + 20 clones

        # Performance: should complete in reasonable time
        assert elapsed_time < 5.0, f"Clone chain of 20 took {elapsed_time:.2f}s, threshold is 5s"


# ============================================================
# FINALIZE BULK PERFORMANCE TESTS
# ============================================================


class TestFinalizeBulkPerformance:
    """Tests for finalize operation performance with many configs."""

    def test_finalize_100_configs_sequentially(
        self, client: TestClient, db_session, stress_user_headers, stress_user, stress_entity_with_version
    ):
        """
        Stress: Finalize 100 configurations sequentially.
        Threshold: < 5 seconds
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        # Create 100 DRAFT configs
        config_ids = []
        for i in range(100):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_user.id,
                name=f"Finalize Test Config {i + 1}",
                status=ConfigurationStatus.DRAFT,
                is_complete=True,
                is_deleted=False,
                data=[
                    {"field_id": fields["name"].id, "value": f"User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": 100 * (i + 1)},
                ],
                created_by_id=stress_user.id,
            )
            db_session.add(config)
            config_ids.append(config)

        db_session.commit()
        for config in config_ids:
            db_session.refresh(config)

        # Finalize all
        start_time = time.time()

        for config in config_ids:
            response = client.post(f"/configurations/{config.id}/finalize", headers=stress_user_headers)
            assert response.status_code == 200, f"Finalize failed for config {config.id}"
            assert response.json()["status"] == "FINALIZED"

        elapsed_time = time.time() - start_time

        # Performance threshold
        assert elapsed_time < 5.0, f"Finalize 100 configs took {elapsed_time:.2f}s, threshold is 5s"

    def test_finalize_status_consistency_under_load(
        self, client: TestClient, db_session, stress_user_headers, stress_user, stress_entity_with_version
    ):
        """
        Stress: Verify status consistency after finalizing 50 configs.
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        # Create and finalize 50 configs
        config_ids = []
        for i in range(50):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_user.id,
                name=f"Consistency Test Config {i + 1}",
                status=ConfigurationStatus.DRAFT,
                is_complete=True,
                is_deleted=False,
                data=[
                    {"field_id": fields["name"].id, "value": f"User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i * 100},
                ],
                created_by_id=stress_user.id,
            )
            db_session.add(config)
            config_ids.append(config)

        db_session.commit()

        # Finalize all
        for config in config_ids:
            db_session.refresh(config)
            client.post(f"/configurations/{config.id}/finalize", headers=stress_user_headers)

        # Verify all are FINALIZED
        db_session.expire_all()
        for config in config_ids:
            db_session.refresh(config)
            assert config.status == ConfigurationStatus.FINALIZED, f"Config {config.id} should be FINALIZED"


# ============================================================
# LIST FILTERING PERFORMANCE TESTS
# ============================================================


class TestListFilteringPerformance:
    """Tests for list filtering performance with large datasets."""

    def test_list_with_status_filter_performance(
        self, client: TestClient, db_session, stress_admin_headers, stress_admin, stress_entity_with_version
    ):
        """
        Stress: Filter configurations by status with large dataset.
        Creates 200 configs (100 DRAFT, 100 FINALIZED) and filters.
        Threshold: < 500ms per query
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        # Create 100 DRAFT configs
        for i in range(100):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_admin.id,
                name=f"Draft Config {i + 1}",
                status=ConfigurationStatus.DRAFT,
                is_complete=True,
                is_deleted=False,
                data=[
                    {"field_id": fields["name"].id, "value": f"Draft User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i * 10},
                ],
                created_by_id=stress_admin.id,
            )
            db_session.add(config)

        # Create 100 FINALIZED configs
        for i in range(100):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_admin.id,
                name=f"Finalized Config {i + 1}",
                status=ConfigurationStatus.FINALIZED,
                is_complete=True,
                is_deleted=False,
                data=[
                    {"field_id": fields["name"].id, "value": f"Final User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i * 100},
                ],
                created_by_id=stress_admin.id,
                updated_by_id=stress_admin.id,
            )
            db_session.add(config)

        db_session.commit()

        # Test DRAFT filter
        start_time = time.time()
        response = client.get("/configurations/?status=DRAFT", headers=stress_admin_headers)
        draft_time = time.time() - start_time

        assert response.status_code == 200
        draft_configs = response.json()
        assert all(c["status"] == "DRAFT" for c in draft_configs)

        # Test FINALIZED filter
        start_time = time.time()
        response = client.get("/configurations/?status=FINALIZED", headers=stress_admin_headers)
        finalized_time = time.time() - start_time

        assert response.status_code == 200
        finalized_configs = response.json()
        assert all(c["status"] == "FINALIZED" for c in finalized_configs)

        # Performance thresholds
        assert draft_time < 0.5, f"DRAFT filter took {draft_time:.3f}s, threshold is 0.5s"
        assert finalized_time < 0.5, f"FINALIZED filter took {finalized_time:.3f}s, threshold is 0.5s"

    def test_list_combines_filters_performance(
        self, client: TestClient, db_session, stress_admin_headers, stress_admin, stress_entity_with_version
    ):
        """
        Stress: Combined status and entity_version_id filtering.
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        # Create 50 configs
        for i in range(50):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_admin.id,
                name=f"Combined Filter Test {i + 1}",
                status=ConfigurationStatus.DRAFT if i % 2 == 0 else ConfigurationStatus.FINALIZED,
                is_complete=True,
                is_deleted=False,
                data=[
                    {"field_id": fields["name"].id, "value": f"User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i * 50},
                ],
                created_by_id=stress_admin.id,
            )
            db_session.add(config)

        db_session.commit()

        # Combined filter
        start_time = time.time()
        response = client.get(
            f"/configurations/?status=DRAFT&entity_version_id={version.id}", headers=stress_admin_headers
        )
        elapsed_time = time.time() - start_time

        assert response.status_code == 200
        configs = response.json()
        for config in configs:
            assert config["status"] == "DRAFT"
            assert config["entity_version_id"] == version.id

        assert elapsed_time < 0.5, f"Combined filter took {elapsed_time:.3f}s, threshold is 0.5s"


# ============================================================
# SOFT DELETE SCAN PERFORMANCE TESTS
# ============================================================


class TestSoftDeleteScanPerformance:
    """Tests for list performance when excluding soft-deleted configs."""

    def test_list_excluding_soft_deleted_performance(
        self, client: TestClient, db_session, stress_admin_headers, stress_admin, stress_entity_with_version
    ):
        """
        Stress: List configs excluding soft-deleted with large dataset.
        Creates 100 active + 100 soft-deleted configs.
        Threshold: < 500ms
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        # Create 100 active configs
        for i in range(100):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_admin.id,
                name=f"Active Config {i + 1}",
                status=ConfigurationStatus.FINALIZED,
                is_complete=True,
                is_deleted=False,
                data=[
                    {"field_id": fields["name"].id, "value": f"Active User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i * 10},
                ],
                created_by_id=stress_admin.id,
                updated_by_id=stress_admin.id,
            )
            db_session.add(config)

        # Create 100 soft-deleted configs
        for i in range(100):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_admin.id,
                name=f"Deleted Config {i + 1}",
                status=ConfigurationStatus.FINALIZED,
                is_complete=True,
                is_deleted=True,
                data=[
                    {"field_id": fields["name"].id, "value": f"Deleted User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i * 100},
                ],
                created_by_id=stress_admin.id,
                updated_by_id=stress_admin.id,
            )
            db_session.add(config)

        db_session.commit()

        # List without include_deleted (default)
        start_time = time.time()
        response = client.get("/configurations/", headers=stress_admin_headers)
        exclude_deleted_time = time.time() - start_time

        assert response.status_code == 200
        configs = response.json()
        assert all(c["is_deleted"] is False for c in configs)

        # Performance threshold
        assert exclude_deleted_time < 0.5, f"List excluding deleted took {exclude_deleted_time:.3f}s, threshold is 0.5s"

    def test_list_including_soft_deleted_performance(
        self, client: TestClient, db_session, stress_admin_headers, stress_admin, stress_entity_with_version
    ):
        """
        Stress: List configs including soft-deleted (admin only).
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        # Create mixed dataset
        for i in range(50):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_admin.id,
                name=f"Mixed Config {i + 1}",
                status=ConfigurationStatus.FINALIZED,
                is_complete=True,
                is_deleted=(i % 2 == 0),  # Half are deleted
                data=[
                    {"field_id": fields["name"].id, "value": f"User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i * 25},
                ],
                created_by_id=stress_admin.id,
                updated_by_id=stress_admin.id,
            )
            db_session.add(config)

        db_session.commit()

        # List with include_deleted=true
        start_time = time.time()
        response = client.get("/configurations/?include_deleted=true", headers=stress_admin_headers)
        include_deleted_time = time.time() - start_time

        assert response.status_code == 200

        # Performance threshold
        assert include_deleted_time < 0.5, f"List including deleted took {include_deleted_time:.3f}s, threshold is 0.5s"


# ============================================================
# MIXED OPERATIONS STRESS TESTS
# ============================================================


class TestMixedOperationsStress:
    """Tests for mixed lifecycle operations under load."""

    def test_mixed_clone_finalize_cycle(
        self, client: TestClient, db_session, stress_user_headers, stress_user, stress_entity_with_version
    ):
        """
        Stress: Alternating clone and finalize operations.
        Create -> Finalize -> Clone -> Finalize (repeat 30 times)
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        # Create initial config
        initial_config = Configuration(
            entity_version_id=version.id,
            user_id=stress_user.id,
            name="Cycle Start Config",
            status=ConfigurationStatus.DRAFT,
            is_complete=True,
            is_deleted=False,
            data=[
                {"field_id": fields["name"].id, "value": "Cycle User"},
                {"field_id": fields["amount"].id, "value": 500},
            ],
            created_by_id=stress_user.id,
        )
        db_session.add(initial_config)
        db_session.commit()
        db_session.refresh(initial_config)

        current_id = initial_config.id
        finalized_count = 0

        start_time = time.time()

        for i in range(30):
            # Finalize current
            finalize_resp = client.post(f"/configurations/{current_id}/finalize", headers=stress_user_headers)
            assert finalize_resp.status_code == 200
            finalized_count += 1

            # Clone
            clone_resp = client.post(f"/configurations/{current_id}/clone", headers=stress_user_headers)
            assert clone_resp.status_code == 201
            current_id = clone_resp.json()["id"]

        elapsed_time = time.time() - start_time

        assert finalized_count == 30
        assert elapsed_time < 10.0, f"30 clone-finalize cycles took {elapsed_time:.2f}s, threshold is 10s"

    def test_parallel_user_operations_simulation(
        self, client: TestClient, db_session, stress_admin, stress_user, stress_entity_with_version
    ):
        """
        Stress: Simulate multiple users performing operations.
        Admin and User creating/cloning configs simultaneously.
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        admin_headers = {"Authorization": f"Bearer {create_access_token(subject=stress_admin.id)}"}
        user_headers = {"Authorization": f"Bearer {create_access_token(subject=stress_user.id)}"}

        # Create base configs for each user
        admin_base = Configuration(
            entity_version_id=version.id,
            user_id=stress_admin.id,
            name="Admin Base Config",
            status=ConfigurationStatus.DRAFT,
            is_complete=True,
            is_deleted=False,
            data=[{"field_id": fields["name"].id, "value": "Admin"}, {"field_id": fields["amount"].id, "value": 10000}],
            created_by_id=stress_admin.id,
        )
        user_base = Configuration(
            entity_version_id=version.id,
            user_id=stress_user.id,
            name="User Base Config",
            status=ConfigurationStatus.DRAFT,
            is_complete=True,
            is_deleted=False,
            data=[{"field_id": fields["name"].id, "value": "User"}, {"field_id": fields["amount"].id, "value": 1000}],
            created_by_id=stress_user.id,
        )
        db_session.add_all([admin_base, user_base])
        db_session.commit()
        db_session.refresh(admin_base)
        db_session.refresh(user_base)

        start_time = time.time()

        # Interleaved operations
        for i in range(20):
            # Admin clones
            admin_clone = client.post(f"/configurations/{admin_base.id}/clone", headers=admin_headers)
            assert admin_clone.status_code == 201

            # User clones
            user_clone = client.post(f"/configurations/{user_base.id}/clone", headers=user_headers)
            assert user_clone.status_code == 201

        elapsed_time = time.time() - start_time

        assert elapsed_time < 5.0, f"40 interleaved clones took {elapsed_time:.2f}s, threshold is 5s"


# ============================================================
# DATABASE INTEGRITY UNDER STRESS
# ============================================================


class TestDatabaseIntegrityStress:
    """Tests for database integrity under stress conditions."""

    def test_no_orphaned_configs_after_mass_operations(
        self, client: TestClient, db_session, stress_user_headers, stress_user, stress_entity_with_version
    ):
        """
        Stress: Verify no orphaned configs after mass create/clone/finalize.
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        initial_count = db_session.query(Configuration).count()

        # Create and operate on many configs
        created_ids = []
        for i in range(30):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_user.id,
                name=f"Integrity Test {i + 1}",
                status=ConfigurationStatus.DRAFT,
                is_complete=True,
                is_deleted=False,
                data=[
                    {"field_id": fields["name"].id, "value": f"User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i * 100},
                ],
                created_by_id=stress_user.id,
            )
            db_session.add(config)
            created_ids.append(config)

        db_session.commit()

        # Clone each
        cloned_ids = []
        for config in created_ids:
            db_session.refresh(config)
            response = client.post(f"/configurations/{config.id}/clone", headers=stress_user_headers)
            if response.status_code == 201:
                cloned_ids.append(response.json()["id"])

        # Finalize originals
        for config in created_ids:
            client.post(f"/configurations/{config.id}/finalize", headers=stress_user_headers)

        # Verify database state
        final_count = db_session.query(Configuration).count()
        expected_count = initial_count + 30 + len(cloned_ids)

        assert final_count == expected_count, f"Expected {expected_count} configs, found {final_count}"

    def test_status_field_integrity_after_bulk_finalize(
        self, client: TestClient, db_session, stress_user_headers, stress_user, stress_entity_with_version
    ):
        """
        Stress: Verify status field integrity after bulk finalize.
        """
        version = stress_entity_with_version["version"]
        fields = stress_entity_with_version["fields"]

        # Create 50 DRAFT configs
        configs = []
        for i in range(50):
            config = Configuration(
                entity_version_id=version.id,
                user_id=stress_user.id,
                name=f"Status Integrity Test {i + 1}",
                status=ConfigurationStatus.DRAFT,
                is_complete=True,
                is_deleted=False,
                data=[
                    {"field_id": fields["name"].id, "value": f"User {i + 1}"},
                    {"field_id": fields["amount"].id, "value": i},
                ],
                created_by_id=stress_user.id,
            )
            db_session.add(config)
            configs.append(config)

        db_session.commit()

        # Finalize all
        for config in configs:
            db_session.refresh(config)
            client.post(f"/configurations/{config.id}/finalize", headers=stress_user_headers)

        # Verify all have FINALIZED status in database
        db_session.expire_all()
        for config in configs:
            db_session.refresh(config)
            assert config.status == ConfigurationStatus.FINALIZED, (
                f"Config {config.id} should be FINALIZED, got {config.status}"
            )

        # Also verify via API
        for config in configs[:10]:  # Sample check
            response = client.get(f"/configurations/{config.id}", headers=stress_user_headers)
            assert response.json()["status"] == "FINALIZED"


# ============================================================
# UPGRADE PERFORMANCE TESTS
# ============================================================


class TestUpgradePerformance:
    """Tests for upgrade operation performance."""

    def test_upgrade_50_configs_sequentially(
        self, client: TestClient, db_session, stress_user_headers, stress_admin, stress_user
    ):
        """
        Stress: Upgrade 50 configurations from archived to published version.
        """
        # Create entity with archived and published versions
        entity = Entity(
            name="Upgrade Stress Test Entity",
            description="Entity for upgrade stress testing",
            created_by_id=stress_admin.id,
            updated_by_id=stress_admin.id,
        )
        db_session.add(entity)
        db_session.flush()

        # Archived version (v1)
        archived_version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.ARCHIVED,
            changelog="Archived version",
            published_at=datetime.now(UTC),
            created_by_id=stress_admin.id,
            updated_by_id=stress_admin.id,
        )
        db_session.add(archived_version)
        db_session.flush()

        archived_field = Field(
            entity_version_id=archived_version.id,
            name="legacy_field",
            label="Legacy Field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=1,
        )
        db_session.add(archived_field)
        db_session.flush()

        # Published version (v2)
        published_version = EntityVersion(
            entity_id=entity.id,
            version_number=2,
            status=VersionStatus.PUBLISHED,
            changelog="Published version",
            published_at=datetime.now(UTC),
            created_by_id=stress_admin.id,
            updated_by_id=stress_admin.id,
        )
        db_session.add(published_version)
        db_session.flush()

        published_field = Field(
            entity_version_id=published_version.id,
            name="new_field",
            label="New Field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=1,
        )
        db_session.add(published_field)
        db_session.flush()

        # Create 50 configs on archived version
        configs = []
        for i in range(50):
            config = Configuration(
                entity_version_id=archived_version.id,
                user_id=stress_user.id,
                name=f"Upgrade Test Config {i + 1}",
                status=ConfigurationStatus.DRAFT,
                is_complete=True,
                is_deleted=False,
                data=[{"field_id": archived_field.id, "value": f"Legacy Value {i + 1}"}],
                created_by_id=stress_user.id,
            )
            db_session.add(config)
            configs.append(config)

        db_session.commit()

        # Upgrade all
        start_time = time.time()

        for config in configs:
            db_session.refresh(config)
            response = client.post(f"/configurations/{config.id}/upgrade", headers=stress_user_headers)
            assert response.status_code == 200, f"Upgrade failed for config {config.id}"
            assert response.json()["entity_version_id"] == published_version.id

        elapsed_time = time.time() - start_time

        # Performance threshold
        assert elapsed_time < 10.0, f"Upgrade 50 configs took {elapsed_time:.2f}s, threshold is 10s"
