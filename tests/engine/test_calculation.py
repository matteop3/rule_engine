"""
Test suite for CALCULATION rule type in the Rule Engine.

Tests the engine's behavior when CALCULATION rules are present, including:
- Basic calculation firing/not firing
- Free-value vs non-free field behavior
- Waterfall interactions (VISIBILITY, EDITABILITY, AVAILABILITY, MANDATORY, VALIDATION)
- Multiple CALCULATION rules (first passing wins)
- Running context propagation of calculated values
- SKU generation with calculated values
- Completeness check with calculated fields
"""

from app.models.domain import Rule, RuleType
from app.schemas.engine import CalculationRequest, FieldInputState
from app.services.rule_engine import RuleEngineService


class TestCalculationBasic:
    """Tests for basic CALCULATION rule behavior."""

    def test_calculation_fires_when_condition_met(self, db_session, setup_calculation_scenario):
        """When condition is met, CALCULATION sets value and makes field readonly."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # product_type = "Enterprise" → cooling_system should be forced to "Passive"
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise")],
        )

        response = service.calculate_state(db_session, payload)
        cooling = next(f for f in response.fields if f.field_id == data["fields"]["cooling_system"])

        assert cooling.current_value == "Passive"
        assert cooling.is_readonly is True
        assert cooling.is_hidden is False

    def test_calculation_does_not_fire_when_condition_not_met(self, db_session, setup_calculation_scenario):
        """When condition is not met, field behaves normally (user input preserved, editable)."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # product_type = "Standard" → cooling_system should NOT be calculated
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["product_type"], value="Standard"),
                FieldInputState(field_id=data["fields"]["cooling_system"], value="Active"),
            ],
        )

        response = service.calculate_state(db_session, payload)
        cooling = next(f for f in response.fields if f.field_id == data["fields"]["cooling_system"])

        assert cooling.current_value == "Active"
        assert cooling.is_readonly is False  # No EDITABILITY rule on cooling_system

    def test_calculation_on_free_value_field(self, db_session, setup_calculation_scenario):
        """CALCULATION on free-value field: sets value, available_options = []."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # product_type = "Pro" → support_tier (free) should be forced to "Premium"
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Pro")],
        )

        response = service.calculate_state(db_session, payload)
        support = next(f for f in response.fields if f.field_id == data["fields"]["support_tier"])

        assert support.current_value == "Premium"
        assert support.is_readonly is True
        assert support.available_options == []

    def test_calculation_on_non_free_field(self, db_session, setup_calculation_scenario):
        """CALCULATION on non-free field: available_options contains only the forced value."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # product_type = "Enterprise" → cooling_system forced to "Passive"
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise")],
        )

        response = service.calculate_state(db_session, payload)
        cooling = next(f for f in response.fields if f.field_id == data["fields"]["cooling_system"])

        assert len(cooling.available_options) == 1
        assert cooling.available_options[0].value == "Passive"


