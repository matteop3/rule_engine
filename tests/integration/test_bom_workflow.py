"""
End-to-end integration tests for the BOM feature.

Covers two full workflows:
- Entity → Version → Fields → BOM Items → BOM Rules → Publish → Calculate → Verify BOM output
- Configuration lifecycle with BOM: create → verify bom_total_price → update → recalculate → finalize → clone → verify copy
"""

from decimal import Decimal

from fastapi.testclient import TestClient

# ============================================================
# FULL BOM LIFECYCLE
# ============================================================


class TestFullBOMLifecycle:
    """End-to-end: version setup through engine calculation with BOM output."""

    def test_full_bom_lifecycle(self, client: TestClient, admin_headers):
        """
        E2E: Create entity → Create version → Add fields → Add BOM items →
             Add BOM rules → Publish → Calculate → Verify BOM output.
        """
        # --- Step 1: Create Entity ---
        entity_resp = client.post(
            "/entities/",
            json={"name": "BOM E2E Product", "description": "End-to-end BOM test"},
            headers=admin_headers,
        )
        assert entity_resp.status_code == 201
        entity_id = entity_resp.json()["id"]

        # --- Step 2: Create Draft Version ---
        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "BOM E2E version"},
            headers=admin_headers,
        )
        assert version_resp.status_code == 201
        version_id = version_resp.json()["id"]
        assert version_resp.json()["status"] == "DRAFT"

        # --- Step 3: Add Fields ---
        # material (dropdown): STEEL, PLASTIC
        f_material_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "material",
                "label": "Material",
                "data_type": "string",
                "is_free_value": False,
                "is_required": True,
                "sequence": 1,
            },
            headers=admin_headers,
        )
        assert f_material_resp.status_code == 201
        f_material_id = f_material_resp.json()["id"]

        # quantity_needed (number, free value)
        f_qty_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "quantity_needed",
                "label": "Quantity Needed",
                "data_type": "number",
                "is_free_value": True,
                "is_required": False,
                "sequence": 2,
            },
            headers=admin_headers,
        )
        assert f_qty_resp.status_code == 201
        f_qty_id = f_qty_resp.json()["id"]

        # Add values for material dropdown
        for val, label in [("STEEL", "Steel"), ("PLASTIC", "Plastic")]:
            v_resp = client.post(
                "/values/",
                json={"field_id": f_material_id, "value": val, "label": label},
                headers=admin_headers,
            )
            assert v_resp.status_code == 201

        # --- Step 4: Add BOM Items ---
        # 4a. Frame — TECHNICAL, unconditional, qty=1
        bom_frame_resp = client.post(
            "/bom-items/",
            json={
                "entity_version_id": version_id,
                "bom_type": "TECHNICAL",
                "part_number": "FRM-001",
                "description": "Main frame",
                "quantity": "1",
                "sequence": 1,
            },
            headers=admin_headers,
        )
        assert bom_frame_resp.status_code == 201
        bom_frame_id = bom_frame_resp.json()["id"]

        # 4b. Bracket — TECHNICAL, child of frame, unconditional, qty from field
        bom_bracket_resp = client.post(
            "/bom-items/",
            json={
                "entity_version_id": version_id,
                "bom_type": "TECHNICAL",
                "part_number": "BRK-002",
                "description": "Mounting bracket",
                "quantity": "2",
                "quantity_from_field_id": f_qty_id,
                "parent_bom_item_id": bom_frame_id,
                "sequence": 2,
            },
            headers=admin_headers,
        )
        assert bom_bracket_resp.status_code == 201
        bom_bracket_id = bom_bracket_resp.json()["id"]

        # 4c. Rust coating — TECHNICAL, child of frame, conditional on STEEL
        bom_coating_resp = client.post(
            "/bom-items/",
            json={
                "entity_version_id": version_id,
                "bom_type": "TECHNICAL",
                "part_number": "CTG-003",
                "description": "Anti-rust coating",
                "quantity": "1",
                "parent_bom_item_id": bom_frame_id,
                "sequence": 3,
            },
            headers=admin_headers,
        )
        assert bom_coating_resp.status_code == 201
        bom_coating_id = bom_coating_resp.json()["id"]

        # 4d. Assembly service — COMMERCIAL, unconditional, priced
        bom_assembly_resp = client.post(
            "/bom-items/",
            json={
                "entity_version_id": version_id,
                "bom_type": "COMMERCIAL",
                "part_number": "SVC-ASM",
                "description": "Assembly service",
                "quantity": "1",
                "unit_price": "50.00",
                "sequence": 4,
            },
            headers=admin_headers,
        )
        assert bom_assembly_resp.status_code == 201

        # 4e. Coating service — COMMERCIAL, conditional on STEEL, priced
        bom_coat_svc_resp = client.post(
            "/bom-items/",
            json={
                "entity_version_id": version_id,
                "bom_type": "COMMERCIAL",
                "part_number": "SVC-CTG",
                "description": "Coating service",
                "quantity": "1",
                "unit_price": "30.00",
                "sequence": 5,
            },
            headers=admin_headers,
        )
        assert bom_coat_svc_resp.status_code == 201
        bom_coat_svc_id = bom_coat_svc_resp.json()["id"]

        # --- Step 5: Add BOM Rules ---
        # Coating (TECHNICAL) included only when material == STEEL
        rule_coating_resp = client.post(
            "/bom-item-rules/",
            json={
                "bom_item_id": bom_coating_id,
                "entity_version_id": version_id,
                "conditions": {
                    "criteria": [{"field_id": f_material_id, "operator": "EQUALS", "value": "STEEL"}],
                },
                "description": "Coating for steel only",
            },
            headers=admin_headers,
        )
        assert rule_coating_resp.status_code == 201

        # Coating service (COMMERCIAL) included only when material == STEEL
        rule_coat_svc_resp = client.post(
            "/bom-item-rules/",
            json={
                "bom_item_id": bom_coat_svc_id,
                "entity_version_id": version_id,
                "conditions": {
                    "criteria": [{"field_id": f_material_id, "operator": "EQUALS", "value": "STEEL"}],
                },
                "description": "Coating service for steel only",
            },
            headers=admin_headers,
        )
        assert rule_coat_svc_resp.status_code == 201

        # --- Step 6: Publish Version ---
        publish_resp = client.post(f"/versions/{version_id}/publish", headers=admin_headers)
        assert publish_resp.status_code == 200
        assert publish_resp.json()["status"] == "PUBLISHED"

        # --- Step 7: Calculate with STEEL + quantity_needed = 5 ---
        calc_steel_resp = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": f_material_id, "value": "STEEL"},
                    {"field_id": f_qty_id, "value": 5},
                ],
            },
            headers=admin_headers,
        )
        assert calc_steel_resp.status_code == 200
        steel_result = calc_steel_resp.json()

        # BOM should be present
        assert steel_result["bom"] is not None
        bom = steel_result["bom"]

        # TECHNICAL: frame (with bracket + coating as children)
        assert len(bom["technical"]) == 1
        frame = bom["technical"][0]
        assert frame["part_number"] == "FRM-001"
        assert len(frame["children"]) == 2

        child_parts = {c["part_number"] for c in frame["children"]}
        assert "BRK-002" in child_parts
        assert "CTG-003" in child_parts

        # Bracket quantity should resolve from field (5)
        bracket = next(c for c in frame["children"] if c["part_number"] == "BRK-002")
        assert Decimal(str(bracket["quantity"])) == Decimal("5")

        # Coating present (STEEL selected)
        coating = next(c for c in frame["children"] if c["part_number"] == "CTG-003")
        assert Decimal(str(coating["quantity"])) == Decimal("1")

        # COMMERCIAL: assembly (unconditional) + coating service (STEEL)
        assert len(bom["commercial"]) == 2
        commercial_parts = {c["part_number"] for c in bom["commercial"]}
        assert "SVC-ASM" in commercial_parts
        assert "SVC-CTG" in commercial_parts

        # commercial_total = assembly(1*50) + coating_svc(1*30) = 80.00
        assert Decimal(str(bom["commercial_total"])) == Decimal("80.00")

        # --- Step 8: Calculate with PLASTIC (no coating items) ---
        calc_plastic_resp = client.post(
            "/engine/calculate",
            json={
                "entity_id": entity_id,
                "current_state": [
                    {"field_id": f_material_id, "value": "PLASTIC"},
                    {"field_id": f_qty_id, "value": 3},
                ],
            },
            headers=admin_headers,
        )
        assert calc_plastic_resp.status_code == 200
        plastic_result = calc_plastic_resp.json()

        bom_plastic = plastic_result["bom"]
        assert bom_plastic is not None

        # TECHNICAL: frame with bracket only (coating excluded)
        assert len(bom_plastic["technical"]) == 1
        frame_p = bom_plastic["technical"][0]
        assert len(frame_p["children"]) == 1
        assert frame_p["children"][0]["part_number"] == "BRK-002"
        assert Decimal(str(frame_p["children"][0]["quantity"])) == Decimal("3")

        # COMMERCIAL: assembly only (coating service excluded)
        assert len(bom_plastic["commercial"]) == 1
        assert bom_plastic["commercial"][0]["part_number"] == "SVC-ASM"

        # commercial_total = assembly only (1*50) = 50.00
        assert Decimal(str(bom_plastic["commercial_total"])) == Decimal("50.00")


