import pytest
from app.models.domain import Entity, EntityVersion, Field, Rule, RuleType, VersionStatus, FieldType
from app.services.rule_engine import RuleEngineService
from app.schemas.engine import CalculationRequest, FieldInputState

# --- FIXTURE SPECIFICA PER TEST OPERATORI ---
@pytest.fixture(scope="function")
def setup_operator_scenario(db_session):
    """
    Crea uno scenario minimale "da laboratorio" per testare gli operatori tecnici.
    Non usa logica di business (assicurazioni), ma campi generici A, B, C.
    """
    # 1. Entity & Version
    entity = Entity(name="Lab Entity", description="Unit Test Lab")
    db_session.add(entity)
    db_session.commit()
    
    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # 2. Fields Generici
    # Campo A: Numero
    f_num = Field(entity_version_id=version.id, name="field_num", label="Numero", data_type=FieldType.NUMBER.value, step=1, sequence=1, is_free_value=True)
    # Campo B: Stringa
    f_str = Field(entity_version_id=version.id, name="field_str", label="Stringa", data_type=FieldType.STRING.value, step=1, sequence=2, is_free_value=True)
    # Campo C: Data
    f_date = Field(entity_version_id=version.id, name="field_date", label="Data", data_type=FieldType.DATE.value, step=1, sequence=3, is_free_value=True)
    # Campo Target (da validare)
    f_target = Field(entity_version_id=version.id, name="field_target", label="Target", data_type=FieldType.STRING.value, step=1, sequence=4, is_free_value=True)

    db_session.add_all([f_num, f_str, f_date, f_target])
    db_session.commit()

    return {
        "v_id": version.id,
        "e_id": entity.id,
        "f_num": f_num.id,
        "f_str": f_str.id,
        "f_date": f_date.id,
        "f_target": f_target.id
    }

# --- TEST SUITE ---

