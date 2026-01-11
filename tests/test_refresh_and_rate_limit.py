"""
Test suite for Refresh Token and Rate Limiting features.

Tests:
1. Login endpoint returns both access and refresh tokens
2. Refresh endpoint works correctly
3. Invalid credentials handling
4. Rate limiting enforcement (when enabled)
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import User, UserRole
from app.core.security import get_password_hash


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def test_user(db_session):
    """
    Creates a test user with valid hashed password.
    """
    user = User(
        email="testuser@example.com",
        hashed_password=get_password_hash("TestPassword123!"),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def inactive_user(db_session):
    """
    Creates an inactive test user.
    """
    user = User(
        email="inactive@example.com",
        hashed_password=get_password_hash("TestPassword123!"),
        role=UserRole.USER,
        is_active=False
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ============================================================
# LOGIN TESTS
# ============================================================

def test_login_success(client: TestClient, test_user):
    """
    Test successful login returns both access and refresh tokens.
    """
    response = client.post(
        "/auth/token",
        data={
            "username": "testuser@example.com",
            "password": "TestPassword123!"
        }
    )

    assert response.status_code == 200
    data = response.json()

    # Verify both tokens are present
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"

    # Tokens should be non-empty strings
    assert len(data["access_token"]) > 0
    assert len(data["refresh_token"]) > 0


def test_login_wrong_password(client: TestClient, test_user):
    """
    Test login with wrong password returns 401.
    """
    response = client.post(
        "/auth/token",
        data={
            "username": "testuser@example.com",
            "password": "WrongPassword123!"
        }
    )

    assert response.status_code == 401
    assert "Incorrect email" in response.json()["detail"]


def test_login_nonexistent_user(client: TestClient):
    """
    Test login with non-existent email returns 401.
    """
    response = client.post(
        "/auth/token",
        data={
            "username": "nonexistent@example.com",
            "password": "AnyPassword123!"
        }
    )

    assert response.status_code == 401


def test_login_inactive_user(client: TestClient, inactive_user):
    """
    Test login with inactive user returns 401.
    """
    response = client.post(
        "/auth/token",
        data={
            "username": "inactive@example.com",
            "password": "TestPassword123!"
        }
    )

    assert response.status_code == 401


# ============================================================
# REFRESH TOKEN TESTS
# ============================================================

def test_refresh_token_success(client: TestClient, test_user):
    """
    Test refresh endpoint returns new access token.
    """
    # First, login to get tokens
    login_response = client.post(
        "/auth/token",
        data={
            "username": "testuser@example.com",
            "password": "TestPassword123!"
        }
    )
    assert login_response.status_code == 200
    refresh_token = login_response.json()["refresh_token"]

    # Use refresh token to get new access token
    refresh_response = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {refresh_token}"}
    )

    assert refresh_response.status_code == 200
    data = refresh_response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_refresh_token_invalid(client: TestClient, test_user):
    """
    Test refresh with invalid token returns 401.
    """
    response = client.post(
        "/auth/refresh",
        headers={"Authorization": "Bearer invalid_token_here"}
    )

    assert response.status_code == 401
    assert "Invalid or expired" in response.json()["detail"]


def test_refresh_token_missing_header(client: TestClient):
    """
    Test refresh without Authorization header returns 403.
    """
    response = client.post("/auth/refresh")

    # HTTPBearer returns 403 when header is missing
    assert response.status_code == 403


def test_access_token_works(client: TestClient, db_session, test_user):
    """
    Test that the access token can be used to access protected endpoints.
    """
    # Login to get access token
    login_response = client.post(
        "/auth/token",
        data={
            "username": "testuser@example.com",
            "password": "TestPassword123!"
        }
    )
    access_token = login_response.json()["access_token"]

    # Create test data for a protected endpoint
    from app.models.domain import Entity, EntityVersion, VersionStatus

    entity = Entity(name="Test Entity", description="Test")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # Try to access configurations endpoint (protected)
    response = client.get(
        f"/configurations/?entity_version_id={version.id}",
        headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200


def test_multiple_refresh_tokens(client: TestClient, test_user):
    """
    Test that user can have multiple valid refresh tokens (multiple devices).
    """
    # Login twice (simulating two devices)
    tokens = []
    for _ in range(2):
        response = client.post(
            "/auth/token",
            data={
                "username": "testuser@example.com",
                "password": "TestPassword123!"
            }
        )
        assert response.status_code == 200
        tokens.append(response.json()["refresh_token"])

    # Both refresh tokens should work
    for refresh_token in tokens:
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"}
        )
        assert response.status_code == 200


# ============================================================
# RATE LIMITING TESTS
# ============================================================
# Note: These tests only work when RATE_LIMIT_ENABLED=true in settings.
# In test environment, rate limiting is typically disabled.
# These tests verify the behavior IF rate limiting is enabled.

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Reset rate limiter state before and after EVERY test.
    This ensures rate limit tests are isolated.
    autouse=True means it runs for every test in this module.
    """
    from app.core.rate_limit import limiter

    # Reset before test
    try:
        if hasattr(limiter, '_storage') and limiter._storage:
            limiter._storage.reset()
        # Also clear the limiter's internal state
        if hasattr(limiter, 'reset'):
            limiter.reset()
    except Exception:
        pass

    yield

    # Reset after test
    try:
        if hasattr(limiter, '_storage') and limiter._storage:
            limiter._storage.reset()
        if hasattr(limiter, 'reset'):
            limiter.reset()
    except Exception:
        pass


def test_rate_limit_login_endpoint(client: TestClient, test_user):
    """
    Test that login endpoint enforces rate limiting when enabled.

    Note: This test may pass even if rate limiting triggers,
    as we're testing the mechanism exists, not that it's enabled.
    """
    from app.core.config import settings

    if not settings.RATE_LIMIT_ENABLED:
        pytest.skip("Rate limiting is disabled in test environment")

    # Make multiple requests to trigger rate limit
    rate_limited = False
    for i in range(settings.RATE_LIMIT_LOGIN_ATTEMPTS + 2):
        response = client.post(
            "/auth/token",
            data={
                "username": "testuser@example.com",
                "password": "WrongPassword!"  # Wrong password to not lock account
            }
        )

        if response.status_code == 429:
            rate_limited = True
            data = response.json()
            assert data["error"] == "rate_limit_exceeded"
            break

    assert rate_limited, "Rate limiting should have been triggered"


def test_rate_limit_refresh_endpoint(client: TestClient, test_user):
    """
    Test that refresh endpoint enforces rate limiting when enabled.
    """
    from app.core.config import settings

    if not settings.RATE_LIMIT_ENABLED:
        pytest.skip("Rate limiting is disabled in test environment")

    # First get a valid refresh token
    login_response = client.post(
        "/auth/token",
        data={
            "username": "testuser@example.com",
            "password": "TestPassword123!"
        }
    )
    refresh_token = login_response.json()["refresh_token"]

    # Make multiple requests to trigger rate limit
    rate_limited = False
    for i in range(settings.RATE_LIMIT_REFRESH_ATTEMPTS + 2):
        response = client.post(
            "/auth/refresh",
            headers={"Authorization": f"Bearer {refresh_token}"}
        )

        if response.status_code == 429:
            rate_limited = True
            data = response.json()
            assert data["error"] == "rate_limit_exceeded"
            break

    assert rate_limited, "Rate limiting should have been triggered"