# ============================================================
# BOM WITH CONFIGURATION LIFECYCLE
# ============================================================


class TestBOMConfigurationLifecycle:
    """End-to-end: configuration lifecycle with BOM total price tracking."""

    def test_bom_with_configuration_lifecycle(self, client: TestClient, admin_headers):
        """
        E2E: Create config → verify bom_total_price → update data →
             verify recalculation → finalize → clone → verify copy.
        """
        # --- Setup: entity, version, fields, BOM items, BOM rules, publish ---
        entity_resp = client.post(
            "/entities/",
            json={"name": "BOM Config Lifecycle", "description": "Config lifecycle with BOM"},
            headers=admin_headers,
        )
        assert entity_resp.status_code == 201
        entity_id = entity_resp.json()["id"]

        version_resp = client.post(
            "/versions/",
            json={"entity_id": entity_id, "changelog": "BOM lifecycle version"},
            headers=admin_headers,
        )
        assert version_resp.status_code == 201
        version_id = version_resp.json()["id"]

        # Field: finish (dropdown): MATTE, GLOSSY
        f_finish_resp = client.post(
            "/fields/",
            json={
                "entity_version_id": version_id,
                "name": "finish",
                "label": "Finish",
                "data_type": "string",
                "is_free_value": False,
                "is_required": False,
                "sequence": 1,
            },
            headers=admin_headers,
        )
        assert f_finish_resp.status_code == 201
        f_finish_id = f_finish_resp.json()["id"]

        for val, label in [("MATTE", "Matte"), ("GLOSSY", "Glossy")]:
            v_resp = client.post(
                "/values/",
                json={"field_id": f_finish_id, "value": val, "label": label},
                headers=admin_headers,
            )
            assert v_resp.status_code == 201

        # BOM: base part — COMMERCIAL, unconditional, qty=1, price=100
        client.post(
            "/bom-items/",
            json={
                "entity_version_id": version_id,
                "bom_type": "COMMERCIAL",
                "part_number": "BASE-001",
                "description": "Base part",
                "quantity": "1",
                "unit_price": "100.00",
                "sequence": 1,
            },
            headers=admin_headers,
        )

        # BOM: gloss finish — COMMERCIAL, conditional on GLOSSY, qty=1, price=25
        bom_gloss_resp = client.post(
            "/bom-items/",
            json={
                "entity_version_id": version_id,
                "bom_type": "COMMERCIAL",
                "part_number": "FIN-GLOSS",
                "description": "Glossy finish",
                "quantity": "1",
                "unit_price": "25.00",
                "sequence": 2,
            },
            headers=admin_headers,
        )
        assert bom_gloss_resp.status_code == 201
        bom_gloss_id = bom_gloss_resp.json()["id"]

        # Rule: glossy finish included only when finish == GLOSSY
        client.post(
            "/bom-item-rules/",
            json={
                "bom_item_id": bom_gloss_id,
                "entity_version_id": version_id,
                "conditions": {
                    "criteria": [{"field_id": f_finish_id, "operator": "EQUALS", "value": "GLOSSY"}],
                },
                "description": "Glossy finish surcharge",
            },
            headers=admin_headers,
        )

        # Publish
        publish_resp = client.post(f"/versions/{version_id}/publish", headers=admin_headers)
        assert publish_resp.status_code == 200

        # --- Step 1: Create configuration with GLOSSY ---
        create_resp = client.post(
            "/configurations/",
            json={
                "entity_version_id": version_id,
                "name": "BOM Lifecycle Config",
                "data": [{"field_id": f_finish_id, "value": "GLOSSY"}],
            },
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        config_id = create_resp.json()["id"]

        # bom_total_price = base(100) + gloss(25) = 125.00
        assert Decimal(str(create_resp.json()["bom_total_price"])) == Decimal("125.00")

        # --- Step 2: Update to MATTE (glossy excluded) ---
        update_resp = client.patch(
            f"/configurations/{config_id}",
            json={"data": [{"field_id": f_finish_id, "value": "MATTE"}]},
            headers=admin_headers,
        )
        assert update_resp.status_code == 200

        # bom_total_price = base only = 100.00
        assert Decimal(str(update_resp.json()["bom_total_price"])) == Decimal("100.00")

        # --- Step 3: Verify via calculate endpoint ---
        calc_resp = client.get(f"/configurations/{config_id}/calculate", headers=admin_headers)
        assert calc_resp.status_code == 200
        assert len(calc_resp.json()["bom"]["commercial"]) == 1
        assert Decimal(str(calc_resp.json()["bom"]["commercial_total"])) == Decimal("100.00")

        # --- Step 4: Update back to GLOSSY and finalize ---
        update_resp2 = client.patch(
            f"/configurations/{config_id}",
            json={"data": [{"field_id": f_finish_id, "value": "GLOSSY"}]},
            headers=admin_headers,
        )
        assert update_resp2.status_code == 200
        assert Decimal(str(update_resp2.json()["bom_total_price"])) == Decimal("125.00")

        finalize_resp = client.post(f"/configurations/{config_id}/finalize", headers=admin_headers)
        assert finalize_resp.status_code == 200
        assert finalize_resp.json()["status"] == "FINALIZED"
        assert Decimal(str(finalize_resp.json()["bom_total_price"])) == Decimal("125.00")

        # --- Step 5: Clone and verify copy ---
        clone_resp = client.post(f"/configurations/{config_id}/clone", headers=admin_headers)
        assert clone_resp.status_code == 201
        clone_id = clone_resp.json()["id"]
        assert clone_resp.json()["status"] == "DRAFT"
        assert Decimal(str(clone_resp.json()["bom_total_price"])) == Decimal("125.00")

        # --- Step 6: Modify clone and verify independent recalculation ---
        clone_update_resp = client.patch(
            f"/configurations/{clone_id}",
            json={"data": [{"field_id": f_finish_id, "value": "MATTE"}]},
            headers=admin_headers,
        )
        assert clone_update_resp.status_code == 200
        assert Decimal(str(clone_update_resp.json()["bom_total_price"])) == Decimal("100.00")

        # Original remains unchanged
        original_resp = client.get(f"/configurations/{config_id}", headers=admin_headers)
        assert original_resp.status_code == 200
        assert Decimal(str(original_resp.json()["bom_total_price"])) == Decimal("125.00")
        assert original_resp.json()["status"] == "FINALIZED"
