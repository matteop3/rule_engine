from typing import List, Dict, Any, Set
from sqlalchemy.orm import Session
from app.models.domain import Entity, Field, Value, Rule
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldOutputState, ValueOption, FieldInputState

class RuleEngineService:
    def calculate_state(self, db: Session, request: CalculationRequest) -> CalculationResponse:
        """
        Main calculation engine (CPQ logic).
        Performs waterfall on all entity fields.
        """
        
        # PERFORMANCE OPTIMIZATION
        # Load Entities, Fields (sorted), Values, and Rules with few queries
        entity = db.query(Entity).filter(Entity.id == request.entity_id).first()
        if not entity:
            raise ValueError(f"Entity {request.entity_id} not found")

        # Retrieve the fields sorted by sequence
        fields_db = db.query(Field).filter(Field.entity_id == entity.id).order_by(Field.sequence).all()
        
        # Retrieve ALL the values from these fields
        field_ids = [f.id for f in fields_db]
        all_values = db.query(Value).filter(Value.field_id.in_(field_ids)).all()
        
        # Retrieve ALL the rules for this entity
        all_rules = db.query(Rule).filter(Rule.entity_id == entity.id).all()

        # INDEXING (Create maps for fast memory access)        
        # Map: field_id -> Value objects list
        values_by_field: Dict[int, List[Value]] = {}
        for v in all_values:
            if v.field_id not in values_by_field:
                values_by_field[v.field_id] = []
            values_by_field[v.field_id].append(v)

        # Map: target_value_id -> Rule objects list (1-to-Many relationship to manage OR)
        rules_by_target_value: Dict[int, List[Rule]] = {}
        for r in all_rules:
            if r.target_value_id not in rules_by_target_value:
                rules_by_target_value[r.target_value_id] = []
            rules_by_target_value[r.target_value_id].append(r)

        # Map: current input user {field_id: value}
        # Note: convert everything to strings to make comparisons easier, or None
        user_input_map: Dict[int, Any] = {
            item.field_id: str(item.value) if item.value is not None else None 
            for item in request.current_state
        }

        # WATERFALL EXECUTION
        # Build the “Running Context” that updates step by step
        running_context: Dict[int, Any] = {} # Key: field_id, Value: current valid value
        output_fields: List[FieldOutputState] = []

        for field in fields_db:
            # Retrieve possible options (static)
            possible_values = values_by_field.get(field.id, [])
            
            # Filter available options (Rule-based dynamics)
            available_values_objs: List[Value] = []
            
            for val_obj in possible_values:
                # Retrieve rules for this specific value
                rules_for_val = rules_by_target_value.get(val_obj.id, [])
                
                if not rules_for_val:
                    # No rules = Always available
                    is_available = True
                else:
                    # OR logic between rules: only one needs to be true
                    is_available = False
                    for rule in rules_for_val:
                        if self._evaluate_rule(rule.conditions, running_context):
                            is_available = True
                            break # Once a valid rule has been found, the value is available.
                
                if is_available:
                    available_values_objs.append(val_obj)

            # Determine the final current value
            # Retrieve user input (if any)
            raw_input = user_input_map.get(field.id)
            final_value = None

            # Create a list of valid values for quick comparison
            valid_str_values = [v.value for v in available_values_objs]

            # Validation: user input is still valid?
            if raw_input is not None and raw_input in valid_str_values:
                final_value = raw_input
            else:
                # Invalid or missing input -> Reset to None
                final_value = None

            # Apply default (if None)
            if final_value is None:
                # Search for a default from available options
                for val_obj in available_values_objs:
                    if val_obj.is_default:
                        final_value = val_obj.value
                        break

            # Context and output update
            # Important: the context is updated with the calculated value, not the raw value.
            running_context[field.id] = final_value

            # Output building
            out_options = [
                ValueOption(id=v.id, value=v.value, label=v.label, is_default=v.is_default)
                for v in available_values_objs
            ]

            output_fields.append(FieldOutputState(
                field_id=field.id,
                field_name=field.name,
                current_value=final_value,
                available_options=out_options
            ))

        return CalculationResponse(entity_id=entity.id, fields=output_fields)

    def _evaluate_rule(self, conditions: Dict[str, Any], context: Dict[int, Any]) -> bool:
        """
        Evaluate a SINGLE rule.
        Logic: All criteria within are ANDed.
        """
        criteria_list = conditions.get("criteria", [])
        if not criteria_list:
            # Empty rule = True
            return True

        for criteria in criteria_list:
            if not self._check_criterion(criteria, context):
                return False # One failed criterion is enough to invalidate the AND
        
        return True # All criteria are passed

    def _check_criterion(self, criterion: Dict[str, Any], context: Dict[int, Any]) -> bool:
        """Compare: context[field_id] OPERATOR expected_Value"""
        # Note: here we assume that JSON uses “field_id” as the key.
        target_field_id = criterion.get("field_id") 
        operator = criterion.get("operator")
        expected_val = criterion.get("value")

        if target_field_id is None: 
            return False

        # Retrieve value from current context
        # Convert to string for safe comparison, handling None
        actual_val = context.get(target_field_id)
        
        if actual_val is None:
            # If the dependent field has no value, the criterion fails.
            return False

        # String normalization
        s_actual = str(actual_val)
        s_expected = str(expected_val)

        if operator == "EQUALS":
            return s_actual == s_expected
        
        elif operator == "NOT_EQUALS":
            return s_actual != s_expected
        
        elif operator == "IN":
            # Expected value must be a list or string separated
            if isinstance(expected_val, list):
                return s_actual in [str(x) for x in expected_val]
            return s_actual in s_expected

        elif operator == "GREATER_THAN":
            try:
                return float(s_actual) > float(s_expected)
            except ValueError:
                return False
        
        elif operator == "LESS_THAN":
            try:
                return float(s_actual) < float(s_expected)
            except ValueError:
                return False

        return False