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

from app.core.security import get_password_hash
from app.models.domain import User, UserRole

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
        is_active=True,
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
        is_active=False,
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
    response = client.post("/auth/token", data={"username": "testuser@example.com", "password": "TestPassword123!"})

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
    response = client.post("/auth/token", data={"username": "testuser@example.com", "password": "WrongPassword123!"})

    assert response.status_code == 401
    assert "Incorrect email" in response.json()["detail"]


def test_login_nonexistent_user(client: TestClient):
    """
    Test login with non-existent email returns 401.
    """
    response = client.post("/auth/token", data={"username": "nonexistent@example.com", "password": "AnyPassword123!"})

    assert response.status_code == 401


def test_login_inactive_user(client: TestClient, inactive_user):
    """
    Test login with inactive user returns 401.
    """
    response = client.post("/auth/token", data={"username": "inactive@example.com", "password": "TestPassword123!"})

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
        "/auth/token", data={"username": "testuser@example.com", "password": "TestPassword123!"}
    )
    assert login_response.status_code == 200
    refresh_token = login_response.json()["refresh_token"]

    # Use refresh token to get new access token
    refresh_response = client.post("/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})

    assert refresh_response.status_code == 200
    data = refresh_response.json()

    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_refresh_token_invalid(client: TestClient, test_user):
    """
    Test refresh with invalid token returns 401.
    """
    response = client.post("/auth/refresh", headers={"Authorization": "Bearer invalid_token_here"})

    assert response.status_code == 401
    assert "Invalid or expired" in response.json()["detail"]


def test_refresh_token_missing_header(client: TestClient):
    """
    Test refresh without Authorization header returns 401/403.
    """
    response = client.post("/auth/refresh")

    # HTTPBearer returns 403 (older FastAPI) or 401 (newer, per HTTP spec)
    assert response.status_code in (401, 403)


def test_access_token_works(client: TestClient, db_session, test_user):
    """
    Test that the access token can be used to access protected endpoints.
    """
    # Login to get access token
    login_response = client.post(
        "/auth/token", data={"username": "testuser@example.com", "password": "TestPassword123!"}
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
        f"/configurations/?entity_version_id={version.id}", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200


def test_multiple_refresh_tokens(client: TestClient, test_user):
    """
    Test that user can have multiple valid refresh tokens (multiple devices).
    """
    # Login twice (simulating two devices)
    tokens = []
    for _ in range(2):
        response = client.post("/auth/token", data={"username": "testuser@example.com", "password": "TestPassword123!"})
        assert response.status_code == 200
        tokens.append(response.json()["refresh_token"])

    # Both refresh tokens should work
    for refresh_token in tokens:
        response = client.post("/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})
        assert response.status_code == 200


# ============================================================
# RATE LIMITING TESTS
# ============================================================
# These tests temporarily enable rate limiting regardless of settings
# to ensure the rate limiting logic is always tested.


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """
    Reset rate limiter state before and after EVERY test.
    autouse=True ensures this runs for all tests in this module.
    """
    from app.core.rate_limit import limiter

    # Reset before test
    try:
        if hasattr(limiter, "_storage") and limiter._storage:
            limiter._storage.reset()
        if hasattr(limiter, "reset"):
            limiter.reset()
    except Exception:
        pass

    yield

    # Reset after test
    try:
        if hasattr(limiter, "_storage") and limiter._storage:
            limiter._storage.reset()
        if hasattr(limiter, "reset"):
            limiter.reset()
    except Exception:
        pass


@pytest.fixture
def enable_rate_limiting():
    """
    Fixture that temporarily enables rate limiting for a test.
    Restores the original state after the test completes.
    """
    from app.core.config import settings
    from app.core.rate_limit import limiter

    # Store original state
    original_enabled = limiter.enabled
    original_setting = settings.RATE_LIMIT_ENABLED

    # Enable rate limiting
    limiter.enabled = True
    settings.RATE_LIMIT_ENABLED = True

    yield

    # Restore original state
    limiter.enabled = original_enabled
    settings.RATE_LIMIT_ENABLED = original_setting


def test_rate_limit_login_endpoint(client: TestClient, test_user, enable_rate_limiting):
    """
    Test that login endpoint enforces rate limiting.

    This test temporarily enables rate limiting to verify the mechanism works.
    """
    from app.core.config import settings

    # Make multiple requests to trigger rate limit
    rate_limited = False
    for i in range(settings.RATE_LIMIT_LOGIN_ATTEMPTS + 2):
        response = client.post(
            "/auth/token",
            data={
                "username": "testuser@example.com",
                "password": "WrongPassword!",  # Wrong password to not lock account
            },
        )

        if response.status_code == 429:
            rate_limited = True
            data = response.json()
            assert data["error"] == "rate_limit_exceeded"
            break

    assert rate_limited, "Rate limiting should have been triggered"


def test_rate_limit_refresh_endpoint(client: TestClient, test_user, enable_rate_limiting):
    """
    Test that refresh endpoint enforces rate limiting.

    This test temporarily enables rate limiting to verify the mechanism works.
    """
    from app.core.config import settings

    # First get a valid refresh token
    login_response = client.post(
        "/auth/token", data={"username": "testuser@example.com", "password": "TestPassword123!"}
    )
    refresh_token = login_response.json()["refresh_token"]

    # Make multiple requests to trigger rate limit
    rate_limited = False
    for i in range(settings.RATE_LIMIT_REFRESH_ATTEMPTS + 2):
        response = client.post("/auth/refresh", headers={"Authorization": f"Bearer {refresh_token}"})

        if response.status_code == 429:
            rate_limited = True
            data = response.json()
            assert data["error"] == "rate_limit_exceeded"
            break

    assert rate_limited, "Rate limiting should have been triggered"


def test_rate_limit_response_format(client: TestClient, test_user, enable_rate_limiting):
    """
    Test that rate limit response has the correct format.

    Verifies:
    - HTTP 429 status code
    - JSON body with 'error' and 'detail' fields
    """
    from app.core.config import settings

    # Trigger rate limit
    for _ in range(settings.RATE_LIMIT_LOGIN_ATTEMPTS + 2):
        response = client.post("/auth/token", data={"username": "testuser@example.com", "password": "wrong"})
        if response.status_code == 429:
            break

    assert response.status_code == 429
    data = response.json()

    # Verify response structure
    assert "error" in data
    assert data["error"] == "rate_limit_exceeded"
    assert "detail" in data
    assert "retry_after" in data


def test_rate_limit_resets_after_window(client: TestClient, test_user, enable_rate_limiting):
    """
    Test that rate limit state can be reset (simulating window expiration).

    Note: We can't wait for actual window expiration in tests,
    so we manually reset the limiter state to verify behavior.
    """
    from app.core.config import settings
    from app.core.rate_limit import limiter

    # Trigger rate limit
    for _ in range(settings.RATE_LIMIT_LOGIN_ATTEMPTS + 2):
        response = client.post("/auth/token", data={"username": "testuser@example.com", "password": "wrong"})
        if response.status_code == 429:
            break

    assert response.status_code == 429

    # Reset limiter (simulating window expiration)
    try:
        if hasattr(limiter, "_storage") and limiter._storage:
            limiter._storage.reset()
    except Exception:
        pass

    # Should be able to make requests again
    response = client.post("/auth/token", data={"username": "testuser@example.com", "password": "TestPassword123!"})

    # Should not be rate limited anymore
    assert response.status_code != 429


def test_rate_limit_disabled_when_setting_false(client: TestClient, test_user):
    """
    Test that rate limiting can be disabled via settings.

    When RATE_LIMIT_ENABLED is False, requests should not be rate limited.
    """
    from app.core.config import settings
    from app.core.rate_limit import limiter

    # Disable rate limiting
    original_enabled = limiter.enabled
    original_setting = settings.RATE_LIMIT_ENABLED

    limiter.enabled = False
    settings.RATE_LIMIT_ENABLED = False

    try:
        # Make many requests - none should be rate limited
        for _ in range(20):
            response = client.post("/auth/token", data={"username": "testuser@example.com", "password": "wrong"})
            # Should get 401 (wrong password), never 429 (rate limited)
            assert response.status_code == 401, "Rate limiting triggered when it should be disabled"
    finally:
        # Restore original state
        limiter.enabled = original_enabled
        settings.RATE_LIMIT_ENABLED = original_setting
