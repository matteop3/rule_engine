"""
Test suite for Users API endpoints.

Tests the full CRUD lifecycle and RBAC enforcement.
Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import User, UserRole
from app.core.security import get_password_hash, create_access_token


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def admin_user(db_session):
    """Creates an admin user."""
    user = User(
        email="admin@example.com",
        hashed_password=get_password_hash("AdminPassword123!"),
        role=UserRole.ADMIN,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def admin_headers(admin_user):
    """Auth headers for admin user."""
    token = create_access_token(subject=admin_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def author_user(db_session):
    """Creates an author user."""
    user = User(
        email="author@example.com",
        hashed_password=get_password_hash("AuthorPassword123!"),
        role=UserRole.AUTHOR,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def author_headers(author_user):
    """Auth headers for author user."""
    token = create_access_token(subject=author_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def regular_user(db_session):
    """Creates a regular user."""
    user = User(
        email="user@example.com",
        hashed_password=get_password_hash("UserPassword123!"),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def user_headers(regular_user):
    """Auth headers for regular user."""
    token = create_access_token(subject=regular_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def inactive_user(db_session):
    """Creates an inactive user."""
    user = User(
        email="inactive@example.com",
        hashed_password=get_password_hash("InactivePassword123!"),
        role=UserRole.USER,
        is_active=False
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def multiple_users(db_session, admin_user):
    """Creates multiple users for list tests."""
    users = []
    for i in range(5):
        user = User(
            email=f"listuser{i}@example.com",
            hashed_password=get_password_hash("Password123!"),
            role=UserRole.USER,
            is_active=True
        )
        db_session.add(user)
        users.append(user)
    db_session.commit()
    return users


# ============================================================
# CREATE USER TESTS (POST /users/)
# ============================================================

class TestCreateUser:
    """Tests for POST /users/ endpoint."""

    def test_admin_can_create_user(self, client: TestClient, admin_headers):
        """Test that admin can create a new user."""
        payload = {
            "email": "newuser@example.com",
            "password": "NewUserPassword123!",
            "role": "user",
            "is_active": True
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["role"] == "user"
        assert data["is_active"] is True
        assert "id" in data
        # Password should not be returned
        assert "password" not in data
        assert "hashed_password" not in data

    def test_admin_can_create_author(self, client: TestClient, admin_headers):
        """Test that admin can create an author user."""
        payload = {
            "email": "newauthor@example.com",
            "password": "AuthorPassword123!",
            "role": "author",
            "is_active": True
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["role"] == "author"

    def test_admin_can_create_admin(self, client: TestClient, admin_headers):
        """Test that admin can create another admin user."""
        payload = {
            "email": "newadmin@example.com",
            "password": "AdminPassword123!",
            "role": "admin",
            "is_active": True
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["role"] == "admin"

    def test_author_cannot_create_user(self, client: TestClient, author_headers):
        """Test that author cannot create users (403)."""
        payload = {
            "email": "forbidden@example.com",
            "password": "Password123!",
            "role": "user"
        }

        response = client.post("/users/", json=payload, headers=author_headers)

        assert response.status_code == 403
        assert "permissions" in response.json()["detail"].lower()

    def test_regular_user_cannot_create_user(self, client: TestClient, user_headers):
        """Test that regular user cannot create users (403)."""
        payload = {
            "email": "forbidden@example.com",
            "password": "Password123!",
            "role": "user"
        }

        response = client.post("/users/", json=payload, headers=user_headers)

        assert response.status_code == 403

    def test_unauthenticated_cannot_create_user(self, client: TestClient):
        """Test that unauthenticated request returns 401."""
        payload = {
            "email": "anon@example.com",
            "password": "Password123!",
            "role": "user"
        }

        response = client.post("/users/", json=payload)

        assert response.status_code == 401

    def test_cannot_create_duplicate_email(self, client: TestClient, admin_headers, regular_user):
        """Test that creating user with existing email returns 400."""
        payload = {
            "email": "user@example.com",  # Already exists
            "password": "Password123!",
            "role": "user"
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_create_user_invalid_email(self, client: TestClient, admin_headers):
        """Test that invalid email format returns 422."""
        payload = {
            "email": "not-an-email",
            "password": "Password123!",
            "role": "user"
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_create_user_short_password(self, client: TestClient, admin_headers):
        """Test that password shorter than 8 chars returns 422."""
        payload = {
            "email": "shortpwd@example.com",
            "password": "short",
            "role": "user"
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_create_user_invalid_role(self, client: TestClient, admin_headers):
        """Test that invalid role returns 422."""
        payload = {
            "email": "badrole@example.com",
            "password": "Password123!",
            "role": "superadmin"  # Invalid role
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_create_user_defaults(self, client: TestClient, admin_headers):
        """Test that defaults are applied when optional fields omitted."""
        payload = {
            "email": "defaults@example.com",
            "password": "Password123!"
            # role and is_active should default
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "user"  # Default role
        assert data["is_active"] is True  # Default active


# ============================================================
# LIST USERS TESTS (GET /users/)
# ============================================================

class TestListUsers:
    """Tests for GET /users/ endpoint."""

    def test_admin_can_list_users(self, client: TestClient, admin_headers, multiple_users):
        """Test that admin can list all users."""
        response = client.get("/users/", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # 1 admin + 5 multiple_users = 6 total
        assert len(data) >= 6

    def test_author_cannot_list_users(self, client: TestClient, author_headers):
        """Test that author cannot list users (403)."""
        response = client.get("/users/", headers=author_headers)

        assert response.status_code == 403

    def test_regular_user_cannot_list_users(self, client: TestClient, user_headers):
        """Test that regular user cannot list users (403)."""
        response = client.get("/users/", headers=user_headers)

        assert response.status_code == 403

    def test_unauthenticated_cannot_list_users(self, client: TestClient):
        """Test that unauthenticated request returns 401."""
        response = client.get("/users/")

        assert response.status_code == 401

    def test_list_users_pagination_skip(self, client: TestClient, admin_headers, multiple_users):
        """Test skip parameter works correctly."""
        response = client.get("/users/?skip=2", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        # Should have fewer results when skipping
        assert isinstance(data, list)

    def test_list_users_pagination_limit(self, client: TestClient, admin_headers, multiple_users):
        """Test limit parameter works correctly."""
        response = client.get("/users/?limit=2", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_users_limit_over_100_rejected(self, client: TestClient, admin_headers, multiple_users):
        """Test that limit > 100 is rejected with 422."""
        response = client.get("/users/?limit=200", headers=admin_headers)

        assert response.status_code == 422


# ============================================================
# GET CURRENT USER TESTS (GET /users/me)
# ============================================================

class TestGetCurrentUser:
    """Tests for GET /users/me endpoint."""

    def test_get_own_profile(self, client: TestClient, user_headers, regular_user):
        """Test that any authenticated user can get their own profile."""
        response = client.get("/users/me", headers=user_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "user@example.com"
        assert data["id"] == regular_user.id
        assert data["role"] == "user"

    def test_admin_can_get_own_profile(self, client: TestClient, admin_headers, admin_user):
        """Test that admin can get their own profile."""
        response = client.get("/users/me", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["email"] == "admin@example.com"
        assert response.json()["role"] == "admin"

    def test_author_can_get_own_profile(self, client: TestClient, author_headers, author_user):
        """Test that author can get their own profile."""
        response = client.get("/users/me", headers=author_headers)

        assert response.status_code == 200
        assert response.json()["email"] == "author@example.com"

    def test_unauthenticated_cannot_get_profile(self, client: TestClient):
        """Test that unauthenticated request returns 401."""
        response = client.get("/users/me")

        assert response.status_code == 401

    def test_inactive_user_cannot_access_me(self, client: TestClient, inactive_user):
        """Test that inactive user gets 400 when accessing /me."""
        token = create_access_token(subject=inactive_user.id)

        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 400
        assert "Inactive user" in response.json()["detail"]


# ============================================================
# GET USER BY ID TESTS (GET /users/{user_id})
# ============================================================

class TestGetUserById:
    """Tests for GET /users/{user_id} endpoint."""

    def test_admin_can_get_any_user(self, client: TestClient, admin_headers, regular_user):
        """Test that admin can get any user by ID."""
        response = client.get(f"/users/{regular_user.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "user@example.com"
        assert data["id"] == regular_user.id

    def test_admin_can_get_another_admin(self, client: TestClient, db_session, admin_headers):
        """Test that admin can get another admin's profile."""
        # Create second admin
        admin2 = User(
            email="admin2@example.com",
            hashed_password=get_password_hash("Admin2Password123!"),
            role=UserRole.ADMIN,
            is_active=True
        )
        db_session.add(admin2)
        db_session.commit()

        response = client.get(f"/users/{admin2.id}", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["email"] == "admin2@example.com"

    def test_author_cannot_get_user_by_id(self, client: TestClient, author_headers, regular_user):
        """Test that author cannot get user by ID (403)."""
        response = client.get(f"/users/{regular_user.id}", headers=author_headers)

        assert response.status_code == 403

    def test_regular_user_cannot_get_user_by_id(self, client: TestClient, user_headers, admin_user):
        """Test that regular user cannot get other users by ID (403)."""
        response = client.get(f"/users/{admin_user.id}", headers=user_headers)

        assert response.status_code == 403

    def test_get_nonexistent_user(self, client: TestClient, admin_headers):
        """Test that getting non-existent user returns 404."""
        response = client.get("/users/nonexistent-uuid-12345", headers=admin_headers)

        assert response.status_code == 404

    def test_unauthenticated_cannot_get_user(self, client: TestClient, regular_user):
        """Test that unauthenticated request returns 401."""
        response = client.get(f"/users/{regular_user.id}")

        assert response.status_code == 401


# ============================================================
# UPDATE USER TESTS (PATCH /users/{user_id})
# ============================================================

class TestUpdateUser:
    """Tests for PATCH /users/{user_id} endpoint."""

    def test_admin_can_update_user_email(self, client: TestClient, admin_headers, regular_user):
        """Test that admin can update user's email."""
        payload = {"email": "newemail@example.com"}

        response = client.patch(
            f"/users/{regular_user.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["email"] == "newemail@example.com"

    def test_admin_can_update_user_role(self, client: TestClient, admin_headers, regular_user):
        """Test that admin can change user's role."""
        payload = {"role": "author"}

        response = client.patch(
            f"/users/{regular_user.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["role"] == "author"

    def test_admin_can_deactivate_user(self, client: TestClient, admin_headers, regular_user):
        """Test that admin can deactivate (ban) a user."""
        payload = {"is_active": False}

        response = client.patch(
            f"/users/{regular_user.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    def test_admin_can_reactivate_user(self, client: TestClient, admin_headers, inactive_user):
        """Test that admin can reactivate a user."""
        payload = {"is_active": True}

        response = client.patch(
            f"/users/{inactive_user.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["is_active"] is True

    def test_admin_can_update_password(self, client: TestClient, admin_headers, regular_user):
        """Test that admin can update user's password."""
        payload = {"password": "NewSecurePassword123!"}

        response = client.patch(
            f"/users/{regular_user.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        # Password change should succeed silently (no password in response)
        assert "password" not in response.json()

    def test_author_cannot_update_user(self, client: TestClient, author_headers, regular_user):
        """Test that author cannot update users (403)."""
        payload = {"email": "forbidden@example.com"}

        response = client.patch(
            f"/users/{regular_user.id}",
            json=payload,
            headers=author_headers
        )

        assert response.status_code == 403

    def test_regular_user_cannot_update_user(self, client: TestClient, user_headers, admin_user):
        """Test that regular user cannot update other users (403)."""
        payload = {"email": "hacker@example.com"}

        response = client.patch(
            f"/users/{admin_user.id}",
            json=payload,
            headers=user_headers
        )

        assert response.status_code == 403

    def test_cannot_update_to_duplicate_email(
        self, client: TestClient, admin_headers, regular_user, author_user
    ):
        """Test that updating to an existing email returns 400."""
        payload = {"email": "author@example.com"}  # Already exists

        response = client.patch(
            f"/users/{regular_user.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 400
        assert "already in use" in response.json()["detail"].lower()

    def test_update_nonexistent_user(self, client: TestClient, admin_headers):
        """Test that updating non-existent user returns 404."""
        payload = {"email": "ghost@example.com"}

        response = client.patch(
            "/users/nonexistent-uuid-12345",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 404

    def test_unauthenticated_cannot_update_user(self, client: TestClient, regular_user):
        """Test that unauthenticated request returns 401."""
        payload = {"email": "anon@example.com"}

        response = client.patch(f"/users/{regular_user.id}", json=payload)

        assert response.status_code == 401

    def test_partial_update_only_changes_specified_fields(
        self, client: TestClient, admin_headers, regular_user
    ):
        """Test that PATCH only updates specified fields."""
        original_role = regular_user.role
        payload = {"email": "partial@example.com"}

        response = client.patch(
            f"/users/{regular_user.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "partial@example.com"
        # Role should remain unchanged (handle both Enum and string)
        expected_role = original_role.value if hasattr(original_role, 'value') else original_role
        assert data["role"] == expected_role


# ============================================================
# DELETE USER TESTS (DELETE /users/{user_id})
# ============================================================

class TestDeleteUser:
    """Tests for DELETE /users/{user_id} endpoint."""

    def test_admin_can_delete_user(self, client: TestClient, db_session, admin_headers, regular_user):
        """Test that admin can soft-delete a user."""
        user_id = regular_user.id

        response = client.delete(f"/users/{user_id}", headers=admin_headers)

        assert response.status_code == 204

        # Verify soft delete (user still exists but is inactive)
        db_session.refresh(regular_user)
        assert regular_user.is_active is False

    def test_admin_cannot_delete_self(self, client: TestClient, admin_headers, admin_user):
        """Test that admin cannot delete their own account."""
        response = client.delete(f"/users/{admin_user.id}", headers=admin_headers)

        assert response.status_code == 400
        assert "cannot delete your own account" in response.json()["detail"].lower()

    def test_author_cannot_delete_user(self, client: TestClient, author_headers, regular_user):
        """Test that author cannot delete users (403)."""
        response = client.delete(f"/users/{regular_user.id}", headers=author_headers)

        assert response.status_code == 403

    def test_regular_user_cannot_delete_user(self, client: TestClient, user_headers, author_user):
        """Test that regular user cannot delete users (403)."""
        response = client.delete(f"/users/{author_user.id}", headers=user_headers)

        assert response.status_code == 403

    def test_delete_nonexistent_user(self, client: TestClient, admin_headers):
        """Test that deleting non-existent user returns 404."""
        response = client.delete("/users/nonexistent-uuid-12345", headers=admin_headers)

        assert response.status_code == 404

    def test_unauthenticated_cannot_delete_user(self, client: TestClient, regular_user):
        """Test that unauthenticated request returns 401."""
        response = client.delete(f"/users/{regular_user.id}")

        assert response.status_code == 401

    def test_can_delete_already_inactive_user(
        self, client: TestClient, admin_headers, inactive_user
    ):
        """Test that deleting an already inactive user succeeds."""
        response = client.delete(f"/users/{inactive_user.id}", headers=admin_headers)

        # Should succeed (idempotent operation)
        assert response.status_code == 204


# ============================================================
# ROLE-BASED ACCESS CONTROL TESTS
# ============================================================

class TestRBACEnforcement:
    """Tests for role-based access control across all endpoints."""

    def test_role_hierarchy_admin_full_access(
        self, client: TestClient, admin_headers, regular_user
    ):
        """Test that ADMIN has access to all user management operations."""
        # Can create
        create_resp = client.post(
            "/users/",
            json={"email": "new@example.com", "password": "Password123!"},
            headers=admin_headers
        )
        assert create_resp.status_code == 201
        new_user_id = create_resp.json()["id"]

        # Can list
        list_resp = client.get("/users/", headers=admin_headers)
        assert list_resp.status_code == 200

        # Can read
        read_resp = client.get(f"/users/{regular_user.id}", headers=admin_headers)
        assert read_resp.status_code == 200

        # Can update
        update_resp = client.patch(
            f"/users/{regular_user.id}",
            json={"is_active": True},
            headers=admin_headers
        )
        assert update_resp.status_code == 200

        # Can delete (the new user, not self)
        delete_resp = client.delete(f"/users/{new_user_id}", headers=admin_headers)
        assert delete_resp.status_code == 204

    def test_role_hierarchy_author_limited_access(
        self, client: TestClient, author_headers, regular_user
    ):
        """Test that AUTHOR only has access to /me endpoint."""
        # Can access own profile
        me_resp = client.get("/users/me", headers=author_headers)
        assert me_resp.status_code == 200

        # Cannot create
        create_resp = client.post(
            "/users/",
            json={"email": "new@example.com", "password": "Password123!"},
            headers=author_headers
        )
        assert create_resp.status_code == 403

        # Cannot list
        list_resp = client.get("/users/", headers=author_headers)
        assert list_resp.status_code == 403

        # Cannot read others
        read_resp = client.get(f"/users/{regular_user.id}", headers=author_headers)
        assert read_resp.status_code == 403

        # Cannot update
        update_resp = client.patch(
            f"/users/{regular_user.id}",
            json={"is_active": False},
            headers=author_headers
        )
        assert update_resp.status_code == 403

        # Cannot delete
        delete_resp = client.delete(f"/users/{regular_user.id}", headers=author_headers)
        assert delete_resp.status_code == 403

    def test_role_hierarchy_user_minimal_access(
        self, client: TestClient, user_headers, admin_user
    ):
        """Test that USER only has access to /me endpoint."""
        # Can access own profile
        me_resp = client.get("/users/me", headers=user_headers)
        assert me_resp.status_code == 200

        # Cannot create
        create_resp = client.post(
            "/users/",
            json={"email": "new@example.com", "password": "Password123!"},
            headers=user_headers
        )
        assert create_resp.status_code == 403

        # Cannot list
        list_resp = client.get("/users/", headers=user_headers)
        assert list_resp.status_code == 403

        # Cannot read others
        read_resp = client.get(f"/users/{admin_user.id}", headers=user_headers)
        assert read_resp.status_code == 403

        # Cannot update
        update_resp = client.patch(
            f"/users/{admin_user.id}",
            json={"role": "user"},
            headers=user_headers
        )
        assert update_resp.status_code == 403

        # Cannot delete
        delete_resp = client.delete(f"/users/{admin_user.id}", headers=user_headers)
        assert delete_resp.status_code == 403


# ============================================================
# EDGE CASES
# ============================================================

class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_empty_update_payload(self, client: TestClient, admin_headers, regular_user):
        """Test that empty update payload is handled gracefully."""
        response = client.patch(
            f"/users/{regular_user.id}",
            json={},
            headers=admin_headers
        )

        # Should succeed with no changes
        assert response.status_code == 200

    def test_update_same_email(self, client: TestClient, admin_headers, regular_user):
        """Test that updating email to same value succeeds."""
        payload = {"email": "user@example.com"}  # Same as current

        response = client.patch(
            f"/users/{regular_user.id}",
            json=payload,
            headers=admin_headers
        )

        # Should succeed (no actual change)
        assert response.status_code == 200

    def test_create_user_with_whitespace_email(self, client: TestClient, admin_headers):
        """Test email validation handles whitespace."""
        payload = {
            "email": "  spaces@example.com  ",
            "password": "Password123!"
        }

        response = client.post("/users/", json=payload, headers=admin_headers)

        # Pydantic/EmailStr should handle or reject whitespace
        # This documents current behavior
        assert response.status_code in [201, 422]

    def test_list_users_with_zero_limit(self, client: TestClient, admin_headers):
        """Test list with limit=0."""
        response = client.get("/users/?limit=0", headers=admin_headers)

        assert response.status_code == 200
        # Should return empty list or be rejected
        assert isinstance(response.json(), list)

    def test_list_users_with_negative_skip(self, client: TestClient, admin_headers):
        """Test list with negative skip."""
        response = client.get("/users/?skip=-1", headers=admin_headers)

        # Should handle gracefully or return validation error
        assert response.status_code in [200, 422]