def test_operator_in_list_numbers(db_session, setup_operator_scenario):
    """ Verifica operatore IN con lista di numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target è VISIBILE solo se f_num è IN [10, 20, 30]
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "IN", "value": [10, 20, 30]}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO (Valore 20 è nella lista)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=20)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False  # Visibile

    # Caso NEGATIVO (Valore 99 non è nella lista)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=99)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True   # Nascosto

def test_operator_not_equals_string(db_session, setup_operator_scenario):
    """ Verifica operatore NOT_EQUALS con stringhe """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Errore se f_str NON è uguale a "PIPPO"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VALIDATION.value,
        error_message="Devi scrivere PIPPO",
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "NOT_EQUALS", "value": "PIPPO"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso VALIDAZIONE ATTIVA (Scrivo "PLUTO" -> è diverso da PIPPO -> Errore)
    # FIX: Aggiungiamo un valore per f_target, altrimenti il motore salta la validazione
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["f_str"], value="PLUTO"),
            FieldInputState(field_id=ids["f_target"], value="Sto scrivendo qualcosa") 
        ]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.error_message == "Devi scrivere PIPPO"

    # Caso VALIDAZIONE PASSATA (Scrivo "PIPPO" -> non è diverso -> OK)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["f_str"], value="PIPPO"),
            FieldInputState(field_id=ids["f_target"], value="Sto scrivendo qualcosa")
        ]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.error_message is None

def test_operator_date_comparison_mixed_types(db_session, setup_operator_scenario):
    """ 
    Verifica robustezza date: 
    Confronta una data Input (Stringa ISO) con una data Regola (Stringa ISO)
    usando operatori matematici.
    """
    ids = setup_operator_scenario
    service = RuleEngineService()
    
    target_date = "2023-01-01"

    # REGOLA: Mandatory se f_date < 2023-01-01
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "LESS_THAN", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso 1: Data precedente (2020) -> Deve diventare Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2020-05-05")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso 2: Data successiva (2025) -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2025-01-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False

def test_multiple_conditions_and_logic(db_session, setup_operator_scenario):
    """ Verifica logica AND implicita (tutte le condizioni devono essere vere) """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target visibile SE (Num > 10) AND (Str = 'OK')
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [
            {"field_id": ids["f_num"], "operator": "GREATER_THAN", "value": 10},
            {"field_id": ids["f_str"], "operator": "EQUALS", "value": "OK"}
        ]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso: Solo Num OK -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["f_num"], value=50),
            FieldInputState(field_id=ids["f_str"], value="NO")
        ]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # Caso: Entrambi OK -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["f_num"], value=50),
            FieldInputState(field_id=ids["f_str"], value="OK")
        ]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False


# ============================================================
# ADDITIONAL OPERATOR TESTS
# ============================================================

def test_operator_equals_string(db_session, setup_operator_scenario):
    """ Verifica operatore EQUALS con stringhe """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target visibile solo se f_str == "MATCH"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "EQUALS", "value": "MATCH"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: Valore uguale -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="MATCH")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso NEGATIVO: Valore diverso -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="DIFFERENT")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_equals_number(db_session, setup_operator_scenario):
    """ Verifica operatore EQUALS con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target obbligatorio se f_num == 100
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "EQUALS", "value": 100}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: Valore uguale -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=100)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso NEGATIVO: Valore diverso -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=99)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_greater_than_number(db_session, setup_operator_scenario):
    """ Verifica operatore GREATER_THAN con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target visibile se f_num > 50
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "GREATER_THAN", "value": 50}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: 51 > 50 -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=51)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso NEGATIVO: 50 non è > 50 -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=50)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # Caso NEGATIVO: 49 < 50 -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=49)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_less_than_number(db_session, setup_operator_scenario):
    """ Verifica operatore LESS_THAN con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target obbligatorio se f_num < 10
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "LESS_THAN", "value": 10}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: 5 < 10 -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=5)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso NEGATIVO: 10 non è < 10 -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=10)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False

    # Caso NEGATIVO: 15 > 10 -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=15)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_in_list_strings(db_session, setup_operator_scenario):
    """ Verifica operatore IN con lista di stringhe """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target visibile solo se f_str è IN ["A", "B", "C"]
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "IN", "value": ["A", "B", "C"]}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: "B" è nella lista
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="B")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso NEGATIVO: "X" non è nella lista
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="X")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_equals_date(db_session, setup_operator_scenario):
    """ Verifica operatore EQUALS con date """
    ids = setup_operator_scenario
    service = RuleEngineService()

    target_date = "2024-06-15"

    # REGOLA: Target obbligatorio se f_date == 2024-06-15
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "EQUALS", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: Stessa data -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-06-15")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso NEGATIVO: Data diversa -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-06-16")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_greater_than_date(db_session, setup_operator_scenario):
    """ Verifica operatore GREATER_THAN con date """
    ids = setup_operator_scenario
    service = RuleEngineService()

    target_date = "2024-01-01"

    # REGOLA: Target visibile se f_date > 2024-01-01
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "GREATER_THAN", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: Data successiva -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-06-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso NEGATIVO: Stessa data -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-01-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # Caso NEGATIVO: Data precedente -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2023-12-31")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


# ============================================================
# GREATER_THAN_OR_EQUAL / LESS_THAN_OR_EQUAL OPERATORS
# ============================================================

