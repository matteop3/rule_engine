from typing import Any, Dict, List, Union

class RuleEngine:
    """
    Core service responsible for evaluating logical conditions against a provided context.
    """

    def evaluate(self, rule_structure: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Recursively evaluates a rule structure (JSON) against a data context.
        
        :param rule_structure: The JSON dict defining the logic (e.g., {"operator": "AND", "criteria": [...]})
        :param context: A dictionary containing the current values selected by the user (e.g., {"age": 25, "country": "IT"})
        :return: True if the condition is met, False otherwise.
        """
        
        # 1. Base Case: If the rule is empty, we assume it's valid (or handle as error depending on requirements)
        if not rule_structure:
            return True

        operator = rule_structure.get("operator")
        
        # 2. Logic Operators (AND / OR) -> Recursive Step
        if operator == "AND":
            criteria = rule_structure.get("criteria", [])
            # All sub-conditions must be True
            return all(self.evaluate(sub_rule, context) for sub_rule in criteria)
        
        elif operator == "OR":
            criteria = rule_structure.get("criteria", [])
            # At least one sub-condition must be True
            return any(self.evaluate(sub_rule, context) for sub_rule in criteria)

        # 3. Comparison Operators (Leaf Nodes)
        else:
            return self._evaluate_criterion(rule_structure, context)

    def _evaluate_criterion(self, criterion: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Evaluates a single leaf condition (e.g., "age > 18").
        """
        field_name = criterion.get("field_name")
        operator = criterion.get("operator")
        expected_value = criterion.get("value")

        # 1. Type Guard: Ensure field_name is a valid string
        if not isinstance(field_name, str):
            return False

        # 2. Type Guard: Ensure expected_value is present (not None)
        # We need this check because float(None) raises an error
        if expected_value is None:
            return False

        # Get the actual value from the context.
        actual_value = context.get(field_name)

        # 3. Fail-safe: If the actual data is missing from context, return False
        if actual_value is None:
            return False 

        # --- Operators Logic ---
        
        if operator == "EQUALS":
            return str(actual_value) == str(expected_value)
        
        elif operator == "NOT_EQUALS":
            return str(actual_value) != str(expected_value)
        
        elif operator == "GREATER_THAN":
            try:
                # Now Pylance knows both values are not None
                return float(actual_value) > float(expected_value)
            except (ValueError, TypeError):
                return False

        elif operator == "LESS_THAN":
            try:
                return float(actual_value) < float(expected_value)
            except (ValueError, TypeError):
                return False
                
        elif operator == "IN":
            if isinstance(expected_value, list):
                return str(actual_value) in [str(v) for v in expected_value]
            return str(actual_value) in str(expected_value)

        return False