import pytest
from app.models.domain import Entity, EntityVersion, Field, Rule, RuleType, VersionStatus, FieldType
from app.services.rule_engine import RuleEngineService
from app.schemas.engine import CalculationRequest, FieldInputState

@pytest.fixture(scope="function")
def setup_stress_scenario(db_session):
    """
    Scenario A -> B -> C (Domino)
    Scenario X <-> Y (Circular/Sequence)
    """
    entity = Entity(name="Stress Test", description="Complex Logic")
    db_session.add(entity)
    db_session.commit()
    
    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # --- FIELDS FOR DOMINO (A, B, C) ---
    # Sequence: 1, 2, 3
    f_a = Field(entity_version_id=version.id, name="A", label="Driver", data_type="string", sequence=1, is_free_value=True)
    f_b = Field(entity_version_id=version.id, name="B", label="Middle", data_type="string", sequence=2, is_free_value=True)
    f_c = Field(entity_version_id=version.id, name="C", label="Tail",   data_type="string", sequence=3, is_free_value=True)

    # --- FIELDS FOR SEQUENCE CHECK (X, Y) ---
    # X (Seq 10) depends on Y (Seq 20)
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
    Test the propagation of changes within the same cycle.
    Rule 1: If A == 'HIDE', hide B.
    Rule 2: If B is NULL (or hidden), hide C.

    Input: A='HIDE', B='Value', C='Value'
    Expected Output: B hidden AND C hidden.
    """
    ids = setup_stress_scenario
    service = RuleEngineService()

    # R1: POSITIVE logic -> Define when B is VISIBLE.
    # I want to hide B if A='HIDE'. So B is visible if A != 'HIDE'.
    r1 = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["B"], rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["A"], "operator": "NOT_EQUALS", "value": "HIDE"}]}
    )
    
    # R2: POSITIVE logic -> Define when C is VISIBLE.
    # C is visible only if B has the value 'SHOW'.
    # If B is hidden by the rule above, its value in the context becomes None -> Rule False -> C Hidden.
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
            FieldInputState(field_id=ids["B"], value="SHOW"), # Insert SHOW, but it will be hidden
            FieldInputState(field_id=ids["C"], value="ANY")
        ]
    )
    
    resp = service.calculate_state(db_session, payload)
    
    field_b = next(f for f in resp.fields if f.field_id == ids["B"])
    field_c = next(f for f in resp.fields if f.field_id == ids["C"])

    # 1. B must be hidden (due to A)
    assert field_b.is_hidden is True
    # 2. B must be None (because hidden)
    assert field_b.current_value is None

    # 3. C must be hidden?
    # If the engine updated the context after hiding B, then the rule on C
    # will read B=None. Since None != 'SHOW', C must be hidden.
    assert field_c.is_hidden is True, "Domino Effect failed: C should react to the fact that B was hidden."

def test_stress_future_dependency(db_session, setup_stress_scenario):
    """
    Test what happens if a rule depends on a field that comes later in the sequence.
    X (seq 10) depends on Y (seq 20).
    Rule: If Y='SECRET', hide X.
    """
    ids = setup_stress_scenario
    service = RuleEngineService()

    rule = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["X"], rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": ids["Y"], "operator": "EQUALS", "value": "SECRET"}]}
    )
    db_session.add(rule)
    db_session.commit()

    # The engine processes X. Y has not been processed yet (it comes after).
    # However, Y's value is present in the initial INPUT.
    # The engine should use the input value.
    payload = CalculationRequest(
        entity_id=ids["e_id"],
        current_state=[
            FieldInputState(field_id=ids["X"], value="I see you"),
            FieldInputState(field_id=ids["Y"], value="SECRET")
        ]
    )

    resp = service.calculate_state(db_session, payload)
    field_x = next(f for f in resp.fields if f.field_id == ids["X"])

    # X should be hidden because it reads the raw input of Y
    assert field_x.is_hidden is True

def test_stress_multiple_validations(db_session, setup_stress_scenario):
    """
    Test if the engine handles multiple errors or overwrites.
    Currently the FieldOutputState model has only one 'error_message' field.
    We expect it to take the last or first error (Last-Win or First-Win behavior).
    """
    ids = setup_stress_scenario
    service = RuleEngineService()

    # Rule 1: Error if A contains "ERR1"
    r1 = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["A"], rule_type=RuleType.VALIDATION.value,
        error_message="Error One",
        conditions={"criteria": [{"field_id": ids["A"], "operator": "EQUALS", "value": "ERR1"}]}
    )
    # Rule 2: Error if B contains "ERR1" (Note: using B to trigger error on A)
    # This simulates two different rules that break A.
    r2 = Rule(
        entity_version_id=ids["v_id"], target_field_id=ids["A"], rule_type=RuleType.VALIDATION.value,
        error_message="Error Two",
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

    # Simply verify that there is ONE error.
    # If we wanted to support multiple errors, we should change FieldOutputState.error_message to List[str]
    assert field_a.error_message in ["Error One", "Error Two"]