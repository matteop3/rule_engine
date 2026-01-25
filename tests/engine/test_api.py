"""
Test suite for Engine API endpoint.

Tests POST /engine/calculate with focus on:
- Authentication and authorization (RBAC)
- Calculation functionality via HTTP
- Rule evaluation via API
- Error handling
"""

import pytest
from fastapi.testclient import TestClient
from datetime import date, timedelta

from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    FieldType, RuleType, VersionStatus, User, UserRole
)
from app.core.security import get_password_hash, create_access_token


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def engine_scenario(db_session, admin_user):
    """
    Complete scenario for engine API tests with all rule types.
    Creates a PUBLISHED version with fields, values, and rules.
    """
    entity = Entity(
        name="Engine Test Entity",
        description="For engine API tests",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(entity)
    db_session.flush()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        changelog="Engine test version",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(version)
    db_session.flush()

    # Fields
    field_type = Field(
        entity_version_id=version.id,
        name="vehicle_type",
        label="Vehicle Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        sequence=1
    )
    field_value = Field(
        entity_version_id=version.id,
        name="vehicle_value",
        label="Vehicle Value",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        sequence=2
    )
    field_alarm = Field(
        entity_version_id=version.id,
        name="has_alarm",
        label="Has Alarm",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        sequence=3
    )
    field_coverage = Field(
        entity_version_id=version.id,
        name="coverage_type",
        label="Coverage Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        sequence=4
    )
    field_birthdate = Field(
        entity_version_id=version.id,
        name="birthdate",
        label="Birth Date",
        data_type=FieldType.DATE.value,
        is_free_value=True,
        is_required=True,
        sequence=5
    )
    db_session.add_all([field_type, field_value, field_alarm, field_coverage, field_birthdate])
    db_session.flush()

    # Values for vehicle_type
    val_car = Value(field_id=field_type.id, value="CAR", label="Car", is_default=True)
    val_moto = Value(field_id=field_type.id, value="MOTO", label="Motorcycle", is_default=False)
    val_truck = Value(field_id=field_type.id, value="TRUCK", label="Truck", is_default=False)

    # Values for coverage_type
    val_basic = Value(field_id=field_coverage.id, value="BASIC", label="Basic", is_default=True)
    val_premium = Value(field_id=field_coverage.id, value="PREMIUM", label="Premium", is_default=False)

    db_session.add_all([val_car, val_moto, val_truck, val_basic, val_premium])
    db_session.flush()

    # Rules
    # MANDATORY: Alarm required if value > 50000
    rule_mandatory = Rule(
        entity_version_id=version.id,
        target_field_id=field_alarm.id,
        rule_type=RuleType.MANDATORY.value,
        description="Alarm mandatory for high-value vehicles",
        conditions={"criteria": [{"field_id": field_value.id, "operator": "GREATER_THAN", "value": 50000}]}
    )

    # VISIBILITY: Hide alarm for motorcycles
    rule_visibility = Rule(
        entity_version_id=version.id,
        target_field_id=field_alarm.id,
        rule_type=RuleType.VISIBILITY.value,
        description="Hide alarm for motorcycles",
        conditions={"criteria": [{"field_id": field_type.id, "operator": "NOT_EQUALS", "value": "MOTO"}]}
    )

    # AVAILABILITY: Basic coverage not available for trucks
    rule_availability = Rule(
        entity_version_id=version.id,
        target_field_id=field_coverage.id,
        target_value_id=val_basic.id,
        rule_type=RuleType.AVAILABILITY.value,
        description="Basic coverage not for trucks",
        conditions={"criteria": [{"field_id": field_type.id, "operator": "NOT_EQUALS", "value": "TRUCK"}]}
    )

    # VALIDATION: Must be adult (18+)
    # Note: VALIDATION rules use "negative pattern" - the condition describes the INVALID state
    # So we check if birthdate > adult_date (i.e., born too recently = minor = invalid)
    adult_date = date.today() - timedelta(days=18*365)
    rule_validation = Rule(
        entity_version_id=version.id,
        target_field_id=field_birthdate.id,
        rule_type=RuleType.VALIDATION.value,
        description="Must be at least 18 years old",
        conditions={"criteria": [{"field_id": field_birthdate.id, "operator": "GREATER_THAN", "value": str(adult_date)}]},
        error_message="Must be at least 18 years old"
    )

    db_session.add_all([rule_mandatory, rule_visibility, rule_availability, rule_validation])
    db_session.commit()

    return {
        "entity": entity,
        "version": version,
        "fields": {
            "type": field_type,
            "value": field_value,
            "alarm": field_alarm,
            "coverage": field_coverage,
            "birthdate": field_birthdate
        },
        "values": {
            "car": val_car,
            "moto": val_moto,
            "truck": val_truck,
            "basic": val_basic,
            "premium": val_premium
        },
        "rules": {
            "mandatory": rule_mandatory,
            "visibility": rule_visibility,
            "availability": rule_availability,
            "validation": rule_validation
        }
    }


@pytest.fixture(scope="function")
def draft_only_scenario(db_session, admin_user):
    """Entity with only a DRAFT version (no PUBLISHED)."""
    entity = Entity(
        name="Draft Only Entity",
        description="Has no published version",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(entity)
    db_session.flush()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.DRAFT,
        changelog="Draft version",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(version)
    db_session.flush()

    field = Field(
        entity_version_id=version.id,
        name="test_field",
        label="Test Field",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=False,
        sequence=1
    )
    db_session.add(field)
    db_session.commit()

    return {"entity": entity, "version": version, "field": field}


@pytest.fixture(scope="function")
def archived_scenario(db_session, admin_user):
    """Entity with an ARCHIVED version."""
    entity = Entity(
        name="Archived Entity",
        description="Has archived version",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(entity)
    db_session.flush()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.ARCHIVED,
        changelog="Archived version",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(version)
    db_session.flush()

    field = Field(
        entity_version_id=version.id,
        name="archived_field",
        label="Archived Field",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=False,
        sequence=1
    )
    db_session.add(field)
    db_session.commit()

    return {"entity": entity, "version": version, "field": field}


# ============================================================
# AUTHENTICATION TESTS
# ============================================================

class TestEngineAuth:
    """Tests for authentication on POST /engine/calculate."""

    def test_unauthenticated_cannot_calculate(self, client: TestClient, engine_scenario):
        """Test that unauthenticated request returns 401."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload)

        assert response.status_code == 401

    def test_invalid_token_rejected(self, client: TestClient, engine_scenario):
        """Test that invalid token is rejected."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": []
        }
        headers = {"Authorization": "Bearer invalid_token_12345"}

        response = client.post("/engine/calculate", json=payload, headers=headers)

        assert response.status_code == 401


# ============================================================
# AUTHORIZATION TESTS
# ============================================================

class TestEngineAuthorization:
    """Tests for role-based access control on engine calculations."""

    def test_user_can_calculate_on_published(
        self, client: TestClient, user_headers, engine_scenario
    ):
        """Test that USER can calculate on PUBLISHED version."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "entity_version_id": engine_scenario["version"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=user_headers)

        assert response.status_code == 200

    def test_user_cannot_calculate_on_draft(
        self, client: TestClient, user_headers, draft_only_scenario
    ):
        """Test that USER cannot calculate on DRAFT version (403)."""
        payload = {
            "entity_id": draft_only_scenario["entity"].id,
            "entity_version_id": draft_only_scenario["version"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=user_headers)

        assert response.status_code == 403
        assert "published" in response.json()["detail"].lower()

    def test_user_cannot_calculate_on_archived(
        self, client: TestClient, user_headers, archived_scenario
    ):
        """Test that USER cannot calculate on ARCHIVED version (403)."""
        payload = {
            "entity_id": archived_scenario["entity"].id,
            "entity_version_id": archived_scenario["version"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=user_headers)

        assert response.status_code == 403

    def test_user_default_uses_published(
        self, client: TestClient, user_headers, engine_scenario
    ):
        """Test that USER without version_id gets PUBLISHED by default."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=user_headers)

        assert response.status_code == 200

    def test_author_can_calculate_on_draft(
        self, client: TestClient, author_headers, draft_only_scenario
    ):
        """Test that AUTHOR can calculate on DRAFT version (for preview)."""
        payload = {
            "entity_id": draft_only_scenario["entity"].id,
            "entity_version_id": draft_only_scenario["version"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=author_headers)

        assert response.status_code == 200

    def test_author_can_calculate_on_published(
        self, client: TestClient, author_headers, engine_scenario
    ):
        """Test that AUTHOR can calculate on PUBLISHED version."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "entity_version_id": engine_scenario["version"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=author_headers)

        assert response.status_code == 200

    def test_author_can_calculate_on_archived(
        self, client: TestClient, author_headers, archived_scenario
    ):
        """Test that AUTHOR can calculate on ARCHIVED version."""
        payload = {
            "entity_id": archived_scenario["entity"].id,
            "entity_version_id": archived_scenario["version"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=author_headers)

        assert response.status_code == 200

    def test_admin_can_calculate_on_draft(
        self, client: TestClient, admin_headers, draft_only_scenario
    ):
        """Test that ADMIN can calculate on DRAFT version."""
        payload = {
            "entity_id": draft_only_scenario["entity"].id,
            "entity_version_id": draft_only_scenario["version"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200

    def test_admin_can_calculate_on_archived(
        self, client: TestClient, admin_headers, archived_scenario
    ):
        """Test that ADMIN can calculate on ARCHIVED version."""
        payload = {
            "entity_id": archived_scenario["entity"].id,
            "entity_version_id": archived_scenario["version"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200


# ============================================================
# CALCULATION FUNCTIONAL TESTS
# ============================================================

class TestEngineCalculation:
    """Tests for calculation functionality."""

    def test_calculate_returns_all_fields(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that calculation returns all fields of the version."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert "fields" in data
        assert len(data["fields"]) == 5  # We have 5 fields in engine_scenario

    def test_calculate_response_format(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that response has correct structure."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Check top-level structure
        assert "entity_id" in data
        assert "fields" in data
        assert "is_complete" in data
        assert data["entity_id"] == engine_scenario["entity"].id

        # Check field structure
        field = data["fields"][0]
        assert "field_id" in field
        assert "field_name" in field
        assert "field_label" in field
        assert "current_value" in field
        assert "available_options" in field
        assert "is_required" in field
        assert "is_readonly" in field
        assert "is_hidden" in field

    def test_is_complete_false_when_required_missing(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that is_complete is false when required fields are missing."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": []  # No values provided, but we have required fields
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["is_complete"] is False

    def test_is_complete_true_when_all_required_filled(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that is_complete is true when all required fields are filled."""
        # Adult birthdate
        adult_birthdate = str(date.today() - timedelta(days=20*365))

        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["type"].id, "value": "CAR"},
                {"field_id": engine_scenario["fields"]["value"].id, "value": 30000},
                {"field_id": engine_scenario["fields"]["coverage"].id, "value": "BASIC"},
                {"field_id": engine_scenario["fields"]["birthdate"].id, "value": adult_birthdate}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["is_complete"] is True

    def test_available_options_for_dropdown_field(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that dropdown fields return available options."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Find vehicle_type field
        type_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["type"].id
        )

        assert len(type_field["available_options"]) == 3  # CAR, MOTO, TRUCK
        option_values = [opt["value"] for opt in type_field["available_options"]]
        assert "CAR" in option_values
        assert "MOTO" in option_values
        assert "TRUCK" in option_values

    def test_free_value_field_has_empty_options(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that free-value fields have empty available_options."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Find vehicle_value field (is_free_value=True)
        value_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["value"].id
        )

        assert value_field["available_options"] == []

    def test_current_value_reflects_input(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that current_value reflects the provided input."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["value"].id, "value": 45000}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        value_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["value"].id
        )

        assert value_field["current_value"] == 45000


# ============================================================
# ERROR HANDLING TESTS
# ============================================================

class TestEngineErrors:
    """Tests for error handling."""

    def test_nonexistent_entity_returns_404(
        self, client: TestClient, admin_headers
    ):
        """Test that non-existent entity returns 404."""
        payload = {
            "entity_id": 99999,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 404

    def test_nonexistent_version_returns_404(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that non-existent version returns 404."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "entity_version_id": 99999,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 404

    def test_entity_without_published_version_returns_404_for_user(
        self, client: TestClient, user_headers, draft_only_scenario
    ):
        """Test that entity without PUBLISHED version returns 404 when USER doesn't specify version."""
        payload = {
            "entity_id": draft_only_scenario["entity"].id,
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=user_headers)

        # Should be 404 because no PUBLISHED version exists
        assert response.status_code == 404

    def test_invalid_payload_returns_422(
        self, client: TestClient, admin_headers
    ):
        """Test that malformed payload returns 422."""
        payload = {
            "entity_id": "not_an_integer",  # Invalid type
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_missing_entity_id_returns_422(
        self, client: TestClient, admin_headers
    ):
        """Test that missing entity_id returns 422."""
        payload = {
            "current_state": []
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_invalid_current_state_format_returns_422(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that invalid current_state format returns 422."""
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": "not_a_list"  # Should be a list
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 422


# ============================================================
# RULE EVALUATION TESTS VIA API
# ============================================================

class TestEngineRules:
    """Tests for rule evaluation via API."""

    def test_mandatory_rule_makes_field_required(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that MANDATORY rule makes field required when condition is true."""
        # Value > 50000 triggers mandatory alarm
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["value"].id, "value": 60000}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        alarm_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["alarm"].id
        )

        assert alarm_field["is_required"] is True

    def test_mandatory_rule_field_not_required_when_condition_false(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that MANDATORY rule keeps field optional when condition is false."""
        # Value <= 50000, alarm should remain optional
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["value"].id, "value": 30000}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        alarm_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["alarm"].id
        )

        assert alarm_field["is_required"] is False

    def test_visibility_rule_hides_field(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that VISIBILITY rule hides field when condition is false."""
        # Type = MOTO hides alarm (condition NOT_EQUALS MOTO becomes false)
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["type"].id, "value": "MOTO"}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        alarm_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["alarm"].id
        )

        assert alarm_field["is_hidden"] is True

    def test_visibility_rule_shows_field_when_condition_true(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that VISIBILITY rule shows field when condition is true."""
        # Type = CAR, alarm should be visible
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["type"].id, "value": "CAR"}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        alarm_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["alarm"].id
        )

        assert alarm_field["is_hidden"] is False

    def test_visibility_rule_resets_hidden_field_value(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that hidden field's value is reset to None."""
        # Provide a value for alarm, then hide it
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["type"].id, "value": "MOTO"},
                {"field_id": engine_scenario["fields"]["alarm"].id, "value": True}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        alarm_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["alarm"].id
        )

        assert alarm_field["is_hidden"] is True
        assert alarm_field["current_value"] is None

    def test_availability_rule_filters_options(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that AVAILABILITY rule filters out unavailable options."""
        # Type = TRUCK removes BASIC from coverage options
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["type"].id, "value": "TRUCK"}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        coverage_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["coverage"].id
        )

        option_values = [opt["value"] for opt in coverage_field["available_options"]]
        assert "PREMIUM" in option_values
        assert "BASIC" not in option_values  # Filtered out for TRUCK

    def test_availability_rule_keeps_options_when_condition_true(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that AVAILABILITY rule keeps options when condition is true."""
        # Type = CAR, BASIC should be available
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["type"].id, "value": "CAR"}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        coverage_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["coverage"].id
        )

        option_values = [opt["value"] for opt in coverage_field["available_options"]]
        assert "BASIC" in option_values
        assert "PREMIUM" in option_values

    def test_validation_rule_sets_error_message(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that VALIDATION rule sets error_message when violated."""
        # Birthdate = today (minor)
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["birthdate"].id, "value": str(date.today())}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        birthdate_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["birthdate"].id
        )

        assert birthdate_field["error_message"] is not None
        assert "18" in birthdate_field["error_message"]

    def test_validation_rule_no_error_when_valid(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that VALIDATION rule has no error when valid."""
        # Adult birthdate
        adult_birthdate = str(date.today() - timedelta(days=20*365))

        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["birthdate"].id, "value": adult_birthdate}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        birthdate_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["birthdate"].id
        )

        assert birthdate_field["error_message"] is None

    def test_validation_error_sets_is_complete_false(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that validation error causes is_complete to be false."""
        # Provide all required fields but with invalid birthdate
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["type"].id, "value": "CAR"},
                {"field_id": engine_scenario["fields"]["value"].id, "value": 30000},
                {"field_id": engine_scenario["fields"]["coverage"].id, "value": "BASIC"},
                {"field_id": engine_scenario["fields"]["birthdate"].id, "value": str(date.today())}  # Minor
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        # Even with all required fields filled, validation error makes it incomplete
        assert data["is_complete"] is False

    def test_multiple_rules_on_same_field(
        self, client: TestClient, admin_headers, engine_scenario
    ):
        """Test that multiple rules on the same field work correctly."""
        # Alarm has both MANDATORY and VISIBILITY rules
        # High value + CAR = mandatory and visible
        payload = {
            "entity_id": engine_scenario["entity"].id,
            "current_state": [
                {"field_id": engine_scenario["fields"]["type"].id, "value": "CAR"},
                {"field_id": engine_scenario["fields"]["value"].id, "value": 60000}
            ]
        }

        response = client.post("/engine/calculate", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()

        alarm_field = next(
            f for f in data["fields"]
            if f["field_id"] == engine_scenario["fields"]["alarm"].id
        )

        assert alarm_field["is_hidden"] is False  # CAR, so visible
        assert alarm_field["is_required"] is True  # Value > 50000, so mandatory
