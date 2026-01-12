"""
End-to-End Integration Tests.

Tests complete flows across multiple routers:
- Entity creation → Version → Fields → Values → Rules → Engine

These tests validate that all components work together correctly
in real-world scenarios.
"""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    FieldType, RuleType, VersionStatus
)


# ============================================================
# COMPLETE ENTITY LIFECYCLE TESTS
# ============================================================

class TestCompleteEntityLifecycle:
    """Full lifecycle test from entity creation to engine calculation."""

    def test_create_entity_through_engine_calculation(
        self, client: TestClient, admin_headers
    ):
        """
        E2E: Create entity → Create version → Add fields → Add values →
             Add rules → Publish → Calculate via Engine.

        This is the primary happy-path test for the entire system.
        """
        # Step 1: Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "E2E Test Insurance", "description": "End-to-end test entity"},
            headers=admin_headers
        )
        assert entity_resp.status_code == 201
        entity_id = entity_resp.json()["id"]

        # Step 2: Create Draft Version
        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Initial E2E version"},
            headers=admin_headers
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
                "sequence": 1
            },
            headers=admin_headers
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
                "sequence": 2
            },
            headers=admin_headers
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
                "sequence": 3
            },
            headers=admin_headers
        )
        assert field_gps_resp.status_code == 201
        field_gps_id = field_gps_resp.json()["id"]

        # Step 4: Add Values for Vehicle Type
        value_car_resp = client.post(
            "/values/",
            json={"field_id": field_type_id, "value": "CAR", "label": "Car", "is_default": True},
            headers=admin_headers
        )
        assert value_car_resp.status_code == 201

        value_moto_resp = client.post(
            "/values/",
            json={"field_id": field_type_id, "value": "MOTO", "label": "Motorcycle", "is_default": False},
            headers=admin_headers
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
                "conditions": {
                    "criteria": [
                        {"field_id": field_value_id, "operator": "GREATER_THAN", "value": 30000}
                    ]
                },
                "error_message": "GPS tracker is required for vehicles over 30000"
            },
            headers=admin_headers
        )
        assert rule_resp.status_code == 201

        # Step 6: Publish Version
        publish_resp = client.post(
            f"/versions/{version_id}/publish",
            headers=admin_headers
        )
        assert publish_resp.status_code == 200
        assert publish_resp.json()["status"] == "PUBLISHED"

        # Step 7: Calculate via Engine - Low value vehicle (GPS not required)
        calc_low_resp = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_type_id, "value": "CAR"},
                    {"field_id": field_value_id, "value": 20000}
                ]
            },
            headers=admin_headers
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
                    {"field_id": field_value_id, "value": 50000}
                ]
            },
            headers=admin_headers
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
            updated_by_id=admin_user.id
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
            sequence=1
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
                "sequence": 2
            },
            headers=admin_headers
        )
        assert add_field_resp.status_code == 409  # Conflict - version not in DRAFT

        # Clone to create new draft
        clone_resp = client.post(
            f"/versions/{version.id}/clone",
            json={"changelog": "Cloned for modifications"},
            headers=admin_headers
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
                "sequence": 2
            },
            headers=admin_headers
        )
        assert add_field_new_resp.status_code == 201


# ============================================================
# CROSS-ROUTER DATA CONSISTENCY TESTS
# ============================================================

