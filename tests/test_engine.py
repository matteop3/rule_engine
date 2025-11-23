from app.services.rule_engine import RuleEngine

def test_simple_equals_true():
    engine = RuleEngine()
    rule = {
        "field_name": "Category",
        "operator": "EQUALS",
        "value": "Luxury"
    }
    context = {"Category": "Luxury"}
    assert engine.evaluate(rule, context) is True

def test_simple_equals_false():
    engine = RuleEngine()
    rule = {
        "field_name": "Category",
        "operator": "EQUALS",
        "value": "Luxury"
    }
    context = {"Category": "Budget"}
    assert engine.evaluate(rule, context) is False

def test_complex_and_logic():
    engine = RuleEngine()
    # Rule: (Category == Luxury) AND (Age > 18)
    rule = {
        "operator": "AND",
        "criteria": [
            {"field_name": "Category", "operator": "EQUALS", "value": "Luxury"},
            {"field_name": "Age", "operator": "GREATER_THAN", "value": 18}
        ]
    }
    
    # Case 1: Both true -> Pass
    context_pass = {"Category": "Luxury", "Age": 25}
    assert engine.evaluate(rule, context_pass) is True
    
    # Case 2: One false -> Fail
    context_fail = {"Category": "Luxury", "Age": 10}
    assert engine.evaluate(rule, context_fail) is False