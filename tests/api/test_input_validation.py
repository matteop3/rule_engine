"""
Tests for API input validation: wrong types, missing fields, invalid values,
empty/null payloads. Verifies that malformed requests return correct error
responses with meaningful field references.
"""

from fastapi.testclient import TestClient


class TestWrongTypes:
    """Payloads with values of the wrong type produce 422."""

    def test_field_create_non_string_data_type(self, client: TestClient, admin_headers, draft_version):
        """data_type must be a valid string enum, not an integer."""
        response = client.post(
            "/fields/",
            json={
                "entity_version_id": draft_version.id,
                "name": "bad_type",
                "data_type": 123,
                "is_free_value": True,
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("data_type" in str(e) for e in body.get("detail", []))

    def test_bom_item_create_non_numeric_quantity(self, client: TestClient, admin_headers, draft_version):
        """quantity must be numeric, not an arbitrary string."""
        response = client.post(
            "/bom-items/",
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "BAD-QTY",
                "quantity": "abc",
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("quantity" in str(e) for e in body.get("detail", []))

    def test_rule_create_non_integer_field_id_in_conditions(self, client: TestClient, admin_headers, draft_field):
        """field_id in rule conditions must be an integer."""
        response = client.post(
            "/rules/",
            json={
                "entity_version_id": draft_field.entity_version_id,
                "target_field_id": draft_field.id,
                "rule_type": "visibility",
                "conditions": {
                    "criteria": [{"field_id": "abc", "operator": "EQUALS", "value": "X"}],
                },
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("field_id" in str(e) for e in body.get("detail", []))

    def test_configuration_create_non_list_data(self, client: TestClient, admin_headers, draft_version):
        """data must be a list, not a string."""
        response = client.post(
            "/configurations/",
            json={
                "entity_version_id": draft_version.id,
                "data": "not a list",
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("data" in str(e) for e in body.get("detail", []))


class TestMissingFields:
    """Payloads missing required fields produce 422."""

    def test_field_create_missing_name(self, client: TestClient, admin_headers, draft_version):
        """Field creation without 'name' fails validation."""
        response = client.post(
            "/fields/",
            json={
                "entity_version_id": draft_version.id,
                "data_type": "string",
                "is_free_value": True,
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("name" in str(e) for e in body.get("detail", []))

    def test_bom_item_create_missing_part_number(self, client: TestClient, admin_headers, draft_version):
        """BOM item creation without 'part_number' fails validation."""
        response = client.post(
            "/bom-items/",
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "quantity": 1,
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("part_number" in str(e) for e in body.get("detail", []))

    def test_rule_create_missing_conditions(self, client: TestClient, admin_headers, draft_field):
        """Rule creation without 'conditions' fails validation."""
        response = client.post(
            "/rules/",
            json={
                "entity_version_id": draft_field.entity_version_id,
                "target_field_id": draft_field.id,
                "rule_type": "visibility",
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("conditions" in str(e) for e in body.get("detail", []))

    def test_configuration_create_missing_entity_version_id(self, client: TestClient, admin_headers):
        """Configuration creation without 'entity_version_id' fails validation."""
        response = client.post(
            "/configurations/",
            json={
                "data": [{"field_id": 1, "value": "test"}],
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("entity_version_id" in str(e) for e in body.get("detail", []))


class TestInvalidValues:
    """Payloads with invalid enum or constraint values."""

    def test_field_create_invalid_data_type(self, client: TestClient, admin_headers, draft_version):
        """data_type 'xml' is not a valid FieldType enum value."""
        response = client.post(
            "/fields/",
            json={
                "entity_version_id": draft_version.id,
                "name": "invalid_dt",
                "data_type": "xml",
                "is_free_value": True,
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("data_type" in str(e) for e in body.get("detail", []))

    def test_bom_item_create_invalid_bom_type(self, client: TestClient, admin_headers, draft_version):
        """bom_type 'HYBRID' is not a valid BOMType enum value."""
        response = client.post(
            "/bom-items/",
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "HYBRID",
                "part_number": "BAD-TYPE",
                "quantity": 1,
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("bom_type" in str(e) for e in body.get("detail", []))

    def test_rule_create_invalid_operator(self, client: TestClient, admin_headers, draft_field):
        """Operator 'LIKE' is not in the CriterionOperator literal."""
        response = client.post(
            "/rules/",
            json={
                "entity_version_id": draft_field.entity_version_id,
                "target_field_id": draft_field.id,
                "rule_type": "visibility",
                "conditions": {
                    "criteria": [{"field_id": draft_field.id, "operator": "LIKE", "value": "X"}],
                },
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("operator" in str(e) for e in body.get("detail", []))

    def test_rule_create_empty_criteria(self, client: TestClient, admin_headers, draft_field):
        """Empty criteria list is rejected by the field validator."""
        response = client.post(
            "/rules/",
            json={
                "entity_version_id": draft_field.entity_version_id,
                "target_field_id": draft_field.id,
                "rule_type": "visibility",
                "conditions": {
                    "criteria": [],
                },
            },
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        assert any("criteria" in str(e) for e in body.get("detail", []))

    def test_bom_item_create_negative_quantity(self, client: TestClient, admin_headers, draft_version):
        """Negative quantity is rejected at router level with 400."""
        response = client.post(
            "/bom-items/",
            json={
                "entity_version_id": draft_version.id,
                "bom_type": "TECHNICAL",
                "part_number": "NEG-QTY",
                "quantity": -5,
            },
            headers=admin_headers,
        )
        assert response.status_code == 400
        body = response.json()
        assert "quantity" in body.get("detail", "").lower() or "Quantity" in body.get("detail", "")


class TestEmptyPayloads:
    """Empty and null request bodies."""

    def test_field_create_empty_body(self, client: TestClient, admin_headers):
        """POST /fields/ with empty object fails validation."""
        response = client.post(
            "/fields/",
            json={},
            headers=admin_headers,
        )
        assert response.status_code == 422
        body = response.json()
        # At least one required field must be mentioned
        detail_str = str(body.get("detail", []))
        assert "name" in detail_str or "entity_version_id" in detail_str

    def test_bom_item_create_null_body(self, client: TestClient, admin_headers):
        """POST /bom-items/ with null body fails."""
        response = client.post(
            "/bom-items/",
            content="null",
            headers={**admin_headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422
