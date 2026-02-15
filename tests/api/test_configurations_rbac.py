"""
Test suite for Configurations API Role-Based Access Control.

Tests user isolation, authorization, and admin privileges.
Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, get_password_hash
from app.models.domain import Entity, EntityVersion, Field, FieldType, User, UserRole, VersionStatus

# ============================================================
# FIXTURES - Entity/Version Scenario
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
# ROLE-BASED ACCESS CONTROL FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def admin_user(db_session):
    """Creates an admin user for RBAC tests."""
    user = User(
        email="admin@example.com",
        hashed_password=get_password_hash("AdminPassword123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def admin_headers_rbac(admin_user):
    """Auth headers for admin user."""
    token = create_access_token(subject=admin_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def author_user(db_session):
    """Creates an author user for RBAC tests."""
    user = User(
        email="author@example.com",
        hashed_password=get_password_hash("AuthorPassword123!"),
        role=UserRole.AUTHOR,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def author_headers_rbac(author_user):
    """Auth headers for author user."""
    token = create_access_token(subject=author_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def regular_user_1(db_session):
    """Creates first regular user for RBAC tests."""
    user = User(
        email="user1@example.com",
        hashed_password=get_password_hash("User1Password123!"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def user1_headers(regular_user_1):
    """Auth headers for regular user 1."""
    token = create_access_token(subject=regular_user_1.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def regular_user_2(db_session):
    """Creates second regular user for RBAC tests."""
    user = User(
        email="user2@example.com",
        hashed_password=get_password_hash("User2Password123!"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def user2_headers(regular_user_2):
    """Auth headers for regular user 2."""
    token = create_access_token(subject=regular_user_2.id)
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# USER ISOLATION TESTS
# ============================================================


def test_user_cannot_read_other_user_configuration(client: TestClient, config_scenario, user1_headers, user2_headers):
    """
    Test that a USER cannot read another USER's configuration.
    """
    # User 1 creates a configuration
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "User1 Config",
        "data": [{"field_id": config_scenario["f_model_id"], "value": "Tesla"}],
    }
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    assert create_resp.status_code == 201
    config_id = create_resp.json()["id"]

    # User 2 tries to read User 1's configuration
    response = client.get(f"/configurations/{config_id}", headers=user2_headers)

    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


def test_user_cannot_update_other_user_configuration(client: TestClient, config_scenario, user1_headers, user2_headers):
    """
    Test that a USER cannot update another USER's configuration.
    """
    # User 1 creates a configuration
    payload = {"entity_version_id": config_scenario["version_id"], "name": "User1 Config", "data": []}
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    config_id = create_resp.json()["id"]

    # User 2 tries to update User 1's configuration
    update_payload = {"name": "Hacked by User2"}
    response = client.patch(f"/configurations/{config_id}", json=update_payload, headers=user2_headers)

    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


def test_user_cannot_delete_other_user_configuration(client: TestClient, config_scenario, user1_headers, user2_headers):
    """
    Test that a USER cannot delete another USER's configuration.
    """
    # User 1 creates a configuration
    payload = {"entity_version_id": config_scenario["version_id"], "name": "User1 Config", "data": []}
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    config_id = create_resp.json()["id"]

    # User 2 tries to delete User 1's configuration
    response = client.delete(f"/configurations/{config_id}", headers=user2_headers)

    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


def test_user_cannot_calculate_other_user_configuration(
    client: TestClient, config_scenario, user1_headers, user2_headers
):
    """
    Test that a USER cannot calculate another USER's configuration.
    """
    # User 1 creates a configuration
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "User1 Config",
        "data": [{"field_id": config_scenario["f_model_id"], "value": "BMW"}],
    }
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    config_id = create_resp.json()["id"]

    # User 2 tries to calculate User 1's configuration
    response = client.get(f"/configurations/{config_id}/calculate", headers=user2_headers)

    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


# ============================================================
# AUTHOR ISOLATION TESTS
# ============================================================


def test_author_cannot_read_other_author_configuration(client: TestClient, config_scenario, db_session):
    """
    Test that an AUTHOR cannot read another AUTHOR's configuration.
    """
    # Create two author users
    author1 = User(
        email="author1@example.com",
        hashed_password=get_password_hash("Author1Pass123!"),
        role=UserRole.AUTHOR,
        is_active=True,
    )
    author2 = User(
        email="author2@example.com",
        hashed_password=get_password_hash("Author2Pass123!"),
        role=UserRole.AUTHOR,
        is_active=True,
    )
    db_session.add_all([author1, author2])
    db_session.commit()

    author1_headers = {"Authorization": f"Bearer {create_access_token(subject=author1.id)}"}
    author2_headers = {"Authorization": f"Bearer {create_access_token(subject=author2.id)}"}

    # Author 1 creates a configuration
    payload = {"entity_version_id": config_scenario["version_id"], "name": "Author1 Config", "data": []}
    create_resp = client.post("/configurations/", json=payload, headers=author1_headers)
    config_id = create_resp.json()["id"]

    # Author 2 tries to read Author 1's configuration
    response = client.get(f"/configurations/{config_id}", headers=author2_headers)

    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


def test_author_cannot_access_user_configuration(
    client: TestClient, config_scenario, author_headers_rbac, user1_headers
):
    """
    Test that an AUTHOR cannot access a USER's configuration.
    """
    # User creates a configuration
    payload = {"entity_version_id": config_scenario["version_id"], "name": "User Config", "data": []}
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    config_id = create_resp.json()["id"]

    # Author tries to read User's configuration
    response = client.get(f"/configurations/{config_id}", headers=author_headers_rbac)

    assert response.status_code == 403
    assert "permission" in response.json()["detail"].lower()


# ============================================================
# ADMIN ACCESS TESTS
# ============================================================


def test_admin_can_read_any_user_configuration(client: TestClient, config_scenario, admin_headers_rbac, user1_headers):
    """
    Test that an ADMIN can read any user's configuration.
    """
    # User creates a configuration
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "User Config",
        "data": [{"field_id": config_scenario["f_model_id"], "value": "Audi"}],
    }
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    config_id = create_resp.json()["id"]

    # Admin reads User's configuration
    response = client.get(f"/configurations/{config_id}", headers=admin_headers_rbac)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == config_id
    assert data["name"] == "User Config"


def test_admin_can_update_any_user_configuration(
    client: TestClient, config_scenario, admin_headers_rbac, user1_headers
):
    """
    Test that an ADMIN can update any user's configuration.
    """
    # User creates a configuration
    payload = {"entity_version_id": config_scenario["version_id"], "name": "Original Name", "data": []}
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    config_id = create_resp.json()["id"]

    # Admin updates User's configuration
    update_payload = {"name": "Updated by Admin"}
    response = client.patch(f"/configurations/{config_id}", json=update_payload, headers=admin_headers_rbac)

    assert response.status_code == 200
    assert response.json()["name"] == "Updated by Admin"


def test_admin_can_delete_any_user_configuration(
    client: TestClient, config_scenario, admin_headers_rbac, user1_headers
):
    """
    Test that an ADMIN can delete any user's configuration.
    """
    # User creates a configuration
    payload = {"entity_version_id": config_scenario["version_id"], "name": "User Config", "data": []}
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    config_id = create_resp.json()["id"]

    # Admin deletes User's configuration
    response = client.delete(f"/configurations/{config_id}", headers=admin_headers_rbac)

    assert response.status_code == 204

    # Verify deletion
    verify_resp = client.get(f"/configurations/{config_id}", headers=admin_headers_rbac)
    assert verify_resp.status_code == 404


def test_admin_can_calculate_any_user_configuration(
    client: TestClient, config_scenario, admin_headers_rbac, user1_headers
):
    """
    Test that an ADMIN can calculate any user's configuration.
    """
    # User creates a configuration
    payload = {
        "entity_version_id": config_scenario["version_id"],
        "name": "User Config",
        "data": [{"field_id": config_scenario["f_model_id"], "value": "Mercedes"}],
    }
    create_resp = client.post("/configurations/", json=payload, headers=user1_headers)
    config_id = create_resp.json()["id"]

    # Admin calculates User's configuration
    response = client.get(f"/configurations/{config_id}/calculate", headers=admin_headers_rbac)

    assert response.status_code == 200
    engine_response = response.json()
    assert "fields" in engine_response
    assert "is_complete" in engine_response


# ============================================================
# LIST VISIBILITY TESTS
# ============================================================


def test_list_configurations_user_sees_only_own(client: TestClient, config_scenario, user1_headers, user2_headers):
    """
    Test that USER can only see their own configurations in list.
    """
    # User 1 creates a configuration
    payload1 = {"entity_version_id": config_scenario["version_id"], "name": "User1 Config", "data": []}
    client.post("/configurations/", json=payload1, headers=user1_headers)

    # User 2 creates a configuration
    payload2 = {"entity_version_id": config_scenario["version_id"], "name": "User2 Config", "data": []}
    client.post("/configurations/", json=payload2, headers=user2_headers)

    # User 1 lists configurations
    response1 = client.get(f"/configurations/?entity_version_id={config_scenario['version_id']}", headers=user1_headers)
    assert response1.status_code == 200
    configs1 = response1.json()
    # User 1 should only see their own configuration
    assert all(
        config["name"] == "User1 Config" for config in configs1 if config["name"] in ["User1 Config", "User2 Config"]
    )
    assert not any(config["name"] == "User2 Config" for config in configs1)

    # User 2 lists configurations
    response2 = client.get(f"/configurations/?entity_version_id={config_scenario['version_id']}", headers=user2_headers)
    assert response2.status_code == 200
    configs2 = response2.json()
    # User 2 should only see their own configuration
    assert all(
        config["name"] == "User2 Config" for config in configs2 if config["name"] in ["User1 Config", "User2 Config"]
    )
    assert not any(config["name"] == "User1 Config" for config in configs2)


def test_list_configurations_author_sees_only_own(
    client: TestClient, config_scenario, author_headers_rbac, user1_headers
):
    """
    Test that AUTHOR can only see their own configurations in list.
    """
    # Author creates a configuration
    payload_author = {"entity_version_id": config_scenario["version_id"], "name": "Author Config", "data": []}
    client.post("/configurations/", json=payload_author, headers=author_headers_rbac)

    # User creates a configuration
    payload_user = {"entity_version_id": config_scenario["version_id"], "name": "User Config", "data": []}
    client.post("/configurations/", json=payload_user, headers=user1_headers)

    # Author lists configurations
    response = client.get(
        f"/configurations/?entity_version_id={config_scenario['version_id']}", headers=author_headers_rbac
    )
    assert response.status_code == 200
    configs = response.json()

    # Author should only see their own configuration
    author_configs = [c for c in configs if c["name"] in ["Author Config", "User Config"]]
    assert all(config["name"] == "Author Config" for config in author_configs)
    assert not any(config["name"] == "User Config" for config in configs)


def test_list_configurations_admin_sees_all(
    client: TestClient, config_scenario, admin_headers_rbac, user1_headers, author_headers_rbac
):
    """
    Test that ADMIN can see all users' configurations in list.
    """
    # User creates a configuration
    payload_user = {"entity_version_id": config_scenario["version_id"], "name": "User Config", "data": []}
    user_resp = client.post("/configurations/", json=payload_user, headers=user1_headers)
    user_config_id = user_resp.json()["id"]

    # Author creates a configuration
    payload_author = {"entity_version_id": config_scenario["version_id"], "name": "Author Config", "data": []}
    author_resp = client.post("/configurations/", json=payload_author, headers=author_headers_rbac)
    author_config_id = author_resp.json()["id"]

    # Admin creates a configuration
    payload_admin = {"entity_version_id": config_scenario["version_id"], "name": "Admin Config", "data": []}
    admin_resp = client.post("/configurations/", json=payload_admin, headers=admin_headers_rbac)
    admin_config_id = admin_resp.json()["id"]

    # Admin lists all configurations
    response = client.get(
        f"/configurations/?entity_version_id={config_scenario['version_id']}", headers=admin_headers_rbac
    )
    assert response.status_code == 200
    configs = response.json()
    config_ids = [c["id"] for c in configs]

    # Admin should see all three configurations
    assert user_config_id in config_ids
    assert author_config_id in config_ids
    assert admin_config_id in config_ids


def test_list_configurations_admin_can_filter_by_user_id(
    client: TestClient, config_scenario, admin_headers_rbac, user1_headers, regular_user_1
):
    """
    Test that ADMIN can filter configurations by user_id.
    """
    # User 1 creates a configuration
    payload = {"entity_version_id": config_scenario["version_id"], "name": "User1 Config", "data": []}
    client.post("/configurations/", json=payload, headers=user1_headers)

    # Admin creates a configuration
    payload_admin = {"entity_version_id": config_scenario["version_id"], "name": "Admin Config", "data": []}
    client.post("/configurations/", json=payload_admin, headers=admin_headers_rbac)

    # Admin filters by User 1's ID
    response = client.get(
        f"/configurations/?entity_version_id={config_scenario['version_id']}&user_id={regular_user_1.id}",
        headers=admin_headers_rbac,
    )
    assert response.status_code == 200
    configs = response.json()

    # Should only return User 1's configurations
    assert all(
        config["name"] == "User1 Config" for config in configs if config["name"] in ["User1 Config", "Admin Config"]
    )


def test_list_configurations_non_admin_cannot_filter_by_other_user_id(
    client: TestClient, config_scenario, user1_headers, regular_user_2
):
    """
    Test that non-ADMIN users cannot filter by another user's ID.
    """
    # User 1 tries to list User 2's configurations
    response = client.get(f"/configurations/?user_id={regular_user_2.id}", headers=user1_headers)

    assert response.status_code == 403
    assert "other users" in response.json()["detail"].lower()
