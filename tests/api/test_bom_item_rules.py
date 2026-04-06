"""
Test suite for BOM Item Rules API endpoints.

Tests the full CRUD lifecycle for BOM Item Rule management including:
- RBAC enforcement (admin/author only)
- DRAFT-only modification policy
- bom_item_id must belong to the specified entity_version_id
- field_id values in conditions.criteria must belong to the same entity_version_id
"""

from decimal import Decimal

from fastapi.testclient import TestClient

from app.models.domain import BOMItem, BOMItemRule, BOMType, Field, FieldType

# ============================================================
# LIST BOM ITEM RULES (GET /bom-item-rules/)
# ============================================================


class TestListBOMItemRules:
    """Tests for GET /bom-item-rules/ endpoint."""

    def test_list_by_bom_item_id(self, client: TestClient, admin_headers, db_session, draft_bom_item, draft_field):
        """List rules filtered by bom_item_id."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "A"}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = client.get(
            f"/bom-item-rules/?bom_item_id={draft_bom_item.id}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert all(r["bom_item_id"] == draft_bom_item.id for r in data)

    def test_list_by_entity_version_id(
        self, client: TestClient, admin_headers, db_session, draft_bom_item, draft_field
    ):
        """List rules filtered by entity_version_id."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "B"}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = client.get(
            f"/bom-item-rules/?entity_version_id={draft_bom_item.entity_version_id}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert all(r["entity_version_id"] == draft_bom_item.entity_version_id for r in data)

    def test_list_requires_filter(self, client: TestClient, admin_headers):
        """Listing without any filter returns 400."""
        response = client.get("/bom-item-rules/", headers=admin_headers)
        assert response.status_code == 400
        assert "filter" in response.json()["detail"].lower()

    def test_author_can_list(self, client: TestClient, author_headers, db_session, draft_bom_item, draft_field):
        """Author can list BOM item rules."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "C"}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = client.get(
            f"/bom-item-rules/?bom_item_id={draft_bom_item.id}",
            headers=author_headers,
        )
        assert response.status_code == 200

    def test_user_cannot_list(self, client: TestClient, user_headers, draft_bom_item):
        """Regular user cannot list BOM item rules (403)."""
        response = client.get(
            f"/bom-item-rules/?bom_item_id={draft_bom_item.id}",
            headers=user_headers,
        )
        assert response.status_code == 403


# ============================================================
# READ BOM ITEM RULE (GET /bom-item-rules/{id})
# ============================================================


class TestReadBOMItemRule:
    """Tests for GET /bom-item-rules/{id} endpoint."""

    def test_read_bom_item_rule(self, client: TestClient, admin_headers, db_session, draft_bom_item, draft_field):
        """Read a single BOM item rule by ID."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "X"}]},
            description="Test rule",
        )
        db_session.add(rule)
        db_session.commit()

        response = client.get(f"/bom-item-rules/{rule.id}", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == rule.id
        assert data["bom_item_id"] == draft_bom_item.id
        assert data["description"] == "Test rule"

    def test_read_not_found(self, client: TestClient, admin_headers):
        """404 on missing BOM item rule."""
        response = client.get("/bom-item-rules/99999", headers=admin_headers)
        assert response.status_code == 404


# ============================================================
# CREATE BOM ITEM RULE (POST /bom-item-rules/)
# ============================================================


class TestCreateBOMItemRule:
    """Tests for POST /bom-item-rules/ endpoint."""

    def test_create_valid_rule(self, client: TestClient, admin_headers, draft_bom_item, draft_field):
        """Create a BOM item rule with valid data."""
        response = client.post(
            "/bom-item-rules/",
            headers=admin_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "Red"}]},
                "description": "Include when field is Red",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["bom_item_id"] == draft_bom_item.id
        assert data["entity_version_id"] == draft_bom_item.entity_version_id
        assert data["description"] == "Include when field is Red"
        assert len(data["conditions"]["criteria"]) == 1

    def test_create_rule_multiple_criteria(
        self, client: TestClient, admin_headers, db_session, draft_bom_item, draft_field
    ):
        """Create a rule with multiple criteria (AND logic within a single rule)."""
        second_field = Field(
            entity_version_id=draft_bom_item.entity_version_id,
            name="second_field",
            label="Second Field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add(second_field)
        db_session.commit()

        response = client.post(
            "/bom-item-rules/",
            headers=admin_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {
                    "criteria": [
                        {"field_id": draft_field.id, "operator": "EQUALS", "value": "A"},
                        {"field_id": second_field.id, "operator": "EQUALS", "value": "B"},
                    ]
                },
            },
        )
        assert response.status_code == 201
        assert len(response.json()["conditions"]["criteria"]) == 2

    def test_create_draft_only_published_rejected(
        self, client: TestClient, admin_headers, db_session, published_version
    ):
        """Creating on a PUBLISHED version returns 409."""
        bom_item = BOMItem(
            entity_version_id=published_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PUB-BOM",
            quantity=Decimal("1"),
        )
        field = Field(
            entity_version_id=published_version.id,
            name="pub_field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([bom_item, field])
        db_session.commit()

        response = client.post(
            "/bom-item-rules/",
            headers=admin_headers,
            json={
                "bom_item_id": bom_item.id,
                "entity_version_id": published_version.id,
                "conditions": {"criteria": [{"field_id": field.id, "operator": "EQUALS", "value": "X"}]},
            },
        )
        assert response.status_code == 409

    def test_create_draft_only_archived_rejected(self, client: TestClient, admin_headers, db_session, archived_version):
        """Creating on an ARCHIVED version returns 409."""
        bom_item = BOMItem(
            entity_version_id=archived_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="ARC-BOM",
            quantity=Decimal("1"),
        )
        field = Field(
            entity_version_id=archived_version.id,
            name="arc_field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([bom_item, field])
        db_session.commit()

        response = client.post(
            "/bom-item-rules/",
            headers=admin_headers,
            json={
                "bom_item_id": bom_item.id,
                "entity_version_id": archived_version.id,
                "conditions": {"criteria": [{"field_id": field.id, "operator": "EQUALS", "value": "X"}]},
            },
        )
        assert response.status_code == 409

    def test_bom_item_must_belong_to_version(
        self, client: TestClient, admin_headers, db_session, draft_version, second_entity
    ):
        """bom_item_id must belong to the specified entity_version_id."""
        from app.models.domain import EntityVersion, VersionStatus

        other_version = EntityVersion(
            entity_id=second_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
        )
        db_session.add(other_version)
        db_session.flush()

        other_bom_item = BOMItem(
            entity_version_id=other_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="OTHER-BOM",
            quantity=Decimal("1"),
        )
        db_session.add(other_bom_item)
        db_session.commit()

        # Use a field from draft_version for valid conditions
        field = Field(
            entity_version_id=draft_version.id,
            name="bom_test_field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add(field)
        db_session.commit()

        response = client.post(
            "/bom-item-rules/",
            headers=admin_headers,
            json={
                "bom_item_id": other_bom_item.id,
                "entity_version_id": draft_version.id,
                "conditions": {"criteria": [{"field_id": field.id, "operator": "EQUALS", "value": "X"}]},
            },
        )
        assert response.status_code == 400
        assert "does not belong" in response.json()["detail"]

    def test_field_id_in_conditions_must_belong_to_version(
        self, client: TestClient, admin_headers, db_session, draft_bom_item, second_entity
    ):
        """field_id in conditions.criteria must belong to the same entity_version_id."""
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
            name="other_field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add(other_field)
        db_session.commit()

        response = client.post(
            "/bom-item-rules/",
            headers=admin_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {"criteria": [{"field_id": other_field.id, "operator": "EQUALS", "value": "test"}]},
            },
        )
        assert response.status_code == 400

    def test_create_with_empty_criteria_rejected(self, client: TestClient, admin_headers, draft_bom_item):
        """Create a rule with empty criteria list returns 422 (at least one criterion required)."""
        response = client.post(
            "/bom-item-rules/",
            headers=admin_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {"criteria": []},
            },
        )
        assert response.status_code == 422

    def test_user_cannot_create(self, client: TestClient, user_headers, draft_bom_item, draft_field):
        """Regular user cannot create BOM item rules (403)."""
        response = client.post(
            "/bom-item-rules/",
            headers=user_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "X"}]},
            },
        )
        assert response.status_code == 403

    def test_author_can_create(self, client: TestClient, author_headers, draft_bom_item, draft_field):
        """Author can create BOM item rules."""
        response = client.post(
            "/bom-item-rules/",
            headers=author_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "X"}]},
            },
        )
        assert response.status_code == 201


