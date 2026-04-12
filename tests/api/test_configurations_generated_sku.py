"""
Test suite for generated_sku caching on Configuration records.

The generated_sku is cached on the Configuration model alongside is_complete.
It is set during create, recalculated during update and upgrade, and copied during clone.
"""

import datetime as dt

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.domain import (
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
# AUTH FIXTURES (local to this module)
# ============================================================


@pytest.fixture(scope="function")
def sku_user(db_session):
    """Creates a test user for SKU configuration tests."""
    user = User(
        email="skuuser@example.com",
        hashed_password=get_password_hash("TestPassword123!"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def sku_auth_headers(sku_user):
    """Generates valid auth headers for the SKU test user."""
    access_token = create_access_token(subject=sku_user.id)
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="function")
def sku_price_list(db_session):
    """Creates a price list for SKU configuration tests."""
    price_list = PriceList(
        name="SKU Test Price List",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(price_list)
    db_session.commit()
    db_session.refresh(price_list)
    return price_list


# ============================================================
# CREATE TESTS
# ============================================================


class TestGeneratedSKUCreate:
    """Test that generated_sku is calculated and cached on create."""

    def test_create_caches_generated_sku(self, client, sku_auth_headers, setup_sku_scenario, sku_price_list):
        """Creating a configuration with SKU-enabled version should cache the SKU."""
        data = setup_sku_scenario
        payload = {
            "entity_version_id": data["version_id"],
            "name": "SKU Create Test",
            "price_list_id": sku_price_list.id,
            "data": [
                {"field_id": data["fields"]["cpu"], "value": "Intel i7"},
                {"field_id": data["fields"]["ram"], "value": "32GB"},
            ],
        }

        response = client.post("/configurations/", json=payload, headers=sku_auth_headers)

        assert response.status_code == 201
        result = response.json()
        assert result["generated_sku"] == "LPT-PRO-I7-32G"

    def test_create_without_sku_base_returns_null(self, client, sku_auth_headers, db_session, sku_price_list):
        """Creating a configuration on a version without sku_base should return null SKU."""
        entity = Entity(name="No SKU Entity", description="No SKU")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
        db_session.add(version)
        db_session.commit()

        field = Field(
            entity_version_id=version.id,
            name="color",
            label="Color",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        db_session.add(field)
        db_session.commit()

        payload = {
            "entity_version_id": version.id,
            "name": "No SKU Config",
            "price_list_id": sku_price_list.id,
            "data": [{"field_id": field.id, "value": "Red"}],
        }

        response = client.post("/configurations/", json=payload, headers=sku_auth_headers)

        assert response.status_code == 201
        assert response.json()["generated_sku"] is None


# ============================================================
# UPDATE TESTS
# ============================================================


class TestGeneratedSKUUpdate:
    """Test that generated_sku is recalculated on data update."""

    def test_update_recalculates_generated_sku(self, client, sku_auth_headers, setup_sku_scenario, sku_price_list):
        """Updating configuration data should recalculate the cached SKU."""
        data = setup_sku_scenario

        # Create with CPU=i7, RAM=32GB -> LPT-PRO-I7-32G
        create_payload = {
            "entity_version_id": data["version_id"],
            "name": "SKU Update Test",
            "price_list_id": sku_price_list.id,
            "data": [
                {"field_id": data["fields"]["cpu"], "value": "Intel i7"},
                {"field_id": data["fields"]["ram"], "value": "32GB"},
            ],
        }
        create_resp = client.post("/configurations/", json=create_payload, headers=sku_auth_headers)
        config_id = create_resp.json()["id"]
        assert create_resp.json()["generated_sku"] == "LPT-PRO-I7-32G"

        # Update to CPU=i9, RAM=16GB -> LPT-PRO-I9-16G
        update_payload = {
            "data": [
                {"field_id": data["fields"]["cpu"], "value": "Intel i9"},
                {"field_id": data["fields"]["ram"], "value": "16GB"},
            ]
        }
        update_resp = client.patch(f"/configurations/{config_id}", json=update_payload, headers=sku_auth_headers)

        assert update_resp.status_code == 200
        assert update_resp.json()["generated_sku"] == "LPT-PRO-I9-16G"


# ============================================================
# CLONE TESTS
# ============================================================


class TestGeneratedSKUClone:
    """Test that generated_sku is copied during clone."""

    def test_clone_copies_generated_sku(self, client, sku_auth_headers, setup_sku_scenario, sku_price_list):
        """Cloning a configuration should preserve the cached SKU."""
        data = setup_sku_scenario

        # Create source config
        create_payload = {
            "entity_version_id": data["version_id"],
            "name": "SKU Clone Source",
            "price_list_id": sku_price_list.id,
            "data": [
                {"field_id": data["fields"]["cpu"], "value": "Intel i7"},
                {"field_id": data["fields"]["ram"], "value": "32GB"},
            ],
        }
        create_resp = client.post("/configurations/", json=create_payload, headers=sku_auth_headers)
        config_id = create_resp.json()["id"]
        source_sku = create_resp.json()["generated_sku"]

        # Clone
        clone_resp = client.post(f"/configurations/{config_id}/clone", headers=sku_auth_headers)

        assert clone_resp.status_code == 201
        assert clone_resp.json()["generated_sku"] == source_sku


# ============================================================
# UPGRADE TESTS
# ============================================================


class TestGeneratedSKUUpgrade:
    """Test that generated_sku is recalculated during version upgrade."""

    def test_upgrade_recalculates_generated_sku(self, client, sku_auth_headers, db_session, sku_price_list):
        """Upgrading to a new version should recalculate the SKU with new version's sku_base."""
        # Create entity with two versions (different sku_base)
        entity = Entity(name="SKU Upgrade Entity", description="Test upgrade SKU")
        db_session.add(entity)
        db_session.commit()

        # V1: ARCHIVED, sku_base="V1"
        v1 = EntityVersion(
            entity_id=entity.id, version_number=1, status=VersionStatus.ARCHIVED, sku_base="V1", sku_delimiter="-"
        )
        db_session.add(v1)
        db_session.commit()

        f1 = Field(
            entity_version_id=v1.id,
            name="option",
            label="Option",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_required=False,
            step=1,
            sequence=0,
        )
        db_session.add(f1)
        db_session.commit()

        val1 = Value(field_id=f1.id, value="A", label="A", sku_modifier="A")
        db_session.add(val1)
        db_session.commit()

        # V2: PUBLISHED, sku_base="V2"
        v2 = EntityVersion(
            entity_id=entity.id, version_number=2, status=VersionStatus.PUBLISHED, sku_base="V2", sku_delimiter="-"
        )
        db_session.add(v2)
        db_session.commit()

        f2 = Field(
            entity_version_id=v2.id,
            name="option",
            label="Option",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_required=False,
            step=1,
            sequence=0,
        )
        db_session.add(f2)
        db_session.commit()

        val2 = Value(field_id=f2.id, value="A", label="A", sku_modifier="A")
        db_session.add(val2)
        db_session.commit()

        # Create config on V1 (archived) using admin to bypass USER restriction
        admin = User(
            email="skuadmin@example.com",
            hashed_password=get_password_hash("AdminPass123!"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db_session.add(admin)
        db_session.commit()
        admin_headers = {"Authorization": f"Bearer {create_access_token(subject=admin.id)}"}

        create_payload = {
            "entity_version_id": v1.id,
            "name": "Upgrade SKU Test",
            "price_list_id": sku_price_list.id,
            "data": [{"field_id": f1.id, "value": "A"}],
        }
        create_resp = client.post("/configurations/", json=create_payload, headers=admin_headers)
        assert create_resp.status_code == 201
        assert create_resp.json()["generated_sku"] == "V1-A"

        config_id = create_resp.json()["id"]

        # Upgrade to V2
        upgrade_resp = client.post(f"/configurations/{config_id}/upgrade", headers=admin_headers)

        assert upgrade_resp.status_code == 200
        # After upgrade, the old field_id from V1 doesn't match V2's fields,
        # so the SKU is recalculated as just the new base (no modifiers match)
        assert upgrade_resp.json()["generated_sku"] == "V2"


# ============================================================
# LIST TESTS
# ============================================================


class TestGeneratedSKUList:
    """Test that generated_sku appears in list responses."""

    def test_list_includes_generated_sku(self, client, sku_auth_headers, setup_sku_scenario, sku_price_list):
        """Listed configurations should include the cached generated_sku."""
        data = setup_sku_scenario

        # Create a config with SKU
        payload = {
            "entity_version_id": data["version_id"],
            "name": "SKU List Test",
            "price_list_id": sku_price_list.id,
            "data": [{"field_id": data["fields"]["cpu"], "value": "Intel i5"}],
        }
        client.post("/configurations/", json=payload, headers=sku_auth_headers)

        # List configurations
        list_resp = client.get("/configurations/", headers=sku_auth_headers)

        assert list_resp.status_code == 200
        configs = list_resp.json()
        assert len(configs) >= 1
        assert "generated_sku" in configs[0]
        assert configs[0]["generated_sku"] == "LPT-PRO-I5"
