"""
Test suite for BOM Items API endpoints.

Tests the full CRUD lifecycle for BOM Item management including:
- RBAC enforcement (admin/author only)
- DRAFT-only modification policy
- Quantity validation
- quantity_from_field_id validation (NUMBER type, same version)
- parent_bom_item_id validation (same version, no circular refs)
- Cascade delete of children
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.models.domain import BOMItem, BOMType, Field, FieldType

# ============================================================
# LIST BOM ITEMS (GET /bom-items/)
# ============================================================


class TestListBOMItems:
    """Tests for GET /bom-items/ endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_list_bom_items_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_bom_item):
        """RBAC: admin/author can list BOM items, user gets 403."""
        headers = request.getfixturevalue(headers_fixture)
        response = client.get(
            f"/bom-items/?entity_version_id={draft_bom_item.entity_version_id}",
            headers=headers,
        )
        assert response.status_code == expected_status

    def test_list_bom_items_ordered_by_sequence(self, client: TestClient, admin_headers, db_session, draft_version):
        """BOM items are returned ordered by sequence."""
        for seq, pn in [(3, "C-003"), (1, "A-001"), (2, "B-002")]:
            db_session.add(
                BOMItem(
                    entity_version_id=draft_version.id,
                    bom_type=BOMType.TECHNICAL.value,
                    part_number=pn,
                    quantity=Decimal("1"),
                    sequence=seq,
                )
            )
        db_session.commit()

        response = client.get(
            f"/bom-items/?entity_version_id={draft_version.id}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        part_numbers = [item["part_number"] for item in response.json()]
        assert part_numbers == ["A-001", "B-002", "C-003"]


# ============================================================
# READ BOM ITEM (GET /bom-items/{id})
# ============================================================


class TestReadBOMItem:
    """Tests for GET /bom-items/{id} endpoint."""

    def test_read_bom_item(self, client: TestClient, admin_headers, draft_bom_item):
        """Read a single BOM item by ID."""
        response = client.get(f"/bom-items/{draft_bom_item.id}", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["id"] == draft_bom_item.id
        assert response.json()["part_number"] == draft_bom_item.part_number

    def test_read_bom_item_not_found(self, client: TestClient, admin_headers):
        """404 on missing BOM item."""
        response = client.get("/bom-items/99999", headers=admin_headers)
        assert response.status_code == 404


# ============================================================
# CREATE BOM ITEM (POST /bom-items/)
# ============================================================


class TestCreateBOMItem:
    """Tests for POST /bom-items/ endpoint."""

    def test_create_technical_bom_item(self, client: TestClient, admin_headers, draft_version):
        """Create a TECHNICAL BOM item."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "TECH-001",
                "description": "Technical component",
                "quantity": "2.0000",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["bom_type"] == "TECHNICAL"
        assert data["part_number"] == "TECH-001"

    def test_create_commercial_bom_item(self, client: TestClient, admin_headers, draft_version):
        """Create a COMMERCIAL BOM item."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "COMMERCIAL",
                "part_number": "COM-001",
                "quantity": "1",
            },
        )
        assert response.status_code == 201

    def test_create_draft_only_published_rejected(self, client: TestClient, admin_headers, published_version):
        """Creating on a PUBLISHED version returns 409."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": published_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "FAIL-001",
                "quantity": "1",
            },
        )
        assert response.status_code == 409

    def test_create_draft_only_archived_rejected(self, client: TestClient, admin_headers, archived_version):
        """Creating on an ARCHIVED version returns 409."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": archived_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "FAIL-002",
                "quantity": "1",
            },
        )
        assert response.status_code == 409

    def test_quantity_zero_rejected(self, client: TestClient, admin_headers, draft_version):
        """Quantity = 0 returns 400."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "FAIL-005",
                "quantity": "0",
            },
        )
        assert response.status_code == 400
        assert "Quantity" in response.json()["detail"]

    def test_quantity_negative_rejected(self, client: TestClient, admin_headers, draft_version):
        """Negative quantity returns 400."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "FAIL-006",
                "quantity": "-1",
            },
        )
        assert response.status_code == 400

    def test_quantity_from_field_must_be_number_type(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """quantity_from_field_id must reference a NUMBER field."""
        string_field = Field(
            entity_version_id=draft_version.id,
            name="text_field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add(string_field)
        db_session.commit()

        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "FAIL-007",
                "quantity": "1",
                "quantity_from_field_id": string_field.id,
            },
        )
        assert response.status_code == 400
        assert "NUMBER" in response.json()["detail"]

    def test_quantity_from_field_must_be_same_version(
        self, client: TestClient, admin_headers, db_session, draft_version, second_entity
    ):
        """quantity_from_field_id must belong to the same version."""
        from app.models.domain import EntityVersion, VersionStatus

        other_version = EntityVersion(
            entity_id=second_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
        )
        db_session.add(other_version)
        db_session.flush()

        other_field = Field(
            entity_version_id=other_version.id,
            name="other_num",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
        )
        db_session.add(other_field)
        db_session.commit()

        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "FAIL-008",
                "quantity": "1",
                "quantity_from_field_id": other_field.id,
            },
        )
        assert response.status_code == 400

    def test_quantity_from_field_valid_number(self, client: TestClient, admin_headers, db_session, draft_version):
        """quantity_from_field_id accepts a valid NUMBER field in the same version."""
        num_field = Field(
            entity_version_id=draft_version.id,
            name="qty_field",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
        )
        db_session.add(num_field)
        db_session.commit()

        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "DYN-QTY-001",
                "quantity": "1",
                "quantity_from_field_id": num_field.id,
            },
        )
        assert response.status_code == 201
        assert response.json()["quantity_from_field_id"] == num_field.id

    def test_parent_must_be_same_version(
        self, client: TestClient, admin_headers, db_session, draft_version, second_entity
    ):
        """parent_bom_item_id must belong to the same version."""
        from app.models.domain import EntityVersion, VersionStatus

        other_version = EntityVersion(
            entity_id=second_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
        )
        db_session.add(other_version)
        db_session.flush()

        other_item = BOMItem(
            entity_version_id=other_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="OTHER-001",
            quantity=Decimal("1"),
        )
        db_session.add(other_item)
        db_session.commit()

        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "FAIL-009",
                "quantity": "1",
                "parent_bom_item_id": other_item.id,
            },
        )
        assert response.status_code == 400

    def test_create_with_valid_parent(self, client: TestClient, admin_headers, draft_bom_item):
        """Create a child BOM item with a valid parent."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_bom_item.entity_version_id,
                "bom_type": "TECHNICAL",
                "part_number": "CHILD-001",
                "quantity": "2",
                "parent_bom_item_id": draft_bom_item.id,
            },
        )
        assert response.status_code == 201
        assert response.json()["parent_bom_item_id"] == draft_bom_item.id

    def test_user_cannot_create_bom_item(self, client: TestClient, user_headers, draft_version):
        """Regular user cannot create BOM items (403)."""
        response = client.post(
            "/bom-items/",
            headers=user_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "NOPE-001",
                "quantity": "1",
            },
        )
        assert response.status_code == 403

    def test_commercial_with_parent_rejected(self, client: TestClient, admin_headers, db_session, draft_version):
        """COMMERCIAL item with non-null parent_bom_item_id returns 400."""
        parent = BOMItem(
            entity_version_id=draft_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PARENT-001",
            quantity=Decimal("1"),
        )
        db_session.add(parent)
        db_session.commit()

        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "COMMERCIAL",
                "part_number": "COM-CHILD",
                "quantity": "1",
                "parent_bom_item_id": parent.id,
            },
        )
        assert response.status_code == 400
        assert "COMMERCIAL" in response.json()["detail"]
        assert "root" in response.json()["detail"].lower()

    def test_commercial_without_parent_allowed(self, client: TestClient, admin_headers, draft_version):
        """COMMERCIAL item with null parent_bom_item_id is allowed."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "COMMERCIAL",
                "part_number": "COM-ROOT",
                "quantity": "1",
            },
        )
        assert response.status_code == 201
        assert response.json()["parent_bom_item_id"] is None

    def test_technical_with_parent_allowed(self, client: TestClient, admin_headers, draft_bom_item):
        """TECHNICAL item with parent_bom_item_id is allowed (hierarchy)."""
        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_bom_item.entity_version_id,
                "bom_type": "TECHNICAL",
                "part_number": "TECH-CHILD",
                "quantity": "1",
                "parent_bom_item_id": draft_bom_item.id,
            },
        )
        assert response.status_code == 201
        assert response.json()["parent_bom_item_id"] == draft_bom_item.id

    def test_technical_same_part_allowed(self, client: TestClient, admin_headers, db_session, draft_version):
        """TECHNICAL items with same part_number are allowed."""
        db_session.add(
            BOMItem(
                entity_version_id=draft_version.id,
                bom_type=BOMType.TECHNICAL.value,
                part_number="TECH-DUP",
                quantity=Decimal("1"),
            )
        )
        db_session.commit()

        response = client.post(
            "/bom-items/",
            headers=admin_headers,
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "TECH-DUP",
                "quantity": "3",
            },
        )
        assert response.status_code == 201