# ============================================================
# UPDATE BOM ITEM RULE (PATCH /bom-item-rules/{id})
# ============================================================


class TestUpdateBOMItemRule:
    """Tests for PATCH /bom-item-rules/{id} endpoint."""

    def test_partial_update_description(
        self, client: TestClient, admin_headers, db_session, draft_bom_item, draft_field
    ):
        """Partial update changes only the provided fields."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "A"}]},
            description="Original",
        )
        db_session.add(rule)
        db_session.commit()

        response = client.patch(
            f"/bom-item-rules/{rule.id}",
            headers=admin_headers,
            json={"description": "Updated description"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "Updated description"
        # Conditions unchanged
        assert len(data["conditions"]["criteria"]) == 1

    def test_update_conditions(self, client: TestClient, admin_headers, db_session, draft_bom_item, draft_field):
        """Update conditions with valid field references."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "Old"}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = client.patch(
            f"/bom-item-rules/{rule.id}",
            headers=admin_headers,
            json={"conditions": {"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "New"}]}},
        )
        assert response.status_code == 200
        assert len(response.json()["conditions"]["criteria"]) == 1

    def test_update_conditions_invalid_field(
        self, client: TestClient, admin_headers, db_session, draft_bom_item, second_entity
    ):
        """Update with field_id from another version returns 400."""
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
            name="bad_field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add(other_field)
        db_session.commit()

        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": 1, "operator": "EQUALS", "value": "placeholder"}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = client.patch(
            f"/bom-item-rules/{rule.id}",
            headers=admin_headers,
            json={"conditions": {"criteria": [{"field_id": other_field.id, "operator": "EQUALS", "value": "bad"}]}},
        )
        assert response.status_code == 400

    def test_update_draft_only(self, client: TestClient, admin_headers, db_session, published_version):
        """Update on PUBLISHED version returns 409."""
        bom_item = BOMItem(
            entity_version_id=published_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PUB-BOM-UPD",
            quantity=Decimal("1"),
        )
        field = Field(
            entity_version_id=published_version.id,
            name="pub_field_upd",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([bom_item, field])
        db_session.flush()

        rule = BOMItemRule(
            bom_item_id=bom_item.id,
            entity_version_id=published_version.id,
            conditions={"criteria": [{"field_id": field.id, "operator": "EQUALS", "value": "X"}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = client.patch(
            f"/bom-item-rules/{rule.id}",
            headers=admin_headers,
            json={"description": "Nope"},
        )
        assert response.status_code == 409

    def test_empty_update(self, client: TestClient, admin_headers, db_session, draft_bom_item, draft_field):
        """Empty update returns current state without changes."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "A"}]},
            description="Unchanged",
        )
        db_session.add(rule)
        db_session.commit()

        response = client.patch(
            f"/bom-item-rules/{rule.id}",
            headers=admin_headers,
            json={},
        )
        assert response.status_code == 200
        assert response.json()["description"] == "Unchanged"


# ============================================================
# DELETE BOM ITEM RULE (DELETE /bom-item-rules/{id})
# ============================================================


class TestDeleteBOMItemRule:
    """Tests for DELETE /bom-item-rules/{id} endpoint."""

    def test_delete_rule(self, client: TestClient, admin_headers, db_session, draft_bom_item, draft_field):
        """Delete a BOM item rule."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "A"}]},
        )
        db_session.add(rule)
        db_session.commit()
        rule_id = rule.id

        response = client.delete(f"/bom-item-rules/{rule_id}", headers=admin_headers)
        assert response.status_code == 204

        # Verify deletion
        response = client.get(f"/bom-item-rules/{rule_id}", headers=admin_headers)
        assert response.status_code == 404

    def test_delete_draft_only(self, client: TestClient, admin_headers, db_session, published_version):
        """Delete on PUBLISHED version returns 409."""
        bom_item = BOMItem(
            entity_version_id=published_version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PUB-BOM-DEL",
            quantity=Decimal("1"),
        )
        field = Field(
            entity_version_id=published_version.id,
            name="pub_field_del",
            data_type=FieldType.STRING.value,
            is_free_value=True,
        )
        db_session.add_all([bom_item, field])
        db_session.flush()

        rule = BOMItemRule(
            bom_item_id=bom_item.id,
            entity_version_id=published_version.id,
            conditions={"criteria": [{"field_id": field.id, "operator": "EQUALS", "value": "X"}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = client.delete(f"/bom-item-rules/{rule.id}", headers=admin_headers)
        assert response.status_code == 409

    def test_user_cannot_delete(self, client: TestClient, user_headers, db_session, draft_bom_item, draft_field):
        """Regular user cannot delete BOM item rules (403)."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "A"}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = client.delete(f"/bom-item-rules/{rule.id}", headers=user_headers)
        assert response.status_code == 403

    def test_delete_not_found(self, client: TestClient, admin_headers):
        """Delete non-existent rule returns 404."""
        response = client.delete("/bom-item-rules/99999", headers=admin_headers)
        assert response.status_code == 404


# ============================================================
# RBAC (cross-cutting)
# ============================================================


class TestBOMItemRuleRBAC:
    """Cross-cutting RBAC tests for BOM item rule endpoints."""

    def test_admin_full_access(self, client: TestClient, admin_headers, draft_bom_item, draft_field):
        """Admin can perform all CRUD operations."""
        # Create
        response = client.post(
            "/bom-item-rules/",
            headers=admin_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "A"}]},
            },
        )
        assert response.status_code == 201
        rule_id = response.json()["id"]

        # Read
        response = client.get(f"/bom-item-rules/{rule_id}", headers=admin_headers)
        assert response.status_code == 200

        # Update
        response = client.patch(
            f"/bom-item-rules/{rule_id}",
            headers=admin_headers,
            json={"description": "Admin update"},
        )
        assert response.status_code == 200

        # Delete
        response = client.delete(f"/bom-item-rules/{rule_id}", headers=admin_headers)
        assert response.status_code == 204

    def test_author_full_access(self, client: TestClient, author_headers, draft_bom_item, draft_field):
        """Author can perform all CRUD operations."""
        # Create
        response = client.post(
            "/bom-item-rules/",
            headers=author_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "A"}]},
            },
        )
        assert response.status_code == 201
        rule_id = response.json()["id"]

        # Read
        response = client.get(f"/bom-item-rules/{rule_id}", headers=author_headers)
        assert response.status_code == 200

        # Update
        response = client.patch(
            f"/bom-item-rules/{rule_id}",
            headers=author_headers,
            json={"description": "Author update"},
        )
        assert response.status_code == 200

        # Delete
        response = client.delete(f"/bom-item-rules/{rule_id}", headers=author_headers)
        assert response.status_code == 204

    def test_user_denied_all_operations(
        self, client: TestClient, user_headers, db_session, draft_bom_item, draft_field
    ):
        """Regular user is denied all CRUD operations."""
        rule = BOMItemRule(
            bom_item_id=draft_bom_item.id,
            entity_version_id=draft_bom_item.entity_version_id,
            conditions={"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "A"}]},
        )
        db_session.add(rule)
        db_session.commit()

        # List
        response = client.get(
            f"/bom-item-rules/?bom_item_id={draft_bom_item.id}",
            headers=user_headers,
        )
        assert response.status_code == 403

        # Read
        response = client.get(f"/bom-item-rules/{rule.id}", headers=user_headers)
        assert response.status_code == 403

        # Create
        response = client.post(
            "/bom-item-rules/",
            headers=user_headers,
            json={
                "bom_item_id": draft_bom_item.id,
                "entity_version_id": draft_bom_item.entity_version_id,
                "conditions": {"criteria": [{"field_id": draft_field.id, "operator": "EQUALS", "value": "X"}]},
            },
        )
        assert response.status_code == 403

        # Update
        response = client.patch(
            f"/bom-item-rules/{rule.id}",
            headers=user_headers,
            json={"description": "Nope"},
        )
        assert response.status_code == 403

        # Delete
        response = client.delete(f"/bom-item-rules/{rule.id}", headers=user_headers)
        assert response.status_code == 403
