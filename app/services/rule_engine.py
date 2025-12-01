from typing import List, Dict, Any, Set
from sqlalchemy.orm import Session
from app.models.domain import Entity, Field, Value, Rule
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldOutputState, ValueOption, FieldInputState

class RuleEngineService:
    def calculate_state(self, db: Session, request: CalculationRequest) -> CalculationResponse:
        """
        CPQ Core Engine.
        Executes waterfall logic on all entity fields.
        """
        
        # PERFORMANCE OPTIMIZATION
        # Load Entities, Fields (sorted), Values, and Rules with few queries
        entity = db.query(Entity).filter(Entity.id == request.entity_id).first()
        if not entity:
            raise ValueError(f"Entity {request.entity_id} not found")

        # Retrieve the fields sorted by sequence
        fields_db = db.query(Field).filter(Field.entity_id == entity.id).order_by(Field.step, Field.sequence).all()
        
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
            # Index rules by target_value_id only if it exists (availability rules)
            if r.target_value_id is not None:
                if r.target_value_id not in rules_by_target_value:
                    rules_by_target_value[r.target_value_id] = []
                rules_by_target_value[r.target_value_id].append(r)

        # User input normalization
        user_input_map: Dict[int, Any] = {}
        for item in request.current_state:
            val = item.value
            if isinstance(val, str):
                val = val.strip()
                if not val:
                    val = None
            user_input_map[item.field_id] = val

        # WATERFALL EXECUTION
        running_context: Dict[int, Any] = {}
        output_fields: List[FieldOutputState] = []

        for field in fields_db:

            # Layer 1: visibility check
            visibility_rules = [
                r for r in all_rules 
                if r.target_field_id == field.id and r.rule_type == "visibility"
            ]
            
            # Start from DB static configuration
            is_visible = not field.is_hidden 
            
            if visibility_rules:
                # Visibility logic: field is hidden unless a rule passes
                is_rule_passed = False
                for rule in visibility_rules:
                    if self._evaluate_rule(rule.conditions, running_context):
                        is_rule_passed = True
                        break
                is_visible = is_rule_passed

            if not is_visible:
                # Field is hidden: reset value and skip processing
                running_context[field.id] = None
                output_fields.append(FieldOutputState(
                    field_id=field.id,
                    field_name=field.name,
                    current_value=None,
                    available_options=[],
                    is_required=field.is_required,
                    is_readonly=field.is_readonly,
                    is_hidden=True
                ))
                continue 

            # Layer 2: editability check
            editability_rules = [
                r for r in all_rules 
                if r.target_field_id == field.id and r.rule_type == "editability"
            ]
            
            is_readonly = field.is_readonly
            
            if editability_rules:
                # "Enable if" logic: field is readonly unless a rule passes
                is_rule_passed = False
                for rule in editability_rules:
                    if self._evaluate_rule(rule.conditions, running_context):
                        is_rule_passed = True
                        break
                is_readonly = not is_rule_passed

            # Layer 3: values availability
            possible_values = values_by_field.get(field.id, [])
            available_values_objs: List[Value] = []

            if field.is_free_value:
                # Free-value fields
                raw_input = user_input_map.get(field.id)
                final_value = raw_input 
                
                # Default application logic
                if field.is_required and final_value is None and field.default_value is not None:
                    final_value = field.default_value

                out_options = []

            else:
                # Fields with a data source
                for val_obj in possible_values:
                    # Check rules specific to this value
                    rules_for_val = [
                        r for r in rules_by_target_value.get(val_obj.id, [])
                        if r.rule_type == 'availability'
                    ]
                    
                    if not rules_for_val:
                        # No explicit rules means that the Value is available
                        is_available = True
                    else:
                        is_available = False
                        for rule in rules_for_val:
                            if self._evaluate_rule(rule.conditions, running_context):
                                is_available = True
                                break # Or logic: a single passed Rule is enough to make the Value available
                    
                    if is_available:
                        available_values_objs.append(val_obj)

                # Validation and auto-selection
                raw_input = user_input_map.get(field.id)
                final_value = None
                valid_str_values = [v.value for v in available_values_objs]

                if raw_input is not None and raw_input in valid_str_values:
                    final_value = raw_input
                
                if final_value is None and field.is_required:
                    if len(available_values_objs) == 1:
                        # Force single option
                        final_value = available_values_objs[0].value
                    else:
                        # Default Value application: look for the first default you find.
                        final_value = next((val_obj.value for val_obj in available_values_objs if val_obj.is_default), None)
                
                out_options = [
                    ValueOption(id=v.id, value=v.value, label=v.label, is_default=v.is_default)
                    for v in available_values_objs
                ]

            # Finalization
            running_context[field.id] = final_value

            output_fields.append(FieldOutputState(
                field_id=field.id,
                field_name=field.name,
                current_value=final_value,
                available_options=out_options,
                is_required=field.is_required,
                is_readonly=is_readonly, # Calculated dynamic readonly
                is_hidden=False # We know it's visible if we reached here
            ))

        # Check global completeness for the response flag
        global_complete = True
        for out_f in output_fields:
            if out_f.is_required and not out_f.is_hidden and out_f.current_value is None:
                global_complete = False
                break

        return CalculationResponse(
            entity_id=entity.id, 
            fields=output_fields,
            is_complete=global_complete
        )

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