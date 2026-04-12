"""
Tests for BOM output in calculation responses and bom_total_price persistence
on Configuration records.

Covers:
- Stateless POST /engine/calculate returns BOM output
- Version without BOM items returns bom: null
- GET /configurations/{id}/calculate returns BOM
- bom_total_price persisted on create
- bom_total_price updated on data change
- bom_total_price updated on version upgrade
- bom_total_price copied on clone
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.domain import (
    BOMItem,
    BOMItemRule,
    BOMType,
    Entity,
    EntityVersion,
    Field,
    FieldType,
    PriceList,
    PriceListItem,
    User,
    UserRole,
    Value,
    VersionStatus,
)

# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def bom_user(db_session):
    """Creates a test user for BOM configuration tests."""
    user = User(
        email="bomuser@example.com",
        hashed_password=get_password_hash("TestPassword123!"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def bom_auth_headers(bom_user):
    """Generates valid auth headers for the BOM test user."""
    access_token = create_access_token(subject=bom_user.id)
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="function")
def bom_admin(db_session):
    """Creates an admin user for BOM tests requiring admin access."""
    user = User(
        email="bomadmin@example.com",
        hashed_password=get_password_hash("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def bom_admin_headers(bom_admin):
    """Generates valid auth headers for the BOM admin user."""
    access_token = create_access_token(subject=bom_admin.id)
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="function")
def bom_price_list(db_session):
    """Creates a price list with prices for all BOM test part numbers."""
    price_list = PriceList(
        name="BOM Test Price List",
        description="Price list for BOM configuration tests",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(price_list)
    db_session.flush()

    for part, price in [
        ("BLT-004", Decimal("2.50")),
        ("CTG-001", Decimal("30.00")),
        ("BASE-001", Decimal("0")),
        ("PART-V1", Decimal("5.00")),
        ("PART-V2", Decimal("10.00")),
    ]:
        db_session.add(
            PriceListItem(
                price_list_id=price_list.id,
                part_number=part,
                unit_price=price,
                valid_from=dt.date(2020, 1, 1),
                valid_to=dt.date(9999, 12, 31),
            )
        )
    db_session.commit()
    db_session.refresh(price_list)
    return price_list


@pytest.fixture(scope="function")
def setup_bom_version(db_session):
    """
    Creates a PUBLISHED version with fields, values, and BOM items for testing.

    Fields:
    - material (dropdown): WOOD, METAL

    BOM items:
    - Base plate (TECHNICAL, unconditional, qty=1)
    - Bolts (COMMERCIAL, unconditional, qty=4, unit_price=2.50)
    - Coating (COMMERCIAL, conditional: material == METAL, qty=1, unit_price=30.00)
    """
    entity = Entity(name="BOM Config Test", description="BOM configuration lifecycle tests")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    f_material = Field(
        entity_version_id=version.id,
        name="material",
        label="Material",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=1,
        sequence=0,
    )
    db_session.add(f_material)
    db_session.commit()

    v_wood = Value(field_id=f_material.id, value="WOOD", label="Wood")
    v_metal = Value(field_id=f_material.id, value="METAL", label="Metal")
    db_session.add_all([v_wood, v_metal])
    db_session.commit()

    bom_base = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="BASE-001",
        description="Base plate",
        quantity=Decimal("1"),
        sequence=1,
    )
    bom_bolts = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="BLT-004",
        description="Bolt pack",
        quantity=Decimal("4"),
        sequence=2,
    )
    bom_coating = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="CTG-001",
        description="Metal coating",
        quantity=Decimal("1"),
        sequence=3,
    )
    db_session.add_all([bom_base, bom_bolts, bom_coating])
    db_session.commit()

    # Coating included only when material == METAL
    rule_coating = BOMItemRule(
        bom_item_id=bom_coating.id,
        entity_version_id=version.id,
        conditions={"criteria": [{"field_id": f_material.id, "operator": "EQUALS", "value": "METAL"}]},
        description="Include coating for metal",
    )
    db_session.add(rule_coating)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {"material": f_material.id},
    }


@pytest.fixture(scope="function")
def setup_bom_upgrade_versions(db_session):
    """
    Creates an entity with two versions for upgrade testing:
    - v1: ARCHIVED, with COMMERCIAL BOM items totaling 10.00
    - v2: PUBLISHED, with COMMERCIAL BOM items totaling 50.00
    """
    entity = Entity(name="BOM Upgrade Entity", description="BOM upgrade tests")
    db_session.add(entity)
    db_session.commit()

    # V1: ARCHIVED
    v1 = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.ARCHIVED,
    )
    db_session.add(v1)
    db_session.commit()

    f1 = Field(
        entity_version_id=v1.id,
        name="option",
        label="Option",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=0,
    )
    db_session.add(f1)
    db_session.commit()

    bom_v1 = BOMItem(
        entity_version_id=v1.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="PART-V1",
        description="V1 part",
        quantity=Decimal("2"),
        sequence=1,
    )
    db_session.add(bom_v1)
    db_session.commit()

    # V2: PUBLISHED
    v2 = EntityVersion(
        entity_id=entity.id,
        version_number=2,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(v2)
    db_session.commit()

    f2 = Field(
        entity_version_id=v2.id,
        name="option",
        label="Option",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=0,
    )
    db_session.add(f2)
    db_session.commit()

    bom_v2 = BOMItem(
        entity_version_id=v2.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="PART-V2",
        description="V2 part",
        quantity=Decimal("5"),
        sequence=1,
    )
    db_session.add(bom_v2)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "v1_id": v1.id,
        "v2_id": v2.id,
        "v1_field_id": f1.id,
        "v2_field_id": f2.id,
    }


# ============================================================
# STATELESS ENGINE TESTS
# ============================================================


class TestCalculateIncludesBOM:
    """Stateless POST /engine/calculate returns BOM output."""

    def test_calculate_includes_bom(self, client, bom_auth_headers, setup_bom_version, bom_price_list):
        """Stateless calculation returns BOM output with technical and commercial items."""
        data = setup_bom_version
        payload = {
            "entity_id": data["entity_id"],
            "entity_version_id": data["version_id"],
            "price_list_id": bom_price_list.id,
            "current_state": [
                {"field_id": data["fields"]["material"], "value": "METAL"},
            ],
        }

        response = client.post("/engine/calculate", json=payload, headers=bom_auth_headers)

        assert response.status_code == 200
        result = response.json()
        assert result["bom"] is not None
        assert len(result["bom"]["technical"]) >= 1
        assert len(result["bom"]["commercial"]) >= 1
        # Coating included (METAL selected) → commercial_total = bolts(4*2.50) + coating(1*30.00) = 40.00
        assert Decimal(result["bom"]["commercial_total"]) == Decimal("40.00")

    def test_calculate_no_bom_items(self, client, bom_auth_headers, db_session):
        """Version without BOM items returns bom: null."""
        entity = Entity(name="No BOM Entity", description="No BOM")
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
            "entity_id": entity.id,
            "entity_version_id": version.id,
            "current_state": [{"field_id": field.id, "value": "Red"}],
        }

        response = client.post("/engine/calculate", json=payload, headers=bom_auth_headers)

        assert response.status_code == 200
        assert response.json()["bom"] is None


# ============================================================
# CONFIGURATION CALCULATE ENDPOINT
# ============================================================


class TestConfigurationCalculateIncludesBOM:
    """GET /configurations/{id}/calculate returns BOM."""

    def test_configuration_calculate_includes_bom(
        self,
        client,
        bom_auth_headers,
        db_session,
        setup_bom_version,
        bom_price_list,
    ):
        """Saved configuration recalculation includes BOM output."""
        data = setup_bom_version

        # Create a configuration first
        create_payload = {
            "entity_version_id": data["version_id"],
            "name": "BOM Calc Test",
            "price_list_id": bom_price_list.id,
            "data": [{"field_id": data["fields"]["material"], "value": "WOOD"}],
        }
        create_resp = client.post("/configurations/", json=create_payload, headers=bom_auth_headers)
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]

        # Recalculate
        calc_resp = client.get(f"/configurations/{config_id}/calculate", headers=bom_auth_headers)

        assert calc_resp.status_code == 200
        result = calc_resp.json()
        assert result["bom"] is not None
        # WOOD → coating excluded → commercial_total = bolts only (4*2.50) = 10.00
        assert Decimal(result["bom"]["commercial_total"]) == Decimal("10.00")


# ============================================================
# BOM TOTAL PRICE PERSISTENCE
# ============================================================


class TestBOMTotalPriceCreate:
    """bom_total_price persisted on configuration create."""

    def test_configuration_create_stores_bom_total(
        self,
        client,
        bom_auth_headers,
        setup_bom_version,
        bom_price_list,
    ):
        """Creating a configuration should persist bom_total_price from commercial_total."""
        data = setup_bom_version

        # METAL → coating included → commercial_total = 4*2.50 + 1*30.00 = 40.00
        payload = {
            "entity_version_id": data["version_id"],
            "name": "BOM Create Price Test",
            "price_list_id": bom_price_list.id,
            "data": [{"field_id": data["fields"]["material"], "value": "METAL"}],
        }

        response = client.post("/configurations/", json=payload, headers=bom_auth_headers)

        assert response.status_code == 201
        result = response.json()
        assert Decimal(result["bom_total_price"]) == Decimal("40.00")


class TestBOMTotalPriceUpdate:
    """bom_total_price updated on data change."""

    def test_configuration_update_recalculates_bom_total(
        self,
        client,
        bom_auth_headers,
        setup_bom_version,
        bom_price_list,
    ):
        """Updating configuration data should recalculate bom_total_price."""
        data = setup_bom_version

        # Create with METAL → 40.00
        create_payload = {
            "entity_version_id": data["version_id"],
            "name": "BOM Update Price Test",
            "price_list_id": bom_price_list.id,
            "data": [{"field_id": data["fields"]["material"], "value": "METAL"}],
        }
        create_resp = client.post("/configurations/", json=create_payload, headers=bom_auth_headers)
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]
        assert Decimal(create_resp.json()["bom_total_price"]) == Decimal("40.00")

        # Update to WOOD → coating excluded → 10.00
        update_payload = {
            "data": [{"field_id": data["fields"]["material"], "value": "WOOD"}],
        }
        update_resp = client.patch(
            f"/configurations/{config_id}",
            json=update_payload,
            headers=bom_auth_headers,
        )

        assert update_resp.status_code == 200
        assert Decimal(update_resp.json()["bom_total_price"]) == Decimal("10.00")


class TestBOMTotalPriceUpgrade:
    """bom_total_price updated on version upgrade."""

    def test_configuration_upgrade_recalculates_bom_total(
        self,
        client,
        bom_admin_headers,
        db_session,
        setup_bom_upgrade_versions,
        bom_price_list,
    ):
        """Upgrading to a new version should recalculate bom_total_price."""
        data = setup_bom_upgrade_versions

        # Create config on V1 (archived) — admin bypasses USER restriction
        # V1 commercial total = 2 * 5.00 = 10.00
        create_payload = {
            "entity_version_id": data["v1_id"],
            "name": "BOM Upgrade Price Test",
            "price_list_id": bom_price_list.id,
            "data": [{"field_id": data["v1_field_id"], "value": "anything"}],
        }
        create_resp = client.post("/configurations/", json=create_payload, headers=bom_admin_headers)
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]
        assert Decimal(create_resp.json()["bom_total_price"]) == Decimal("10.00")

        # Upgrade to V2 — V2 commercial total = 5 * 10.00 = 50.00
        upgrade_resp = client.post(
            f"/configurations/{config_id}/upgrade",
            headers=bom_admin_headers,
        )

        assert upgrade_resp.status_code == 200
        assert Decimal(upgrade_resp.json()["bom_total_price"]) == Decimal("50.00")
        assert upgrade_resp.json()["entity_version_id"] == data["v2_id"]


class TestBOMTotalPriceClone:
    """bom_total_price copied on clone."""

    def test_configuration_clone_copies_bom_total(
        self,
        client,
        bom_auth_headers,
        setup_bom_version,
        bom_price_list,
    ):
        """Cloning a configuration should preserve bom_total_price."""
        data = setup_bom_version

        # Create source with METAL → 40.00
        create_payload = {
            "entity_version_id": data["version_id"],
            "name": "BOM Clone Source",
            "price_list_id": bom_price_list.id,
            "data": [{"field_id": data["fields"]["material"], "value": "METAL"}],
        }
        create_resp = client.post("/configurations/", json=create_payload, headers=bom_auth_headers)
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]
        source_bom_total = create_resp.json()["bom_total_price"]

        # Clone
        clone_resp = client.post(
            f"/configurations/{config_id}/clone",
            headers=bom_auth_headers,
        )

        assert clone_resp.status_code == 201
        assert clone_resp.json()["bom_total_price"] == source_bom_total
        assert Decimal(clone_resp.json()["bom_total_price"]) == Decimal("40.00")
