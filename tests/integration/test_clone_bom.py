"""
Version Clone — BOM Remapping Tests.

Tests for BOM data integrity during version clone operations:
- BOM items are copied with correct ID remapping
- BOM item rules are copied with remapped IDs and conditions
- Parent references, quantity field references, and condition field IDs are remapped
- Types, prices, and quantities are preserved exactly
"""

from decimal import Decimal

from fastapi.testclient import TestClient

from app.models.domain import (
    BOMItem,
    BOMItemRule,
    BOMType,
    EntityVersion,
    Field,
    FieldType,
    VersionStatus,
)


class TestCloneBOM:
    """Tests for BOM data integrity during version clone operations."""

    def _create_source_version(self, db_session, test_entity, admin_user):
        """
        Creates a PUBLISHED version with fields, BOM items (root + nested), and BOM item rules.

        Structure:
            Fields: width (NUMBER), color (STRING)
            BOM Items:
                - frame (TECHNICAL, root, quantity=1)
                    - bolt (TECHNICAL, child of frame, quantity=4)
                - panel (TECHNICAL, root, quantity_from_field=width)
                - coating (COMMERCIAL, root, quantity=1)
            BOM Item Rules:
                - rule on bolt: conditions referencing width field
                - rule on coating: conditions referencing color field
        """
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Source version with BOM",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(version)
        db_session.flush()

        # Fields
        width_field = Field(
            entity_version_id=version.id,
            name="width",
            label="Width",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            is_required=True,
            sequence=1,
        )
        color_field = Field(
            entity_version_id=version.id,
            name="color",
            label="Color",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_required=True,
            sequence=2,
        )
        db_session.add_all([width_field, color_field])
        db_session.flush()

        # BOM Items — roots
        frame = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="FRAME-001",
            quantity=Decimal("1"),
            sequence=1,
        )
        panel = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PANEL-001",
            quantity=Decimal("2"),
            quantity_from_field_id=width_field.id,
            sequence=2,
        )
        coating = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="COAT-001",
            quantity=Decimal("1"),
            sequence=3,
        )
        db_session.add_all([frame, panel, coating])
        db_session.flush()

        # BOM Items — child (nested under frame)
        bolt = BOMItem(
            entity_version_id=version.id,
            parent_bom_item_id=frame.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="BOLT-M8",
            quantity=Decimal("4"),
            sequence=1,
        )
        db_session.add(bolt)
        db_session.flush()

        # BOM Item Rules
        bolt_rule = BOMItemRule(
            bom_item_id=bolt.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": width_field.id, "operator": "GREATER_THAN", "value": 100}]},
            description="Include bolts when width > 100",
        )
        coating_rule = BOMItemRule(
            bom_item_id=coating.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": color_field.id, "operator": "EQUALS", "value": "Red"}]},
            description="Include coating for red color",
        )
        db_session.add_all([bolt_rule, coating_rule])
        db_session.commit()

        return {
            "version": version,
            "fields": {"width": width_field, "color": color_field},
            "bom_items": {"frame": frame, "bolt": bolt, "panel": panel, "coating": coating},
            "bom_rules": {"bolt_rule": bolt_rule, "coating_rule": coating_rule},
        }

    def _clone_and_get_data(self, client, admin_headers, source_version_id):
        """Clones a version and returns the new version ID."""
        resp = client.post(
            f"/versions/{source_version_id}/clone",
            json={"changelog": "Cloned with BOM"},
            headers=admin_headers,
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_clone_copies_bom_items(self, client: TestClient, admin_headers, db_session, test_entity, admin_user):
        """All BOM items are present in the cloned version with correct attributes."""
        source = self._create_source_version(db_session, test_entity, admin_user)
        new_version_id = self._clone_and_get_data(client, admin_headers, source["version"].id)

        # Get cloned BOM items
        resp = client.get(f"/bom-items/?entity_version_id={new_version_id}", headers=admin_headers)
        assert resp.status_code == 200
        cloned_items = resp.json()

        assert len(cloned_items) == 4

        # Verify all part numbers are present
        cloned_part_numbers = {item["part_number"] for item in cloned_items}
        assert cloned_part_numbers == {"FRAME-001", "BOLT-M8", "PANEL-001", "COAT-001"}

        # Verify IDs are different from source
        source_ids = {bi.id for bi in source["bom_items"].values()}
        cloned_ids = {item["id"] for item in cloned_items}
        assert cloned_ids.isdisjoint(source_ids)

    def test_clone_copies_bom_item_rules(self, client: TestClient, admin_headers, db_session, test_entity, admin_user):
        """All BOM item rules are present with remapped bom_item_id."""
        source = self._create_source_version(db_session, test_entity, admin_user)
        new_version_id = self._clone_and_get_data(client, admin_headers, source["version"].id)

        # Get cloned BOM item rules
        resp = client.get(f"/bom-item-rules/?entity_version_id={new_version_id}", headers=admin_headers)
        assert resp.status_code == 200
        cloned_rules = resp.json()

        assert len(cloned_rules) == 2

        # Verify IDs are different from source
        source_rule_ids = {r.id for r in source["bom_rules"].values()}
        cloned_rule_ids = {r["id"] for r in cloned_rules}
        assert cloned_rule_ids.isdisjoint(source_rule_ids)

        # Verify bom_item_ids are remapped (not pointing to source items)
        source_bom_item_ids = {bi.id for bi in source["bom_items"].values()}
        for cloned_rule in cloned_rules:
            assert cloned_rule["bom_item_id"] not in source_bom_item_ids

    def test_clone_remaps_parent_bom_item_id(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """Parent references point to cloned items, not source items."""
        source = self._create_source_version(db_session, test_entity, admin_user)
        new_version_id = self._clone_and_get_data(client, admin_headers, source["version"].id)

        # Get cloned BOM items
        resp = client.get(f"/bom-items/?entity_version_id={new_version_id}", headers=admin_headers)
        cloned_items = resp.json()

        cloned_by_part = {item["part_number"]: item for item in cloned_items}
        cloned_frame = cloned_by_part["FRAME-001"]
        cloned_bolt = cloned_by_part["BOLT-M8"]

        # Bolt's parent should be the cloned frame, not the source frame
        assert cloned_bolt["parent_bom_item_id"] == cloned_frame["id"]
        assert cloned_bolt["parent_bom_item_id"] != source["bom_items"]["frame"].id

        # Root items have no parent
        assert cloned_frame["parent_bom_item_id"] is None
        assert cloned_by_part["PANEL-001"]["parent_bom_item_id"] is None
        assert cloned_by_part["COAT-001"]["parent_bom_item_id"] is None

    def test_clone_remaps_quantity_from_field_id(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """Field references for dynamic quantity point to cloned fields."""
        source = self._create_source_version(db_session, test_entity, admin_user)
        new_version_id = self._clone_and_get_data(client, admin_headers, source["version"].id)

        # Get cloned fields
        fields_resp = client.get(f"/fields/?entity_version_id={new_version_id}", headers=admin_headers)
        cloned_fields = fields_resp.json()
        cloned_width = next(f for f in cloned_fields if f["name"] == "width")

        # Get cloned BOM items
        items_resp = client.get(f"/bom-items/?entity_version_id={new_version_id}", headers=admin_headers)
        cloned_items = items_resp.json()
        cloned_panel = next(item for item in cloned_items if item["part_number"] == "PANEL-001")

        # quantity_from_field_id should point to the cloned width field
        assert cloned_panel["quantity_from_field_id"] == cloned_width["id"]
        assert cloned_panel["quantity_from_field_id"] != source["fields"]["width"].id

        # Items without quantity_from_field_id remain null
        cloned_frame = next(item for item in cloned_items if item["part_number"] == "FRAME-001")
        assert cloned_frame["quantity_from_field_id"] is None

    def test_clone_remaps_conditions_field_ids(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """field_id inside BOM rule conditions are remapped to cloned fields."""
        source = self._create_source_version(db_session, test_entity, admin_user)
        new_version_id = self._clone_and_get_data(client, admin_headers, source["version"].id)

        # Get cloned fields
        fields_resp = client.get(f"/fields/?entity_version_id={new_version_id}", headers=admin_headers)
        cloned_fields = fields_resp.json()
        cloned_field_ids = {f["id"] for f in cloned_fields}
        cloned_width = next(f for f in cloned_fields if f["name"] == "width")
        cloned_color = next(f for f in cloned_fields if f["name"] == "color")

        # Get cloned BOM items to identify bolt and coating
        items_resp = client.get(f"/bom-items/?entity_version_id={new_version_id}", headers=admin_headers)
        cloned_items = items_resp.json()
        cloned_bolt = next(item for item in cloned_items if item["part_number"] == "BOLT-M8")
        cloned_coating = next(item for item in cloned_items if item["part_number"] == "COAT-001")

        # Get cloned BOM item rules
        rules_resp = client.get(f"/bom-item-rules/?entity_version_id={new_version_id}", headers=admin_headers)
        cloned_rules = rules_resp.json()

        # Source field IDs should not appear in any condition
        source_field_ids = {f.id for f in source["fields"].values()}

        for rule in cloned_rules:
            for criterion in rule["conditions"]["criteria"]:
                assert criterion["field_id"] not in source_field_ids
                assert criterion["field_id"] in cloned_field_ids

        # Verify specific remappings
        bolt_rule = next(r for r in cloned_rules if r["bom_item_id"] == cloned_bolt["id"])
        assert bolt_rule["conditions"]["criteria"][0]["field_id"] == cloned_width["id"]

        coating_rule = next(r for r in cloned_rules if r["bom_item_id"] == cloned_coating["id"])
        assert coating_rule["conditions"]["criteria"][0]["field_id"] == cloned_color["id"]

    def test_clone_preserves_bom_type_and_quantity(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """Types and quantities are preserved exactly after clone."""
        source = self._create_source_version(db_session, test_entity, admin_user)
        new_version_id = self._clone_and_get_data(client, admin_headers, source["version"].id)

        resp = client.get(f"/bom-items/?entity_version_id={new_version_id}", headers=admin_headers)
        cloned_items = resp.json()
        cloned_by_part = {item["part_number"]: item for item in cloned_items}

        frame = cloned_by_part["FRAME-001"]
        assert frame["bom_type"] == "TECHNICAL"
        assert Decimal(frame["quantity"]) == Decimal("1")

        bolt = cloned_by_part["BOLT-M8"]
        assert bolt["bom_type"] == "TECHNICAL"
        assert Decimal(bolt["quantity"]) == Decimal("4")

        panel = cloned_by_part["PANEL-001"]
        assert panel["bom_type"] == "TECHNICAL"
        assert Decimal(panel["quantity"]) == Decimal("2")
        assert panel["quantity_from_field_id"] is not None

        coating = cloned_by_part["COAT-001"]
        assert coating["bom_type"] == "COMMERCIAL"
        assert Decimal(coating["quantity"]) == Decimal("1")
