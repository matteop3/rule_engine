"""
Test suite for Configurations API CRUD endpoints.

Tests basic Create, Read, List, Update, Delete operations.
Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Entity, EntityVersion, Field, User, UserRole, VersionStatus, FieldType
from app.core.security import create_access_token, get_password_hash


# ============================================================
# AUTH FIXTURES (locale per questo modulo)
# ============================================================

@pytest.fixture(scope="function")
def test_user_for_config(db_session):
    """
    Creates a test user for configuration tests.
    Uses the same db_session to ensure consistency.
    """
    user = User(
        email="configuser@example.com",
        hashed_password=get_password_hash("TestPassword123!"),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def auth_headers(db_session, test_user_for_config):
    """
    Generates valid auth headers for the test user.
    Depends on db_session to ensure the user exists in the same session.
    """
    access_token = create_access_token(subject=test_user_for_config.id)
    return {"Authorization": f"Bearer {access_token}"}


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def config_scenario(db_session):
    """
    Prepares an entity, version and fields for configuration tests.
    """
    entity = Entity(name="Config Test Entity", description="Test API")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    f_model = Field(
        entity_version_id=version.id,
        name="model",
        label="Modello",
        data_type=FieldType.STRING.value,
        step=1,
        sequence=1,
        is_free_value=True
    )
    f_color = Field(
        entity_version_id=version.id,
        name="color",
        label="Colore",
        data_type=FieldType.STRING.value,
        step=1,
        sequence=2,
        is_free_value=True
    )

    db_session.add_all([f_model, f_color])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "f_model_id": f_model.id,
        "f_color_id": f_color.id
    }


# ============================================================
# CREATE TESTS
# ============================================================

def test_create_configuration_success(client: TestClient, auth_headers, config_scenario):
    """
    Test successful configuration creation.
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "My Configuration",
        "data": [
            {"field_id": config_scenario["f_model_id"], "value": "Tesla Model S"},
            {"field_id": config_scenario["f_color_id"], "value": "Red"}
        ]
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "My Configuration"
    assert len(data["data"]) == 2
    assert "id" in data


def test_create_configuration_without_auth(client: TestClient, config_scenario):
    """
    Test that creating configuration without auth returns 401.
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Unauthorized Config",
        "data": []
    }

    response = client.post("/configurations/", json=payload)

    assert response.status_code == 401


def test_create_configuration_empty_name(client: TestClient, auth_headers, config_scenario):
    """
    Test that creating configuration with empty name is allowed.
    The API accepts empty strings for name (schema allows Optional[str]).
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "",
        "data": []
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    # Empty name is valid - API creates the configuration
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == ""
    assert "id" in data


# ============================================================
# READ TESTS
# ============================================================

def test_read_configuration_success(client: TestClient, auth_headers, config_scenario):
    """
    Test reading a configuration by ID.
    """
    # First create a configuration
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Test Read",
        "data": [{"field_id": config_scenario["f_model_id"], "value": "BMW"}]
    }
    create_resp = client.post("/configurations/", json=payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Now read it
    response = client.get(f"/configurations/{config_id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["id"] == config_id
    assert response.json()["name"] == "Test Read"


def test_read_configuration_not_found(client: TestClient, auth_headers):
    """
    Test reading non-existent configuration returns 404.
    """
    response = client.get("/configurations/99999", headers=auth_headers)

    assert response.status_code == 404


def test_read_configuration_without_auth(client: TestClient, auth_headers, config_scenario):
    """
    Test reading configuration without auth returns 401.
    """
    # Create config first
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Private Config",
        "data": []
    }
    create_resp = client.post("/configurations/", json=payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Try to read without auth
    response = client.get(f"/configurations/{config_id}")

    assert response.status_code == 401


# ============================================================
# LIST TESTS
# ============================================================

def test_list_configurations_success(client: TestClient, auth_headers, config_scenario):
    """
    Test listing configurations by entity_version_id.
    """
    # Create two configurations
    for name in ["Config A", "Config B"]:
        payload = {
            "entity_version_id": config_scenario["version_id"],
            "name": name,
            "data": []
        }
        client.post("/configurations/", json=payload, headers=auth_headers)

    # List configurations
    response = client.get(
        f"/configurations/?entity_version_id={config_scenario['version_id']}",
        headers=auth_headers
    )

    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 2


def test_list_configurations_empty(client: TestClient, auth_headers, db_session):
    """
    Test listing configurations when none exist returns empty list.
    Uses a fresh version with no configurations to ensure deterministic result.
    """
    # Create a separate version with no configurations
    from app.models.domain import Entity, EntityVersion, VersionStatus

    entity = Entity(name="Empty Config Entity", description="For empty list test")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # Query configurations for this fresh version
    response = client.get(
        f"/configurations/?entity_version_id={version.id}",
        headers=auth_headers
    )

    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert len(items) == 0, "Expected empty list for version with no configurations"


# ============================================================
# UPDATE TESTS
# ============================================================

def test_update_configuration_success(client: TestClient, auth_headers, config_scenario):
    """
    Test updating a configuration.
    """
    # Create config
    create_payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Original Name",
        "data": [{"field_id": config_scenario["f_model_id"], "value": "Audi A4"}]
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Update config
    update_payload = {
        "name": "Updated Name",
        "data": [{"field_id": config_scenario["f_model_id"], "value": "Audi A6"}]
    }
    response = client.patch(f"/configurations/{config_id}", json=update_payload, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Name"

    # Verify the update persisted
    get_resp = client.get(f"/configurations/{config_id}", headers=auth_headers)
    model_value = next(d["value"] for d in get_resp.json()["data"] if d["field_id"] == config_scenario["f_model_id"])
    assert model_value == "Audi A6"


def test_update_configuration_not_found(client: TestClient, auth_headers):
    """
    Test updating non-existent configuration returns 404.
    """
    update_payload = {"name": "Ghost Config"}
    response = client.patch("/configurations/99999", json=update_payload, headers=auth_headers)

    assert response.status_code == 404


def test_update_configuration_without_auth(client: TestClient, auth_headers, config_scenario):
    """
    Test updating configuration without auth returns 401.
    """
    # Create config first
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "To Update",
        "data": []
    }
    create_resp = client.post("/configurations/", json=payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Try to update without auth
    response = client.patch(f"/configurations/{config_id}", json={"name": "Hacked"})

    assert response.status_code == 401


# ============================================================
# DELETE TESTS
# ============================================================

def test_delete_configuration_success(client: TestClient, auth_headers, config_scenario):
    """
    Test deleting a configuration.
    """
    # Create config
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "To Delete",
        "data": []
    }
    create_resp = client.post("/configurations/", json=payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Delete config
    response = client.delete(f"/configurations/{config_id}", headers=auth_headers)

    assert response.status_code == 204

    # Verify it's gone
    get_resp = client.get(f"/configurations/{config_id}", headers=auth_headers)
    assert get_resp.status_code == 404


def test_delete_configuration_not_found(client: TestClient, auth_headers):
    """
    Test deleting non-existent configuration returns 404.
    """
    response = client.delete("/configurations/99999", headers=auth_headers)

    assert response.status_code == 404


def test_delete_configuration_without_auth(client: TestClient, auth_headers, config_scenario):
    """
    Test deleting configuration without auth returns 401.
    """
    # Create config first
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Cannot Delete",
        "data": []
    }
    create_resp = client.post("/configurations/", json=payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Try to delete without auth
    response = client.delete(f"/configurations/{config_id}")

    assert response.status_code == 401