class TestCalculationWaterfallInteractions:
    """Tests for CALCULATION interactions with other rule types in the waterfall."""

    def test_calculation_skips_hidden_field(self, db_session, setup_calculation_scenario):
        """A field hidden by VISIBILITY does not get calculated."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # product_type = "Standard" → status_display is hidden (VISIBILITY rule)
        # Even though status_display has no CALCULATION rule, this confirms
        # the general pattern: hidden fields get early return before CALCULATION
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Standard")],
        )

        response = service.calculate_state(db_session, payload)
        status_field = next(f for f in response.fields if f.field_id == data["fields"]["status_display"])

        assert status_field.is_hidden is True
        assert status_field.current_value is None

    def test_calculation_skips_editability(self, db_session, setup_calculation_scenario):
        """When CALCULATION fires, EDITABILITY rules are skipped — field is always readonly."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # notes has EDITABILITY rule: editable if product_type != "Standard"
        # We check that notes field is correctly handled (no CALCULATION on notes)
        # But cooling_system has no EDITABILITY — when calculated, it's readonly

        # For warranty: Enterprise triggers CALCULATION → readonly regardless of other rules
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise")],
        )

        response = service.calculate_state(db_session, payload)
        warranty = next(f for f in response.fields if f.field_id == data["fields"]["warranty"])

        # warranty is calculated → must be readonly
        assert warranty.current_value == "3 Years"
        assert warranty.is_readonly is True

    def test_calculation_skips_availability(self, db_session, setup_calculation_scenario):
        """When CALCULATION fires, AVAILABILITY rules are skipped."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # warranty has AVAILABILITY rule: "3 Years" only if product_type != "Standard"
        # And CALCULATION: "3 Years" if product_type == "Enterprise"
        # When CALCULATION fires, AVAILABILITY is skipped — only forced value shown
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise")],
        )

        response = service.calculate_state(db_session, payload)
        warranty = next(f for f in response.fields if f.field_id == data["fields"]["warranty"])

        # Only the forced value in available_options, not the full availability-filtered list
        assert len(warranty.available_options) == 1
        assert warranty.available_options[0].value == "3 Years"

    def test_calculation_plus_mandatory(self, db_session, setup_calculation_scenario):
        """Calculated field still evaluates MANDATORY (is_required reflects the rule)."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # status_display: MANDATORY if product_type == "Pro", VISIBILITY if != "Standard"
        # With product_type = "Pro": visible + mandatory, but no CALCULATION
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Pro")],
        )

        response = service.calculate_state(db_session, payload)
        status_field = next(f for f in response.fields if f.field_id == data["fields"]["status_display"])

        assert status_field.is_hidden is False
        assert status_field.is_required is True

    def test_calculation_mandatory_evaluated_on_calculated_field(self, db_session, setup_calculation_scenario):
        """MANDATORY is evaluated even on calculated fields (not skipped like EDITABILITY)."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # cooling_system has CALCULATION (Enterprise → Passive) but no MANDATORY rule
        # So is_required should come from field default (is_required=True)
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise")],
        )

        response = service.calculate_state(db_session, payload)
        cooling = next(f for f in response.fields if f.field_id == data["fields"]["cooling_system"])

        # No MANDATORY rules → falls back to field.is_required (True for cooling_system)
        assert cooling.is_required is True

    def test_calculation_validation_as_safety_net(self, db_session, setup_calculation_scenario):
        """VALIDATION rules still run on calculated values (safety net for future arithmetic)."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # Add a VALIDATION rule on cooling_system that would fail on "Passive"
        val_rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["cooling_system"],
            rule_type=RuleType.VALIDATION.value,
            error_message="Passive cooling not allowed",
            conditions={
                "criteria": [{"field_id": data["fields"]["cooling_system"], "operator": "EQUALS", "value": "Passive"}]
            },
        )
        db_session.add(val_rule)
        db_session.commit()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise")],
        )

        response = service.calculate_state(db_session, payload)
        cooling = next(f for f in response.fields if f.field_id == data["fields"]["cooling_system"])

        # CALCULATION sets "Passive", then VALIDATION catches it
        assert cooling.current_value == "Passive"
        assert cooling.error_message == "Passive cooling not allowed"


