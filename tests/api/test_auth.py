"""
Test suite for Authentication API endpoints.

Tests the /auth/token and /auth/refresh endpoints.
Each test is atomic and independent.
"""

import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.models.domain import User, UserRole, RefreshToken
from app.core.security import get_password_hash, create_access_token, hash_refresh_token


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def active_user(db_session):
    """Creates an active test user for authentication tests."""
    user = User(
        email="active@example.com",
        hashed_password=get_password_hash("ValidPassword123!"),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def inactive_user(db_session):
    """Creates an inactive (banned) test user."""
    user = User(
        email="inactive@example.com",
        hashed_password=get_password_hash("ValidPassword123!"),
        role=UserRole.USER,
        is_active=False
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def admin_user(db_session):
    """Creates an admin user for privileged operations."""
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
def valid_refresh_token(db_session, active_user):
    """Creates a valid refresh token for the active user."""
    import secrets
    plaintext = secrets.token_urlsafe(32)
    token_hash = hash_refresh_token(plaintext)

    db_token = RefreshToken(
        user_id=active_user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        is_revoked=False
    )
    db_session.add(db_token)
    db_session.commit()
    db_session.refresh(db_token)

    return {"plaintext": plaintext, "db_token": db_token}


@pytest.fixture(scope="function")
def expired_refresh_token(db_session, active_user):
    """Creates an expired refresh token."""
    import secrets
    plaintext = secrets.token_urlsafe(32)
    token_hash = hash_refresh_token(plaintext)

    db_token = RefreshToken(
        user_id=active_user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
        is_revoked=False
    )
    db_session.add(db_token)
    db_session.commit()

    return {"plaintext": plaintext, "db_token": db_token}


@pytest.fixture(scope="function")
def revoked_refresh_token(db_session, active_user):
    """Creates a revoked refresh token."""
    import secrets
    plaintext = secrets.token_urlsafe(32)
    token_hash = hash_refresh_token(plaintext)

    db_token = RefreshToken(
        user_id=active_user.id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        is_revoked=True,
        revoked_at=datetime.now(timezone.utc)
    )
    db_session.add(db_token)
    db_session.commit()

    return {"plaintext": plaintext, "db_token": db_token}


# ============================================================
# LOGIN ENDPOINT TESTS (/auth/token)
# ============================================================

class TestLoginEndpoint:
    """Tests for POST /auth/token endpoint."""

    def test_login_success(self, client: TestClient, active_user):
        """Test successful login with valid credentials."""
        response = client.post(
            "/auth/token",
            data={"username": "active@example.com", "password": "ValidPassword123!"}
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

        # Verify tokens are non-empty strings
        assert isinstance(data["access_token"], str)
        assert len(data["access_token"]) > 0
        assert isinstance(data["refresh_token"], str)
        assert len(data["refresh_token"]) > 0

    def test_login_wrong_password(self, client: TestClient, active_user):
        """Test login with incorrect password returns 401."""
        response = client.post(
            "/auth/token",
            data={"username": "active@example.com", "password": "WrongPassword123!"}
        )

        assert response.status_code == 401
        assert "Incorrect email and/or password" in response.json()["detail"]

    def test_login_nonexistent_user(self, client: TestClient):
        """Test login with non-existent email returns 401."""
        response = client.post(
            "/auth/token",
            data={"username": "nonexistent@example.com", "password": "SomePassword123!"}
        )

        assert response.status_code == 401
        assert "Incorrect email and/or password" in response.json()["detail"]

    def test_login_inactive_user(self, client: TestClient, inactive_user):
        """Test that inactive (banned) users cannot login."""
        response = client.post(
            "/auth/token",
            data={"username": "inactive@example.com", "password": "ValidPassword123!"}
        )

        assert response.status_code == 401
        # Should return generic error (security best practice)
        assert "Incorrect email and/or password" in response.json()["detail"]

    def test_login_empty_credentials(self, client: TestClient):
        """Test login with empty credentials returns 401 (security best practice)."""
        response = client.post(
            "/auth/token",
            data={"username": "", "password": ""}
        )

        # Returns 401 with generic error message (security: don't reveal if user exists)
        assert response.status_code == 401

    def test_login_missing_password(self, client: TestClient):
        """Test login without password returns 422."""
        response = client.post(
            "/auth/token",
            data={"username": "active@example.com"}
        )

        assert response.status_code == 422

    def test_login_missing_username(self, client: TestClient):
        """Test login without username returns 422."""
        response = client.post(
            "/auth/token",
            data={"password": "SomePassword123!"}
        )

        assert response.status_code == 422

    def test_login_case_sensitive_email(self, client: TestClient, active_user):
        """Test that email matching is case-sensitive (or not, depending on implementation)."""
        response = client.post(
            "/auth/token",
            data={"username": "ACTIVE@EXAMPLE.COM", "password": "ValidPassword123!"}
        )

        # Email lookup is typically case-sensitive in this implementation
        # The test documents current behavior
        assert response.status_code == 401

    def test_login_returns_different_tokens_per_request(self, client: TestClient, active_user):
        """Test that each login generates unique tokens."""
        response1 = client.post(
            "/auth/token",
            data={"username": "active@example.com", "password": "ValidPassword123!"}
        )
        response2 = client.post(
            "/auth/token",
            data={"username": "active@example.com", "password": "ValidPassword123!"}
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Refresh tokens should be different
        assert response1.json()["refresh_token"] != response2.json()["refresh_token"]

    def test_login_admin_success(self, client: TestClient, admin_user):
        """Test that admin users can login successfully."""
        response = client.post(
            "/auth/token",
            data={"username": "admin@example.com", "password": "AdminPassword123!"}
        )

        assert response.status_code == 200
        assert "access_token" in response.json()


# ============================================================
# REFRESH ENDPOINT TESTS (/auth/refresh)
# ============================================================

class TestRefreshEndpoint:
    """Tests for POST /auth/refresh endpoint."""

    def test_refresh_success(self, client: TestClient, valid_refresh_token):
        """Test successful token refresh with valid refresh token."""
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {valid_refresh_token['plaintext']}"}
        )

        assert response.status_code == 200
        data = response.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_refresh_invalid_token(self, client: TestClient):
        """Test refresh with invalid token returns 401."""
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": "Bearer invalid_token_string"}
        )

        assert response.status_code == 401
        assert "Invalid or expired refresh token" in response.json()["detail"]

    def test_refresh_expired_token(self, client: TestClient, expired_refresh_token):
        """Test refresh with expired token returns 401."""
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {expired_refresh_token['plaintext']}"}
        )

        assert response.status_code == 401
        assert "Invalid or expired refresh token" in response.json()["detail"]

    def test_refresh_revoked_token(self, client: TestClient, revoked_refresh_token):
        """Test refresh with revoked token returns 401."""
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {revoked_refresh_token['plaintext']}"}
        )

        assert response.status_code == 401
        assert "Invalid or expired refresh token" in response.json()["detail"]

    def test_refresh_missing_authorization_header(self, client: TestClient):
        """Test refresh without Authorization header returns 403."""
        response = client.post("/auth/refresh")

        # HTTPBearer returns 403 when no credentials provided
        assert response.status_code == 403

    def test_refresh_malformed_authorization_header(self, client: TestClient):
        """Test refresh with malformed Authorization header."""
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": "NotBearer token"}
        )

        assert response.status_code == 403

    def test_refresh_inactive_user(self, client: TestClient, db_session, inactive_user):
        """Test refresh fails when user has been deactivated after token creation."""
        import secrets
        plaintext = secrets.token_urlsafe(32)
        token_hash = hash_refresh_token(plaintext)

        db_token = RefreshToken(
            user_id=inactive_user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            is_revoked=False
        )
        db_session.add(db_token)
        db_session.commit()

        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {plaintext}"}
        )

        assert response.status_code == 401
        assert "User not found or inactive" in response.json()["detail"]


