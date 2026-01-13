import pytest
from datetime import date
from app.services.rule_engine import RuleEngineService
from app.schemas.engine import CalculationRequest, FieldInputState

def test_engine_minorenne_validation(db_session, setup_insurance_scenario):
    """
    Testiamo che se un utente inserisce una data di nascita da minorenne,
    il motore restituisca un errore di validazione.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # Create an input with birth date = Today (0 years old -> Underage)
    payload = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[
            FieldInputState(field_id=data_map["fields"]["nascita"], value=str(date.today()))
        ]
    )

    response = service.calculate_state(db_session, payload)

    # Asserzioni
    field_out = next(f for f in response.fields if f.field_id == data_map["fields"]["nascita"])

    assert field_out.error_message == "Minorenne"
    assert response.is_complete is False
    #print("\n✅ Test Underage passed: Error detected correctly.")


def test_engine_mandatory_rule(db_session, setup_insurance_scenario):
    """
    Testiamo la regola MANDATORY: Se valore auto > 50.000, il satellitare diventa obbligatorio.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # CASE A: Low value (40,000) -> Satellite NOT required
    payload_low = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[
            FieldInputState(field_id=data_map["fields"]["valore"], value=40000)
        ]
    )
    resp_low = service.calculate_state(db_session, payload_low)
    sat_low = next(f for f in resp_low.fields if f.field_id == data_map["fields"]["satellitare"])
    assert sat_low.is_required is False # Field default

    # CASE B: High value (60,000) -> Satellite BECOMES required
    payload_high = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[
            FieldInputState(field_id=data_map["fields"]["valore"], value=60000)
        ]
    )
    resp_high = service.calculate_state(db_session, payload_high)
    sat_high = next(f for f in resp_high.fields if f.field_id == data_map["fields"]["satellitare"])
    
    assert sat_high.is_required is True
    # Since no value was provided for satellite field, is_complete must be False
    assert resp_high.is_complete is False

    #print("\n✅ Test Mandatory passed: Field became required dynamically.")


def test_engine_visibility_logic(db_session, setup_insurance_scenario):
    """
    Testiamo la regola VISIBILITY: Se Tipo = MOTO, il campo Infortuni deve sparire.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # CASE A: Type = AUTO -> Infortuni Visible
    payload_auto = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[
            FieldInputState(field_id=data_map["fields"]["tipo"], value="AUTO")
        ]
    )
    resp_auto = service.calculate_state(db_session, payload_auto)
    inf_auto = next(f for f in resp_auto.fields if f.field_id == data_map["fields"]["infortuni"])
    assert inf_auto.is_hidden is False

    # CASE B: Type = MOTO -> Infortuni Hidden
    payload_moto = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[
            FieldInputState(field_id=data_map["fields"]["tipo"], value="MOTO")
        ]
    )
    resp_moto = service.calculate_state(db_session, payload_moto)
    inf_moto = next(f for f in resp_moto.fields if f.field_id == data_map["fields"]["infortuni"])
    
    assert inf_moto.is_hidden is True
    # When hidden, the value must be reset to None
    assert inf_moto.current_value is None

    #print("\n✅ Test Visibility passed: Field hidden correctly on MOTO.")

def test_engine_availability_filter(db_session, setup_insurance_scenario):
    """
    Testiamo la regola AVAILABILITY: Se Tipo = CAMION, l'opzione 'MINIMO' deve sparire dal Massimale.
    """
    data_map = setup_insurance_scenario
    service = RuleEngineService()

    # Input: Seleziono CAMION
    payload = CalculationRequest(
        entity_id=data_map["entity_id"],
        current_state=[
            FieldInputState(field_id=data_map["fields"]["tipo"], value="CAMION")
        ]
    )
    resp = service.calculate_state(db_session, payload)
    massimale_field = next(f for f in resp.fields if f.field_id == data_map["fields"]["massimale"])
    
    # Verifichiamo le opzioni disponibili
    available_values = [opt.value for opt in massimale_field.available_options]
    
    assert "VIP" in available_values      # Must be present
    assert "MINIMO" not in available_values # Must NOT be present

    #print("\n✅ Test Availability passed: Option MINIMO removed for CAMION.")