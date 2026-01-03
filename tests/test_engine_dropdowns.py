import pytest
from app.models.domain import Entity, EntityVersion, Field, Value, Rule, RuleType, VersionStatus, FieldType
from app.services.rule_engine import RuleEngineService
from app.schemas.engine import CalculationRequest, FieldInputState

@pytest.fixture(scope="function")
def setup_dropdown_scenario(db_session):
    """
    Scenario: Regione -> Città.
    Regione: [Nord, Sud]
    Città: [Milano, Torino, Napoli, Palermo]
    
    Regole:
    - Se Regione != Nord -> Rimuovi Milano, Torino
    - Se Regione != Sud -> Rimuovi Napoli, Palermo
    """
    entity = Entity(name="Dropdown Test", description="Cascading menus")
    db_session.add(entity)
    db_session.commit()
    
    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # 1. Campo Regione (Dropdown)
    f_region = Field(entity_version_id=version.id, name="region", label="Regione", data_type="string", sequence=1, is_free_value=False)
    db_session.add(f_region)
    db_session.commit() # Commit per avere l'ID

    # Valori Regione
    v_north = Value(field_id=f_region.id, value="NORD", label="Nord Italia")
    v_south = Value(field_id=f_region.id, value="SUD", label="Sud Italia")
    db_session.add_all([v_north, v_south])
    
    # 2. Campo Città (Dropdown)
    f_city = Field(entity_version_id=version.id, name="city", label="Città", data_type="string", sequence=2, is_free_value=False)
    db_session.add(f_city)
    db_session.commit()

    # Valori Città
    v_milano = Value(field_id=f_city.id, value="MILANO", label="Milano")
    v_torino = Value(field_id=f_city.id, value="TORINO", label="Torino")
    v_napoli = Value(field_id=f_city.id, value="NAPOLI", label="Napoli")
    v_palermo = Value(field_id=f_city.id, value="PALERMO", label="Palermo")
    db_session.add_all([v_milano, v_torino, v_napoli, v_palermo])
    db_session.commit()

    # 3. Regole di Availability (Filtro)
    # Regola 1: Se Regione != NORD, Rimuovi Milano (Target Value ID specifici)
    # Nota: AVAILABILITY funziona "al contrario" (constraint)? O "filter out"?
    # Solitamente: Availability Rule dice "Questo valore è disponibile SE..."
    # Quindi: Milano è disponibile SE Regione == NORD.
    
    # Scriviamo le regole in logica positiva (Standard):
    # "Milano è disponibile SOLO SE Regione == NORD"
    r_milano = Rule(
        entity_version_id=version.id, target_field_id=f_city.id, target_value_id=v_milano.id,
        rule_type=RuleType.AVAILABILITY.value,
        conditions={"criteria": [{"field_id": f_region.id, "operator": "EQUALS", "value": "NORD"}]}
    )
    # "Napoli è disponibile SOLO SE Regione == SUD"
    r_napoli = Rule(
        entity_version_id=version.id, target_field_id=f_city.id, target_value_id=v_napoli.id,
        rule_type=RuleType.AVAILABILITY.value,
        conditions={"criteria": [{"field_id": f_region.id, "operator": "EQUALS", "value": "SUD"}]}
    )

    db_session.add_all([r_milano, r_napoli])
    db_session.commit()

    return {
        "e_id": entity.id,
        "f_region": f_region.id,
        "f_city": f_city.id,
        "val_milano": v_milano.id
    }

def test_dropdown_cascade_logic(db_session, setup_dropdown_scenario):
    """ Verifica che le opzioni vengano filtrate correttamente. """
    ids = setup_dropdown_scenario
    service = RuleEngineService()

    # Caso 1: Regione = NORD -> Mi aspetto Milano tra le opzioni, ma NON Napoli
    payload = CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_region"], value="NORD")]
    )
    resp = service.calculate_state(db_session, payload)
    
    f_city = next(f for f in resp.fields if f.field_id == ids["f_city"])
    
    options_codes = [o.value for o in f_city.available_options]
    assert "MILANO" in options_codes
    assert "NAPOLI" not in options_codes

    # Caso 2: Regione = SUD -> Mi aspetto Napoli, NON Milano
    payload = CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_region"], value="SUD")]
    )
    resp = service.calculate_state(db_session, payload)
    f_city = next(f for f in resp.fields if f.field_id == ids["f_city"])
    
    options_codes = [o.value for o in f_city.available_options]
    assert "NAPOLI" in options_codes
    assert "MILANO" not in options_codes

def test_dropdown_illegal_value_injection(db_session, setup_dropdown_scenario):
    """ 
    SECURITY TEST:
    Seleziono NORD, ma forzo il valore NAPOLI (che esiste nel DB ma non è disponibile).
    Il motore dovrebbe dare errore o resettare il valore.
    """
    ids = setup_dropdown_scenario
    service = RuleEngineService()

    payload = CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["f_region"], value="NORD"),
            FieldInputState(field_id=ids["f_city"], value="NAPOLI") # ILLEGALE per il Nord
        ]
    )
    
    resp = service.calculate_state(db_session, payload)
    f_city = next(f for f in resp.fields if f.field_id == ids["f_city"])

    # Ci aspettiamo che il motore si accorga che NAPOLI non è tra le opzioni disponibili per il NORD.
    # Comportamento desiderato: Error Message popolato OPPURE current_value resettato a None/Default.
    
    # Verifica 1: Le opzioni devono essere corrette (solo Milano)
    assert "MILANO" in [o.value for o in f_city.available_options]
    assert "NAPOLI" not in [o.value for o in f_city.available_options]

    # Verifica 2: Il valore illegale è stato accettato?
    # Se validation error è None E current_value è ancora "NAPOLI", abbiamo un problema di sicurezza.
    is_value_rejected = (f_city.error_message is not None) or (f_city.current_value != "NAPOLI")
    
    assert is_value_rejected is True, \
        f"Security Breach: Il motore ha accettato 'NAPOLI' anche se le opzioni valide erano solo {f_city.available_options}"