# ============================================================
# ACCESS TOKEN USAGE TESTS
# ============================================================

class TestAccessTokenUsage:
    """Tests for using access tokens with protected endpoints."""

    def test_access_protected_endpoint_with_valid_token(self, client: TestClient, active_user):
        """Test that valid access token allows access to protected endpoints."""
        access_token = create_access_token(subject=active_user.id)

        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 200
        assert response.json()["email"] == "active@example.com"

    def test_access_protected_endpoint_without_token(self, client: TestClient, active_user):
        """Test that missing token returns 401."""
        response = client.get("/users/me")

        assert response.status_code == 401

    def test_access_protected_endpoint_with_invalid_token(self, client: TestClient):
        """Test that invalid token returns 401."""
        response = client.get(
            "/users/me",
            headers={"Authorization": "Bearer invalid_access_token"}
        )

        assert response.status_code == 401

    def test_access_protected_endpoint_with_expired_token(self, client: TestClient, active_user):
        """Test that expired access token returns 401."""
        # Create an already-expired token
        expired_token = create_access_token(
            subject=active_user.id,
            expires_delta=timedelta(seconds=-1)  # Already expired
        )

        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert response.status_code == 401

    def test_access_protected_endpoint_inactive_user(self, client: TestClient, inactive_user):
        """Test that token for inactive user returns 400."""
        access_token = create_access_token(subject=inactive_user.id)

        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 400
        assert "Inactive user" in response.json()["detail"]


# ============================================================
# TOKEN FLOW INTEGRATION TESTS
# ============================================================

class TestTokenFlowIntegration:
    """Integration tests for the complete authentication flow."""

    def test_full_auth_flow(self, client: TestClient, active_user):
        """Test complete flow: login -> use token -> refresh -> use new token."""
        # Step 1: Login
        login_response = client.post(
            "/auth/token",
            data={"username": "active@example.com", "password": "ValidPassword123!"}
        )
        assert login_response.status_code == 200

        tokens = login_response.json()
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]

        # Step 2: Use access token
        me_response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "active@example.com"

        # Step 3: Refresh token
        refresh_response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"}
        )
        assert refresh_response.status_code == 200

        new_access_token = refresh_response.json()["access_token"]

        # Step 4: Use new access token
        me_response2 = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {new_access_token}"}
        )
        assert me_response2.status_code == 200

    def test_multiple_logins_create_multiple_refresh_tokens(self, client: TestClient, db_session, active_user):
        """Test that multiple logins create multiple refresh tokens in DB."""
        # Login 3 times
        for _ in range(3):
            response = client.post(
                "/auth/token",
                data={"username": "active@example.com", "password": "ValidPassword123!"}
            )
            assert response.status_code == 200

        # Check DB has 3 refresh tokens for this user
        token_count = db_session.query(RefreshToken).filter(
            RefreshToken.user_id == active_user.id,
            RefreshToken.is_revoked == False
        ).count()

        assert token_count == 3
