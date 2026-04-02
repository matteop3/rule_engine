"""
Main conftest.py for pytest configuration.
Provides core fixtures: db_session, client.
Imports all fixtures from fixtures/ subdirectory.

Uses testcontainers to spin up a real PostgreSQL database for tests.
This ensures tests run against the same database type as production.

Database schema is managed by:
- Tests: Base.metadata.create_all() in db_session fixture (ephemeral)
- Production: Alembic migrations via docker-entrypoint.sh
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.database import Base, get_db
from app.main import app

# Use plain-text logs during tests to avoid JSON noise in pytest output
setup_logging(level=settings.LOG_LEVEL, json_output=False)

# Import all fixtures from subdirectories via pytest_plugins
# This makes all fixtures available automatically in all test files
pytest_plugins = [
    "tests.fixtures.auth",
    "tests.fixtures.entities",
    "tests.fixtures.engine",
    "tests.fixtures.configurations_lifecycle",
]


# ============================================================
# DATABASE SETUP (PostgreSQL via testcontainers)
# ============================================================


@pytest.fixture(scope="session")
def postgres_container():
    """
    Starts a PostgreSQL container that lives for the entire test session.

    Why session-scoped?
    - Starting a container takes ~2-3 seconds
    - We don't want to pay this cost for every single test
    - The container is shared, but each test gets clean tables (see db_session)

    The 'with' statement ensures the container is properly stopped
    when all tests are done, even if tests fail.
    """
    with PostgresContainer("postgres:16") as postgres:
        yield postgres


@pytest.fixture(scope="session")
def test_engine(postgres_container):
    """
    Creates a SQLAlchemy engine connected to the test container.

    Session-scoped because:
    - Creating engines is relatively expensive
    - The engine is just a connection pool, not actual data
    - Safe to reuse across tests
    """
    engine = create_engine(postgres_container.get_connection_url())
    yield engine
    engine.dispose()  # Clean up connection pool when done


@pytest.fixture(scope="function")
def db_session(test_engine):
    """
    Creates a fresh database state for each individual test.

    Why function-scoped?
    - Each test needs isolation (test A shouldn't affect test B)
    - Create all tables before the test
    - Drop all tables after the test
    - This guarantees a clean slate for every test

    Flow:
    1. Create all tables (empty database)
    2. Create a session
    3. yield session to the test
    4. Test runs and does whatever it wants
    5. Close session
    6. Drop all tables (clean up)
    """
    # Create tables before the test
    Base.metadata.create_all(bind=test_engine)

    # Create a session for this test
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        # Drop all tables after the test - ensures complete isolation
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db_session, test_engine):
    """
    HTTP test client that uses the test database.

    How it works:
    1. We override FastAPI's get_db dependency
    2. Instead of connecting to the real database, it uses our test session
    3. All HTTP requests through this client use the test database

    This is dependency injection in action!
    """
    # Reset rate limiter before each test to avoid 429 errors
    limiter.reset()

    def override_get_db():
        """
        This function replaces the real get_db.
        Instead of creating a new session, it returns our test session.
        """
        yield db_session

    # Tell FastAPI: "when someone asks for get_db, use override_get_db instead"
    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    # Cleanup: remove the override to avoid side effects between tests
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_engine_cache():
    """Prevent cross-test cache pollution."""
    yield
    from app.dependencies.services import get_rule_engine_service

    get_rule_engine_service()._cache.clear()


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
- setup_calculation_scenario (CALCULATION rule testing scenario)

Usage example:
    def test_something(client, admin_headers, db_session):
        response = client.get("/api/endpoint", headers=admin_headers)
        assert response.status_code == 200
"""
