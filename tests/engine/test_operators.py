import pytest
from app.models.domain import Entity, EntityVersion, Field, Rule, RuleType, VersionStatus, FieldType
from app.services.rule_engine import RuleEngineService
from app.schemas.engine import CalculationRequest, FieldInputState

# --- SPECIFIC FIXTURE FOR OPERATOR TESTS ---
@pytest.fixture(scope="function")
def setup_operator_scenario(db_session):
    """
    Creates a minimal "laboratory" scenario to test technical operators.
    Does not use business logic (insurance), but generic fields A, B, C.
    """
    # 1. Entity & Version
    entity = Entity(name="Lab Entity", description="Unit Test Lab")
    db_session.add(entity)
    db_session.commit()
    
    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # 2. Generic Fields
    # Field A: Number
    f_num = Field(entity_version_id=version.id, name="field_num", label="Numero", data_type=FieldType.NUMBER.value, step=1, sequence=1, is_free_value=True)
    # Field B: String
    f_str = Field(entity_version_id=version.id, name="field_str", label="Stringa", data_type=FieldType.STRING.value, step=1, sequence=2, is_free_value=True)
    # Field C: Date
    f_date = Field(entity_version_id=version.id, name="field_date", label="Data", data_type=FieldType.DATE.value, step=1, sequence=3, is_free_value=True)
    # Target Field (to be validated)
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
    """ Verify IN operator with list of numbers """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target is VISIBLE only if f_num is IN [10, 20, 30]
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "IN", "value": [10, 20, 30]}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case (Value 20 is in the list)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=20)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False  # Visible

    # NEGATIVE case (Value 99 is not in the list)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=99)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True   # Hidden

