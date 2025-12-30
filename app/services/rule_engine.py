from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.domain import Entity, Field, FieldType, Value, Rule, RuleType, EntityVersion, VersionStatus
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldOutputState, ValueOption
from datetime import date

class RuleEngineService:
    def calculate_state(self, db: Session, request: CalculationRequest) -> CalculationResponse:
        """
        CPQ core engine.
        Finds the PUBLISHED Version of the Entity and executes waterfall logic.
        """

        # Fetch Entity
        entity = db.query(Entity).filter(Entity.id == request.entity_id).first()
        if not entity:
            raise ValueError(f"Entity {request.entity_id} not found.")

        target_version = None

        # Preview mode (explicit Version)
        if request.entity_version_id is not None:
            target_version = db.query(EntityVersion).filter(
                EntityVersion.id == request.entity_version_id
            ).first()

            if not target_version:
                raise ValueError(f"Version {request.entity_version_id} not found.")
            
            # Integrity check: ensure the Version belongs to the requested Entity
            if target_version.entity_id != request.entity_id:
                raise ValueError(f"Version {request.entity_version_id} does not belong to Entity {request.entity_id}.")

        # Production mode (PUBLISHED Version)
        else:
            # Fetch PUBLISHED Version
            target_version = db.query(EntityVersion).filter(
                EntityVersion.entity_id == request.entity_id,
                EntityVersion.status == VersionStatus.PUBLISHED
            ).first()

            if not target_version:
                raise ValueError(f"Entity {request.entity_id} has no PUBLISHED version ready for calculation.")
        
        # Fetch Fields and Rules from the target Version
        fields_db = db.query(Field).filter(
            Field.entity_version_id == target_version.id
        ).order_by(Field.step, Field.sequence).all()
        
        field_ids = [f.id for f in fields_db]
        all_values = db.query(Value).filter(Value.field_id.in_(field_ids)).all()
        
        # Retrieve Rules for this Version
        all_rules = db.query(Rule).filter(
            Rule.entity_version_id == target_version.id
        ).all()

        # Prepare Fields data_type map
        type_map: Dict[int, str] = {f.id: f.data_type for f in fields_db}

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
                if r.target_field_id == field.id and r.rule_type == RuleType.VISIBILITY
            ]
            
            # Start from DB static configuration
            is_visible = not field.is_hidden 
            
            if visibility_rules:
                # Visibility logic: field is hidden unless a rule passes
                is_rule_passed = False
                for rule in visibility_rules:
                    if self._evaluate_rule(rule.conditions, running_context, type_map):
                        is_rule_passed = True
                        break
                is_visible = is_rule_passed

            if not is_visible:
                # Field is hidden: reset value and skip processing
                running_context[field.id] = None
                output_fields.append(FieldOutputState(
                    field_id=field.id,
                    field_name=field.name,
                    field_label=field.label,
                    current_value=None,
                    available_options=[],
                    is_required=field.is_required,
                    is_readonly=field.is_readonly,
                    is_hidden=not is_visible,
                    error_message=None
                ))
                continue 

            # Layer 2: editability check
            editability_rules = [
                r for r in all_rules 
                if r.target_field_id == field.id and r.rule_type == RuleType.EDITABILITY
            ]
            
            is_readonly = field.is_readonly
            
            if editability_rules:
                # "Enable if" logic: field is readonly unless a rule passes
                is_rule_passed = False
                for rule in editability_rules:
                    if self._evaluate_rule(rule.conditions, running_context, type_map):
                        is_rule_passed = True
                        break
                is_readonly = not is_rule_passed

            # Layer 3: mandatory check
            mandatory_rules = [
                r for r in all_rules 
                if r.target_field_id == field.id and r.rule_type == RuleType.MANDATORY
            ]
            
            # Start from DB static configuration
            is_required = field.is_required

            if mandatory_rules:
                # "Make mandatory if" logic: field becomes required if a rule passes
                for rule in mandatory_rules:
                    if self._evaluate_rule(rule.conditions, running_context, type_map):
                        is_required = True
                        break

            # Layer 4: values availability
            possible_values = values_by_field.get(field.id, [])
            available_values_objs: List[Value] = []

            if field.is_free_value:
                # Free-value fields
                raw_input = user_input_map.get(field.id)
                final_value = raw_input 
                
                # Default application logic
                if is_required and final_value is None and field.default_value is not None:
                    final_value = field.default_value

                out_options = []

            else:
                # Fields with a data source
                for val_obj in possible_values:
                    # Check rules specific to this value
                    rules_for_val = [
                        r for r in rules_by_target_value.get(val_obj.id, [])
                        if r.rule_type == RuleType.AVAILABILITY
                    ]
                    
                    if not rules_for_val:
                        # No explicit rules means that the Value is available
                        is_available = True
                    else:
                        is_available = False
                        for rule in rules_for_val:
                            if self._evaluate_rule(rule.conditions, running_context, type_map):
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
                
                if final_value is None and is_required:
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

            # Layer 5: validation (negative pattern: if rule passes -> error message)
            validation_error = None

            if is_visible and final_value is not None:                
                validation_rules = [
                    r for r in all_rules 
                    if r.target_field_id == field.id and r.rule_type == RuleType.VALIDATION
                ]

                for rule in validation_rules:
                    if self._evaluate_rule(rule.conditions, running_context, type_map):
                        validation_error = rule.error_message or "Validation error."
                        break

            # Finalization
            running_context[field.id] = final_value

            output_fields.append(FieldOutputState(
                field_id=field.id,
                field_name=field.name,
                field_label=field.label,
                current_value=final_value,
                available_options=out_options,
                is_required=is_required,
                is_readonly=is_readonly,
                is_hidden=not is_visible,
                error_message=validation_error
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

    def _evaluate_rule(self, conditions: Dict[str, Any], context: Dict[int, Any], type_map: Dict[int, str]) -> bool:
        """
        Evaluate a SINGLE rule.
        Logic: All criteria within are ANDed.
        """
        criteria_list = conditions.get("criteria", [])
        if not criteria_list:
            # Empty rule = True
            return True

        for criteria in criteria_list:
            if not self._check_criterion(criteria, context, type_map):
                return False # One failed criterion is enough to invalidate the AND
        
        return True # All criteria are passed

    def _check_criterion(self, criterion: Dict[str, Any], context: Dict[int, Any], type_map: Dict[int, str]) -> bool:
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
        
        # Retrieve Field's data_type
        f_type = type_map.get(target_field_id, FieldType.STRING)

        try:
            # Date handling
            if f_type == FieldType.DATE:
                if expected_val is None:
                    return False
                
                # Assume ISO format YYYY-MM-DD
                d_actual = date.fromisoformat(str(actual_val))

                if operator == "IN":
                    if isinstance(expected_val, list):
                        # Convert every list element to date
                        target_dates = []
                        for x in expected_val:
                            try:
                                target_dates.append(date.fromisoformat(str(x)))
                            except ValueError:
                                continue # Ignore wrong items
                        return d_actual in target_dates
                    else:
                        # If 'IN' but not a real list
                        return d_actual == date.fromisoformat(str(expected_val))

                d_expected = date.fromisoformat(str(expected_val))
                
                if operator == "GREATER_THAN": return d_actual > d_expected
                if operator == "LESS_THAN":    return d_actual < d_expected
                if operator == "EQUALS":       return d_actual == d_expected
                if operator == "NOT_EQUALS":   return d_actual != d_expected

            # Number handling
            elif f_type == FieldType.NUMBER:
                if expected_val is None:
                    return False
                
                n_actual = float(actual_val)

                if operator == "IN":
                    if isinstance(expected_val, list):
                        # Convert every list element to date
                        target_numbers = []
                        for x in expected_val:
                            try:
                                target_numbers.append(float(x))
                            except (ValueError, TypeError):
                                continue # Ignore wrong items
                        return n_actual in target_numbers
                    else:
                        # If 'IN' but not a real list
                        return n_actual == float(expected_val)

                n_expected = float(expected_val)
                
                if operator == "GREATER_THAN": return n_actual > n_expected
                if operator == "LESS_THAN":    return n_actual < n_expected
                if operator == "EQUALS":       return n_actual == n_expected
                if operator == "NOT_EQUALS":   return n_actual != n_expected

            # String/boolean handling
            else:
                s_actual = str(actual_val)
                s_expected = str(expected_val)

                if operator == "EQUALS":       return s_actual == s_expected
                if operator == "NOT_EQUALS":   return s_actual != s_expected
                if operator == "GREATER_THAN": return s_actual > s_expected
                if operator == "LESS_THAN":    return s_actual < s_expected
                
                if operator == "IN":
                    if isinstance(expected_val, list):
                        return s_actual in [str(x) for x in expected_val]
                    return s_actual in s_expected

        except (ValueError, TypeError):
            # Casting failed
            return False

        return False