def test_operator_greater_than_or_equal_number(db_session, setup_operator_scenario):
    """ Verifica operatore GREATER_THAN_OR_EQUAL con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target visibile se f_num >= 50
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "GREATER_THAN_OR_EQUAL", "value": 50}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: 51 >= 50 -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=51)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso POSITIVO: 50 >= 50 -> Visibile (caso limite)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=50)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso NEGATIVO: 49 < 50 -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=49)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_less_than_or_equal_number(db_session, setup_operator_scenario):
    """ Verifica operatore LESS_THAN_OR_EQUAL con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target obbligatorio se f_num <= 10
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "LESS_THAN_OR_EQUAL", "value": 10}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: 5 <= 10 -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=5)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso POSITIVO: 10 <= 10 -> Obbligatorio (caso limite)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=10)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso NEGATIVO: 11 > 10 -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=11)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_greater_than_or_equal_date(db_session, setup_operator_scenario):
    """ Verifica operatore GREATER_THAN_OR_EQUAL con date """
    ids = setup_operator_scenario
    service = RuleEngineService()

    target_date = "2024-01-01"

    # REGOLA: Target visibile se f_date >= 2024-01-01
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "GREATER_THAN_OR_EQUAL", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: Data successiva -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-06-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso POSITIVO: Stessa data -> Visibile (caso limite)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-01-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso NEGATIVO: Data precedente -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2023-12-31")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_less_than_or_equal_date(db_session, setup_operator_scenario):
    """ Verifica operatore LESS_THAN_OR_EQUAL con date """
    ids = setup_operator_scenario
    service = RuleEngineService()

    target_date = "2024-01-01"

    # REGOLA: Target obbligatorio se f_date <= 2024-01-01
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "LESS_THAN_OR_EQUAL", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: Data precedente -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2023-06-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso POSITIVO: Stessa data -> Obbligatorio (caso limite)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-01-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso NEGATIVO: Data successiva -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-01-02")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


# ============================================================
# LEXICOGRAPHIC STRING COMPARISON OPERATORS
# ============================================================

def test_operator_greater_than_string(db_session, setup_operator_scenario):
    """
    Verifica operatore GREATER_THAN con stringhe (confronto lessicografico).
    Le stringhe sono confrontate carattere per carattere secondo i codici Unicode.
    """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target visibile se f_str > "M" (lessicograficamente)
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "GREATER_THAN", "value": "M"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: "Z" > "M" -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="Z")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso POSITIVO: "N" > "M" -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="N")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso NEGATIVO: "M" non è > "M" -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="M")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # Caso NEGATIVO: "A" < "M" -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="A")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_less_than_string(db_session, setup_operator_scenario):
    """
    Verifica operatore LESS_THAN con stringhe (confronto lessicografico).
    """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target obbligatorio se f_str < "M"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "LESS_THAN", "value": "M"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: "A" < "M" -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="A")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso POSITIVO: "L" < "M" -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="L")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso NEGATIVO: "M" non è < "M" -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="M")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False

    # Caso NEGATIVO: "Z" > "M" -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="Z")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_greater_than_or_equal_string(db_session, setup_operator_scenario):
    """
    Verifica operatore GREATER_THAN_OR_EQUAL con stringhe (confronto lessicografico).
    """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target visibile se f_str >= "M"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "GREATER_THAN_OR_EQUAL", "value": "M"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: "Z" >= "M" -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="Z")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso POSITIVO: "M" >= "M" -> Visibile (caso limite)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="M")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # Caso NEGATIVO: "L" < "M" -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="L")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_less_than_or_equal_string(db_session, setup_operator_scenario):
    """
    Verifica operatore LESS_THAN_OR_EQUAL con stringhe (confronto lessicografico).
    """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target obbligatorio se f_str <= "M"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "LESS_THAN_OR_EQUAL", "value": "M"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Caso POSITIVO: "A" <= "M" -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="A")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso POSITIVO: "M" <= "M" -> Obbligatorio (caso limite)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="M")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Caso NEGATIVO: "N" > "M" -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="N")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_lexicographic_comparison_multichar_strings(db_session, setup_operator_scenario):
    """
    Verifica confronto lessicografico con stringhe multi-carattere.
    Dimostra che il confronto avviene carattere per carattere.
    """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # REGOLA: Target visibile se f_str >= "cat"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "GREATER_THAN_OR_EQUAL", "value": "cat"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # "cat" >= "cat" -> True
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="cat")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # "dog" >= "cat" -> True (d > c)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="dog")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # "car" >= "cat" -> False (car < cat perché 'r' < 't')
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="car")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # "apple" >= "cat" -> False (a < c)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="apple")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True