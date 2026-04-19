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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.database import Base, get_db
from app.main import app
from app.models.domain import BOMItem, CatalogItem, CatalogItemStatus, PriceListItem

# Use plain-text logs during tests to avoid JSON noise in pytest output
setup_logging(level=settings.LOG_LEVEL, json_output=False)

# Import all fixtures from subdirectories via pytest_plugins
# This makes all fixtures available automatically in all test files
pytest_plugins = [
    "tests.fixtures.auth",
    "tests.fixtures.entities",
    "tests.fixtures.engine",
    "tests.fixtures.configurations_lifecycle",
    "tests.fixtures.price_lists",
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


@pytest.fixture
def strict_catalog_validation():
    """
    Opt-in marker that disables autouse catalog auto-seeding.

    Requesting this fixture keeps the real `validate_catalog_reference`
    logic (missing part -> 409, OBSOLETE -> 409). Tests that exercise the
    validation rules themselves request this fixture; everything else
    relies on the autouse auto-seed to stay green through the FK.
    """
    return True


@pytest.fixture(autouse=True)
def auto_seed_catalog(request, db_session, monkeypatch):
    """
    Auto-seed CatalogItem rows so existing BOM/PriceList tests stay green.

    Two mechanisms:
      1. A SQLAlchemy `before_flush` listener on the shared test session
         inspects pending BOMItem/PriceListItem inserts and creates any
         missing CatalogItem on the same flush. This covers direct-DB
         fixtures that build rows via `session.add(...)`.
      2. A monkeypatch of `validate_catalog_reference` swaps the strict
         validator for a lenient one that auto-creates the catalog entry
         instead of raising. This covers API tests that POST/PATCH via
         the HTTP layer.

    Tests that want the real validation (new CRUD validation tests,
    OBSOLETE-rejection tests) request `strict_catalog_validation` to
    opt out.
    """
    if "strict_catalog_validation" in request.fixturenames:
        yield
        return

    def _before_flush(session: Session, flush_context, instances) -> None:
        part_numbers: set[str] = set()
        for obj in session.new:
            if isinstance(obj, BOMItem | PriceListItem) and obj.part_number:
                part_numbers.add(obj.part_number)
        if not part_numbers:
            return
        existing = {
            row.part_number
            for row in session.query(CatalogItem).filter(CatalogItem.part_number.in_(part_numbers)).all()
        }
        for part_number in part_numbers - existing:
            session.add(
                CatalogItem(
                    part_number=part_number,
                    description=part_number,
                    unit_of_measure="PC",
                    status=CatalogItemStatus.ACTIVE,
                )
            )

    event.listen(db_session, "before_flush", _before_flush)

    def _lenient_validate_catalog_reference(db: Session, part_number: str, *, on_create: bool) -> CatalogItem:
        item = db.query(CatalogItem).filter(CatalogItem.part_number == part_number).first()
        if item is None:
            item = CatalogItem(
                part_number=part_number,
                description=part_number,
                unit_of_measure="PC",
                status=CatalogItemStatus.ACTIVE,
            )
            db.add(item)
            db.flush()
        return item

    monkeypatch.setattr(
        "app.dependencies.validators.validate_catalog_reference",
        _lenient_validate_catalog_reference,
    )
    monkeypatch.setattr(
        "app.routers.bom_items.validate_catalog_reference",
        _lenient_validate_catalog_reference,
    )
    monkeypatch.setattr(
        "app.routers.price_list_items.validate_catalog_reference",
        _lenient_validate_catalog_reference,
    )

    try:
        yield
    finally:
        event.remove(db_session, "before_flush", _before_flush)


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
