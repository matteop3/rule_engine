"""
Test suite for FINALIZED configuration snapshots.

Covers:
- Finalize stores a full CalculationResponse snapshot
- Loading a FINALIZED config returns the snapshot without recalculating
- Snapshot contains fields, BOM, generated_sku
- Modifying the price list after finalization does not alter the snapshot
- A FINALIZED config without a snapshot (legacy) falls back to rehydration
"""

import datetime as dt
from decimal import Decimal

from fastapi.testclient import TestClient

from app.models.domain import (
    BOMItem,
    BOMType,
    Configuration,
    ConfigurationStatus,
    EntityVersion,
    Field,
    FieldType,
    PriceList,
    PriceListItem,
    Value,
    VersionStatus,
)


def _seed_priced_version(db_session, admin_user):
    """Create a published version with one COMMERCIAL BOM item and a price list."""
    from app.models.domain import Entity

    entity = Entity(name="Snapshot Entity", description="snapshot tests")
    db_session.add(entity)
    db_session.flush()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id,
    )
    db_session.add(version)
    db_session.flush()

    f_type = Field(
        entity_version_id=version.id,
        name="product_type",
        label="Product Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        sequence=1,
    )
    db_session.add(f_type)
    db_session.flush()
    db_session.add_all(
        [
            Value(field_id=f_type.id, value="BASIC", label="Basic", is_default=True),
            Value(field_id=f_type.id, value="PREMIUM", label="Premium", is_default=False),
        ]
    )

    bom = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="SNAP-001",
        quantity=Decimal("2"),
        sequence=1,
    )
    db_session.add(bom)

    pl = PriceList(
        name="Snapshot PL",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(pl)
    db_session.flush()

    db_session.add(
        PriceListItem(
            price_list_id=pl.id,
            part_number="SNAP-001",
            unit_price=Decimal("10.00"),
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
    )
    db_session.commit()

    return {"entity": entity, "version": version, "field": f_type, "price_list": pl}


class TestFinalizeCreatesSnapshot:
    def test_finalize_stores_full_snapshot(self, client: TestClient, admin_headers, db_session, admin_user):
        env = _seed_priced_version(db_session, admin_user)
        create = client.post(
            "/configurations/",
            json={
                "entity_version_id": env["version"].id,
                "name": "Snap Config",
                "price_list_id": env["price_list"].id,
                "data": [{"field_id": env["field"].id, "value": "BASIC"}],
            },
            headers=admin_headers,
        )
        assert create.status_code == 201
        config_id = create.json()["id"]

        finalize = client.post(f"/configurations/{config_id}/finalize", headers=admin_headers)
        assert finalize.status_code == 200
        assert finalize.json()["status"] == "FINALIZED"

        db_session.expire_all()
        config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
        assert config.snapshot is not None
        assert "bom" in config.snapshot
        assert "fields" in config.snapshot
        assert Decimal(str(config.snapshot["bom"]["commercial_total"])) == Decimal("20.00")


class TestLoadFinalizedReturnsSnapshot:
    def test_calculate_returns_snapshot_contents(self, client: TestClient, admin_headers, db_session, admin_user):
        env = _seed_priced_version(db_session, admin_user)
        create = client.post(
            "/configurations/",
            json={
                "entity_version_id": env["version"].id,
                "name": "Snap Load",
                "price_list_id": env["price_list"].id,
                "data": [{"field_id": env["field"].id, "value": "BASIC"}],
            },
            headers=admin_headers,
        )
        config_id = create.json()["id"]
        client.post(f"/configurations/{config_id}/finalize", headers=admin_headers)

        resp = client.get(f"/configurations/{config_id}/calculate", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["bom"] is not None
        assert Decimal(str(body["bom"]["commercial_total"])) == Decimal("20.00")
        assert any(f["field_name"] == "product_type" for f in body["fields"])

    def test_snapshot_immune_to_price_list_mutation(self, client: TestClient, admin_headers, db_session, admin_user):
        env = _seed_priced_version(db_session, admin_user)
        create = client.post(
            "/configurations/",
            json={
                "entity_version_id": env["version"].id,
                "name": "Immune",
                "price_list_id": env["price_list"].id,
                "data": [{"field_id": env["field"].id, "value": "BASIC"}],
            },
            headers=admin_headers,
        )
        config_id = create.json()["id"]
        client.post(f"/configurations/{config_id}/finalize", headers=admin_headers)

        # Mutate the underlying price.
        item = db_session.query(PriceListItem).filter(PriceListItem.price_list_id == env["price_list"].id).first()
        item.unit_price = Decimal("999.00")
        db_session.commit()

        resp = client.get(f"/configurations/{config_id}/calculate", headers=admin_headers)
        assert resp.status_code == 200
        # Snapshot preserved — 20.00, not 1998.00
        assert Decimal(str(resp.json()["bom"]["commercial_total"])) == Decimal("20.00")


class TestLegacyFinalizedWithoutSnapshot:
    """A FINALIZED config whose snapshot is NULL must rehydrate via the engine."""

    def test_falls_back_to_rehydration(self, client: TestClient, admin_headers, db_session, admin_user):
        env = _seed_priced_version(db_session, admin_user)

        config = Configuration(
            entity_version_id=env["version"].id,
            user_id=admin_user.id,
            name="Legacy Finalized",
            status=ConfigurationStatus.FINALIZED,
            is_complete=True,
            is_deleted=False,
            price_list_id=env["price_list"].id,
            price_date=dt.date.today(),
            data=[{"field_id": env["field"].id, "value": "BASIC"}],
            snapshot=None,
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(config)
        db_session.commit()

        resp = client.get(f"/configurations/{config.id}/calculate", headers=admin_headers)
        assert resp.status_code == 200
        assert Decimal(str(resp.json()["bom"]["commercial_total"])) == Decimal("20.00")
