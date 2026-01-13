"""
Authentication and User fixtures for tests.
Centralizes all user creation and auth header generation.
"""
import pytest
from app.models.domain import User, UserRole
from app.core.security import get_password_hash, create_access_token


# ============================================================
# USER FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def admin_user(db_session):
    """Creates an admin user for tests."""
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
    """Creates an author user for tests."""
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
    """Creates a regular user for tests."""
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
    """Creates an inactive user for testing access denial."""
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
