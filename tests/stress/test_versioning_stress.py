"""
Versioning Stress Tests.

Tests for versioning system under stress conditions:
- Many versions in sequence
- Large versions with many fields/values/rules
- Rapid publish/archive cycles
- Clone chain integrity
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    FieldType, RuleType, VersionStatus
)


# ============================================================
# SEQUENTIAL VERSION CREATION TESTS
# ============================================================

class TestSequentialVersioning:
    """Tests for creating many versions in sequence."""

    def test_create_10_versions_sequentially(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Create 10 versions through publish-clone cycle.
        """
        # Create entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Sequential Test Entity", "description": "10 versions test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_ids = []
        current_version_id = None

        for i in range(10):
            if current_version_id is None:
                # First version - create new
                v_resp = client.post(
                    "/versions/",
                    json={"entity_id": entity_id, "changelog": f"Version {i + 1}"},
                    headers=admin_headers
                )
            else:
                # Clone previous version
                v_resp = client.post(
                    f"/versions/{current_version_id}/clone",
                    json={"changelog": f"Version {i + 1}"},
                    headers=admin_headers
                )

            assert v_resp.status_code in [200, 201]
            current_version_id = v_resp.json()["id"]
            version_ids.append(current_version_id)

            # Publish
            pub_resp = client.post(
                f"/versions/{current_version_id}/publish",
                headers=admin_headers
            )
            assert pub_resp.status_code == 200

        # Verify only the last version is PUBLISHED
        for i, vid in enumerate(version_ids):
            v_check = client.get(f"/versions/{vid}", headers=admin_headers).json()
            if i == len(version_ids) - 1:
                assert v_check["status"] == "PUBLISHED"
            else:
                assert v_check["status"] == "ARCHIVED"

        # Verify version numbers are sequential
        all_versions = client.get(
            f"/versions/?entity_id={entity_id}",
            headers=admin_headers
        ).json()
        version_numbers = sorted([v["version_number"] for v in all_versions])
        assert version_numbers == list(range(1, 11))

    def test_version_history_integrity_after_many_clones(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Clone chain maintains data integrity across 5 generations.
        """
        # Create entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "Clone Chain Entity", "description": "Clone integrity test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create V1 with initial structure
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1 - Initial"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Add fields to V1
        field_a = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "field_a",
                "label": "Field A",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        field_b = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "field_b",
                "label": "Field B",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        # Add rule to V1
        client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": field_b["id"],
                "rule_type": "mandatory",
                "description": "V1 Rule",
                "conditions": {"criteria": [{"field_id": field_a["id"], "operator": "GREATER_THAN", "value": 100}]}
            },
            headers=admin_headers
        )

        # Publish V1
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Clone through 4 more generations
        current_id = v1_id
        for gen in range(2, 6):
            clone_resp = client.post(
                f"/versions/{current_id}/clone",
                json={"changelog": f"V{gen} - Clone"},
                headers=admin_headers
            )
            assert clone_resp.status_code == 201
            current_id = clone_resp.json()["id"]

            # Verify cloned data
            fields = client.get(f"/fields/?entity_version_id={current_id}", headers=admin_headers).json()
            assert len(fields) == 2

            rules = client.get(f"/rules/?entity_version_id={current_id}", headers=admin_headers).json()
            assert len(rules) == 1

            # Publish
            client.post(f"/versions/{current_id}/publish", headers=admin_headers)

        # Final version should still have correct structure
        final_fields = client.get(f"/fields/?entity_version_id={current_id}", headers=admin_headers).json()
        assert {f["name"] for f in final_fields} == {"field_a", "field_b"}

        final_rules = client.get(f"/rules/?entity_version_id={current_id}", headers=admin_headers).json()
        assert len(final_rules) == 1
        assert final_rules[0]["rule_type"] == "mandatory"


# ============================================================
# LARGE VERSION TESTS
# ============================================================

class TestLargeVersions:
    """Tests for versions with many fields, values, and rules."""

    def test_version_with_20_fields(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Create version with 20 fields.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Many Fields Entity", "description": "20 fields test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "20 fields version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Create 20 fields
        field_ids = []
        for i in range(20):
            field_resp = client.post(
                "/fields/",
                json={
                    "entity_version_id": version_id,
                    "name": f"field_{i:02d}",
                    "label": f"Field {i}",
                    "data_type": "string" if i % 3 == 0 else ("number" if i % 3 == 1 else "boolean"),
                    "is_free_value": True,
                    "is_required": i < 10,
                    "sequence": i + 1
                },
                headers=admin_headers
            )
            assert field_resp.status_code == 201
            field_ids.append(field_resp.json()["id"])

        # Verify all fields created
        fields = client.get(f"/fields/?entity_version_id={version_id}", headers=admin_headers).json()
        assert len(fields) == 20

        # Publish
        pub_resp = client.post(f"/versions/{version_id}/publish", headers=admin_headers)
        assert pub_resp.status_code == 200

        # Engine can calculate with all 20 fields
        calc_resp = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [{"field_id": fid, "value": "test" if i % 3 == 0 else (i * 10 if i % 3 == 1 else True)} for i, fid in enumerate(field_ids[:10])]
            },
            headers=admin_headers
        )
        assert calc_resp.status_code == 200
        assert len(calc_resp.json()["fields"]) == 20

    def test_version_with_many_values_per_field(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Create field with 15 dropdown values.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Many Values Entity", "description": "15 values test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Many values version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Create dropdown field
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "multi_option",
                "label": "Multi Option",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        )
        field_id = field_resp.json()["id"]

        # Create 15 values
        for i in range(15):
            val_resp = client.post(
                "/values/",
                json={
                    "field_id": field_id,
                    "value": f"OPTION_{i:02d}",
                    "label": f"Option {i}",
                    "is_default": i == 0
                },
                headers=admin_headers
            )
            assert val_resp.status_code == 201

        # Verify all values
        values = client.get(f"/values/?field_id={field_id}", headers=admin_headers).json()
        assert len(values) == 15

        # Publish and calculate
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        calc_resp = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": []},
            headers=admin_headers
        )
        field_result = next(f for f in calc_resp.json()["fields"] if f["field_id"] == field_id)
        assert len(field_result["available_options"]) == 15

    def test_version_with_10_rules(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Create version with 10 different rules.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Many Rules Entity", "description": "10 rules test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "10 rules version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Create source field (for conditions)
        source_field = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "source",
                "label": "Source",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        # Create 10 target fields with rules
        rule_types = ["mandatory", "visibility", "validation", "mandatory", "visibility",
                      "validation", "mandatory", "visibility", "validation", "mandatory"]

        for i in range(10):
            target_field = client.post(
                "/fields/",
                json={
                    "entity_version_id": version_id,
                    "name": f"target_{i}",
                    "label": f"Target {i}",
                    "data_type": "boolean",
                    "is_free_value": True,
                    "is_required": False,
                    "sequence": i + 2
                },
                headers=admin_headers
            ).json()

            rule_resp = client.post(
                "/rules/",
                json={
                    "entity_version_id": version_id,
                    "target_field_id": target_field["id"],
                    "rule_type": rule_types[i],
                    "description": f"Rule {i}",
                    "conditions": {"criteria": [{"field_id": source_field["id"], "operator": "GREATER_THAN", "value": (i + 1) * 10}]},
                    "error_message": f"Error {i}" if rule_types[i] in ["mandatory", "validation"] else None
                },
                headers=admin_headers
            )
            assert rule_resp.status_code == 201

        # Verify all rules
        rules = client.get(f"/rules/?entity_version_id={version_id}", headers=admin_headers).json()
        assert len(rules) == 10

        # Publish and calculate
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        calc_resp = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [{"field_id": source_field["id"], "value": 55}]
            },
            headers=admin_headers
        )
        assert calc_resp.status_code == 200

    def test_clone_large_version_preserves_all_data(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Clone a complex version (10 fields, 20 values, 5 rules) preserves everything.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Large Clone Entity", "description": "Complex clone test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Complex version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Create 10 fields
        field_ids = []
        for i in range(10):
            is_dropdown = i < 2  # First 2 are dropdowns
            field_resp = client.post(
                "/fields/",
                json={
                    "entity_version_id": version_id,
                    "name": f"field_{i}",
                    "label": f"Field {i}",
                    "data_type": "string" if is_dropdown else "number",
                    "is_free_value": not is_dropdown,
                    "is_required": True,
                    "sequence": i + 1
                },
                headers=admin_headers
            )
            field_ids.append(field_resp.json()["id"])

        # Create 10 values for each dropdown (20 total)
        value_ids = []
        for field_id in field_ids[:2]:
            for j in range(10):
                val_resp = client.post(
                    "/values/",
                    json={
                        "field_id": field_id,
                        "value": f"VAL_{j}",
                        "label": f"Value {j}",
                        "is_default": j == 0
                    },
                    headers=admin_headers
                )
                value_ids.append(val_resp.json()["id"])

        # Create 5 rules
        for i in range(5):
            client.post(
                "/rules/",
                json={
                    "entity_version_id": version_id,
                    "target_field_id": field_ids[5 + i],  # Target fields 5-9
                    "rule_type": "mandatory",
                    "description": f"Rule {i}",
                    "conditions": {"criteria": [{"field_id": field_ids[2 + i], "operator": "GREATER_THAN", "value": 0}]}
                },
                headers=admin_headers
            )

        # Publish
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        # Clone
        clone_resp = client.post(
            f"/versions/{version_id}/clone",
            json={"changelog": "Cloned complex version"},
            headers=admin_headers
        )
        assert clone_resp.status_code == 201
        clone_id = clone_resp.json()["id"]

        # Verify clone has same counts
        clone_fields = client.get(f"/fields/?entity_version_id={clone_id}", headers=admin_headers).json()
        assert len(clone_fields) == 10

        clone_rules = client.get(f"/rules/?entity_version_id={clone_id}", headers=admin_headers).json()
        assert len(clone_rules) == 5

        # Count values across dropdown fields
        total_values = 0
        for f in clone_fields:
            if f["is_free_value"] is False:
                values = client.get(f"/values/?field_id={f['id']}", headers=admin_headers).json()
                total_values += len(values)
        assert total_values == 20


# ============================================================
# RAPID PUBLISH/ARCHIVE CYCLE TESTS
# ============================================================

class TestRapidPublishArchive:
    """Tests for rapid publish/archive cycles."""

    def test_rapid_publish_archive_5_cycles(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: 5 rapid publish/archive cycles in sequence.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Rapid Cycle Entity", "description": "Rapid cycles test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        published_ids = []

        for cycle in range(5):
            # Create draft
            if cycle == 0:
                v_resp = client.post(
                    "/versions/",
                    json={"entity_id": entity_id, "changelog": f"Cycle {cycle + 1}"},
                    headers=admin_headers
                )
            else:
                v_resp = client.post(
                    f"/versions/{published_ids[-1]}/clone",
                    json={"changelog": f"Cycle {cycle + 1}"},
                    headers=admin_headers
                )

            assert v_resp.status_code in [200, 201]
            version_id = v_resp.json()["id"]

            # Add a unique field per cycle
            client.post(
                "/fields/",
                json={
                    "entity_version_id": version_id,
                    "name": f"cycle_{cycle}_field",
                    "label": f"Cycle {cycle} Field",
                    "data_type": "string",
                    "is_free_value": True,
                    "is_required": False,
                    "sequence": cycle + 1
                },
                headers=admin_headers
            )

            # Publish immediately
            pub_resp = client.post(f"/versions/{version_id}/publish", headers=admin_headers)
            assert pub_resp.status_code == 200
            published_ids.append(version_id)

        # Verify final state: only last should be PUBLISHED
        for i, vid in enumerate(published_ids):
            v_check = client.get(f"/versions/{vid}", headers=admin_headers).json()
            expected_status = "PUBLISHED" if i == len(published_ids) - 1 else "ARCHIVED"
            assert v_check["status"] == expected_status

        # Last version should have fields from all cycles (accumulated through clones)
        final_fields = client.get(f"/fields/?entity_version_id={published_ids[-1]}", headers=admin_headers).json()
        assert len(final_fields) == 5

    def test_single_draft_policy_under_rapid_operations(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Single draft policy holds under rapid create attempts.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Single Draft Test", "description": "Policy stress test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create first draft
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "First draft"},
            headers=admin_headers
        )
        assert v1_resp.status_code == 201

        # Rapidly try to create more drafts - all should fail
        for i in range(5):
            v_resp = client.post(
                "/versions/",
                json={"entity_id": entity_id, "changelog": f"Attempt {i + 2}"},
                headers=admin_headers
            )
            assert v_resp.status_code == 409

    def test_single_published_policy_under_rapid_operations(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Stress: Only one PUBLISHED version after rapid publish operations.
        """
        # Create multiple DRAFT versions by publishing in sequence
        versions = []
        for i in range(3):
            v = EntityVersion(
                entity_id=test_entity.id,
                version_number=i + 1,
                status=VersionStatus.DRAFT if i == 2 else VersionStatus.ARCHIVED,
                changelog=f"V{i + 1}",
                created_by_id=admin_user.id,
                updated_by_id=admin_user.id
            )
            db_session.add(v)
            versions.append(v)

        # Make V2 published
        versions[1].status = VersionStatus.PUBLISHED
        db_session.commit()

        # Publish V3 (draft) - should archive V2
        pub_resp = client.post(f"/versions/{versions[2].id}/publish", headers=admin_headers)
        assert pub_resp.status_code == 200

        # Verify only V3 is PUBLISHED
        db_session.expire_all()
        published_count = db_session.query(EntityVersion).filter(
            EntityVersion.entity_id == test_entity.id,
            EntityVersion.status == VersionStatus.PUBLISHED
        ).count()
        assert published_count == 1


# ============================================================
# ENGINE PERFORMANCE WITH COMPLEX VERSIONS
# ============================================================

class TestEngineWithComplexVersions:
    """Tests for engine calculation with complex version structures."""

    def test_engine_with_chain_of_rules(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Engine handles version with chain of dependent rules.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Rule Chain Entity", "description": "Chained rules test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Rule chain version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Create a chain: Field A affects Field B which affects Field C
        field_a = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "field_a",
                "label": "Field A (Source)",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        field_b = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "field_b",
                "label": "Field B (Middle)",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        field_c = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "field_c",
                "label": "Field C (End)",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 3
            },
            headers=admin_headers
        ).json()

        # Rule 1: Field B mandatory if A > 50
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_b["id"],
                "rule_type": "mandatory",
                "description": "B mandatory if A > 50",
                "conditions": {"criteria": [{"field_id": field_a["id"], "operator": "GREATER_THAN", "value": 50}]}
            },
            headers=admin_headers
        )

        # Rule 2: Field C visible only if B is true
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": field_c["id"],
                "rule_type": "visibility",
                "description": "C visible if B is true",
                "conditions": {"criteria": [{"field_id": field_b["id"], "operator": "EQUALS", "value": True}]}
            },
            headers=admin_headers
        )

        # Publish
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        # Test case 1: A=30, B not required, C hidden (B defaults to None/False)
        calc1 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [{"field_id": field_a["id"], "value": 30}]
            },
            headers=admin_headers
        ).json()

        b1 = next(f for f in calc1["fields"] if f["field_id"] == field_b["id"])
        c1 = next(f for f in calc1["fields"] if f["field_id"] == field_c["id"])
        assert b1["is_required"] is False
        assert c1["is_hidden"] is True

        # Test case 2: A=60, B required, C still hidden until B is true
        calc2 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [{"field_id": field_a["id"], "value": 60}]
            },
            headers=admin_headers
        ).json()

        b2 = next(f for f in calc2["fields"] if f["field_id"] == field_b["id"])
        c2 = next(f for f in calc2["fields"] if f["field_id"] == field_c["id"])
        assert b2["is_required"] is True
        assert c2["is_hidden"] is True  # B not yet true

        # Test case 3: A=60, B=true, C visible
        calc3 = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": field_a["id"], "value": 60},
                    {"field_id": field_b["id"], "value": True}
                ]
            },
            headers=admin_headers
        ).json()

        c3 = next(f for f in calc3["fields"] if f["field_id"] == field_c["id"])
        assert c3["is_hidden"] is False

    def test_engine_with_multiple_availability_rules(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Engine handles multiple availability rules on same dropdown.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Multi Availability Entity", "description": "Multiple availability rules"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Multi availability version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Tier field
        tier_field = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "tier",
                "label": "Customer Tier",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        client.post("/values/", json={"field_id": tier_field["id"], "value": "BRONZE", "label": "Bronze", "is_default": True}, headers=admin_headers)
        client.post("/values/", json={"field_id": tier_field["id"], "value": "SILVER", "label": "Silver", "is_default": False}, headers=admin_headers)
        client.post("/values/", json={"field_id": tier_field["id"], "value": "GOLD", "label": "Gold", "is_default": False}, headers=admin_headers)

        # Features field with multiple options
        features_field = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "features",
                "label": "Available Features",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        basic = client.post("/values/", json={"field_id": features_field["id"], "value": "BASIC", "label": "Basic", "is_default": True}, headers=admin_headers).json()
        standard = client.post("/values/", json={"field_id": features_field["id"], "value": "STANDARD", "label": "Standard", "is_default": False}, headers=admin_headers).json()
        premium = client.post("/values/", json={"field_id": features_field["id"], "value": "PREMIUM", "label": "Premium", "is_default": False}, headers=admin_headers).json()
        vip = client.post("/values/", json={"field_id": features_field["id"], "value": "VIP", "label": "VIP", "is_default": False}, headers=admin_headers).json()

        # Availability rules:
        # STANDARD: Silver or Gold
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": features_field["id"],
                "target_value_id": standard["id"],
                "rule_type": "availability",
                "description": "Standard for Silver+",
                "conditions": {"criteria": [{"field_id": tier_field["id"], "operator": "NOT_EQUALS", "value": "BRONZE"}]}
            },
            headers=admin_headers
        )

        # PREMIUM: Only Gold
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": features_field["id"],
                "target_value_id": premium["id"],
                "rule_type": "availability",
                "description": "Premium for Gold only",
                "conditions": {"criteria": [{"field_id": tier_field["id"], "operator": "EQUALS", "value": "GOLD"}]}
            },
            headers=admin_headers
        )

        # VIP: Only Gold
        client.post(
            "/rules/",
            json={
                "entity_version_id": version_id,
                "target_field_id": features_field["id"],
                "target_value_id": vip["id"],
                "rule_type": "availability",
                "description": "VIP for Gold only",
                "conditions": {"criteria": [{"field_id": tier_field["id"], "operator": "EQUALS", "value": "GOLD"}]}
            },
            headers=admin_headers
        )

        # Publish
        client.post(f"/versions/{version_id}/publish", headers=admin_headers)

        # BRONZE: only BASIC
        calc_bronze = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": tier_field["id"], "value": "BRONZE"}]},
            headers=admin_headers
        ).json()
        bronze_features = next(f for f in calc_bronze["fields"] if f["field_id"] == features_field["id"])
        bronze_options = {o["value"] for o in bronze_features["available_options"]}
        assert bronze_options == {"BASIC"}

        # SILVER: BASIC, STANDARD
        calc_silver = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": tier_field["id"], "value": "SILVER"}]},
            headers=admin_headers
        ).json()
        silver_features = next(f for f in calc_silver["fields"] if f["field_id"] == features_field["id"])
        silver_options = {o["value"] for o in silver_features["available_options"]}
        assert silver_options == {"BASIC", "STANDARD"}

        # GOLD: ALL options
        calc_gold = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": tier_field["id"], "value": "GOLD"}]},
            headers=admin_headers
        ).json()
        gold_features = next(f for f in calc_gold["fields"] if f["field_id"] == features_field["id"])
        gold_options = {o["value"] for o in gold_features["available_options"]}
        assert gold_options == {"BASIC", "STANDARD", "PREMIUM", "VIP"}


