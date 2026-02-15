"""
Test suite for Configurations Calculate endpoint.

Tests the integration with the Rule Engine for configuration calculations.
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
# CALCULATE (RULE ENGINE INTEGRATION) TESTS
# ============================================================


def test_calculate_configuration_success(client: TestClient, auth_headers, config_scenario):
    """
    Test the calculate endpoint integrates correctly with Rule Engine.
    """
    # Create config with data
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "Calculate Test",
        "data": [
            {"field_id": config_scenario["f_model_id"], "value": "Porsche 911"},
            {"field_id": config_scenario["f_color_id"], "value": "Black"},
        ],
    }
    create_resp = client.post("/configurations/", json=payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Call calculate
    response = client.get(f"/configurations/{config_id}/calculate", headers=auth_headers)

    assert response.status_code == 200
    engine_response = response.json()

    # Verify engine response structure
    assert "fields" in engine_response
    assert "is_complete" in engine_response

    # Find the model field in the response
    model_field = next((f for f in engine_response["fields"] if f["field_id"] == config_scenario["f_model_id"]), None)
    assert model_field is not None
    assert model_field["current_value"] == "Porsche 911"
    assert model_field["is_hidden"] is False


def test_calculate_configuration_not_found(client: TestClient, auth_headers):
    """
    Test calculate on non-existent configuration returns 404.
    """
    response = client.get("/configurations/99999/calculate", headers=auth_headers)

    assert response.status_code == 404


def test_calculate_configuration_without_auth(client: TestClient, auth_headers, config_scenario):
    """
    Test calculate without auth returns 401.
    """
    # Create config first
    payload = {"entity_version_id": config_scenario["version_id"], "name": "Calc Test", "data": []}
    create_resp = client.post("/configurations/", json=payload, headers=auth_headers)
    config_id = create_resp.json()["id"]

    # Try to calculate without auth
    response = client.get(f"/configurations/{config_id}/calculate")

    assert response.status_code == 401