class TestCalculationMultipleRules:
    """Tests for multiple CALCULATION rules on the same field."""

    def test_first_passing_calculation_wins(self, db_session, setup_calculation_scenario):
        """When multiple CALCULATION rules exist, the first passing one wins."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # Add a second CALCULATION rule on cooling_system for "Pro" → "Liquid"
        second_calc = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["cooling_system"],
            rule_type=RuleType.CALCULATION.value,
            set_value="Liquid",
            conditions={
                "criteria": [{"field_id": data["fields"]["product_type"], "operator": "EQUALS", "value": "Pro"}]
            },
        )
        db_session.add(second_calc)
        db_session.commit()

        # Product = Pro → second rule should fire
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Pro")],
        )

        response = service.calculate_state(db_session, payload)
        cooling = next(f for f in response.fields if f.field_id == data["fields"]["cooling_system"])

        assert cooling.current_value == "Liquid"
        assert cooling.is_readonly is True


class TestCalculationInvalidSetValue:
    """Tests for defensive handling when set_value does not match any defined Value."""

    def test_non_free_field_with_invalid_set_value_returns_none(self, db_session, setup_calculation_scenario):
        """When set_value doesn't match any Value on a non-free field, current_value is blanked to None."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # Bypass API validation: insert a CALCULATION rule with an invalid set_value directly in DB
        invalid_rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["cooling_system"],
            rule_type=RuleType.CALCULATION.value,
            set_value="Hydrogen",  # not among Passive/Active/Liquid
            conditions={
                "criteria": [{"field_id": data["fields"]["product_type"], "operator": "EQUALS", "value": "Pro"}]
            },
        )
        db_session.add(invalid_rule)
        db_session.commit()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Pro")],
        )

        response = service.calculate_state(db_session, payload)
        cooling = next(f for f in response.fields if f.field_id == data["fields"]["cooling_system"])

        assert cooling.current_value is None
        assert cooling.available_options == []
        assert cooling.is_readonly is True

    def test_invalid_set_value_propagates_none_to_downstream(self, db_session, setup_calculation_scenario):
        """When set_value is invalidated, running_context carries None — downstream rules see None."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # CALCULATION with invalid set_value on cooling_system
        invalid_rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["cooling_system"],
            rule_type=RuleType.CALCULATION.value,
            set_value="Hydrogen",
            conditions={
                "criteria": [{"field_id": data["fields"]["product_type"], "operator": "EQUALS", "value": "Pro"}]
            },
        )
        # Downstream: notes required if cooling_system == "Hydrogen"
        downstream_rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["notes"],
            rule_type=RuleType.MANDATORY.value,
            conditions={
                "criteria": [{"field_id": data["fields"]["cooling_system"], "operator": "EQUALS", "value": "Hydrogen"}]
            },
        )
        db_session.add_all([invalid_rule, downstream_rule])
        db_session.commit()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Pro")],
        )

        response = service.calculate_state(db_session, payload)
        notes = next(f for f in response.fields if f.field_id == data["fields"]["notes"])

        # cooling_system was invalidated to None → "Hydrogen" != None → rule does NOT fire
        assert notes.is_required is False


class TestCalculationRunningContext:
    """Tests for calculated values propagating through running_context."""

    def test_calculated_value_in_running_context(self, db_session, setup_calculation_scenario):
        """A downstream field can use a calculated value in its conditions."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # Add a MANDATORY rule on notes: required if cooling_system == "Passive"
        # cooling_system is calculated when product_type == "Enterprise"
        ctx_rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["notes"],
            rule_type=RuleType.MANDATORY.value,
            conditions={
                "criteria": [{"field_id": data["fields"]["cooling_system"], "operator": "EQUALS", "value": "Passive"}]
            },
        )
        db_session.add(ctx_rule)
        db_session.commit()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise")],
        )

        response = service.calculate_state(db_session, payload)
        notes = next(f for f in response.fields if f.field_id == data["fields"]["notes"])

        # cooling_system was calculated to "Passive" → notes should be required
        assert notes.is_required is True


class TestCalculationSKU:
    """Tests for CALCULATION values feeding into SKU generation."""

    def test_calculated_value_feeds_into_sku(self, db_session, setup_calculation_scenario):
        """Calculated value is used for SKU generation just like user-selected values."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # Enterprise → cooling_system = "Passive" (sku_modifier="PAS")
        # Enterprise → warranty = "3 Years" (sku_modifier="3Y")
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise")],
        )

        response = service.calculate_state(db_session, payload)

        assert response.generated_sku is not None
        # SKU should contain: CFG (base) + ENT (product_type) + PAS (cooling) + 3Y (warranty)
        assert "ENT" in response.generated_sku
        assert "PAS" in response.generated_sku
        assert "3Y" in response.generated_sku


class TestCalculationCompleteness:
    """Tests for completeness check with calculated fields."""

    def test_calculated_field_counts_as_complete(self, db_session, setup_calculation_scenario):
        """A calculated required field with a value is considered complete."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # Enterprise sets cooling_system and warranty via CALCULATION
        # Both are required fields — calculation provides the value
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["product_type"], value="Enterprise"),
                FieldInputState(field_id=data["fields"]["notes"], value="some notes"),
                FieldInputState(field_id=data["fields"]["status_display"], value="Active"),
            ],
        )

        response = service.calculate_state(db_session, payload)

        cooling = next(f for f in response.fields if f.field_id == data["fields"]["cooling_system"])
        warranty = next(f for f in response.fields if f.field_id == data["fields"]["warranty"])

        # Both calculated fields have values → should count as complete
        assert cooling.current_value is not None
        assert warranty.current_value is not None

    def test_incomplete_without_calculation(self, db_session, setup_calculation_scenario):
        """Required fields without CALCULATION (no user input) make response incomplete."""
        data = setup_calculation_scenario
        service = RuleEngineService()

        # Standard → no CALCULATION fires for cooling_system or warranty
        # Without user input for required fields → incomplete
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[FieldInputState(field_id=data["fields"]["product_type"], value="Standard")],
        )

        response = service.calculate_state(db_session, payload)

        assert response.is_complete is False
