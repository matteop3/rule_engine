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

    def test_calculation_rule_full_workflow(
        self, client: TestClient, admin_headers
    ):
        """
        E2E: CALCULATION rule forces value and makes field readonly.
        Create entity → fields → values → CALCULATION rule → publish → calculate.
        """
        # Create entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "Calculation E2E", "description": "CALCULATION workflow"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Calculation version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Source field (dropdown trigger)
        field_tier = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "tier",
                "label": "Tier",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        # Target field (non-free, will be calculated)
        field_sla = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "sla",
                "label": "SLA",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        # Free-value target field (will also be calculated)
        field_notes = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "auto_notes",
                "label": "Auto Notes",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 3
            },
            headers=admin_headers
        ).json()

        # Values for tier
        client.post("/values/", json={"field_id": field_tier["id"], "value": "BASIC", "label": "Basic", "is_default": True}, headers=admin_headers)
        client.post("/values/", json={"field_id": field_tier["id"], "value": "ENTERPRISE", "label": "Enterprise", "is_default": False}, headers=admin_headers)

        # Values for sla
        client.post("/values/", json={"field_id": field_sla["id"], "value": "STANDARD", "label": "Standard", "is_default": True}, headers=admin_headers)
        client.post("/values/", json={"field_id": field_sla["id"], "value": "PRIORITY", "label": "Priority", "is_default": False}, headers=admin_headers)

        # CALCULATION rule: ENTERPRISE tier → SLA forced to PRIORITY
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_sla["id"],
                "rule_type": "calculation",
                "description": "Enterprise gets priority SLA",
                "set_value": "PRIORITY",
                "conditions": {"criteria": [{"field_id": field_tier["id"], "operator": "EQUALS", "value": "ENTERPRISE"}]}
            },
            headers=admin_headers
        )

        # CALCULATION rule on free field: ENTERPRISE → auto_notes forced
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_notes["id"],
                "rule_type": "calculation",
                "description": "Enterprise gets auto note",
                "set_value": "Enterprise customer - priority handling",
                "conditions": {"criteria": [{"field_id": field_tier["id"], "operator": "EQUALS", "value": "ENTERPRISE"}]}
            },
            headers=admin_headers
        )

        # Publish
        pub_resp = client.post(f"/versions/{version_id}/publish", headers=admin_headers)
        assert pub_resp.status_code == 200

        # Test Case 1: ENTERPRISE → both fields calculated
        calc1 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_tier["id"], "value": "ENTERPRISE"}
                ]
            },
            headers=admin_headers
        ).json()

        sla1 = next(f for f in calc1["fields"] if f["field_id"] == field_sla["id"])
        assert sla1["current_value"] == "PRIORITY"
        assert sla1["is_readonly"] is True
        assert len(sla1["available_options"]) == 1
        assert sla1["available_options"][0]["value"] == "PRIORITY"

        notes1 = next(f for f in calc1["fields"] if f["field_id"] == field_notes["id"])
        assert notes1["current_value"] == "Enterprise customer - priority handling"
        assert notes1["is_readonly"] is True
        assert notes1["available_options"] == []

        # Test Case 2: BASIC → no calculation fires, user-controlled
        calc2 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_tier["id"], "value": "BASIC"},
                    {"field_id": field_sla["id"], "value": "STANDARD"}
                ]
            },
            headers=admin_headers
        ).json()

        sla2 = next(f for f in calc2["fields"] if f["field_id"] == field_sla["id"])
        assert sla2["current_value"] == "STANDARD"
        assert sla2["is_readonly"] is False
        assert len(sla2["available_options"]) == 2  # Both options available

        notes2 = next(f for f in calc2["fields"] if f["field_id"] == field_notes["id"])
        assert notes2["current_value"] is None
        assert notes2["is_readonly"] is False
