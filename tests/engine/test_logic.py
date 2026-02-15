from datetime import date

from app.schemas.engine import CalculationRequest, FieldInputState
from app.services.rule_engine import RuleEngineService


def test_engine_minorenne_validation(db_session, setup_insurance_scenario):
    """
    Test that if a user enters a birth date for a minor,
    the engine returns a validation error.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # Create an input with birth date = Today (0 years old -> Underage)
    payload = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[FieldInputState(field_id=data_map["fields"]["nascita"], value=str(date.today()))],
    )

    response = service.calculate_state(db_session, payload)

    # Assertions
    field_out = next(f for f in response.fields if f.field_id == data_map["fields"]["nascita"])

    assert field_out.error_message == "Underage"
    assert response.is_complete is False
    # print("\n✅ Test Underage passed: Error detected correctly.")


def test_engine_mandatory_rule(db_session, setup_insurance_scenario):
    """
    Test the MANDATORY rule: If vehicle value > 50,000, the satellite tracker becomes required.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # CASE A: Low value (40,000) -> Satellite NOT required
    payload_low = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[FieldInputState(field_id=data_map["fields"]["valore"], value=40000)],
    )
    resp_low = service.calculate_state(db_session, payload_low)
    sat_low = next(f for f in resp_low.fields if f.field_id == data_map["fields"]["satellitare"])
    assert sat_low.is_required is False  # Field default

    # CASE B: High value (60,000) -> Satellite BECOMES required
    payload_high = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[FieldInputState(field_id=data_map["fields"]["valore"], value=60000)],
    )
    resp_high = service.calculate_state(db_session, payload_high)
    sat_high = next(f for f in resp_high.fields if f.field_id == data_map["fields"]["satellitare"])

    assert sat_high.is_required is True
    # Since no value was provided for satellite field, is_complete must be False
    assert resp_high.is_complete is False

    # print("\n✅ Test Mandatory passed: Field became required dynamically.")


def test_engine_visibility_logic(db_session, setup_insurance_scenario):
    """
    Test the VISIBILITY rule: If Type = MOTO, the Injuries field must be hidden.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # CASE A: Type = AUTO -> Infortuni Visible
    payload_auto = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[FieldInputState(field_id=data_map["fields"]["tipo"], value="AUTO")],
    )
    resp_auto = service.calculate_state(db_session, payload_auto)
    inf_auto = next(f for f in resp_auto.fields if f.field_id == data_map["fields"]["infortuni"])
    assert inf_auto.is_hidden is False

    # CASE B: Type = MOTO -> Infortuni Hidden
    payload_moto = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[FieldInputState(field_id=data_map["fields"]["tipo"], value="MOTO")],
    )
    resp_moto = service.calculate_state(db_session, payload_moto)
    inf_moto = next(f for f in resp_moto.fields if f.field_id == data_map["fields"]["infortuni"])

    assert inf_moto.is_hidden is True
    # When hidden, the value must be reset to None
    assert inf_moto.current_value is None

    # print("\n✅ Test Visibility passed: Field hidden correctly on MOTO.")


def test_engine_mandatory_rule_overrides_is_required(db_session, setup_insurance_scenario):
    """
    Test the new MANDATORY rule behavior: when MANDATORY rules exist for a field,
    they fully govern the outcome. A field with is_required=True should become
    NOT required when its MANDATORY rule condition is not met.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # Patch satellite tracker to is_required=True
    from app.models.domain import Field

    sat_field = db_session.query(Field).filter(Field.id == data_map["fields"]["satellitare"]).one()
    sat_field.is_required = True
    db_session.commit()

    # CASE A: Low value (40,000) -> MANDATORY rule condition NOT met
    # NEW behavior: field becomes NOT required (rules fully govern)
    payload_low = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[FieldInputState(field_id=data_map["fields"]["valore"], value=40000)],
    )
    resp_low = service.calculate_state(db_session, payload_low)
    sat_low = next(f for f in resp_low.fields if f.field_id == data_map["fields"]["satellitare"])
    assert sat_low.is_required is False  # Rules override is_required=True

    # CASE B: High value (60,000) -> MANDATORY rule condition met -> required
    payload_high = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[FieldInputState(field_id=data_map["fields"]["valore"], value=60000)],
    )
    resp_high = service.calculate_state(db_session, payload_high)
    sat_high = next(f for f in resp_high.fields if f.field_id == data_map["fields"]["satellitare"])
    assert sat_high.is_required is True


def test_engine_availability_filter(db_session, setup_insurance_scenario):
    """
    Test the AVAILABILITY rule: If Type = CAMION, the 'MINIMO' option must be removed from Coverage.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # Input: Select CAMION
    payload = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[FieldInputState(field_id=data_map["fields"]["tipo"], value="CAMION")],
    )
    resp = service.calculate_state(db_session, payload)
    massimale_field = next(f for f in resp.fields if f.field_id == data_map["fields"]["massimale"])

    # Verify the available options
    available_values = [opt.value for opt in massimale_field.available_options]

    assert "VIP" in available_values  # Must be present
    assert "MINIMO" not in available_values  # Must NOT be present

    # print("\n✅ Test Availability passed: Option MINIMO removed for CAMION.")