class TestCrossRouterDataConsistency:
    """Tests data consistency across router boundaries."""

    def test_engine_uses_latest_published_version(
        self, client: TestClient, admin_headers
    ):
        """
        E2E: Create v1 with rule A, publish. Create v2 with rule B, publish.
        Engine should use v2 rules (and v1 should be archived).
        """
        # Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Version Switch Test", "description": "Test version switching"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create and setup V1
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Add field to V1
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "amount",
                "label": "Amount",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        )
        field_id = field_resp.json()["id"]

        # Add optional field for V1 rule
        opt_field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "approval_needed",
                "label": "Approval Needed",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        )
        opt_field_id = opt_field_resp.json()["id"]

        # V1 Rule: Approval needed if amount > 1000
        client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": opt_field_id,
                "rule_type": "mandatory",
                "description": "V1 Rule - threshold 1000",
                "conditions": {
                    "criteria": [{"field_id": field_id, "operator": "GREATER_THAN", "value": 1000}]
                }
            },
            headers=admin_headers
        )

        # Publish V1
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Calculate with V1 - amount 1500 should trigger mandatory
        calc_v1 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [{"field_id": field_id, "value": 1500}]
            },
            headers=admin_headers
        )
        assert calc_v1.status_code == 200
        v1_result = calc_v1.json()
        approval_v1 = next(f for f in v1_result["fields"] if f["field_id"] == opt_field_id)
        assert approval_v1["is_required"] is True  # V1: 1500 > 1000

        # Clone V1 to create V2
        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2 - higher threshold"},
            headers=admin_headers
        )
        v2_id = v2_resp.json()["id"]

        # Get cloned fields for V2
        v2_fields = client.get(
            f"/fields/?entity_version_id={v2_id}",
            headers=admin_headers
        ).json()
        v2_amount_field = next(f for f in v2_fields if f["name"] == "amount")
        v2_approval_field = next(f for f in v2_fields if f["name"] == "approval_needed")

        # Delete V2's rule and create new one with higher threshold
        v2_rules = client.get(
            f"/rules/?entity_version_id={v2_id}",
            headers=admin_headers
        ).json()
        for rule in v2_rules:
            client.delete(f"/rules/{rule['id']}", headers=admin_headers)

        # V2 Rule: Approval needed if amount > 5000 (higher threshold)
        client.post(
            "/rules/",
            json={
                "entity_version_id": v2_id,
                "target_field_id": v2_approval_field["id"],
                "rule_type": "mandatory",
                "description": "V2 Rule - threshold 5000",
                "conditions": {
                    "criteria": [{"field_id": v2_amount_field["id"], "operator": "GREATER_THAN", "value": 5000}]
                }
            },
            headers=admin_headers
        )

        # Publish V2 (should archive V1)
        client.post(f"/versions/{v2_id}/publish", headers=admin_headers)

        # Verify V1 is now archived
        v1_check = client.get(f"/versions/{v1_id}", headers=admin_headers)
        assert v1_check.json()["status"] == "ARCHIVED"

        # Calculate again with same amount 1500 - should NOT trigger with V2 rules
        calc_v2 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [{"field_id": v2_amount_field["id"], "value": 1500}]
            },
            headers=admin_headers
        )
        assert calc_v2.status_code == 200
        v2_result = calc_v2.json()
        approval_v2 = next(f for f in v2_result["fields"] if f["field_id"] == v2_approval_field["id"])
        assert approval_v2["is_required"] is False  # V2: 1500 < 5000

    def test_clone_preserves_complete_data_structure(
        self, client: TestClient, admin_headers
    ):
        """
        E2E: Clone a complex version and verify all data is preserved.
        """
        # Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Clone Integrity Test", "description": "Test clone preserves data"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create Version with complex structure
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Complex structure"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Add multiple fields
        fields_data = [
            {"name": "field_a", "label": "Field A", "data_type": "string", "is_free_value": False, "is_required": True, "sequence": 1},
            {"name": "field_b", "label": "Field B", "data_type": "number", "is_free_value": True, "is_required": True, "sequence": 2},
            {"name": "field_c", "label": "Field C", "data_type": "boolean", "is_free_value": True, "is_required": False, "sequence": 3},
        ]

        created_fields = []
        for field_data in fields_data:
            resp = client.post(
                "/fields/",
                json={"entity_version_id": v1_id, **field_data},
                headers=admin_headers
            )
            created_fields.append(resp.json())

        # Add values to field_a
        for val in ["OPT_1", "OPT_2", "OPT_3"]:
            client.post(
                "/values/",
                json={"field_id": created_fields[0]["id"], "value": val, "label": val, "is_default": val == "OPT_1"},
                headers=admin_headers
            )

        # Add rules
        client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": created_fields[2]["id"],
                "rule_type": "mandatory",
                "description": "Field C mandatory if B > 100",
                "conditions": {"criteria": [{"field_id": created_fields[1]["id"], "operator": "GREATER_THAN", "value": 100}]}
            },
            headers=admin_headers
        )

        # Publish V1
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Clone V1
        clone_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "Clone of V1"},
            headers=admin_headers
        )
        assert clone_resp.status_code == 201
        v2_id = clone_resp.json()["id"]

        # Verify cloned fields
        v2_fields = client.get(f"/fields/?entity_version_id={v2_id}", headers=admin_headers).json()
        assert len(v2_fields) == 3
        v2_field_names = {f["name"] for f in v2_fields}
        assert v2_field_names == {"field_a", "field_b", "field_c"}

        # Verify cloned values
        v2_field_a = next(f for f in v2_fields if f["name"] == "field_a")
        v2_values = client.get(f"/values/?field_id={v2_field_a['id']}", headers=admin_headers).json()
        assert len(v2_values) == 3

        # Verify cloned rules
        v2_rules = client.get(f"/rules/?entity_version_id={v2_id}", headers=admin_headers).json()
        assert len(v2_rules) == 1

        # Verify rule references new field IDs (not original)
        v2_field_b = next(f for f in v2_fields if f["name"] == "field_b")
        v2_field_c = next(f for f in v2_fields if f["name"] == "field_c")

        rule = v2_rules[0]
        assert rule["target_field_id"] == v2_field_c["id"]
        assert rule["conditions"]["criteria"][0]["field_id"] == v2_field_b["id"]


