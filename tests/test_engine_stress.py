import pytest
from app.models.domain import Entity, EntityVersion, Field, Rule, RuleType, VersionStatus, FieldType
from app.services.rule_engine import RuleEngineService
from app.schemas.engine import CalculationRequest, FieldInputState

@pytest.fixture(scope="function")
def setup_stress_scenario(db_session):
    """
    Scenario A -> B -> C (Domino)
    Scenario X <-> Y (Circolare/Sequenza)
    """
    entity = Entity(name="Stress Test", description="Complex Logic")
    db_session.add(entity)
    db_session.commit()
    
    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # --- CAMPI PER DOMINO (A, B, C) ---
    # Sequenza: 1, 2, 3
    f_a = Field(entity_version_id=version.id, name="A", label="Driver", data_type="string", sequence=1, is_free_value=True)
    f_b = Field(entity_version_id=version.id, name="B", label="Middle", data_type="string", sequence=2, is_free_value=True)
    f_c = Field(entity_version_id=version.id, name="C", label="Tail",   data_type="string", sequence=3, is_free_value=True)

    # --- CAMPI PER SEQUENCE CHECK (X, Y) ---
    # X (Seq 10) dipende da Y (Seq 20)
    f_x = Field(entity_version_id=version.id, name="X", label="Early", data_type="string", sequence=10, is_free_value=True)
    f_y = Field(entity_version_id=version.id, name="Y", label="Late",  data_type="string", sequence=20, is_free_value=True)

    db_session.add_all([f_a, f_b, f_c, f_x, f_y])
    db_session.commit()

    return {
        "v_id": version.id, "e_id": entity.id,
        "A": f_a.id, "B": f_b.id, "C": f_c.id,
        "X": f_x.id, "Y": f_y.id
    }

def test_stress_domino_effect(db_session, setup_stress_scenario):
    """
    Testa la propagazione delle modifiche nello stesso ciclo.
    Regola 1: Se A == 'HIDE', nascondi B.
    Regola 2: Se B è NULL (o nascosto), nascondi C.
    
    Input: A='HIDE', B='Valore', C='Valore'
    Output Atteso: B nascosto E C nascosto.
    """
    ids = setup_stress_scenario
    service = RuleEngineService()

    # R1: Logica POSITIVA -> Definisco quando B è VISIBILE.
    # Voglio nascondere B se A='HIDE'. Quindi B è visibile se A != 'HIDE'.
    r1 = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["B"], rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["A"], "operator": "NOT_EQUALS", "value": "HIDE"}]}
    )
    
    # R2: Logica POSITIVA -> Definisco quando C è VISIBILE.
    # C è visibile solo se B ha il valore 'SHOW'.
    # Se B viene nascosto dalla regola sopra, il suo valore nel contesto diventerà None -> Regola Falsa -> C Nascosto.
    r2 = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["C"], rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["B"], "operator": "EQUALS", "value": "SHOW"}]}
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    # TEST: Trigger Domino
    payload = CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["A"], value="HIDE"),
            FieldInputState(field_id=ids["B"], value="SHOW"), # Inserisco SHOW, ma verrà nascosto
            FieldInputState(field_id=ids["C"], value="ANY")
        ]
    )
    
    resp = service.calculate_state(db_session, payload)
    
    field_b = next(f for f in resp.fields if f.field_id == ids["B"])
    field_c = next(f for f in resp.fields if f.field_id == ids["C"])

    # 1. B deve essere nascosto (causa A)
    assert field_b.is_hidden is True
    # 2. B deve essere None (perché nascosto)
    assert field_b.current_value is None

    # 3. C deve essere nascosto?
    # Se il motore ha aggiornato il contesto dopo aver nascosto B, allora la regola su C
    # leggerà B=None. Siccome None != 'SHOW', C deve essere nascosto.
    assert field_c.is_hidden is True, "Il Domino Effect ha fallito: C dovrebbe reagire al fatto che B è stato nascosto."

def test_stress_future_dependency(db_session, setup_stress_scenario):
    """
    Testa cosa succede se una regola dipende da un campo che viene dopo nella sequenza.
    X (seq 10) dipende da Y (seq 20).
    Regola: Se Y='SECRET', nascondi X.
    """
    ids = setup_stress_scenario
    service = RuleEngineService()

    rule = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["X"], rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["Y"], "operator": "EQUALS", "value": "SECRET"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Il motore processa X. Y non è ancora stato elaborato (è dopo).
    # Tuttavia, il valore di Y è presente nell'INPUT iniziale.
    # Il motore dovrebbe usare il valore di input.
    payload = CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["X"], value="I see you"),
            FieldInputState(field_id=ids["Y"], value="SECRET")
        ]
    )

    resp = service.calculate_state(db_session, payload)
    field_x = next(f for f in resp.fields if f.field_id == ids["X"])

    # X dovrebbe essere nascosto perché legge l'input grezzo di Y
    assert field_x.is_hidden is True

def test_stress_multiple_validations(db_session, setup_stress_scenario):
    """
    Testa se il motore gestisce errori multipli o sovrascrive.
    Attualmente il modello FieldOutputState ha un solo campo 'error_message'.
    Ci aspettiamo che prenda l'ultimo o il primo errore (comportamento Last-Win o First-Win).
    """
    ids = setup_stress_scenario
    service = RuleEngineService()

    # Regola 1: Errore se A contiene "ERR1"
    r1 = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["A"], rule_type=RuleType.VALIDATION.value,
        error_message="Errore Uno",
        conditions={"criteria": [{"field_id": ids["A"], "operator": "EQUALS", "value": "ERR1"}]}
    )
    # Regola 2: Errore se B contiene "ERR1" (Nota: uso B per triggerare errore su A)
    # Questo simula due regole diverse che rompono A.
    r2 = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["A"], rule_type=RuleType.VALIDATION.value,
        error_message="Errore Due",
        conditions={"criteria": [{"field_id": ids["B"], "operator": "EQUALS", "value": "ERR1"}]}
    )
    db_session.add_all([r1, r2])
    db_session.commit()

    payload = CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["A"], value="ERR1"),
            FieldInputState(field_id=ids["B"], value="ERR1")
        ]
    )

    resp = service.calculate_state(db_session, payload)
    field_a = next(f for f in resp.fields if f.field_id == ids["A"])

    # Verifichiamo semplicemente che ci sia UN errore.
    # Se volessimo supportare errori multipli, dovremmo cambiare FieldOutputState.error_message in List[str]
    assert field_a.error_message in ["Errore Uno", "Errore Due"]