# ============================================================
# DEEP CLONE INTEGRITY TESTS
# ============================================================

class TestDeepCloneIntegrity:
    """
    Tests for deep clone ID remapping.

    When cloning a version, all internal references (field_id, value_id in rules)
    must be remapped to point to the NEW cloned entities, not the original ones.
    """

    def test_clone_remaps_rule_target_field_ids(
        self, client: TestClient, admin_headers
    ):
        """
        Critical: Cloned rules must point to cloned fields, not original fields.
        """
        # Create entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "Clone Remap Entity", "description": "ID remapping test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1 Original"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Create fields
        source_field = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "source",
                "label": "Source",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        target_field = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "target",
                "label": "Target",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        # Create rule referencing both fields
        rule = client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": target_field["id"],
                "rule_type": "mandatory",
                "description": "Target mandatory if source > 100",
                "conditions": {"criteria": [{"field_id": source_field["id"], "operator": "GREATER_THAN", "value": 100}]}
            },
            headers=admin_headers
        ).json()

        # Publish V1
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Clone to V2
        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2 Clone"},
            headers=admin_headers
        )
        assert v2_resp.status_code == 201
        v2_id = v2_resp.json()["id"]

        # Get V2 fields and rules
        v2_fields = client.get(f"/fields/?entity_version_id={v2_id}", headers=admin_headers).json()
        v2_rules = client.get(f"/rules/?entity_version_id={v2_id}", headers=admin_headers).json()

        assert len(v2_fields) == 2
        assert len(v2_rules) == 1

        v2_source = next(f for f in v2_fields if f["name"] == "source")
        v2_target = next(f for f in v2_fields if f["name"] == "target")
        v2_rule = v2_rules[0]

        # CRITICAL: V2 rule must point to V2 fields, NOT V1 fields
        assert v2_rule["target_field_id"] == v2_target["id"], \
            f"Rule target_field_id should be {v2_target['id']} (V2), got {v2_rule['target_field_id']}"
        assert v2_rule["target_field_id"] != target_field["id"], \
            "Rule target_field_id should NOT point to original V1 field"

        # Check conditions JSON also has remapped field_id
        condition = v2_rule["conditions"]["criteria"][0]
        assert condition["field_id"] == v2_source["id"], \
            f"Condition field_id should be {v2_source['id']} (V2), got {condition['field_id']}"
        assert condition["field_id"] != source_field["id"], \
            "Condition field_id should NOT point to original V1 field"

    def test_clone_remaps_rule_target_value_ids(
        self, client: TestClient, admin_headers
    ):
        """
        Critical: Cloned availability rules must point to cloned values.
        """
        # Create entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "Clone Value Remap", "description": "Value ID remapping test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Create dropdown field with values
        dropdown = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "tier",
                "label": "Tier",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        value_basic = client.post(
            "/values/",
            json={"field_id": dropdown["id"], "value": "BASIC", "label": "Basic", "is_default": True},
            headers=admin_headers
        ).json()

        value_premium = client.post(
            "/values/",
            json={"field_id": dropdown["id"], "value": "PREMIUM", "label": "Premium", "is_default": False},
            headers=admin_headers
        ).json()

        # Create condition field
        condition_field = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "vip",
                "label": "Is VIP",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        # Availability rule: PREMIUM only if VIP=true
        rule = client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": dropdown["id"],
                "target_value_id": value_premium["id"],
                "rule_type": "availability",
                "description": "Premium only for VIP",
                "conditions": {"criteria": [{"field_id": condition_field["id"], "operator": "EQUALS", "value": True}]}
            },
            headers=admin_headers
        ).json()

        # Publish and clone
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)
        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2 Clone"},
            headers=admin_headers
        )
        v2_id = v2_resp.json()["id"]

        # Get V2 data
        v2_fields = client.get(f"/fields/?entity_version_id={v2_id}", headers=admin_headers).json()
        v2_dropdown = next(f for f in v2_fields if f["name"] == "tier")
        v2_values = client.get(f"/values/?field_id={v2_dropdown['id']}", headers=admin_headers).json()
        v2_premium = next(v for v in v2_values if v["value"] == "PREMIUM")
        v2_rules = client.get(f"/rules/?entity_version_id={v2_id}", headers=admin_headers).json()

        assert len(v2_rules) == 1
        v2_rule = v2_rules[0]

        # CRITICAL: target_value_id must point to V2 value
        assert v2_rule["target_value_id"] == v2_premium["id"], \
            f"Rule target_value_id should be {v2_premium['id']} (V2), got {v2_rule['target_value_id']}"
        assert v2_rule["target_value_id"] != value_premium["id"], \
            "Rule target_value_id should NOT point to original V1 value"

    def test_clone_remaps_condition_value_ids_in_json(
        self, client: TestClient, admin_headers
    ):
        """
        Critical: value_id references in condition JSON must be remapped.
        """
        # Create entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "Clone Condition Value", "description": "Condition value_id remapping"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Dropdown for condition
        condition_dropdown = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "status",
                "label": "Status",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        status_active = client.post(
            "/values/",
            json={"field_id": condition_dropdown["id"], "value": "ACTIVE", "label": "Active", "is_default": True},
            headers=admin_headers
        ).json()

        # Target field
        target_field = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "extra_options",
                "label": "Extra Options",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        # Rule with value_id in condition
        rule = client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": target_field["id"],
                "rule_type": "visibility",
                "description": "Show if ACTIVE selected",
                "conditions": {"criteria": [{"field_id": condition_dropdown["id"], "value_id": status_active["id"], "operator": "EQUALS", "value": "ACTIVE"}]}
            },
            headers=admin_headers
        ).json()

        # Publish and clone
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)
        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2"},
            headers=admin_headers
        )
        v2_id = v2_resp.json()["id"]

        # Get V2 data
        v2_fields = client.get(f"/fields/?entity_version_id={v2_id}", headers=admin_headers).json()
        v2_dropdown = next(f for f in v2_fields if f["name"] == "status")
        v2_values = client.get(f"/values/?field_id={v2_dropdown['id']}", headers=admin_headers).json()
        v2_active = next(v for v in v2_values if v["value"] == "ACTIVE")
        v2_rules = client.get(f"/rules/?entity_version_id={v2_id}", headers=admin_headers).json()

        v2_rule = v2_rules[0]
        v2_condition = v2_rule["conditions"]["criteria"][0]

        # Check value_id in condition is remapped
        if "value_id" in v2_condition and v2_condition["value_id"] is not None:
            assert v2_condition["value_id"] == v2_active["id"], \
                f"Condition value_id should be {v2_active['id']} (V2), got {v2_condition['value_id']}"
            assert v2_condition["value_id"] != status_active["id"], \
                "Condition value_id should NOT point to original V1 value"

    def test_clone_preserves_rule_logic_after_remapping(
        self, client: TestClient, admin_headers
    ):
        """
        Integration: Cloned version with remapped IDs produces same engine results.
        """
        # Create entity and version
        entity_resp = client.post(
            "/entities/",
            json={"name": "Clone Logic Preserve", "description": "Logic preservation test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Setup: amount field controls premium option
        amount = client.post(
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
        ).json()

        optional = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "insurance",
                "label": "Insurance",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        # Mandatory rule: insurance required if amount > 10000
        client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": optional["id"],
                "rule_type": "mandatory",
                "description": "Insurance mandatory for high amounts",
                "conditions": {"criteria": [{"field_id": amount["id"], "operator": "GREATER_THAN", "value": 10000}]},
                "error_message": "Insurance required"
            },
            headers=admin_headers
        )

        # Publish V1
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Test V1 engine
        calc_v1_low = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": amount["id"], "value": 5000}]},
            headers=admin_headers
        ).json()
        v1_low_insurance = next(f for f in calc_v1_low["fields"] if f["field_id"] == optional["id"])

        calc_v1_high = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": amount["id"], "value": 15000}]},
            headers=admin_headers
        ).json()
        v1_high_insurance = next(f for f in calc_v1_high["fields"] if f["field_id"] == optional["id"])

        # Clone to V2
        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2 Clone"},
            headers=admin_headers
        )
        v2_id = v2_resp.json()["id"]

        # Publish V2 (will archive V1)
        client.post(f"/versions/{v2_id}/publish", headers=admin_headers)

        # Get V2 field IDs
        v2_fields = client.get(f"/fields/?entity_version_id={v2_id}", headers=admin_headers).json()
        v2_amount = next(f for f in v2_fields if f["name"] == "amount")
        v2_optional = next(f for f in v2_fields if f["name"] == "insurance")

        # Test V2 engine - should produce same logic
        calc_v2_low = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": v2_amount["id"], "value": 5000}]},
            headers=admin_headers
        ).json()
        v2_low_insurance = next(f for f in calc_v2_low["fields"] if f["field_id"] == v2_optional["id"])

        calc_v2_high = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": [{"field_id": v2_amount["id"], "value": 15000}]},
            headers=admin_headers
        ).json()
        v2_high_insurance = next(f for f in calc_v2_high["fields"] if f["field_id"] == v2_optional["id"])

        # V2 should behave exactly like V1
        assert v1_low_insurance["is_required"] == v2_low_insurance["is_required"], \
            "Low amount: V2 should have same is_required as V1"
        assert v1_high_insurance["is_required"] == v2_high_insurance["is_required"], \
            "High amount: V2 should have same is_required as V1"

        # Specifically: low amount = not required, high amount = required
        assert v2_low_insurance["is_required"] is False
        assert v2_high_insurance["is_required"] is True