# ============================================================
# CASCADE OPERATIONS TESTS
# ============================================================

class TestCascadeOperations:
    """Tests cascade behavior across entities."""

    def test_delete_draft_version_removes_all_children(
        self, client: TestClient, admin_headers, db_session
    ):
        """
        E2E: Delete DRAFT version → Verify all fields, values deleted.
        Note: Rules require valid conditions, so we test with fields/values only.
        """
        # Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Cascade Delete Test", "description": "Test cascade delete"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create Version
        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "To be deleted"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Add field
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "test_field",
                "label": "Test Field",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        )
        field_id = field_resp.json()["id"]

        # Add value
        value_resp = client.post(
            "/values/",
            json={"field_id": field_id, "value": "TEST", "label": "Test", "is_default": True},
            headers=admin_headers
        )
        value_id = value_resp.json()["id"]

        # Verify all exist
        assert client.get(f"/fields/{field_id}", headers=admin_headers).status_code == 200
        assert client.get(f"/values/{value_id}", headers=admin_headers).status_code == 200

        # Delete version
        delete_resp = client.delete(f"/versions/{version_id}", headers=admin_headers)
        assert delete_resp.status_code == 204

        # Verify cascade delete
        assert client.get(f"/versions/{version_id}", headers=admin_headers).status_code == 404
        assert client.get(f"/fields/{field_id}", headers=admin_headers).status_code == 404
        assert client.get(f"/values/{value_id}", headers=admin_headers).status_code == 404

    def test_entity_delete_requires_versions_deleted_first(
        self, client: TestClient, admin_headers
    ):
        """
        E2E: Entity with versions cannot be deleted directly.
        Must delete versions first, then entity.
        """
        # Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Delete Order Test", "description": "Test delete order"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create version
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Add field to V1
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "field",
                "label": "Field",
                "data_type": "string",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        )
        field_id = field_resp.json()["id"]

        # Try to delete entity with version - should fail with 409
        delete_entity_resp = client.delete(f"/entities/{entity_id}", headers=admin_headers)
        assert delete_entity_resp.status_code == 409
        assert "version" in delete_entity_resp.json()["detail"].lower()

        # Entity still exists
        assert client.get(f"/entities/{entity_id}", headers=admin_headers).status_code == 200

        # Delete version first (DRAFT can be deleted)
        delete_version_resp = client.delete(f"/versions/{v1_id}", headers=admin_headers)
        assert delete_version_resp.status_code == 204

        # Now entity can be deleted
        delete_entity_resp2 = client.delete(f"/entities/{entity_id}", headers=admin_headers)
        assert delete_entity_resp2.status_code == 204

        # Verify entity is gone
        assert client.get(f"/entities/{entity_id}", headers=admin_headers).status_code == 404


