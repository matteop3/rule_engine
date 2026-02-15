"""
Test suite for Configurations API validation and input handling.

Tests malformed input, missing fields, null values, and data validation.
Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, get_password_hash
from app.models.domain import Entity, EntityVersion, Field, FieldType, User, UserRole, VersionStatus

# ============================================================
# AUTH FIXTURES (local to this module)
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
        is_active=True,
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
        is_free_value=True,
    )
    f_color = Field(
        entity_version_id=version.id,
        name="color",
        label="Colore",
        data_type=FieldType.STRING.value,
        step=1,
        sequence=2,
        is_free_value=True,
    )

    db_session.add_all([f_model, f_color])
    db_session.commit()

    return {"entity_id": entity.id, "version_id": version.id, "f_model_id": f_model.id, "f_color_id": f_color.id}


# ============================================================
# MALFORMED INPUT TESTS
# ============================================================


def test_create_configuration_missing_entity_version_id(client: TestClient, auth_headers):
    """
    Test that missing entity_version_id returns 422 validation error.
    """
    payload = {"name": "No Version", "data": []}

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 422
    error_detail = response.json()["detail"]
    assert any("entity_version_id" in str(e).lower() for e in error_detail)


def test_create_configuration_invalid_entity_version_id_type(client: TestClient, auth_headers):
    """
    Test that entity_version_id with wrong type returns 422.
    """
    payload = {"entity_version_id": "not_an_integer", "name": "Bad Type", "data": []}

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 422


def test_create_configuration_nonexistent_entity_version(client: TestClient, auth_headers):
    """
    Test that referencing a non-existent entity_version_id returns 404.
    """
    payload = {"entity_version_id": 999999, "name": "Ghost Version", "data": []}

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 404


def test_create_configuration_invalid_field_id(client: TestClient, auth_headers, config_scenario):
    """
    Test that referencing a non-existent field_id returns 400.
    This tests the validate_input_data_integrity function.
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Invalid Field",
        "data": [{"field_id": 999999, "value": "test"}],
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 400
    assert "field_id" in response.json()["detail"].lower()


def test_create_configuration_duplicate_field_ids(client: TestClient, auth_headers, config_scenario):
    """
    Test that duplicate field_ids in data array returns 400.
    This tests the validate_input_data_integrity function.
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Duplicate Fields",
        "data": [
            {"field_id": config_scenario["f_model_id"], "value": "First"},
            {"field_id": config_scenario["f_model_id"], "value": "Second"},  # Duplicate!
        ],
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 400
    assert "duplicate" in response.json()["detail"].lower()


def test_create_configuration_invalid_data_structure(client: TestClient, auth_headers, config_scenario):
    """
    Test that data with wrong structure returns 422.
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Bad Data",
        "data": "not_a_list",  # Should be a list
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 422


def test_create_configuration_missing_field_id_in_data(client: TestClient, auth_headers, config_scenario):
    """
    Test that data item missing field_id returns 422.
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Missing field_id",
        "data": [
            {"value": "orphan_value"}  # Missing field_id
        ],
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 422


def test_create_configuration_negative_field_id(client: TestClient, auth_headers, config_scenario):
    """
    Test that negative field_id is rejected.
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Negative ID",
        "data": [{"field_id": -1, "value": "test"}],
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    # Pydantic accepts negative ints, but validation should catch invalid field
    assert response.status_code == 400


def test_create_configuration_empty_payload(client: TestClient, auth_headers):
    """
    Test that completely empty payload returns 422.
    """
    response = client.post("/configurations/", json={}, headers=auth_headers)

    assert response.status_code == 422


# ============================================================
# NULL/NONE VALUE TESTS
# ============================================================


def test_create_configuration_null_value_in_field(client: TestClient, auth_headers, config_scenario):
    """
    Test that null value in a field is accepted (value: Any allows null).
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Null Value Config",
        "data": [{"field_id": config_scenario["f_model_id"], "value": None}],
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    # Null values should be accepted - FieldInputState.value is typed as Any
    assert response.status_code == 201
    data = response.json()
    field_data = next(d for d in data["data"] if d["field_id"] == config_scenario["f_model_id"])
    assert field_data["value"] is None


def test_create_configuration_null_name(client: TestClient, auth_headers, config_scenario):
    """
    Test that null name is accepted (name: Optional[str]).
    """
    payload = {"entity_version_id": config_scenario["version_id"], "name": None, "data": []}

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    # Null name should be accepted - schema defines name as Optional[str]
    assert response.status_code == 201
    assert response.json()["name"] is None


def test_create_configuration_null_entity_version_id(client: TestClient, auth_headers):
    """
    Test that null entity_version_id returns 422 (required field).
    """
    payload = {"entity_version_id": None, "name": "Null Version", "data": []}

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 422


def test_update_configuration_with_null_values(client: TestClient, auth_headers, config_scenario):
    """
    Test that updating configuration with null values in data works correctly.
    """
    # First create a config with a value
    create_payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Original",
        "data": [{"field_id": config_scenario["f_model_id"], "value": "Initial Value"}],
    }
    create_resp = client.post("/configurations/", json=create_payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Update with null value
    update_payload = {"data": [{"field_id": config_scenario["f_model_id"], "value": None}]}
    response = client.patch(f"/configurations/{config_id}", json=update_payload, headers=auth_headers)

    assert response.status_code == 200
    field_data = next(d for d in response.json()["data"] if d["field_id"] == config_scenario["f_model_id"])
    assert field_data["value"] is None


def test_create_configuration_mixed_null_and_valid_values(client: TestClient, auth_headers, config_scenario):
    """
    Test configuration with mix of null and valid values in data array.
    """
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Mixed Values",
        "data": [
            {"field_id": config_scenario["f_model_id"], "value": "Valid String"},
            {"field_id": config_scenario["f_color_id"], "value": None},
        ],
    }

    response = client.post("/configurations/", json=payload, headers=auth_headers)

    assert response.status_code == 201
    data = response.json()["data"]
    model_field = next(d for d in data if d["field_id"] == config_scenario["f_model_id"])
    color_field = next(d for d in data if d["field_id"] == config_scenario["f_color_id"])
    assert model_field["value"] == "Valid String"
    assert color_field["value"] is None
