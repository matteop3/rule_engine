"""
End-to-End Integration Tests.

Tests complete flows across multiple routers:
- Entity creation → Version → Fields → Values → Rules → Engine

These tests validate that all components work together correctly
in real-world scenarios.
"""

from fastapi.testclient import TestClient

from app.models.domain import EntityVersion, Field, FieldType, VersionStatus

# ============================================================
# COMPLETE ENTITY LIFECYCLE TESTS
# ============================================================


class TestCompleteEntityLifecycle:
    """Full lifecycle test from entity creation to engine calculation."""

    def test_create_entity_through_engine_calculation(self, client: TestClient, admin_headers):
        """
        E2E: Create entity → Create version → Add fields → Add values →
             Add rules → Publish → Calculate via Engine.

        This is the primary happy-path test for the entire system.
        """
        # Step 1: Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "E2E Test Insurance", "description": "End-to-end test entity"},
            headers=admin_headers,
        )
        assert entity_resp.status_code == 201
        entity_id = entity_resp.json()["id"]

        # Step 2: Create Draft Version
        version_resp = client.post(
            "/versions/", json={"entity_id": entity_id, "changelog": "Initial E2E version"}, headers=admin_headers
        )
        assert version_resp.status_code == 201
        version_id = version_resp.json()["id"]
        assert version_resp.json()["status"] == "DRAFT"

        # Step 3: Add Fields
        # Field 1: Vehicle Type (dropdown)
        field_type_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "vehicle_type",
                "label": "Vehicle Type",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1,
            },
            headers=admin_headers,
        )
        assert field_type_resp.status_code == 201
        field_type_id = field_type_resp.json()["id"]

        # Field 2: Vehicle Value (free number)
        field_value_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "vehicle_value",
                "label": "Vehicle Value",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 2,
            },
            headers=admin_headers,
        )
        assert field_value_resp.status_code == 201
        field_value_id = field_value_resp.json()["id"]

        # Field 3: Has GPS (boolean, optional but becomes mandatory based on rule)
        field_gps_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "has_gps",
                "label": "Has GPS Tracker",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 3,
            },
            headers=admin_headers,
        )
        assert field_gps_resp.status_code == 201
        field_gps_id = field_gps_resp.json()["id"]

        # Step 4: Add Values for Vehicle Type
        value_car_resp = client.post(
            "/values/",
            json={"field_id": field_type_id, "value": "CAR", "label": "Car", "is_default": True},
            headers=admin_headers,
        )
        assert value_car_resp.status_code == 201

        value_moto_resp = client.post(
            "/values/",
            json={"field_id": field_type_id, "value": "MOTO", "label": "Motorcycle", "is_default": False},
            headers=admin_headers,
        )
        assert value_moto_resp.status_code == 201

        # Step 5: Add Rules
        # MANDATORY rule: GPS required if value > 30000
        rule_resp = client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_gps_id,
                "rule_type": "mandatory",
                "description": "GPS mandatory for high-value vehicles",
                "conditions": {"criteria": [{"field_id": field_value_id, "operator": "GREATER_THAN", "value": 30000}]},
            },
            headers=admin_headers,
        )
        assert rule_resp.status_code == 201

        # Step 6: Publish Version
        publish_resp = client.post(f"/versions/{version_id}/publish", headers=admin_headers)
        assert publish_resp.status_code == 200
        assert publish_resp.json()["status"] == "PUBLISHED"

        # Step 7: Calculate via Engine - Low value vehicle (GPS not required)
        calc_low_resp = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_type_id, "value": "CAR"},
                    {"field_id": field_value_id, "value": 20000},
                ],
            },
            headers=admin_headers,
        )
        assert calc_low_resp.status_code == 200
        low_result = calc_low_resp.json()

        gps_field_low = next(f for f in low_result["fields"] if f["field_id"] == field_gps_id)
        assert gps_field_low["is_required"] is False  # GPS not required for low value

        # Step 8: Calculate via Engine - High value vehicle (GPS required)
        calc_high_resp = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_type_id, "value": "CAR"},
                    {"field_id": field_value_id, "value": 50000},
                ],
            },
            headers=admin_headers,
        )
        assert calc_high_resp.status_code == 200
        high_result = calc_high_resp.json()

        gps_field_high = next(f for f in high_result["fields"] if f["field_id"] == field_gps_id)
        assert gps_field_high["is_required"] is True  # GPS required for high value

    def test_modify_published_requires_new_draft(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        E2E: After publish, modifications require creating a new draft via clone.
        """
        # Create and publish a version
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Published version",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(version)
        db_session.flush()

        field = Field(
            entity_version_id=version.id,
            name="original_field",
            label="Original Field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=1,
        )
        db_session.add(field)
        db_session.commit()

        # Try to add a new field to PUBLISHED version - should fail
        add_field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version.id,
                "name": "new_field",
                "label": "New Field",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2,
            },
            headers=admin_headers,
        )
        assert add_field_resp.status_code == 409  # Conflict - version not in DRAFT

        # Clone to create new draft
        clone_resp = client.post(
            f"/versions/{version.id}/clone", json={"changelog": "Cloned for modifications"}, headers=admin_headers
        )
        assert clone_resp.status_code == 201
        new_version_id = clone_resp.json()["id"]
        assert clone_resp.json()["status"] == "DRAFT"

        # Now we can add field to the new DRAFT version
        add_field_new_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": new_version_id,
                "name": "new_field",
                "label": "New Field",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2,
            },
            headers=admin_headers,
        )
        assert add_field_new_resp.status_code == 201


# ============================================================
# CROSS-ROUTER DATA CONSISTENCY TESTS
# ============================================================