# ============================================================
# ROLE-BASED ACCESS CONTROL E2E TESTS
# ============================================================

class TestRBACEndToEnd:
    """End-to-end tests for role-based access control."""

    def test_user_role_can_only_use_published_versions(
        self, client: TestClient, admin_headers, user_headers
    ):
        """
        E2E: USER role can only calculate on PUBLISHED versions.
        """
        # Admin creates entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "RBAC Test Entity", "description": "RBAC test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Draft"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Add field
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "test",
                "label": "Test",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 1
            },
            headers=admin_headers
        )
        field_id = field_resp.json()["id"]

        # USER tries to calculate on DRAFT - should fail
        calc_draft = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "entity_version_id": version_id,
                "current_state": []
            },
            headers=user_headers
        )
        assert calc_draft.status_code == 403

        # Admin publishes
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        # USER calculates on PUBLISHED - should succeed
        calc_published = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": []
            },
            headers=user_headers
        )
        assert calc_published.status_code == 200

    def test_author_can_preview_draft_via_engine(
        self, client: TestClient, admin_headers, author_headers
    ):
        """
        E2E: AUTHOR role can calculate on DRAFT versions for preview.
        """
        # Admin creates entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Author Preview Test", "description": "Author preview"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Author creates version (authors can create versions)
        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Author draft"},
            headers=author_headers
        )
        version_id = version_resp.json()["id"]

        # Author adds field
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "preview_field",
                "label": "Preview Field",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=author_headers
        )
        field_id = field_resp.json()["id"]

        # Author previews via engine
        calc_preview = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "entity_version_id": version_id,
                "current_state": [{"field_id": field_id, "value": 42}]
            },
            headers=author_headers
        )
        assert calc_preview.status_code == 200
        result = calc_preview.json()

        field_result = next(f for f in result["fields"] if f["field_id"] == field_id)
        assert field_result["current_value"] == 42


# ============================================================
# COMPLEX RULE INTERACTION TESTS
# ============================================================