# ============================================================
# UPDATE BOM ITEM (PATCH /bom-items/{id})
# ============================================================


class TestUpdateBOMItem:
    """Tests for PATCH /bom-items/{id} endpoint."""

    def test_partial_update(self, client: TestClient, admin_headers, draft_bom_item):
        """Partial update changes only the provided fields."""
        response = client.patch(
            f"/bom-items/{draft_bom_item.id}",
            headers=admin_headers,
            json={"description": "Updated description"},
        )
        assert response.status_code == 200
        assert response.json()["description"] == "Updated description"
        assert response.json()["part_number"] == draft_bom_item.part_number

    def test_update_draft_only(self, client: TestClient, admin_headers, db_session, published_version):
        """Update on PUBLISHED version returns 409."""
        item = BOMItem(
            entity_version_id=published_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PUB-001",
            quantity=Decimal("1"),
        )
        db_session.add(item)
        db_session.commit()

        response = client.patch(
            f"/bom-items/{item.id}",
            headers=admin_headers,
            json={"description": "Nope"},
        )
        assert response.status_code == 409

    def test_update_parent_cycle_detection(self, client: TestClient, admin_headers, db_session, draft_bom_item):
        """Setting parent to a child creates a cycle — rejected."""
        child = BOMItem(
            entity_version_id=draft_bom_item.entity_version_id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="CHILD-CYC",
            quantity=Decimal("1"),
            parent_bom_item_id=draft_bom_item.id,
        )
        db_session.add(child)
        db_session.commit()

        # Try to set parent to its own child
        response = client.patch(
            f"/bom-items/{draft_bom_item.id}",
            headers=admin_headers,
            json={"parent_bom_item_id": child.id},
        )
        assert response.status_code == 400
        assert "Circular" in response.json()["detail"]

    def test_update_to_commercial_with_parent_rejected(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Changing bom_type to COMMERCIAL when item has a parent returns 400."""
        parent = BOMItem(
            entity_version_id=draft_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="UPD-PARENT",
            quantity=Decimal("1"),
        )
        db_session.add(parent)
        db_session.flush()

        child = BOMItem(
            entity_version_id=draft_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="UPD-CHILD",
            quantity=Decimal("1"),
            parent_bom_item_id=parent.id,
        )
        db_session.add(child)
        db_session.commit()

        response = client.patch(
            f"/bom-items/{child.id}",
            headers=admin_headers,
            json={"bom_type": "COMMERCIAL"},
        )
        assert response.status_code == 400
        assert "COMMERCIAL" in response.json()["detail"]


# ============================================================
# DELETE BOM ITEM (DELETE /bom-items/{id})
# ============================================================


class TestDeleteBOMItem:
    """Tests for DELETE /bom-items/{id} endpoint."""

    def test_delete_bom_item(self, client: TestClient, admin_headers, draft_bom_item):
        """Delete a BOM item."""
        response = client.delete(f"/bom-items/{draft_bom_item.id}", headers=admin_headers)
        assert response.status_code == 204

        # Verify it's gone
        response = client.get(f"/bom-items/{draft_bom_item.id}", headers=admin_headers)
        assert response.status_code == 404

    def test_delete_cascades_to_children(self, client: TestClient, admin_headers, db_session, draft_bom_item):
        """Deleting a parent cascades to children."""
        child = BOMItem(
            entity_version_id=draft_bom_item.entity_version_id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="CHILD-DEL",
            quantity=Decimal("1"),
            parent_bom_item_id=draft_bom_item.id,
        )
        db_session.add(child)
        db_session.commit()
        child_id = child.id

        response = client.delete(f"/bom-items/{draft_bom_item.id}", headers=admin_headers)
        assert response.status_code == 204

        # Child is also deleted
        response = client.get(f"/bom-items/{child_id}", headers=admin_headers)
        assert response.status_code == 404

    def test_delete_draft_only(self, client: TestClient, admin_headers, db_session, published_version):
        """Delete on PUBLISHED version returns 409."""
        item = BOMItem(
            entity_version_id=published_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PUB-DEL",
            quantity=Decimal("1"),
        )
        db_session.add(item)
        db_session.commit()

        response = client.delete(f"/bom-items/{item.id}", headers=admin_headers)
        assert response.status_code == 409

    def test_user_cannot_delete_bom_item(self, client: TestClient, user_headers, draft_bom_item):
        """Regular user cannot delete BOM items (403)."""
        response = client.delete(f"/bom-items/{draft_bom_item.id}", headers=user_headers)
        assert response.status_code == 403
