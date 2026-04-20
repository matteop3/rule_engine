"""
Integration tests for ConfigurationCustomItem lifecycle.

Covers: create DRAFT → add custom items → calculate → finalize (with
snapshot verification), snapshot immutability under DB mutation,
clone-with-fresh-keys, and upgrade preservation.
"""

from decimal import Decimal

from app.models.domain import ConfigurationCustomItem


def _add_custom_item(client, headers, config_id: str, **overrides) -> dict:
    payload = {
        "description": "Integration custom line",
        "quantity": "2",
        "unit_price": "50.00",
        "unit_of_measure": "PC",
        "sequence": 0,
    }
    payload.update(overrides)
    response = client.post(
        f"/configurations/{config_id}/custom-items/",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestEndToEndCustomItemLifecycle:
    """Create → add customs → calculate → finalize, verifying the snapshot freezes custom lines."""

    def test_finalize_snapshot_contains_custom_items(self, client, lifecycle_user_headers, draft_configuration):
        config_id = draft_configuration.id

        first = _add_custom_item(
            client,
            lifecycle_user_headers,
            config_id,
            description="Install kit",
            quantity="1",
            unit_price="120.00",
            sequence=0,
        )
        second = _add_custom_item(
            client,
            lifecycle_user_headers,
            config_id,
            description="Priority shipping",
            quantity="2",
            unit_price="35.50",
            sequence=1,
        )

        calc_response = client.get(f"/configurations/{config_id}/calculate", headers=lifecycle_user_headers)
        assert calc_response.status_code == 200
        calc_body = calc_response.json()
        assert calc_body["bom"] is not None
        commercial = calc_body["bom"]["commercial"]
        custom_lines = [line for line in commercial if line["is_custom"]]
        assert len(custom_lines) == 2
        by_key = {line["part_number"]: line for line in custom_lines}
        assert by_key[first["custom_key"]]["description"] == "Install kit"
        assert Decimal(by_key[first["custom_key"]]["line_total"]) == Decimal("120.00")
        assert by_key[second["custom_key"]]["description"] == "Priority shipping"
        assert Decimal(by_key[second["custom_key"]]["line_total"]) == Decimal("71.00")

        finalize_response = client.post(f"/configurations/{config_id}/finalize", headers=lifecycle_user_headers)
        assert finalize_response.status_code == 200
        assert finalize_response.json()["status"] == "FINALIZED"

        # Snapshot retrieval path
        read_response = client.get(f"/configurations/{config_id}/calculate", headers=lifecycle_user_headers)
        assert read_response.status_code == 200
        snapshot_body = read_response.json()
        snapshot_customs = [line for line in snapshot_body["bom"]["commercial"] if line["is_custom"]]
        assert len(snapshot_customs) == 2
        snap_by_key = {line["part_number"]: line for line in snapshot_customs}
        assert Decimal(snap_by_key[first["custom_key"]]["line_total"]) == Decimal("120.00")
        assert Decimal(snap_by_key[second["custom_key"]]["line_total"]) == Decimal("71.00")


class TestFinalizedSnapshotImmutability:
    """Mutations to the underlying custom items after finalize must not leak into the snapshot read."""

    def test_snapshot_unchanged_after_custom_item_mutated(
        self, client, db_session, lifecycle_user_headers, draft_configuration
    ):
        config_id = draft_configuration.id

        created = _add_custom_item(
            client,
            lifecycle_user_headers,
            config_id,
            description="Pre-finalize value",
            quantity="1",
            unit_price="100.00",
        )

        finalize_response = client.post(f"/configurations/{config_id}/finalize", headers=lifecycle_user_headers)
        assert finalize_response.status_code == 200

        # Bypass the API to mutate the row directly (FINALIZED gating blocks API writes)
        row = (
            db_session.query(ConfigurationCustomItem)
            .filter(ConfigurationCustomItem.configuration_id == config_id)
            .one()
        )
        row.description = "Post-finalize mutation"
        row.unit_price = Decimal("999.99")
        db_session.commit()

        read_response = client.get(f"/configurations/{config_id}/calculate", headers=lifecycle_user_headers)
        assert read_response.status_code == 200
        customs = [line for line in read_response.json()["bom"]["commercial"] if line["is_custom"]]
        assert len(customs) == 1
        assert customs[0]["part_number"] == created["custom_key"]
        assert customs[0]["description"] == "Pre-finalize value"
        assert Decimal(customs[0]["unit_price"]) == Decimal("100.00")

    def test_snapshot_unchanged_after_custom_item_deleted(
        self, client, db_session, lifecycle_user_headers, draft_configuration
    ):
        config_id = draft_configuration.id

        _add_custom_item(client, lifecycle_user_headers, config_id, description="To be deleted")

        finalize_response = client.post(f"/configurations/{config_id}/finalize", headers=lifecycle_user_headers)
        assert finalize_response.status_code == 200

        db_session.query(ConfigurationCustomItem).filter(ConfigurationCustomItem.configuration_id == config_id).delete()
        db_session.commit()

        read_response = client.get(f"/configurations/{config_id}/calculate", headers=lifecycle_user_headers)
        assert read_response.status_code == 200
        customs = [line for line in read_response.json()["bom"]["commercial"] if line["is_custom"]]
        assert len(customs) == 1
        assert customs[0]["description"] == "To be deleted"


class TestCloneCopiesCustomItemsWithFreshKeys:
    """Cloning copies custom items with brand-new ``custom_key`` values."""

    def test_clone_finalized_preserves_values_but_renews_keys(
        self, client, db_session, lifecycle_user_headers, draft_configuration
    ):
        source_id = draft_configuration.id

        first = _add_custom_item(
            client,
            lifecycle_user_headers,
            source_id,
            description="Onsite install",
            quantity="1",
            unit_price="75.00",
            sequence=0,
        )
        second = _add_custom_item(
            client,
            lifecycle_user_headers,
            source_id,
            description="Rush delivery",
            quantity="1",
            unit_price="40.00",
            sequence=1,
        )
        source_keys = {first["custom_key"], second["custom_key"]}

        finalize_response = client.post(f"/configurations/{source_id}/finalize", headers=lifecycle_user_headers)
        assert finalize_response.status_code == 200

        clone_response = client.post(f"/configurations/{source_id}/clone", headers=lifecycle_user_headers)
        assert clone_response.status_code == 201
        clone_id = clone_response.json()["id"]
        assert clone_response.json()["status"] == "DRAFT"
        assert clone_response.json()["source_id"] == source_id

        clone_items = client.get(f"/configurations/{clone_id}/custom-items/", headers=lifecycle_user_headers)
        assert clone_items.status_code == 200
        clone_rows = clone_items.json()
        assert len(clone_rows) == 2
        clone_keys = {row["custom_key"] for row in clone_rows}
        # Keys must be disjoint between source and clone
        assert source_keys.isdisjoint(clone_keys)
        # But content fields are preserved
        by_description = {row["description"]: row for row in clone_rows}
        assert Decimal(by_description["Onsite install"]["unit_price"]) == Decimal("75.00")
        assert Decimal(by_description["Rush delivery"]["unit_price"]) == Decimal("40.00")
        assert by_description["Onsite install"]["sequence"] == 0
        assert by_description["Rush delivery"]["sequence"] == 1

        # The source snapshot is still intact after the clone
        source_read = client.get(f"/configurations/{source_id}/calculate", headers=lifecycle_user_headers)
        assert source_read.status_code == 200
        source_customs = [line for line in source_read.json()["bom"]["commercial"] if line["is_custom"]]
        assert {line["part_number"] for line in source_customs} == source_keys


class TestUpgradePreservesCustomItems:
    """Upgrading a DRAFT to a newer version leaves custom items untouched."""

    def test_custom_items_survive_upgrade(
        self,
        client,
        db_session,
        lifecycle_user_headers,
        configuration_on_archived_version,
        multi_version_entity,
    ):
        config_id = configuration_on_archived_version.id
        published_version = multi_version_entity["published_version"]

        created = _add_custom_item(
            client,
            lifecycle_user_headers,
            config_id,
            description="Legacy-era custom line",
            quantity="3",
            unit_price="20.00",
        )

        upgrade_response = client.post(f"/configurations/{config_id}/upgrade", headers=lifecycle_user_headers)
        assert upgrade_response.status_code == 200
        assert upgrade_response.json()["entity_version_id"] == published_version.id

        after = client.get(f"/configurations/{config_id}/custom-items/", headers=lifecycle_user_headers)
        assert after.status_code == 200
        rows = after.json()
        assert len(rows) == 1
        assert rows[0]["custom_key"] == created["custom_key"]
        assert rows[0]["description"] == "Legacy-era custom line"
        assert Decimal(rows[0]["unit_price"]) == Decimal("20.00")
