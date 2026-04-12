"""
Configuration lifecycle fixtures for tests.
Provides fixtures for testing DRAFT/FINALIZED status, clone, upgrade, finalize operations.
"""

from datetime import UTC, datetime

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.domain import (
    Configuration,
    ConfigurationStatus,
    Entity,
    EntityVersion,
    Field,
    FieldType,
    PriceList,
    User,
    UserRole,
    Value,
    VersionStatus,
)

# ============================================================
# USER FIXTURES FOR LIFECYCLE TESTS
# ============================================================


@pytest.fixture(scope="function")
def lifecycle_admin(db_session):
    """Creates an admin user for lifecycle tests."""
    user = User(
        email="lifecycle_admin@example.com",
        hashed_password=get_password_hash("AdminPassword123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def lifecycle_admin_headers(lifecycle_admin):
    """Auth headers for lifecycle admin."""
    token = create_access_token(subject=lifecycle_admin.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def lifecycle_author(db_session):
    """Creates an author user for lifecycle tests."""
    user = User(
        email="lifecycle_author@example.com",
        hashed_password=get_password_hash("AuthorPassword123!"),
        role=UserRole.AUTHOR,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def lifecycle_author_headers(lifecycle_author):
    """Auth headers for lifecycle author."""
    token = create_access_token(subject=lifecycle_author.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def lifecycle_user(db_session):
    """Creates a regular user for lifecycle tests."""
    user = User(
        email="lifecycle_user@example.com",
        hashed_password=get_password_hash("UserPassword123!"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def lifecycle_user_headers(lifecycle_user):
    """Auth headers for lifecycle user."""
    token = create_access_token(subject=lifecycle_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def second_lifecycle_user(db_session):
    """Creates a second regular user for ownership tests."""
    user = User(
        email="lifecycle_user2@example.com",
        hashed_password=get_password_hash("UserPassword123!"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def second_lifecycle_user_headers(second_lifecycle_user):
    """Auth headers for second lifecycle user."""
    token = create_access_token(subject=second_lifecycle_user.id)
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# PRICE LIST FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def lifecycle_price_list(db_session):
    """Creates a price list for lifecycle tests."""
    import datetime as dt

    price_list = PriceList(
        name="Lifecycle Test Price List",
        description="Price list for configuration lifecycle testing",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(price_list)
    db_session.commit()
    db_session.refresh(price_list)
    return price_list


# ============================================================
# ENTITY & VERSION FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def lifecycle_entity(db_session, lifecycle_admin):
    """Creates a basic Entity for lifecycle tests."""
    entity = Entity(
        name="Lifecycle Test Entity",
        description="Entity for configuration lifecycle testing",
        created_by_id=lifecycle_admin.id,
        updated_by_id=lifecycle_admin.id,
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture(scope="function")
def multi_version_entity(db_session, lifecycle_admin):
    """
    Creates an entity with multiple versions for upgrade testing:
    - v1: ARCHIVED (old)
    - v2: PUBLISHED (current)
    - v3: DRAFT (future, optional)
    """
    entity = Entity(
        name="Multi-Version Entity",
        description="Entity with ARCHIVED, PUBLISHED, and DRAFT versions",
        created_by_id=lifecycle_admin.id,
        updated_by_id=lifecycle_admin.id,
    )
    db_session.add(entity)
    db_session.flush()

    # v1: ARCHIVED
    archived_version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.ARCHIVED,
        changelog="Archived version for testing",
        published_at=datetime.now(UTC),
        created_by_id=lifecycle_admin.id,
        updated_by_id=lifecycle_admin.id,
    )
    db_session.add(archived_version)
    db_session.flush()

    # Add fields to archived version
    archived_field = Field(
        entity_version_id=archived_version.id,
        name="legacy_field",
        label="Legacy Field",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=True,
        sequence=1,
    )
    db_session.add(archived_field)
    db_session.flush()

    # v2: PUBLISHED (current)
    published_version = EntityVersion(
        entity_id=entity.id,
        version_number=2,
        status=VersionStatus.PUBLISHED,
        changelog="Current published version",
        published_at=datetime.now(UTC),
        created_by_id=lifecycle_admin.id,
        updated_by_id=lifecycle_admin.id,
    )
    db_session.add(published_version)
    db_session.flush()

    # Add fields to published version
    pub_field_type = Field(
        entity_version_id=published_version.id,
        name="product_type",
        label="Product Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        sequence=1,
    )
    pub_field_value = Field(
        entity_version_id=published_version.id,
        name="product_value",
        label="Product Value",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        sequence=2,
    )
    pub_field_optional = Field(
        entity_version_id=published_version.id,
        name="has_warranty",
        label="Has Warranty",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        sequence=3,
    )
    db_session.add_all([pub_field_type, pub_field_value, pub_field_optional])
    db_session.flush()

    # Add values for product_type
    value_basic = Value(field_id=pub_field_type.id, value="BASIC", label="Basic", is_default=True)
    value_premium = Value(field_id=pub_field_type.id, value="PREMIUM", label="Premium", is_default=False)
    db_session.add_all([value_basic, value_premium])
    db_session.flush()

    # v3: DRAFT (future)
    draft_version = EntityVersion(
        entity_id=entity.id,
        version_number=3,
        status=VersionStatus.DRAFT,
        changelog="Draft version for future",
        created_by_id=lifecycle_admin.id,
        updated_by_id=lifecycle_admin.id,
    )
    db_session.add(draft_version)
    db_session.flush()

    # Add fields to draft version (more fields than published)
    draft_field_type = Field(
        entity_version_id=draft_version.id,
        name="product_type",
        label="Product Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        sequence=1,
    )
    draft_field_value = Field(
        entity_version_id=draft_version.id,
        name="product_value",
        label="Product Value",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        sequence=2,
    )
    draft_field_new = Field(
        entity_version_id=draft_version.id,
        name="new_required_field",
        label="New Required Field",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=True,
        sequence=3,
    )
    db_session.add_all([draft_field_type, draft_field_value, draft_field_new])
    db_session.flush()

    db_session.commit()

    return {
        "entity": entity,
        "archived_version": archived_version,
        "published_version": published_version,
        "draft_version": draft_version,
        "archived_fields": {"legacy": archived_field},
        "published_fields": {"type": pub_field_type, "value": pub_field_value, "optional": pub_field_optional},
        "published_values": {"basic": value_basic, "premium": value_premium},
        "draft_fields": {"type": draft_field_type, "value": draft_field_value, "new_required": draft_field_new},
    }


@pytest.fixture(scope="function")
def published_version_for_lifecycle(db_session, lifecycle_entity, lifecycle_admin):
    """Creates a PUBLISHED version with fields for lifecycle tests."""
    version = EntityVersion(
        entity_id=lifecycle_entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        changelog="Published version for lifecycle tests",
        published_at=datetime.now(UTC),
        created_by_id=lifecycle_admin.id,
        updated_by_id=lifecycle_admin.id,
    )
    db_session.add(version)
    db_session.flush()

    # Create fields
    field_name = Field(
        entity_version_id=version.id,
        name="customer_name",
        label="Customer Name",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=True,
        sequence=1,
    )
    field_amount = Field(
        entity_version_id=version.id,
        name="amount",
        label="Amount",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        sequence=2,
    )
    field_optional = Field(
        entity_version_id=version.id,
        name="notes",
        label="Notes",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=False,
        sequence=3,
    )
    db_session.add_all([field_name, field_amount, field_optional])
    db_session.commit()

    db_session.refresh(version)

    return {"version": version, "fields": {"name": field_name, "amount": field_amount, "optional": field_optional}}


# ============================================================
# CONFIGURATION FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def draft_configuration(db_session, lifecycle_user, published_version_for_lifecycle, lifecycle_price_list):
    """Creates a DRAFT configuration owned by lifecycle_user."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=lifecycle_user.id,
        name="Test Draft Configuration",
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[{"field_id": fields["name"].id, "value": "John Doe"}, {"field_id": fields["amount"].id, "value": 1000}],
        created_by_id=lifecycle_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def finalized_configuration(db_session, lifecycle_user, published_version_for_lifecycle, lifecycle_price_list):
    """Creates a FINALIZED configuration owned by lifecycle_user."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=lifecycle_user.id,
        name="Test Finalized Configuration",
        status=ConfigurationStatus.FINALIZED,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[{"field_id": fields["name"].id, "value": "Jane Doe"}, {"field_id": fields["amount"].id, "value": 2000}],
        created_by_id=lifecycle_user.id,
        updated_by_id=lifecycle_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def soft_deleted_configuration(db_session, lifecycle_admin, published_version_for_lifecycle, lifecycle_price_list):
    """Creates a soft-deleted FINALIZED configuration."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=lifecycle_admin.id,
        name="Soft Deleted Configuration",
        status=ConfigurationStatus.FINALIZED,
        is_complete=True,
        is_deleted=True,
        price_list_id=lifecycle_price_list.id,
        data=[
            {"field_id": fields["name"].id, "value": "Deleted User"},
            {"field_id": fields["amount"].id, "value": 500},
        ],
        created_by_id=lifecycle_admin.id,
        updated_by_id=lifecycle_admin.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def configuration_with_empty_data(db_session, lifecycle_user, published_version_for_lifecycle, lifecycle_price_list):
    """Creates a DRAFT configuration with empty data array."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=lifecycle_user.id,
        name="Empty Data Configuration",
        status=ConfigurationStatus.DRAFT,
        is_complete=False,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[],
        created_by_id=lifecycle_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def configuration_null_name(db_session, lifecycle_user, published_version_for_lifecycle, lifecycle_price_list):
    """Creates a DRAFT configuration with null name."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=lifecycle_user.id,
        name=None,
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[{"field_id": fields["name"].id, "value": "Anonymous"}, {"field_id": fields["amount"].id, "value": 100}],
        created_by_id=lifecycle_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def admin_owned_draft_configuration(db_session, lifecycle_admin, published_version_for_lifecycle, lifecycle_price_list):
    """Creates a DRAFT configuration owned by admin."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=lifecycle_admin.id,
        name="Admin Draft Configuration",
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[{"field_id": fields["name"].id, "value": "Admin User"}, {"field_id": fields["amount"].id, "value": 5000}],
        created_by_id=lifecycle_admin.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def admin_owned_finalized_configuration(
    db_session, lifecycle_admin, published_version_for_lifecycle, lifecycle_price_list
):
    """Creates a FINALIZED configuration owned by admin."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=lifecycle_admin.id,
        name="Admin Finalized Configuration",
        status=ConfigurationStatus.FINALIZED,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[
            {"field_id": fields["name"].id, "value": "Admin Finalized"},
            {"field_id": fields["amount"].id, "value": 10000},
        ],
        created_by_id=lifecycle_admin.id,
        updated_by_id=lifecycle_admin.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def author_owned_draft_configuration(
    db_session, lifecycle_author, published_version_for_lifecycle, lifecycle_price_list
):
    """Creates a DRAFT configuration owned by author."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=lifecycle_author.id,
        name="Author Draft Configuration",
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[
            {"field_id": fields["name"].id, "value": "Author User"},
            {"field_id": fields["amount"].id, "value": 3000},
        ],
        created_by_id=lifecycle_author.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def second_user_draft_configuration(
    db_session, second_lifecycle_user, published_version_for_lifecycle, lifecycle_price_list
):
    """Creates a DRAFT configuration owned by second user (for ownership tests)."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=second_lifecycle_user.id,
        name="Second User Configuration",
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[{"field_id": fields["name"].id, "value": "Second User"}, {"field_id": fields["amount"].id, "value": 750}],
        created_by_id=second_lifecycle_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def second_user_finalized_configuration(
    db_session, second_lifecycle_user, published_version_for_lifecycle, lifecycle_price_list
):
    """Creates a FINALIZED configuration owned by second user."""
    version_data = published_version_for_lifecycle
    version = version_data["version"]
    fields = version_data["fields"]

    config = Configuration(
        entity_version_id=version.id,
        user_id=second_lifecycle_user.id,
        name="Second User Finalized",
        status=ConfigurationStatus.FINALIZED,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[
            {"field_id": fields["name"].id, "value": "Second User Final"},
            {"field_id": fields["amount"].id, "value": 999},
        ],
        created_by_id=second_lifecycle_user.id,
        updated_by_id=second_lifecycle_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


# ============================================================
# CONFIGURATION WITH ARCHIVED VERSION (for upgrade tests)
# ============================================================


@pytest.fixture(scope="function")
def configuration_on_archived_version(db_session, lifecycle_user, multi_version_entity, lifecycle_price_list):
    """Creates a DRAFT configuration linked to an ARCHIVED version."""
    archived_version = multi_version_entity["archived_version"]
    archived_fields = multi_version_entity["archived_fields"]

    config = Configuration(
        entity_version_id=archived_version.id,
        user_id=lifecycle_user.id,
        name="Config on Archived Version",
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[{"field_id": archived_fields["legacy"].id, "value": "Legacy Value"}],
        created_by_id=lifecycle_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


@pytest.fixture(scope="function")
def configuration_on_published_multi_version(db_session, lifecycle_user, multi_version_entity, lifecycle_price_list):
    """Creates a DRAFT configuration linked to the PUBLISHED version of multi_version_entity."""
    published_version = multi_version_entity["published_version"]
    published_fields = multi_version_entity["published_fields"]

    config = Configuration(
        entity_version_id=published_version.id,
        user_id=lifecycle_user.id,
        name="Config on Published Version",
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        is_deleted=False,
        price_list_id=lifecycle_price_list.id,
        data=[
            {"field_id": published_fields["type"].id, "value": "BASIC"},
            {"field_id": published_fields["value"].id, "value": 1500},
        ],
        created_by_id=lifecycle_user.id,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)
    return config


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def create_sample_input_data(fields: dict) -> list:
    """
    Creates sample input data for configuration tests.

    Args:
        fields: Dict of field objects with 'name', 'amount', and optionally 'optional' keys

    Returns:
        List of field input dicts
    """
    data = [{"field_id": fields["name"].id, "value": "Sample User"}, {"field_id": fields["amount"].id, "value": 1234}]
    if "optional" in fields:
        data.append({"field_id": fields["optional"].id, "value": "Optional notes"})
    return data
