"""
Main conftest.py for pytest configuration.
Provides core fixtures: db_session, client.
Imports all fixtures from fixtures/ subdirectory.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.core.rate_limit import limiter

# Import all fixtures from subdirectories via pytest_plugins
# This makes all fixtures available automatically in all test files
pytest_plugins = [
    "tests.fixtures.auth",
    "tests.fixtures.entities",
    "tests.fixtures.engine",
    "tests.fixtures.configurations_lifecycle"
]

# ============================================================
# DATABASE SETUP (In-Memory SQLite)
# ============================================================

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # Required for in-memory SQLite
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ============================================================
# CORE FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def db_session():
    """
    Creates a new clean database for each individual test.
    Ensures total isolation between tests.
    """
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """
    HTTP test client that overrides get_db dependency to use test database.
    Resets rate limiter before each test to avoid 429 errors.
    """
    # Reset rate limiter storage before each test
    limiter.reset()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    # Cleanup: remove the override to avoid side effects between tests
    app.dependency_overrides.clear()


# ============================================================
# FIXTURE DOCUMENTATION
# ============================================================
"""
All other fixtures are imported automatically via pytest_plugins above.

Available fixtures from tests.fixtures.auth:
- admin_user, admin_headers
- author_user, author_headers
- regular_user, user_headers
- inactive_user

Available fixtures from tests.fixtures.entities:
- test_entity, second_entity
- draft_version, published_version, archived_version, version_with_data
- draft_field, free_field, field_with_values, field_as_rule_target, published_field
- draft_value, value_in_rule_target, value_in_rule_condition
- draft_rule, published_rule, rule_with_value_target

Available fixtures from tests.fixtures.engine:
- setup_insurance_scenario (complex auto insurance scenario)
- setup_dropdown_scenario (cascading dropdown scenario)
- setup_operator_scenario (operator testing scenario)
- setup_stress_scenario (stress testing scenario)

Usage example:
    def test_something(client, admin_headers, db_session):
        response = client.get("/api/endpoint", headers=admin_headers)
        assert response.status_code == 200
"""
