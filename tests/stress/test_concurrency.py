"""
Test suite for Concurrency scenarios.

Tests:
1. Rapid sequential updates (simulates concurrent-like behavior)
2. Multiple configuration creation
3. Read/write interleaving
4. Race condition detection for delete operations

Note: SQLite in-memory with a single connection doesn't support true multi-threaded
concurrency. These tests verify the application logic handles rapid sequential
operations correctly, which catches many concurrency-related bugs.

For true concurrent testing, use PostgreSQL in a separate test environment.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Entity, EntityVersion, Field, User, UserRole, VersionStatus, FieldType
from app.core.security import create_access_token, get_password_hash
from app.services.rule_engine import RuleEngineService
from app.schemas.engine import CalculationRequest, FieldInputState


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def concurrent_user(db_session):
    """Creates a test user for concurrency tests."""
    user = User(
        email="concurrent@example.com",
        hashed_password=get_password_hash("TestPassword123!"),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def concurrent_auth_headers(concurrent_user):
    """Generates valid auth headers for the concurrent test user."""
    access_token = create_access_token(subject=concurrent_user.id)
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="function")
def concurrent_scenario(db_session):
    """
    Prepares an entity, version and fields for concurrency tests.
    """
    entity = Entity(name="Concurrency Test Entity", description="Test concurrent access")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    f_counter = Field(
        entity_version_id=version.id,
        name="counter",
        label="Counter",
        data_type=FieldType.NUMBER.value,
        step=1,
        sequence=1,
        is_free_value=True
    )
    f_status = Field(
        entity_version_id=version.id,
        name="status",
        label="Status",
        data_type=FieldType.STRING.value,
        step=1,
        sequence=2,
        is_free_value=True
    )

    db_session.add_all([f_counter, f_status])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "f_counter_id": f_counter.id,
        "f_status_id": f_status.id
    }


# ============================================================
# RAPID SEQUENTIAL UPDATE TESTS
# ============================================================

def test_rapid_updates_same_configuration(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Test that rapid sequential updates to the same configuration don't corrupt data.

    Simulates concurrent-like behavior by performing many updates in quick succession.
    Verifies:
    1. All requests complete successfully
    2. Final state is consistent
    3. No data corruption occurs
    """
    # Create initial configuration
    create_payload = {
        "entity_version_id": concurrent_scenario["version_id"],
        "name": "Rapid Update Test Config",
        "data": [
            {"field_id": concurrent_scenario["f_counter_id"], "value": 0},
            {"field_id": concurrent_scenario["f_status_id"], "value": "initial"}
        ]
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=concurrent_auth_headers)
    assert create_resp.status_code == 201
    config_id = create_resp.json()["id"]

    # Perform many rapid updates
    num_updates = 50
    successful_updates = 0
    last_value = None

    for i in range(num_updates):
        update_payload = {
            "name": f"Updated iteration {i}",
            "data": [
                {"field_id": concurrent_scenario["f_counter_id"], "value": i},
                {"field_id": concurrent_scenario["f_status_id"], "value": f"status_{i}"}
            ]
        }
        response = client.patch(
            f"/configurations/{config_id}",
            json=update_payload,
            headers=concurrent_auth_headers
        )
        if response.status_code == 200:
            successful_updates += 1
            last_value = i

    # All updates should succeed
    assert successful_updates == num_updates, f"Only {successful_updates}/{num_updates} updates succeeded"

    # Verify final state is consistent
    final_resp = client.get(f"/configurations/{config_id}", headers=concurrent_auth_headers)
    assert final_resp.status_code == 200
    final_data = final_resp.json()

    # Data should reflect the last update
    assert final_data["name"] == f"Updated iteration {last_value}"
    counter_field = next(d for d in final_data["data"] if d["field_id"] == concurrent_scenario["f_counter_id"])
    assert counter_field["value"] == last_value