class TestComplexRuleInteractions:
    """Tests for complex rule interactions across the system."""

    def test_multiple_rules_affecting_same_field(
        self, client: TestClient, admin_headers
    ):
        """
        E2E: Multiple rules (VISIBILITY + MANDATORY) on the same field.
        """
        # Create entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "Multi-Rule Test", "description": "Multiple rules"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Multi-rule version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Fields
        field_type = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "product_type",
                "label": "Product Type",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        field_value = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "product_value",
                "label": "Product Value",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        field_insurance = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "insurance",
                "label": "Insurance",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 3
            },
            headers=admin_headers
        ).json()

        # Values
        client.post("/values/", json={"field_id": field_type["id"], "value": "STANDARD", "label": "Standard", "is_default": True}, headers=admin_headers)
        client.post("/values/", json={"field_id": field_type["id"], "value": "PREMIUM", "label": "Premium", "is_default": False}, headers=admin_headers)

        # Rule 1: VISIBILITY - Insurance hidden for STANDARD products
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_insurance["id"],
                "rule_type": "visibility",
                "description": "Show insurance for premium",
                "conditions": {"criteria": [{"field_id": field_type["id"], "operator": "EQUALS", "value": "PREMIUM"}]}
            },
            headers=admin_headers
        )

        # Rule 2: MANDATORY - Insurance required if value > 10000 (only applies when visible)
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_insurance["id"],
                "rule_type": "mandatory",
                "description": "Insurance mandatory for high value",
                "conditions": {"criteria": [{"field_id": field_value["id"], "operator": "GREATER_THAN", "value": 10000}]}
            },
            headers=admin_headers
        )

        # Publish
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        # Test Case 1: STANDARD product - insurance should be hidden
        calc1 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_type["id"], "value": "STANDARD"},
                    {"field_id": field_value["id"], "value": 50000}
                ]
            },
            headers=admin_headers
        ).json()

        insurance1 = next(f for f in calc1["fields"] if f["field_id"] == field_insurance["id"])
        assert insurance1["is_hidden"] is True

        # Test Case 2: PREMIUM + low value - insurance visible but not required
        calc2 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_type["id"], "value": "PREMIUM"},
                    {"field_id": field_value["id"], "value": 5000}
                ]
            },
            headers=admin_headers
        ).json()

        insurance2 = next(f for f in calc2["fields"] if f["field_id"] == field_insurance["id"])
        assert insurance2["is_hidden"] is False
        assert insurance2["is_required"] is False

        # Test Case 3: PREMIUM + high value - insurance visible AND required
        calc3 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_type["id"], "value": "PREMIUM"},
                    {"field_id": field_value["id"], "value": 20000}
                ]
            },
            headers=admin_headers
        ).json()

        insurance3 = next(f for f in calc3["fields"] if f["field_id"] == field_insurance["id"])
        assert insurance3["is_hidden"] is False
        assert insurance3["is_required"] is True

    def test_availability_rule_filters_dropdown_options(
        self, client: TestClient, admin_headers
    ):
        """
        E2E: AVAILABILITY rule filters options in a dropdown field.
        """
        # Create entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "Availability Test", "description": "Option filtering"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Availability version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Source field (determines what options are available)
        field_category = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "category",
                "label": "Category",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        # Target field (has filtered options)
        field_plan = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "plan",
                "label": "Plan",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        # Values for category
        client.post("/values/", json={"field_id": field_category["id"], "value": "PERSONAL", "label": "Personal", "is_default": True}, headers=admin_headers)
        client.post("/values/", json={"field_id": field_category["id"], "value": "BUSINESS", "label": "Business", "is_default": False}, headers=admin_headers)

        # Values for plan
        basic_val = client.post("/values/", json={"field_id": field_plan["id"], "value": "BASIC", "label": "Basic", "is_default": True}, headers=admin_headers).json()
        pro_val = client.post("/values/", json={"field_id": field_plan["id"], "value": "PRO", "label": "Pro", "is_default": False}, headers=admin_headers).json()
        enterprise_val = client.post("/values/", json={"field_id": field_plan["id"], "value": "ENTERPRISE", "label": "Enterprise", "is_default": False}, headers=admin_headers).json()

        # AVAILABILITY rules:
        # - BASIC: only for PERSONAL
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_plan["id"],
                "target_value_id": basic_val["id"],
                "rule_type": "availability",
                "description": "Basic only for personal",
                "conditions": {"criteria": [{"field_id": field_category["id"], "operator": "EQUALS", "value": "PERSONAL"}]}
            },
            headers=admin_headers
        )

        # - ENTERPRISE: only for BUSINESS
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_plan["id"],
                "target_value_id": enterprise_val["id"],
                "rule_type": "availability",
                "description": "Enterprise only for business",
                "conditions": {"criteria": [{"field_id": field_category["id"], "operator": "EQUALS", "value": "BUSINESS"}]}
            },
            headers=admin_headers
        )

        # Publish
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        # Test PERSONAL: should have BASIC, PRO (not ENTERPRISE)
        calc_personal = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [{"field_id": field_category["id"], "value": "PERSONAL"}]
            },
            headers=admin_headers
        ).json()

        plan_personal = next(f for f in calc_personal["fields"] if f["field_id"] == field_plan["id"])
        personal_options = {o["value"] for o in plan_personal["available_options"]}
        assert "BASIC" in personal_options
        assert "PRO" in personal_options
        assert "ENTERPRISE" not in personal_options

        # Test BUSINESS: should have PRO, ENTERPRISE (not BASIC)
        calc_business = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [{"field_id": field_category["id"], "value": "BUSINESS"}]
            },
            headers=admin_headers
        ).json()

        plan_business = next(f for f in calc_business["fields"] if f["field_id"] == field_plan["id"])
        business_options = {o["value"] for o in plan_business["available_options"]}
        assert "BASIC" not in business_options
        assert "PRO" in business_options
        assert "ENTERPRISE" in business_options
