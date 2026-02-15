"""
End-to-End Integration Tests.

Tests complete flows across multiple routers:
- Entity creation → Version → Fields → Values → Rules → Engine

These tests validate that all components work together correctly
in real-world scenarios.
"""

from fastapi.testclient import TestClient

# ============================================================
# COMPLETE ENTITY LIFECYCLE TESTS
# ============================================================


class TestCrossRouterDataConsistency:
    """Tests data consistency across router boundaries."""

    def test_engine_uses_latest_published_version(self, client: TestClient, admin_headers):
        """
        E2E: Create v1 with rule A, publish. Create v2 with rule B, publish.
        Engine should use v2 rules (and v1 should be archived).
        """
        # Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Version Switch Test", "description": "Test version switching"},
            headers=admin_headers,
        )
        entity_id = entity_resp.json()["id"]

        # Create and setup V1
        v1_resp = client.post("/versions/", json={"entity_id": entity_id, "changelog": "V1"}, headers=admin_headers)
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
                "sequence": 1,
            },
            headers=admin_headers,
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
                "sequence": 2,
            },
            headers=admin_headers,
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
                "conditions": {"criteria": [{"field_id": field_id, "operator": "GREATER_THAN", "value": 1000}]},
            },
            headers=admin_headers,
        )

        # Publish V1
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Calculate with V1 - amount 1500 should trigger mandatory
        calc_v1 = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": field_id, "value": 1500}]},
            headers=admin_headers,
        )
        assert calc_v1.status_code == 200
        v1_result = calc_v1.json()
        approval_v1 = next(f for f in v1_result["fields"] if f["field_id"] == opt_field_id)
        assert approval_v1["is_required"] is True  # V1: 1500 > 1000

        # Clone V1 to create V2
        v2_resp = client.post(
            f"/versions/{v1_id}/clone", json={"changelog": "V2 - higher threshold"}, headers=admin_headers
        )
        v2_id = v2_resp.json()["id"]

        # Get cloned fields for V2
        v2_fields = client.get(f"/fields/?entity_version_id={v2_id}", headers=admin_headers).json()
        v2_amount_field = next(f for f in v2_fields if f["name"] == "amount")
        v2_approval_field = next(f for f in v2_fields if f["name"] == "approval_needed")

        # Delete V2's rule and create new one with higher threshold
        v2_rules = client.get(f"/rules/?entity_version_id={v2_id}", headers=admin_headers).json()
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
                },
            },
            headers=admin_headers,
        )

        # Publish V2 (should archive V1)
        client.post(f"/versions/{v2_id}/publish", headers=admin_headers)

        # Verify V1 is now archived
        v1_check = client.get(f"/versions/{v1_id}", headers=admin_headers)
        assert v1_check.json()["status"] == "ARCHIVED"

        # Calculate again with same amount 1500 - should NOT trigger with V2 rules
        calc_v2 = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": v2_amount_field["id"], "value": 1500}]},
            headers=admin_headers,
        )
        assert calc_v2.status_code == 200
        v2_result = calc_v2.json()
        approval_v2 = next(f for f in v2_result["fields"] if f["field_id"] == v2_approval_field["id"])
        assert approval_v2["is_required"] is False  # V2: 1500 < 5000

    def test_clone_preserves_complete_data_structure(self, client: TestClient, admin_headers):
        """
        E2E: Clone a complex version and verify all data is preserved.
        """
        # Create Entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Clone Integrity Test", "description": "Test clone preserves data"},
            headers=admin_headers,
        )
        entity_id = entity_resp.json()["id"]

        # Create Version with complex structure
        v1_resp = client.post(
            "/versions/", json={"entity_id": entity_id, "changelog": "Complex structure"}, headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Add multiple fields
        fields_data = [
            {
                "name": "field_a",
                "label": "Field A",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1,
            },
            {
                "name": "field_b",
                "label": "Field B",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 2,
            },
            {
                "name": "field_c",
                "label": "Field C",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 3,
            },
        ]

        created_fields = []
        for field_data in fields_data:
            resp = client.post("/fields/", json={"entity_version_id": v1_id, **field_data}, headers=admin_headers)
            created_fields.append(resp.json())

        # Add values to field_a
        for val in ["OPT_1", "OPT_2", "OPT_3"]:
            client.post(
                "/values/",
                json={"field_id": created_fields[0]["id"], "value": val, "label": val, "is_default": val == "OPT_1"},
                headers=admin_headers,
            )

        # Add rules
        client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": created_fields[2]["id"],
                "rule_type": "mandatory",
                "description": "Field C mandatory if B > 100",
                "conditions": {
                    "criteria": [{"field_id": created_fields[1]["id"], "operator": "GREATER_THAN", "value": 100}]
                },
            },
            headers=admin_headers,
        )

        # Publish V1
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Clone V1
        clone_resp = client.post(f"/versions/{v1_id}/clone", json={"changelog": "Clone of V1"}, headers=admin_headers)
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
