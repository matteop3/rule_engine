"""
Test suite for Rules API endpoints.

Tests the full CRUD lifecycle for Rule management including:
- RBAC enforcement (admin/author only)
- DRAFT-only modification policy
- Target field/value ownership validation
- Version immutability on updates

Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Field, Value, Rule, RuleType, FieldType


# ============================================================
# LIST RULES TESTS (GET /rules/)
# ============================================================

class TestListRules:
    """Tests for GET /rules/ endpoint."""

    def test_admin_can_list_rules(self, client: TestClient, admin_headers, draft_rule):
        """Test that admin can list rules."""
        rule = draft_rule["rule"]
        response = client.get(
            f"/rules/?entity_version_id={rule.entity_version_id}",
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_author_can_list_rules(self, client: TestClient, author_headers, draft_rule):
        """Test that author can list rules."""
        rule = draft_rule["rule"]
        response = client.get(
            f"/rules/?entity_version_id={rule.entity_version_id}",
            headers=author_headers
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_regular_user_cannot_list_rules(self, client: TestClient, user_headers, draft_rule):
        """Test that regular user cannot list rules (403)."""
        rule = draft_rule["rule"]
        response = client.get(
            f"/rules/?entity_version_id={rule.entity_version_id}",
            headers=user_headers
        )

        assert response.status_code == 403

    def test_unauthenticated_cannot_list_rules(self, client: TestClient, draft_rule):
        """Test that unauthenticated request returns 401."""
        rule = draft_rule["rule"]
        response = client.get(f"/rules/?entity_version_id={rule.entity_version_id}")

        assert response.status_code == 401

    def test_list_rules_without_filter(self, client: TestClient, admin_headers, draft_rule):
        """Test that listing without filter returns all accessible rules."""
        response = client.get("/rules/", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_rules_pagination(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test pagination parameters work correctly."""
        # Create target and source fields
        target_field = Field(
            entity_version_id=draft_version.id,
            name="pagination_target",
            label="Pagination Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="pagination_source",
            label="Pagination Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        # Create 5 rules with valid conditions
        for i in range(5):
            rule = Rule(
                entity_version_id=draft_version.id,
                target_field_id=target_field.id,
                rule_type=RuleType.VISIBILITY.value,
                description=f"Pagination rule {i}",
                conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": i}]}
            )
            db_session.add(rule)
        db_session.commit()

        response = client.get(
            f"/rules/?entity_version_id={draft_version.id}&limit=2",
            headers=admin_headers
        )

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_rules_limit_over_100_rejected(self, client: TestClient, admin_headers, draft_rule):
        """Test that limit > 100 is rejected with 422."""
        response = client.get("/rules/?limit=200", headers=admin_headers)

        assert response.status_code == 422


# ============================================================
# READ RULE TESTS (GET /rules/{rule_id})
# ============================================================

class TestReadRule:
    """Tests for GET /rules/{rule_id} endpoint."""

    def test_admin_can_read_rule(self, client: TestClient, admin_headers, draft_rule):
        """Test that admin can read rule by ID."""
        rule = draft_rule["rule"]
        response = client.get(f"/rules/{rule.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == rule.id
        assert data["rule_type"] == RuleType.MANDATORY.value

    def test_author_can_read_rule(self, client: TestClient, author_headers, draft_rule):
        """Test that author can read rule by ID."""
        rule = draft_rule["rule"]
        response = client.get(f"/rules/{rule.id}", headers=author_headers)

        assert response.status_code == 200
        assert response.json()["id"] == rule.id

    def test_regular_user_cannot_read_rule(self, client: TestClient, user_headers, draft_rule):
        """Test that regular user cannot read rules (403)."""
        rule = draft_rule["rule"]
        response = client.get(f"/rules/{rule.id}", headers=user_headers)

        assert response.status_code == 403

    def test_read_nonexistent_rule_returns_404(self, client: TestClient, admin_headers):
        """Test that reading non-existent rule returns 404."""
        response = client.get("/rules/99999", headers=admin_headers)

        assert response.status_code == 404

    def test_unauthenticated_cannot_read_rule(self, client: TestClient, draft_rule):
        """Test that unauthenticated request returns 401."""
        rule = draft_rule["rule"]
        response = client.get(f"/rules/{rule.id}")

        assert response.status_code == 401

    def test_read_rule_includes_conditions(self, client: TestClient, admin_headers, draft_rule):
        """Test that rule includes conditions in response."""
        rule = draft_rule["rule"]
        response = client.get(f"/rules/{rule.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "conditions" in data
        assert "criteria" in data["conditions"]


# ============================================================
# CREATE RULE TESTS (POST /rules/)
# ============================================================

class TestCreateRule:
    """Tests for POST /rules/ endpoint."""

    def test_admin_can_create_rule(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that admin can create a rule in DRAFT version."""
        # Create target and source fields
        target_field = Field(
            entity_version_id=draft_version.id,
            name="rule_target_field",
            label="Rule Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="rule_source_field",
            label="Rule Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "visibility",
            "description": "Test visibility rule",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
            "error_message": None
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["target_field_id"] == target_field.id
        assert data["rule_type"] == "visibility"
        assert "id" in data

    def test_author_can_create_rule(
        self, client: TestClient, author_headers, db_session, draft_version
    ):
        """Test that author can create a rule."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="author_rule_target",
            label="Author Target",
            data_type=FieldType.STRING.value,
            is_free_value=True
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="author_rule_source",
            label="Author Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "mandatory",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 100}]}
        }

        response = client.post("/rules/", json=payload, headers=author_headers)

        assert response.status_code == 201

    def test_regular_user_cannot_create_rule(
        self, client: TestClient, user_headers, draft_rule
    ):
        """Test that regular user cannot create rules (403)."""
        rule = draft_rule["rule"]
        target_field = draft_rule["target_field"]
        source_field = draft_rule["source_field"]

        payload = {
            "entity_version_id": rule.entity_version_id,
            "target_field_id": target_field.id,
            "rule_type": "visibility",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": 1}]}
        }

        response = client.post("/rules/", json=payload, headers=user_headers)

        assert response.status_code == 403

    def test_unauthenticated_cannot_create_rule(self, client: TestClient, draft_rule):
        """Test that unauthenticated request returns 401."""
        rule = draft_rule["rule"]
        target_field = draft_rule["target_field"]
        source_field = draft_rule["source_field"]

        payload = {
            "entity_version_id": rule.entity_version_id,
            "target_field_id": target_field.id,
            "rule_type": "visibility",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": 1}]}
        }

        response = client.post("/rules/", json=payload)

        assert response.status_code == 401

    def test_cannot_create_rule_in_published_version(
        self, client: TestClient, admin_headers, published_rule
    ):
        """
        Test DRAFT-only policy: cannot create rule in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        rule = published_rule["rule"]
        target_field = published_rule["target_field"]
        source_field = published_rule["source_field"]

        payload = {
            "entity_version_id": rule.entity_version_id,
            "target_field_id": target_field.id,
            "rule_type": "mandatory",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_create_rule_in_archived_version(
        self, client: TestClient, admin_headers, archived_rule
    ):
        """
        Test DRAFT-only policy: cannot create rule in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        rule = archived_rule["rule"]
        target_field = archived_rule["target_field"]
        source_field = archived_rule["source_field"]

        payload = {
            "entity_version_id": rule.entity_version_id,
            "target_field_id": target_field.id,
            "rule_type": "mandatory",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_target_field_must_belong_to_version(
        self, client: TestClient, admin_headers, db_session, draft_version, second_entity, admin_user
    ):
        """
        Test ownership: target_field must belong to the specified version.
        This is a CRITICAL business rule.
        """
        from app.models.domain import EntityVersion, VersionStatus

        # Create source field in draft_version
        source_field = Field(
            entity_version_id=draft_version.id,
            name="source_field_ok",
            label="Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add(source_field)
        db_session.flush()

        # Create field in a different version
        other_version = EntityVersion(
            entity_id=second_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Other",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(other_version)
        db_session.flush()

        other_field = Field(
            entity_version_id=other_version.id,
            name="other_version_field",
            label="Other Field",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        db_session.add(other_field)
        db_session.commit()

        # Try to create rule with mismatched field
        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": other_field.id,  # Wrong version!
            "rule_type": "visibility",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "version" in response.json()["detail"].lower() or "belong" in response.json()["detail"].lower()

    def test_target_value_must_belong_to_target_field(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """
        Test ownership: target_value must belong to target_field.
        This is a CRITICAL business rule.
        """
        # Create source field for conditions
        source_field = Field(
            entity_version_id=draft_version.id,
            name="source_for_value_test",
            label="Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add(source_field)
        db_session.flush()

        # Create two fields
        field1 = Field(
            entity_version_id=draft_version.id,
            name="field_one",
            label="Field One",
            data_type=FieldType.STRING.value,
            is_free_value=False
        )
        field2 = Field(
            entity_version_id=draft_version.id,
            name="field_two",
            label="Field Two",
            data_type=FieldType.STRING.value,
            is_free_value=False
        )
        db_session.add_all([field1, field2])
        db_session.flush()

        # Create value for field1
        value_for_field1 = Value(field_id=field1.id, value="VAL1", label="Val1")
        # Create value for field2
        value_for_field2 = Value(field_id=field2.id, value="VAL2", label="Val2")
        db_session.add_all([value_for_field1, value_for_field2])
        db_session.commit()

        # Try to create AVAILABILITY rule targeting field1 but with value from field2
        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": field1.id,
            "target_value_id": value_for_field2.id,  # Wrong field!
            "rule_type": "availability",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "field" in response.json()["detail"].lower() or "belong" in response.json()["detail"].lower()

    def test_create_rule_with_target_value(
        self, client: TestClient, admin_headers, rule_with_value_target
    ):
        """Test creating an AVAILABILITY rule that targets a specific value."""
        # The fixture already creates this, we verify it exists
        rule = rule_with_value_target["rule"]

        response = client.get(f"/rules/{rule.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["target_value_id"] == rule_with_value_target["value2"].id
        assert data["rule_type"] == "availability"

    def test_create_rule_for_nonexistent_version(self, client: TestClient, admin_headers):
        """Test that creating rule for non-existent version fails."""
        payload = {
            "entity_version_id": 99999,
            "target_field_id": 1,
            "rule_type": "visibility",
            "conditions": {"criteria": [{"field_id": 1, "operator": "EQUALS", "value": 1}]}
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 404

    def test_create_non_availability_rule_types(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that visibility, mandatory, and validation rule types can be created."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="rule_types_target",
            label="Rule Types Target",
            data_type=FieldType.STRING.value,
            is_free_value=True
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="rule_types_source",
            label="Rule Types Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.commit()

        # These rule types don't require target_value_id
        rule_types = ["visibility", "mandatory", "validation"]

        for rule_type in rule_types:
            payload = {
                "entity_version_id": draft_version.id,
                "target_field_id": target_field.id,
                "rule_type": rule_type,
                "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
                "description": f"Test {rule_type} rule"
            }

            response = client.post("/rules/", json=payload, headers=admin_headers)
            assert response.status_code == 201, f"Failed for rule_type: {rule_type}"

    def test_create_availability_rule_requires_target_value(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that AVAILABILITY rule type requires target_value_id."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="avail_test_target",
            label="Availability Target",
            data_type=FieldType.STRING.value,
            is_free_value=False
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="avail_test_source",
            label="Availability Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        value = Value(field_id=target_field.id, value="TEST", label="Test")
        db_session.add(value)
        db_session.commit()

        # Without target_value_id, availability should fail
        payload_fail = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "availability",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        }

        response_fail = client.post("/rules/", json=payload_fail, headers=admin_headers)
        assert response_fail.status_code == 422  # Validation error

        # With target_value_id, availability should succeed
        payload_ok = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "target_value_id": value.id,
            "rule_type": "availability",
            "conditions": {"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        }

        response_ok = client.post("/rules/", json=payload_ok, headers=admin_headers)
        assert response_ok.status_code == 201

    def test_create_rule_with_conditions(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test creating rule with complex conditions."""
        # Create source and target fields
        source_field = Field(
            entity_version_id=draft_version.id,
            name="condition_source",
            label="Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        target_field = Field(
            entity_version_id=draft_version.id,
            name="condition_target",
            label="Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        db_session.add_all([source_field, target_field])
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "mandatory",
            "conditions": {
                "criteria": [
                    {"field_id": source_field.id, "operator": "GREATER_THAN", "value": 100}
                ]
            },
            "error_message": "Field required when source > 100"
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert len(data["conditions"]["criteria"]) == 1

    def test_create_rule_empty_criteria_fails(
        self, client: TestClient, admin_headers, db_session, draft_version
    ):
        """Test that rules with empty criteria fail validation."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="empty_criteria_target",
            label="Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        db_session.add(target_field)
        db_session.commit()

        payload = {
            "entity_version_id": draft_version.id,
            "target_field_id": target_field.id,
            "rule_type": "visibility",
            "conditions": {"criteria": []}  # Empty criteria not allowed
        }

        response = client.post("/rules/", json=payload, headers=admin_headers)

        assert response.status_code == 422
        assert "criteria" in str(response.json()).lower()


# ============================================================
# UPDATE RULE TESTS (PATCH /rules/{rule_id})
# ============================================================

class TestUpdateRule:
    """Tests for PATCH /rules/{rule_id} endpoint."""

    def test_admin_can_update_rule(self, client: TestClient, admin_headers, draft_rule):
        """Test that admin can update a rule in DRAFT version."""
        rule = draft_rule["rule"]
        payload = {
            "description": "Updated description",
            "error_message": "Updated error message"
        }

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "Updated description"
        assert data["error_message"] == "Updated error message"

    def test_author_can_update_rule(self, client: TestClient, author_headers, draft_rule):
        """Test that author can update a rule."""
        rule = draft_rule["rule"]
        payload = {"description": "Author updated"}

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=author_headers
        )

        assert response.status_code == 200
        assert response.json()["description"] == "Author updated"

    def test_regular_user_cannot_update_rule(self, client: TestClient, user_headers, draft_rule):
        """Test that regular user cannot update rules (403)."""
        rule = draft_rule["rule"]
        payload = {"description": "User updated"}

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=user_headers
        )

        assert response.status_code == 403

    def test_cannot_update_rule_in_published_version(
        self, client: TestClient, admin_headers, published_rule
    ):
        """
        Test DRAFT-only policy: cannot update rule in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        rule = published_rule["rule"]
        payload = {"description": "Should fail"}

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_update_rule_in_archived_version(
        self, client: TestClient, admin_headers, archived_rule
    ):
        """
        Test DRAFT-only policy: cannot update rule in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        rule = archived_rule["rule"]
        payload = {"description": "Should fail"}

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_can_update_target_field(
        self, client: TestClient, admin_headers, db_session, draft_rule
    ):
        """Test that target_field can be updated to another field in same version."""
        rule = draft_rule["rule"]

        # Create another target field in the same version
        new_target = Field(
            entity_version_id=rule.entity_version_id,
            name="new_target",
            label="New Target",
            data_type=FieldType.STRING.value,
            is_free_value=True
        )
        db_session.add(new_target)
        db_session.commit()

        payload = {"target_field_id": new_target.id}

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["target_field_id"] == new_target.id

    def test_cannot_update_target_field_to_different_version(
        self, client: TestClient, admin_headers, db_session, draft_rule, second_entity, admin_user
    ):
        """
        Test ownership: cannot update target_field to field in different version.
        This is a CRITICAL business rule.
        """
        from app.models.domain import EntityVersion, VersionStatus

        rule = draft_rule["rule"]

        # Create field in different version
        other_version = EntityVersion(
            entity_id=second_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Other",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id
        )
        db_session.add(other_version)
        db_session.flush()

        other_field = Field(
            entity_version_id=other_version.id,
            name="other_field",
            label="Other",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        db_session.add(other_field)
        db_session.commit()

        payload = {"target_field_id": other_field.id}

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 400
        assert "version" in response.json()["detail"].lower() or "belong" in response.json()["detail"].lower()

    def test_can_update_conditions(self, client: TestClient, admin_headers, draft_rule):
        """Test that conditions can be updated."""
        rule = draft_rule["rule"]
        source_field = draft_rule["source_field"]

        new_conditions = {
            "criteria": [
                {"field_id": source_field.id, "operator": "LESS_THAN", "value": 50}
            ]
        }

        payload = {"conditions": new_conditions}

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["conditions"]["criteria"][0]["operator"] == "LESS_THAN"

    def test_can_update_rule_type(self, client: TestClient, admin_headers, draft_rule):
        """Test that rule_type can be updated."""
        rule = draft_rule["rule"]
        payload = {"rule_type": "visibility"}

        response = client.patch(
            f"/rules/{rule.id}",
            json=payload,
            headers=admin_headers
        )

        assert response.status_code == 200
        assert response.json()["rule_type"] == "visibility"

    def test_empty_update_handled(self, client: TestClient, admin_headers, draft_rule):
        """Test that empty update payload is handled gracefully."""
        rule = draft_rule["rule"]

        response = client.patch(
            f"/rules/{rule.id}",
            json={},
            headers=admin_headers
        )

        assert response.status_code == 200

    def test_update_nonexistent_rule_returns_404(self, client: TestClient, admin_headers):
        """Test that updating non-existent rule returns 404."""
        payload = {"description": "Ghost"}

        response = client.patch("/rules/99999", json=payload, headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# DELETE RULE TESTS (DELETE /rules/{rule_id})
# ============================================================

class TestDeleteRule:
    """Tests for DELETE /rules/{rule_id} endpoint."""

    def test_admin_can_delete_rule(self, client: TestClient, admin_headers, draft_rule):
        """Test that admin can delete a rule in DRAFT version."""
        rule = draft_rule["rule"]

        response = client.delete(f"/rules/{rule.id}", headers=admin_headers)

        assert response.status_code == 204

    def test_author_can_delete_rule(
        self, client: TestClient, author_headers, db_session, draft_version
    ):
        """Test that author can delete a rule."""
        target_field = Field(
            entity_version_id=draft_version.id,
            name="delete_target",
            label="Delete Target",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True
        )
        source_field = Field(
            entity_version_id=draft_version.id,
            name="delete_source",
            label="Delete Source",
            data_type=FieldType.NUMBER.value,
            is_free_value=True
        )
        db_session.add_all([target_field, source_field])
        db_session.flush()

        rule = Rule(
            entity_version_id=draft_version.id,
            target_field_id=target_field.id,
            rule_type=RuleType.VISIBILITY.value,
            description="To delete",
            conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
        )
        db_session.add(rule)
        db_session.commit()

        response = client.delete(f"/rules/{rule.id}", headers=author_headers)

        assert response.status_code == 204

    def test_regular_user_cannot_delete_rule(self, client: TestClient, user_headers, draft_rule):
        """Test that regular user cannot delete rules (403)."""
        rule = draft_rule["rule"]

        response = client.delete(f"/rules/{rule.id}", headers=user_headers)

        assert response.status_code == 403

    def test_unauthenticated_cannot_delete_rule(self, client: TestClient, draft_rule):
        """Test that unauthenticated request returns 401."""
        rule = draft_rule["rule"]

        response = client.delete(f"/rules/{rule.id}")

        assert response.status_code == 401

    def test_cannot_delete_rule_in_published_version(
        self, client: TestClient, admin_headers, published_rule
    ):
        """
        Test DRAFT-only policy: cannot delete rule in PUBLISHED version.
        This is a CRITICAL business rule.
        """
        rule = published_rule["rule"]

        response = client.delete(f"/rules/{rule.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_delete_rule_in_archived_version(
        self, client: TestClient, admin_headers, archived_rule
    ):
        """
        Test DRAFT-only policy: cannot delete rule in ARCHIVED version.
        This is a CRITICAL business rule.
        """
        rule = archived_rule["rule"]

        response = client.delete(f"/rules/{rule.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_delete_nonexistent_rule_returns_404(self, client: TestClient, admin_headers):
        """Test that deleting non-existent rule returns 404."""
        response = client.delete("/rules/99999", headers=admin_headers)

        assert response.status_code == 404
