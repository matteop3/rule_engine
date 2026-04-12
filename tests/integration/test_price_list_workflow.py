"""
End-to-end integration tests for the Price List feature.

Covers HTTP-level workflows:
- Create price list → add items → build entity with BOM → calculate → verify prices
- Temporal pricing: same part, different periods, different dates
- Config lifecycle with price list: finalize snapshot → clone inheritance → upgrade
- Delete a price list while a DRAFT config references it (FK SET NULL)
"""

import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Configuration, PriceList


@pytest.fixture(scope="function")
def workflow_price_list(db_session):
    pl = PriceList(
        name="Integration Workflow PL",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(pl)
    db_session.commit()
    db_session.refresh(pl)
    return pl


def _build_priced_entity(client: TestClient, headers, price_list_id: int):
    """Create entity + version with a simple COMMERCIAL BOM, publish it, and seed prices."""
    entity_id = client.post(
        "/entities/",
        json={"name": "Priced Entity", "description": "pricing workflow"},
        headers=headers,
    ).json()["id"]

    version_id = client.post(
        "/versions/",
        json={"entity_id": entity_id, "changelog": "initial"},
        headers=headers,
    ).json()["id"]

    field_id = client.post(
        "/fields/",
        json={
            "entity_version_id": version_id,
            "name": "qty",
            "label": "Qty",
            "data_type": "number",
            "is_free_value": True,
            "is_required": False,
            "sequence": 1,
        },
        headers=headers,
    ).json()["id"]

    for pn, qty, seq in [("WIDGET-A", "2", 1), ("WIDGET-B", "3", 2)]:
        resp = client.post(
            "/bom-items/",
            json={
                "entity_version_id": version_id,
                "bom_type": "COMMERCIAL",
                "part_number": pn,
                "quantity": qty,
                "sequence": seq,
            },
            headers=headers,
        )
        assert resp.status_code == 201

    publish = client.post(f"/versions/{version_id}/publish", headers=headers)
    assert publish.status_code == 200

    for pn, price in [("WIDGET-A", "10.00"), ("WIDGET-B", "5.00")]:
        resp = client.post(
            "/price-list-items/",
            json={"price_list_id": price_list_id, "part_number": pn, "unit_price": price},
            headers=headers,
        )
        assert resp.status_code == 201

    return {"entity_id": entity_id, "version_id": version_id, "field_id": field_id}


class TestEndToEndPricing:
    """Full HTTP pipeline: price list → items → entity/BOM → calculate."""

    def test_create_price_list_then_calculate(self, client: TestClient, admin_headers, workflow_price_list):
        env = _build_priced_entity(client, admin_headers, workflow_price_list.id)

        resp = client.post(
            "/engine/calculate",
            json={
                "entity_id": env["entity_id"],
                "price_list_id": workflow_price_list.id,
                "current_state": [],
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        bom = resp.json()["bom"]
        # 2*10 + 3*5 = 35
        assert Decimal(str(bom["commercial_total"])) == Decimal("35.00")
        by_part = {i["part_number"]: i for i in bom["commercial"]}
        assert Decimal(str(by_part["WIDGET-A"]["unit_price"])) == Decimal("10.00")
        assert Decimal(str(by_part["WIDGET-B"]["line_total"])) == Decimal("15.00")
        assert bom["warnings"] == []


class TestTemporalPricing:
    """Two price periods for the same part return the correct price at each date."""

    def test_temporal_price_resolution(self, client: TestClient, admin_headers, db_session):
        pl = PriceList(
            name="Temporal Workflow PL",
            valid_from=dt.date(2024, 1, 1),
            valid_to=dt.date(2030, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()
        db_session.refresh(pl)

        env = _build_priced_entity(client, admin_headers, pl.id)

        # Delete the seeded flat WIDGET-A price and replace with two temporal rows
        list_resp = client.get(f"/price-list-items/?price_list_id={pl.id}", headers=admin_headers)
        for item in list_resp.json():
            if item["part_number"] == "WIDGET-A":
                client.delete(f"/price-list-items/{item['id']}", headers=admin_headers)

        for vf, vt, price in [
            ("2025-01-01", "2025-12-31", "10.00"),
            ("2026-01-01", "2026-12-31", "12.00"),
        ]:
            r = client.post(
                "/price-list-items/",
                json={
                    "price_list_id": pl.id,
                    "part_number": "WIDGET-A",
                    "unit_price": price,
                    "valid_from": vf,
                    "valid_to": vt,
                },
                headers=admin_headers,
            )
            assert r.status_code == 201

        def price_at(date_str):
            resp = client.post(
                "/engine/calculate",
                json={
                    "entity_id": env["entity_id"],
                    "price_list_id": pl.id,
                    "price_date": date_str,
                    "current_state": [],
                },
                headers=admin_headers,
            )
            assert resp.status_code == 200
            by_part = {i["part_number"]: i for i in resp.json()["bom"]["commercial"]}
            return Decimal(str(by_part["WIDGET-A"]["unit_price"]))

        assert price_at("2025-06-01") == Decimal("10.00")
        assert price_at("2026-06-01") == Decimal("12.00")


class TestConfigLifecycleWithPricing:
    """Create config → finalize snapshot → clone inherits → modifying price list does not affect finalized."""

    def test_finalize_snapshot_survives_price_changes(self, client: TestClient, admin_headers, workflow_price_list):
        env = _build_priced_entity(client, admin_headers, workflow_price_list.id)

        create_resp = client.post(
            "/configurations/",
            json={
                "entity_version_id": env["version_id"],
                "name": "Config With Pricing",
                "price_list_id": workflow_price_list.id,
                "data": [],
            },
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]
        assert Decimal(str(create_resp.json()["bom_total_price"])) == Decimal("35.00")

        finalize_resp = client.post(f"/configurations/{config_id}/finalize", headers=admin_headers)
        assert finalize_resp.status_code == 200
        assert finalize_resp.json()["status"] == "FINALIZED"
        assert Decimal(str(finalize_resp.json()["bom_total_price"])) == Decimal("35.00")

        # Mutate price list after finalization — snapshot must be immune.
        items = client.get(
            f"/price-list-items/?price_list_id={workflow_price_list.id}",
            headers=admin_headers,
        ).json()
        widget_a = next(i for i in items if i["part_number"] == "WIDGET-A")
        patch = client.patch(
            f"/price-list-items/{widget_a['id']}",
            json={"unit_price": "999.00"},
            headers=admin_headers,
        )
        assert patch.status_code == 200

        calc_resp = client.get(f"/configurations/{config_id}/calculate", headers=admin_headers)
        assert calc_resp.status_code == 200
        # Snapshot still reflects the original 35.00
        assert Decimal(str(calc_resp.json()["bom"]["commercial_total"])) == Decimal("35.00")

    def test_clone_inherits_price_list_id(self, client: TestClient, admin_headers, workflow_price_list):
        env = _build_priced_entity(client, admin_headers, workflow_price_list.id)

        create_resp = client.post(
            "/configurations/",
            json={
                "entity_version_id": env["version_id"],
                "name": "Cloneable",
                "price_list_id": workflow_price_list.id,
                "data": [],
            },
            headers=admin_headers,
        )
        source_id = create_resp.json()["id"]

        client.post(f"/configurations/{source_id}/finalize", headers=admin_headers)

        clone_resp = client.post(f"/configurations/{source_id}/clone", headers=admin_headers)
        assert clone_resp.status_code == 201
        assert clone_resp.json()["status"] == "DRAFT"
        assert clone_resp.json()["price_list_id"] == workflow_price_list.id
        assert Decimal(str(clone_resp.json()["bom_total_price"])) == Decimal("35.00")


class TestDeletePriceListSetsNullOnDrafts:
    """Deleting a price list unreferenced by FINALIZED configs nulls price_list_id on DRAFTs."""

    def test_delete_nulls_draft_reference(self, client: TestClient, admin_headers, db_session):
        pl = PriceList(
            name="Deletable Workflow PL",
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()
        db_session.refresh(pl)
        pl_id = pl.id

        env = _build_priced_entity(client, admin_headers, pl_id)

        create_resp = client.post(
            "/configurations/",
            json={
                "entity_version_id": env["version_id"],
                "name": "Draft With PL",
                "price_list_id": pl_id,
                "data": [],
            },
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]

        delete_resp = client.delete(f"/price-lists/{pl_id}", headers=admin_headers)
        assert delete_resp.status_code == 204

        db_session.expire_all()
        config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
        assert config is not None
        assert config.price_list_id is None