def test_operator_not_equals_string(db_session, setup_operator_scenario):
    """ Verify NOT_EQUALS operator with strings """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Error if f_str is NOT equal to "PIPPO"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VALIDATION.value,
        error_message="Devi scrivere PIPPO",
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "NOT_EQUALS", "value": "PIPPO"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # ACTIVE VALIDATION case (Write "PLUTO" -> different from PIPPO -> Error)
    # Add a value for f_target, otherwise the engine skips validation
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["f_str"], value="PLUTO"),
            FieldInputState(field_id=ids["f_target"], value="Sto scrivendo qualcosa") 
        ]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.error_message == "Devi scrivere PIPPO"

    # PASSED VALIDATION case (Write "PIPPO" -> not different -> OK)
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
    Verify date robustness:
    Compare an Input date (ISO String) with a Rule date (ISO String)
    using mathematical operators.
    """
    ids = setup_operator_scenario
    service = RuleEngineService()
    
    target_date = "2023-01-01"

    # RULE: Mandatory if f_date < 2023-01-01
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "LESS_THAN", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # Case 1: Earlier date (2020) -> Must become Required
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2020-05-05")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # Case 2: Later date (2025) -> Not required
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2025-01-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False

def test_multiple_conditions_and_logic(db_session, setup_operator_scenario):
    """ Verify logic AND implicita (tutte le condizioni devono essere vere) """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target visible IF (Num > 10) AND (Str = 'OK')
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

    # Case: Only Num OK -> Hidden
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["f_num"], value=50),
            FieldInputState(field_id=ids["f_str"], value="NO")
        ]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # Case: Both OK -> Visible
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
    """ Verify operator EQUALS con stringhe """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target visible only if f_str == "MATCH"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "EQUALS", "value": "MATCH"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: Equal value -> Visible
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="MATCH")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # NEGATIVE case: Different value -> Hidden
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="DIFFERENT")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_equals_number(db_session, setup_operator_scenario):
    """ Verify operator EQUALS con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target required if f_num == 100
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "EQUALS", "value": 100}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: Equal value -> Required
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=100)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # NEGATIVE case: Different value -> Not required
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=99)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_greater_than_number(db_session, setup_operator_scenario):
    """ Verify operator GREATER_THAN con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target visible if f_num > 50
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "GREATER_THAN", "value": 50}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: 51 > 50 -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=51)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # NEGATIVE case: 50 non è > 50 -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=50)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # NEGATIVE case: 49 < 50 -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=49)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_less_than_number(db_session, setup_operator_scenario):
    """ Verify operator LESS_THAN con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target required if f_num < 10
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "LESS_THAN", "value": 10}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: 5 < 10 -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=5)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # NEGATIVE case: 10 non è < 10 -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=10)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False

    # NEGATIVE case: 15 > 10 -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=15)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_in_list_strings(db_session, setup_operator_scenario):
    """ Verify operator IN con lista di stringhe """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target visible only if f_str is IN ["A", "B", "C"]
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "IN", "value": ["A", "B", "C"]}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: "B" è nella lista
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="B")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # NEGATIVE case: "X" non è nella lista
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="X")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_equals_date(db_session, setup_operator_scenario):
    """ Verify operator EQUALS con date """
    ids = setup_operator_scenario
    service = RuleEngineService()

    target_date = "2024-06-15"

    # RULE: Target required if f_date == 2024-06-15
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "EQUALS", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: Stessa data -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-06-15")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # NEGATIVE case: Data diversa -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-06-16")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_greater_than_date(db_session, setup_operator_scenario):
    """ Verify operator GREATER_THAN con date """
    ids = setup_operator_scenario
    service = RuleEngineService()

    target_date = "2024-01-01"

    # RULE: Target visible if f_date > 2024-01-01
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "GREATER_THAN", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: Data successiva -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-06-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # NEGATIVE case: Stessa data -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-01-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # NEGATIVE case: Data precedente -> Nascosto
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
    """ Verify operator GREATER_THAN_OR_EQUAL con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target visible if f_num >= 50
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "GREATER_THAN_OR_EQUAL", "value": 50}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: 51 >= 50 -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=51)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # POSITIVE case: 50 >= 50 -> Visibile (edge case)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=50)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # NEGATIVE case: 49 < 50 -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=49)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_less_than_or_equal_number(db_session, setup_operator_scenario):
    """ Verify operator LESS_THAN_OR_EQUAL con numeri """
    ids = setup_operator_scenario
    service = RuleEngineService()

    # RULE: Target required if f_num <= 10
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_num"], "operator": "LESS_THAN_OR_EQUAL", "value": 10}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: 5 <= 10 -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=5)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # POSITIVE case: 10 <= 10 -> Obbligatorio (edge case)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=10)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # NEGATIVE case: 11 > 10 -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_num"], value=11)]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False


def test_operator_greater_than_or_equal_date(db_session, setup_operator_scenario):
    """ Verify operator GREATER_THAN_OR_EQUAL con date """
    ids = setup_operator_scenario
    service = RuleEngineService()

    target_date = "2024-01-01"

    # RULE: Target visible if f_date >= 2024-01-01
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "GREATER_THAN_OR_EQUAL", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: Data successiva -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-06-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # POSITIVE case: Stessa data -> Visibile (edge case)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-01-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # NEGATIVE case: Data precedente -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2023-12-31")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True


def test_operator_less_than_or_equal_date(db_session, setup_operator_scenario):
    """ Verify operator LESS_THAN_OR_EQUAL con date """
    ids = setup_operator_scenario
    service = RuleEngineService()

    target_date = "2024-01-01"

    # RULE: Target required if f_date <= 2024-01-01
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_date"], "operator": "LESS_THAN_OR_EQUAL", "value": target_date}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: Data precedente -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2023-06-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # POSITIVE case: Stessa data -> Obbligatorio (edge case)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_date"], value="2024-01-01")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # NEGATIVE case: Data successiva -> Non obbligatorio
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

    # RULE: Target visible if f_str > "M" (lexicographically)
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "GREATER_THAN", "value": "M"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: "Z" > "M" -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="Z")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # POSITIVE case: "N" > "M" -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="N")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # NEGATIVE case: "M" non è > "M" -> Nascosto
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="M")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is True

    # NEGATIVE case: "A" < "M" -> Nascosto
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

    # RULE: Target required if f_str < "M"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "LESS_THAN", "value": "M"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: "A" < "M" -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="A")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # POSITIVE case: "L" < "M" -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="L")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # NEGATIVE case: "M" non è < "M" -> Non obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="M")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is False

    # NEGATIVE case: "Z" > "M" -> Non obbligatorio
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

    # RULE: Target visible if f_str >= "M"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "GREATER_THAN_OR_EQUAL", "value": "M"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: "Z" >= "M" -> Visibile
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="Z")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # POSITIVE case: "M" >= "M" -> Visibile (edge case)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="M")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_hidden is False

    # NEGATIVE case: "L" < "M" -> Nascosto
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

    # RULE: Target required if f_str <= "M"
    rule = Rule(
        entity_version_id=ids["v_id"],
        target_field_id=ids["f_target"],
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": ids["f_str"], "operator": "LESS_THAN_OR_EQUAL", "value": "M"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # POSITIVE case: "A" <= "M" -> Obbligatorio
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="A")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # POSITIVE case: "M" <= "M" -> Obbligatorio (edge case)
    resp = service.calculate_state(db_session, CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[FieldInputState(field_id=ids["f_str"], value="M")]
    ))
    f_out = next(f for f in resp.fields if f.field_id == ids["f_target"])
    assert f_out.is_required is True

    # NEGATIVE case: "N" > "M" -> Non obbligatorio
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

    # RULE: Target visible if f_str >= "cat"
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