def test_rapid_create_configurations(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Test creating multiple configurations in rapid succession.

    Verifies:
    1. All IDs are unique
    2. No missing records
    3. Database integrity is maintained
    """
    num_configurations = 20
    created_ids = []

    for i in range(num_configurations):
        payload = {
            "entity_version_id": concurrent_scenario["version_id"],
            "name": f"Rapid Config {i}",
            "data": [
                {"field_id": concurrent_scenario["f_counter_id"], "value": i}
            ]
        }
        response = client.post("/configurations/", json=payload, headers=concurrent_auth_headers)
        assert response.status_code == 201, f"Failed to create config {i}: {response.text}"
        created_ids.append(response.json()["id"])

    # All IDs should be unique
    assert len(created_ids) == len(set(created_ids)), "Duplicate configuration IDs detected!"

    # Verify all configurations are readable
    for config_id in created_ids:
        resp = client.get(f"/configurations/{config_id}", headers=concurrent_auth_headers)
        assert resp.status_code == 200, f"Config {config_id} not readable"


def test_interleaved_read_write(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Test interleaved read and write operations on the same configuration.

    Verifies reads always return consistent data even during writes.
    """
    # Create initial configuration
    create_payload = {
        "entity_version_id": concurrent_scenario["version_id"],
        "name": "Read-Write Test",
        "data": [{"field_id": concurrent_scenario["f_counter_id"], "value": 0}]
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=concurrent_auth_headers)
    config_id = create_resp.json()["id"]

    read_count = 0
    write_count = 0

    # Interleave reads and writes
    for i in range(100):
        if i % 2 == 0:
            # Read
            response = client.get(f"/configurations/{config_id}", headers=concurrent_auth_headers)
            assert response.status_code == 200
            data = response.json()
            # Data should always be consistent (have expected structure)
            assert "id" in data
            assert "data" in data
            read_count += 1
        else:
            # Write
            payload = {"data": [{"field_id": concurrent_scenario["f_counter_id"], "value": i}]}
            response = client.patch(f"/configurations/{config_id}", json=payload, headers=concurrent_auth_headers)
            assert response.status_code == 200
            write_count += 1

    assert read_count == 50
    assert write_count == 50


# ============================================================
# RULE ENGINE CALCULATION TESTS
# ============================================================

def test_rapid_rule_engine_calculations(db_session, concurrent_scenario):
    """
    Test that the rule engine handles rapid sequential calculations correctly.

    Verifies calculations don't interfere with each other.
    """
    service = RuleEngineService()
    results = []

    for i in range(20):
        payload = CalculationRequest(
            entity_id=concurrent_scenario["entity_id"],
            current_state=[
                FieldInputState(field_id=concurrent_scenario["f_counter_id"], value=i),
                FieldInputState(field_id=concurrent_scenario["f_status_id"], value=f"status_{i}")
            ]
        )
        response = service.calculate_state(db_session, payload)
        results.append({
            "input_value": i,
            "fields_count": len(response.fields)
        })

    # All calculations should succeed and return correct field count
    assert len(results) == 20
    for r in results:
        assert r["fields_count"] == 2


def test_rapid_calculate_endpoint(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Test rapid access to the calculate endpoint via API.
    """
    # Create configuration
    create_payload = {
        "entity_version_id": concurrent_scenario["version_id"],
        "name": "Calculate Test",
        "data": [
            {"field_id": concurrent_scenario["f_counter_id"], "value": 100},
            {"field_id": concurrent_scenario["f_status_id"], "value": "active"}
        ]
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=concurrent_auth_headers)
    config_id = create_resp.json()["id"]

    # Rapid calculate calls
    num_calls = 20
    successful_calls = 0

    for _ in range(num_calls):
        response = client.get(f"/configurations/{config_id}/calculate", headers=concurrent_auth_headers)
        if response.status_code == 200:
            data = response.json()
            if "fields" in data:
                successful_calls += 1

    assert successful_calls == num_calls, f"Only {successful_calls}/{num_calls} calculate calls succeeded"


# ============================================================
# DELETE OPERATION TESTS
# ============================================================

def test_delete_then_access(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Test that accessing a deleted configuration returns 404.

    Simulates a race condition where one client deletes while another reads.
    """
    # Create configuration
    create_payload = {
        "entity_version_id": concurrent_scenario["version_id"],
        "name": "Delete Test",
        "data": []
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=concurrent_auth_headers)
    config_id = create_resp.json()["id"]

    # Delete the configuration
    delete_resp = client.delete(f"/configurations/{config_id}", headers=concurrent_auth_headers)
    assert delete_resp.status_code == 204

    # Subsequent access should return 404
    get_resp = client.get(f"/configurations/{config_id}", headers=concurrent_auth_headers)
    assert get_resp.status_code == 404

    # Update should also return 404
    update_resp = client.patch(
        f"/configurations/{config_id}",
        json={"name": "Updated"},
        headers=concurrent_auth_headers
    )
    assert update_resp.status_code == 404

    # Delete again should return 404
    delete_again_resp = client.delete(f"/configurations/{config_id}", headers=concurrent_auth_headers)
    assert delete_again_resp.status_code == 404


def test_multiple_delete_attempts(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Test that multiple sequential delete attempts handle correctly.

    First delete succeeds, subsequent ones return 404.
    """
    # Create configuration
    create_payload = {
        "entity_version_id": concurrent_scenario["version_id"],
        "name": "Multi Delete Test",
        "data": []
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=concurrent_auth_headers)
    config_id = create_resp.json()["id"]

    # Attempt multiple deletes
    results = []
    for _ in range(5):
        response = client.delete(f"/configurations/{config_id}", headers=concurrent_auth_headers)
        results.append(response.status_code)

    # First should be 204 (success), rest should be 404
    assert results[0] == 204, "First delete should succeed"
    assert all(r == 404 for r in results[1:]), "Subsequent deletes should return 404"


# ============================================================
# MIXED OPERATIONS STRESS TEST
# ============================================================

def test_mixed_operations_stress(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Stress test with mixed operations in rapid succession.

    Simulates real-world load patterns.
    """
    created_configs = []

    # Phase 1: Create configurations
    for i in range(10):
        payload = {
            "entity_version_id": concurrent_scenario["version_id"],
            "name": f"Stress Test {i}",
            "data": [{"field_id": concurrent_scenario["f_counter_id"], "value": i}]
        }
        resp = client.post("/configurations/", json=payload, headers=concurrent_auth_headers)
        assert resp.status_code == 201
        created_configs.append(resp.json()["id"])

    # Phase 2: Mixed operations
    operations_results = {"read": 0, "update": 0, "create": 0}

    for i in range(30):
        op_type = i % 3

        if op_type == 0 and created_configs:
            # Read
            config_id = created_configs[i % len(created_configs)]
            resp = client.get(f"/configurations/{config_id}", headers=concurrent_auth_headers)
            if resp.status_code == 200:
                operations_results["read"] += 1

        elif op_type == 1 and created_configs:
            # Update
            config_id = created_configs[i % len(created_configs)]
            payload = {"data": [{"field_id": concurrent_scenario["f_counter_id"], "value": i * 10}]}
            resp = client.patch(f"/configurations/{config_id}", json=payload, headers=concurrent_auth_headers)
            if resp.status_code == 200:
                operations_results["update"] += 1

        else:
            # Create
            payload = {
                "entity_version_id": concurrent_scenario["version_id"],
                "name": f"Stress Extra {i}",
                "data": []
            }
            resp = client.post("/configurations/", json=payload, headers=concurrent_auth_headers)
            if resp.status_code == 201:
                operations_results["create"] += 1
                created_configs.append(resp.json()["id"])

    # Verify operations succeeded
    total_ops = sum(operations_results.values())
    assert total_ops >= 25, f"Too many operations failed: only {total_ops}/30 succeeded"

    # Final consistency check
    for config_id in created_configs[:5]:
        resp = client.get(f"/configurations/{config_id}", headers=concurrent_auth_headers)
        assert resp.status_code == 200, f"Config {config_id} not accessible after stress test"


# ============================================================
# DATA INTEGRITY TESTS
# ============================================================

def test_update_preserves_unmodified_fields(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Test that updating all fields multiple times doesn't corrupt data.

    Note: The API replaces the entire 'data' array on PATCH, so updates must
    include all fields to preserve them. This test verifies data integrity
    when doing full updates rapidly.
    """
    # Create configuration with both fields
    create_payload = {
        "entity_version_id": concurrent_scenario["version_id"],
        "name": "Integrity Test",
        "data": [
            {"field_id": concurrent_scenario["f_counter_id"], "value": 42},
            {"field_id": concurrent_scenario["f_status_id"], "value": "original"}
        ]
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=concurrent_auth_headers)
    config_id = create_resp.json()["id"]

    # Update counter field while preserving status field (full replacement)
    for i in range(10):
        update_payload = {
            "data": [
                {"field_id": concurrent_scenario["f_counter_id"], "value": i},
                {"field_id": concurrent_scenario["f_status_id"], "value": "original"}
            ]
        }
        client.patch(f"/configurations/{config_id}", json=update_payload, headers=concurrent_auth_headers)

    # Verify both fields are correct
    final_resp = client.get(f"/configurations/{config_id}", headers=concurrent_auth_headers)
    final_data = final_resp.json()

    counter_field = next(
        (d for d in final_data["data"] if d["field_id"] == concurrent_scenario["f_counter_id"]),
        None
    )
    status_field = next(
        (d for d in final_data["data"] if d["field_id"] == concurrent_scenario["f_status_id"]),
        None
    )

    assert counter_field is not None, "Counter field was lost during updates"
    assert counter_field["value"] == 9, "Counter field has wrong value"
    assert status_field is not None, "Status field was lost during updates"
    assert status_field["value"] == "original", "Status field was corrupted"


def test_rapid_name_updates(client: TestClient, concurrent_auth_headers, concurrent_scenario):
    """
    Test rapid updates to configuration name only.
    """
    # Create configuration
    create_payload = {
        "entity_version_id": concurrent_scenario["version_id"],
        "name": "Original Name",
        "data": [{"field_id": concurrent_scenario["f_counter_id"], "value": 100}]
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=concurrent_auth_headers)
    config_id = create_resp.json()["id"]

    # Rapid name updates
    for i in range(20):
        update_payload = {"name": f"Name Version {i}"}
        resp = client.patch(f"/configurations/{config_id}", json=update_payload, headers=concurrent_auth_headers)
        assert resp.status_code == 200

    # Verify final name
    final_resp = client.get(f"/configurations/{config_id}", headers=concurrent_auth_headers)
    assert final_resp.json()["name"] == "Name Version 19"

    # Verify data wasn't corrupted
    data = final_resp.json()["data"]
    counter_field = next(d for d in data if d["field_id"] == concurrent_scenario["f_counter_id"])
    assert counter_field["value"] == 100