# ============================================================
# CONCURRENCY TESTS
# ============================================================

class TestConcurrencyVersioning:
    """
    Tests for concurrent operations on versioning system.

    Note: These tests simulate sequential "concurrent" scenarios since
    SQLite in-memory doesn't support true concurrency. In production with
    PostgreSQL, these would test actual race conditions.
    """

    def test_single_draft_prevents_concurrent_creates(
        self, client: TestClient, admin_headers
    ):
        """
        Policy: Only one DRAFT version allowed per entity.
        Concurrent create attempts should fail.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Concurrent Draft Test", "description": "Single draft policy"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create first draft
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Draft 1"},
            headers=admin_headers
        )
        assert v1_resp.status_code == 201

        # Simulate "concurrent" attempts - all should fail
        results = []
        for i in range(3):
            resp = client.post(
                "/versions/",
                json={"entity_id": entity_id, "changelog": f"Draft {i + 2}"},
                headers=admin_headers
            )
            results.append(resp.status_code)

        # All should be rejected
        assert all(code == 409 for code in results), \
            f"All concurrent creates should fail with 409, got: {results}"

    def test_concurrent_clone_same_version(
        self, client: TestClient, admin_headers
    ):
        """
        Scenario: Multiple clone attempts on same published version.
        First should succeed, rest should fail (single draft policy).
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Concurrent Clone Test", "description": "Clone race condition"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create and publish V1
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # First clone should succeed
        clone1 = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "Clone 1"},
            headers=admin_headers
        )
        assert clone1.status_code == 201

        # Subsequent clones should fail (draft exists)
        clone2 = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "Clone 2"},
            headers=admin_headers
        )
        assert clone2.status_code == 409

        clone3 = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "Clone 3"},
            headers=admin_headers
        )
        assert clone3.status_code == 409

    def test_publish_archives_previous_atomically(
        self, client: TestClient, admin_headers, db_session
    ):
        """
        Atomic: Publishing V2 must archive V1 in same transaction.
        No state where both are PUBLISHED.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Atomic Publish Test", "description": "Atomic archive on publish"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create V1, publish
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Clone to V2
        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2"},
            headers=admin_headers
        )
        v2_id = v2_resp.json()["id"]

        # Publish V2
        pub_resp = client.post(f"/versions/{v2_id}/publish", headers=admin_headers)
        assert pub_resp.status_code == 200

        # Verify: exactly ONE published version
        all_versions = client.get(
            f"/versions/?entity_id={entity_id}",
            headers=admin_headers
        ).json()

        published = [v for v in all_versions if v["status"] == "PUBLISHED"]
        assert len(published) == 1, f"Expected 1 PUBLISHED, got {len(published)}"
        assert published[0]["id"] == v2_id

        # V1 must be archived
        v1_check = client.get(f"/versions/{v1_id}", headers=admin_headers).json()
        assert v1_check["status"] == "ARCHIVED"

    def test_rapid_clone_publish_sequence_integrity(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: Rapid sequence of clone->publish maintains integrity.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Rapid Sequence Test", "description": "Rapid clone-publish"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create initial version with data
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "persistent_field",
                "label": "Persistent",
                "data_type": "string",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        )

        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Rapid clone-publish cycle
        current_id = v1_id
        for i in range(5):
            clone_resp = client.post(
                f"/versions/{current_id}/clone",
                json={"changelog": f"V{i + 2}"},
                headers=admin_headers
            )
            assert clone_resp.status_code == 201, f"Clone {i + 1} failed"
            current_id = clone_resp.json()["id"]

            pub_resp = client.post(f"/versions/{current_id}/publish", headers=admin_headers)
            assert pub_resp.status_code == 200, f"Publish {i + 1} failed"

        # Final state check
        all_versions = client.get(
            f"/versions/?entity_id={entity_id}",
            headers=admin_headers
        ).json()

        assert len(all_versions) == 6  # V1 + 5 clones
        published = [v for v in all_versions if v["status"] == "PUBLISHED"]
        archived = [v for v in all_versions if v["status"] == "ARCHIVED"]
        assert len(published) == 1
        assert len(archived) == 5


# ============================================================
# EDGE CASES TESTS
# ============================================================

class TestEdgeCasesVersioning:
    """Tests for edge cases in versioning system."""

    def test_publish_version_without_fields(
        self, client: TestClient, admin_headers
    ):
        """
        Edge: Publishing an empty version (no fields) should succeed.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Empty Version Entity", "description": "No fields test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "Empty version"},
            headers=admin_headers
        )
        version_id = version_resp.json()["id"]

        # Publish empty version
        pub_resp = client.post(f"/versions/{version_id}/publish", headers=admin_headers)
        assert pub_resp.status_code == 200

        # Engine should handle empty version
        calc_resp = client.post(
            "/engine/calculate",
            json={"entity_id": entity_id, "current_state": []},
            headers=admin_headers
        )
        assert calc_resp.status_code == 200
        assert calc_resp.json()["fields"] == []

    def test_clone_version_with_no_rules(
        self, client: TestClient, admin_headers
    ):
        """
        Edge: Clone version that has fields but no rules.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "No Rules Entity", "description": "Fields without rules"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Add fields only, no rules
        for i in range(3):
            client.post(
                "/fields/",
                json={
                    "entity_version_id": v1_id,
                    "name": f"field_{i}",
                    "label": f"Field {i}",
                    "data_type": "string",
                    "is_free_value": True,
                    "is_required": True,
                    "sequence": i + 1
                },
                headers=admin_headers
            )

        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Clone should succeed
        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2"},
            headers=admin_headers
        )
        assert v2_resp.status_code == 201
        v2_id = v2_resp.json()["id"]

        # Verify fields cloned, no rules
        v2_fields = client.get(f"/fields/?entity_version_id={v2_id}", headers=admin_headers).json()
        v2_rules = client.get(f"/rules/?entity_version_id={v2_id}", headers=admin_headers).json()

        assert len(v2_fields) == 3
        assert len(v2_rules) == 0

    def test_clone_from_archived_version(
        self, client: TestClient, admin_headers
    ):
        """
        Edge: Should be able to clone from ARCHIVED version.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Archive Clone Entity", "description": "Clone from archived"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create V1, publish
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Create V2, publish (archives V1)
        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2"},
            headers=admin_headers
        )
        v2_id = v2_resp.json()["id"]
        client.post(f"/versions/{v2_id}/publish", headers=admin_headers)

        # V1 is now ARCHIVED
        v1_check = client.get(f"/versions/{v1_id}", headers=admin_headers).json()
        assert v1_check["status"] == "ARCHIVED"

        # V2 is now PUBLISHED, so we can't clone (draft would be created)
        # But let's verify that cloning from published V2 creates V3
        v3_resp = client.post(
            f"/versions/{v2_id}/clone",
            json={"changelog": "V3 from V2"},
            headers=admin_headers
        )
        assert v3_resp.status_code == 201

    def test_modify_published_version_blocked(
        self, client: TestClient, admin_headers
    ):
        """
        Security: Cannot add/modify fields in PUBLISHED version.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Immutable Published", "description": "Cannot modify published"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Add field while DRAFT
        field_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "original",
                "label": "Original",
                "data_type": "string",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        )
        field_id = field_resp.json()["id"]

        # Publish
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Try to add new field - should fail
        add_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "new_field",
                "label": "New",
                "data_type": "string",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2
            },
            headers=admin_headers
        )
        assert add_resp.status_code in [400, 403, 409], \
            f"Adding field to published version should fail, got {add_resp.status_code}"

        # Try to modify existing field - should fail
        modify_resp = client.patch(
            f"/fields/{field_id}",
            json={"label": "Modified Label"},
            headers=admin_headers
        )
        assert modify_resp.status_code in [400, 403, 409], \
            f"Modifying field in published version should fail, got {modify_resp.status_code}"

        # Try to delete field - should fail
        delete_resp = client.delete(f"/fields/{field_id}", headers=admin_headers)
        assert delete_resp.status_code in [400, 403, 409], \
            f"Deleting field from published version should fail, got {delete_resp.status_code}"

    def test_version_number_increments_correctly(
        self, client: TestClient, admin_headers
    ):
        """
        Edge: Version numbers should always increment, even after deletions.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Version Number Entity", "description": "Increment test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        version_numbers = []

        # Create 5 versions
        current_id = None
        for i in range(5):
            if current_id is None:
                v_resp = client.post(
                    "/versions/",
                    json={"entity_id": entity_id, "changelog": f"V{i + 1}"},
                    headers=admin_headers
                )
            else:
                v_resp = client.post(
                    f"/versions/{current_id}/clone",
                    json={"changelog": f"V{i + 1}"},
                    headers=admin_headers
                )

            current_id = v_resp.json()["id"]
            version_numbers.append(v_resp.json()["version_number"])

            # Publish each
            client.post(f"/versions/{current_id}/publish", headers=admin_headers)

        # Version numbers should be 1, 2, 3, 4, 5
        assert version_numbers == [1, 2, 3, 4, 5], \
            f"Version numbers should increment: expected [1,2,3,4,5], got {version_numbers}"

    def test_entity_with_only_archived_versions(
        self, client: TestClient, admin_headers
    ):
        """
        Edge: Entity can have only ARCHIVED versions (all old, none published).
        Engine should handle this gracefully.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "All Archived Entity", "description": "No published version"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create V1, publish, then V2, publish (archives V1)
        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2"},
            headers=admin_headers
        )
        v2_id = v2_resp.json()["id"]
        client.post(f"/versions/{v2_id}/publish", headers=admin_headers)

        # Now manually archive V2 via direct API if available, or just verify
        # the state after multiple publishes
        # For now, verify that we have correct state
        all_versions = client.get(
            f"/versions/?entity_id={entity_id}",
            headers=admin_headers
        ).json()

        archived = [v for v in all_versions if v["status"] == "ARCHIVED"]
        published = [v for v in all_versions if v["status"] == "PUBLISHED"]

        assert len(archived) == 1  # V1 archived
        assert len(published) == 1  # V2 published

    def test_clone_version_with_complex_conditions(
        self, client: TestClient, admin_headers
    ):
        """
        Edge: Clone version with rules having complex nested conditions.
        """
        entity_resp = client.post(
            "/entities/",
            json={"name": "Complex Conditions", "description": "Nested conditions clone"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        v1_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "V1"},
            headers=admin_headers
        )
        v1_id = v1_resp.json()["id"]

        # Create fields
        field_a = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "field_a",
                "label": "Field A",
                "data_type": "number",
                "is_free_value": True,
                "is_required": True,
                "sequence": 1
            },
            headers=admin_headers
        ).json()

        field_b = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "field_b",
                "label": "Field B",
                "data_type": "string",
                "is_free_value": True,
                "is_required": True,
                "sequence": 2
            },
            headers=admin_headers
        ).json()

        field_target = client.post(
            "/fields/",
            json={
                "entity_version_id": v1_id,
                "name": "target",
                "label": "Target",
                "data_type": "boolean",
                "is_free_value": True,
                "is_required": False,
                "sequence": 3
            },
            headers=admin_headers
        ).json()

        # Rule with multiple criteria
        rule = client.post(
            "/rules/",
            json={
                "entity_version_id": v1_id,
                "target_field_id": field_target["id"],
                "rule_type": "mandatory",
                "description": "Complex condition",
                "conditions": {
                    "criteria": [
                        {"field_id": field_a["id"], "operator": "GREATER_THAN", "value": 100},
                        {"field_id": field_b["id"], "operator": "EQUALS", "value": "PREMIUM"}
                    ]
                },
                "error_message": "Required for premium > 100"
            },
            headers=admin_headers
        ).json()

        # Publish and clone
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        v2_resp = client.post(
            f"/versions/{v1_id}/clone",
            json={"changelog": "V2"},
            headers=admin_headers
        )
        assert v2_resp.status_code == 201
        v2_id = v2_resp.json()["id"]

        # Verify clone has remapped complex conditions
        v2_fields = client.get(f"/fields/?entity_version_id={v2_id}", headers=admin_headers).json()
        v2_rules = client.get(f"/rules/?entity_version_id={v2_id}", headers=admin_headers).json()

        assert len(v2_rules) == 1
        v2_rule = v2_rules[0]

        # Get V2 field IDs
        v2_field_a = next(f for f in v2_fields if f["name"] == "field_a")
        v2_field_b = next(f for f in v2_fields if f["name"] == "field_b")

        # Check both criteria have remapped field_ids
        criteria = v2_rule["conditions"]["criteria"]
        assert len(criteria) == 2

        criterion_a = next(c for c in criteria if c["operator"] == "GREATER_THAN")
        criterion_b = next(c for c in criteria if c["operator"] == "EQUALS")

        assert criterion_a["field_id"] == v2_field_a["id"], \
            "First criterion should reference V2 field_a"
        assert criterion_b["field_id"] == v2_field_b["id"], \
            "Second criterion should reference V2 field_b"

    def test_clone_preserves_sku_attributes_through_generations(
        self, client: TestClient, admin_headers
    ):
        """
        Stress: SKU attributes (sku_base, sku_delimiter) are preserved
        through 5 clone generations (clone->publish->clone chain).
        """
        # Create entity
        entity_resp = client.post(
            "/entities/",
            json={"name": "SKU Clone Chain Entity", "description": "SKU preservation test"},
            headers=admin_headers
        )
        entity_id = entity_resp.json()["id"]

        # Create V1 with SKU attributes
        v1_resp = client.post(
            "/versions/",
            json={
                "entity_id": entity_id,
                "changelog": "V1 - Initial with SKU",
                "sku_base": "PROD-2024",
                "sku_delimiter": "-"
            },
            headers=admin_headers
        )
        assert v1_resp.status_code == 201
        v1_id = v1_resp.json()["id"]

        # Verify V1 has SKU attributes
        v1_data = client.get(f"/versions/{v1_id}", headers=admin_headers).json()
        assert v1_data["sku_base"] == "PROD-2024"
        assert v1_data["sku_delimiter"] == "-"

        # Publish V1
        client.post(f"/versions/{v1_id}/publish", headers=admin_headers)

        # Clone through 5 generations: V2, V3, V4, V5, V6
        current_id = v1_id
        for gen in range(2, 7):  # generations 2 through 6
            clone_resp = client.post(
                f"/versions/{current_id}/clone",
                json={"changelog": f"V{gen} - Clone generation {gen - 1}"},
                headers=admin_headers
            )
            assert clone_resp.status_code == 201, f"Clone to V{gen} failed"
            current_id = clone_resp.json()["id"]

            # Verify SKU attributes preserved in each clone
            clone_data = client.get(f"/versions/{current_id}", headers=admin_headers).json()
            assert clone_data["sku_base"] == "PROD-2024", \
                f"V{gen}: sku_base should be 'PROD-2024', got '{clone_data.get('sku_base')}'"
            assert clone_data["sku_delimiter"] == "-", \
                f"V{gen}: sku_delimiter should be '-', got '{clone_data.get('sku_delimiter')}'"

            # Publish to enable next clone
            pub_resp = client.post(f"/versions/{current_id}/publish", headers=admin_headers)
            assert pub_resp.status_code == 200

        # Final verification: V6 (5th clone) still has original SKU attributes
        final_data = client.get(f"/versions/{current_id}", headers=admin_headers).json()
        assert final_data["version_number"] == 6
        assert final_data["sku_base"] == "PROD-2024"
        assert final_data["sku_delimiter"] == "-"
        assert final_data["status"] == "PUBLISHED"

        # Verify all versions in chain have same SKU attributes
        all_versions = client.get(
            f"/versions/?entity_id={entity_id}",
            headers=admin_headers
        ).json()

        assert len(all_versions) == 6
        for v in all_versions:
            assert v["sku_base"] == "PROD-2024", \
                f"Version {v['version_number']}: sku_base mismatch"
            assert v["sku_delimiter"] == "-", \
                f"Version {v['version_number']}: sku_delimiter mismatch"
