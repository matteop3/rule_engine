from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session, joinedload
from app.models.domain import Entity, Field, FieldType, Value, Rule, RuleType, EntityVersion, VersionStatus
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldOutputState, ValueOption
from datetime import date, datetime


class RuleEngineService:
    """
    CPQ Rule Engine: evaluates field states based on rules and user input.
    
    Note: This service does NOT handle database commits.
    """
    
    def calculate_state(
        self, 
        db: Session, 
        request: CalculationRequest
    ) -> CalculationResponse:
        """
        CPQ core engine.
        Finds the target Version (PUBLISHED or explicit) and executes waterfall logic.
        """
        
        # Resolve target version
        target_version = self._resolve_target_version(db, request)
        
        # Load all data for the version (with optimized queries)
        fields_db, all_values, all_rules = self._load_version_data(db, target_version.id)
        
        # Build indexing structures
        type_map = self._build_type_map(fields_db)
        values_by_field = self._build_values_index(all_values)
        rules_by_target_value = self._build_rules_index(all_rules)
        user_input_map = self._normalize_user_input(request.current_state)
        
        # Execute waterfall
        running_context: Dict[int, Any] = {}
        output_fields: List[FieldOutputState] = []
        
        for field in fields_db:
            field_state = self._process_field(
                field=field,
                all_rules=all_rules,
                values_by_field=values_by_field,
                rules_by_target_value=rules_by_target_value,
                user_input_map=user_input_map,
                running_context=running_context,
                type_map=type_map
            )
            
            output_fields.append(field_state)
            running_context[field.id] = field_state.current_value
        
        # Check global completeness
        is_complete = self._check_completeness(output_fields)
        
        return CalculationResponse(
            entity_id=request.entity_id,
            fields=output_fields,
            is_complete=is_complete
        )
    

    # ============================================================
    # DATA LOADING & INDEXING
    # ============================================================
    
    def _resolve_target_version(
        self, 
        db: Session, 
        request: CalculationRequest
    ) -> EntityVersion:
        """
        Resolves the target EntityVersion based on request parameters.
        
        - If entity_version_id is provided: preview mode (explicit version)
        - Otherwise: production mode (PUBLISHED version)
        """
        # Check entity existence
        entity = db.query(Entity).filter(Entity.id == request.entity_id).first()
        if not entity:
            raise ValueError(f"Entity {request.entity_id} not found.")
        
        # Preview mode
        if request.entity_version_id is not None:
            target_version = db.query(EntityVersion).filter(
                EntityVersion.id == request.entity_version_id
            ).first()
            
            if not target_version:
                raise ValueError(f"Version {request.entity_version_id} not found.")
            
            if target_version.entity_id != request.entity_id:
                raise ValueError(
                    f"Version {request.entity_version_id} does not belong to "
                    f"Entity {request.entity_id}."
                )
            
            return target_version
        
        # Production mode
        target_version = db.query(EntityVersion).filter(
            EntityVersion.entity_id == request.entity_id,
            EntityVersion.status == VersionStatus.PUBLISHED
        ).first()
        
        if not target_version:
            raise ValueError(
                f"Entity {request.entity_id} has no PUBLISHED version ready for calculation."
            )
        
        return target_version
    
    def _load_version_data(
        self, 
        db: Session, 
        version_id: int
    ) -> Tuple[List[Field], List[Value], List[Rule]]:
        """
        Loads all Fields, Values, and Rules for a given version.
        
        Note: avoid N+1 by loading Values and Rules separately
        instead of relying on lazy loading through relationships.
        """
        # Load fields ordered by execution sequence
        fields_db = db.query(Field).filter(
            Field.entity_version_id == version_id
        ).order_by(Field.step, Field.sequence).all()
        
        field_ids = [f.id for f in fields_db]
        
        # Batch load all values
        all_values = db.query(Value).filter(
            Value.field_id.in_(field_ids)
        ).all() if field_ids else []
        
        # Batch load all rules
        all_rules = db.query(Rule).filter(
            Rule.entity_version_id == version_id
        ).all()
        
        return fields_db, all_values, all_rules
    
    def _build_type_map(self, fields: List[Field]) -> Dict[int, str]:
        """Creates a mapping of field_id -> data_type string."""
        return {f.id: f.data_type for f in fields}
    
    def _build_values_index(self, values: List[Value]) -> Dict[int, List[Value]]:
        """Creates a mapping of field_id -> list of Value objects."""
        index: Dict[int, List[Value]] = {}
        for v in values:
            if v.field_id not in index:
                index[v.field_id] = []
            index[v.field_id].append(v)
        return index
    
    def _build_rules_index(self, rules: List[Rule]) -> Dict[int, List[Rule]]:
        """
        Creates a mapping of target_value_id -> list of Rule objects.
        Only indexes rules with a target_value_id (availability rules).
        """
        index: Dict[int, List[Rule]] = {}
        for r in rules:
            if r.target_value_id is not None:
                if r.target_value_id not in index:
                    index[r.target_value_id] = []
                index[r.target_value_id].append(r)
        return index
    
    def _normalize_user_input(
        self, 
        current_state: List[Any]
    ) -> Dict[int, Any]:
        """
        Normalizes user input by stripping strings and converting empty to None.
        """
        user_input_map: Dict[int, Any] = {}
        for item in current_state:
            val = item.value
            if isinstance(val, str):
                val = val.strip()
                if not val:
                    val = None
            elif isinstance(val, list):
                if len(val) == 0:
                    val = None
            user_input_map[item.field_id] = val
        return user_input_map
    

    # ============================================================
    # FIELD PROCESSING (Waterfall Logic)
    # ============================================================
    
    def _process_field(
        self,
        field: Field,
        all_rules: List[Rule],
        values_by_field: Dict[int, List[Value]],
        rules_by_target_value: Dict[int, List[Rule]],
        user_input_map: Dict[int, Any],
        running_context: Dict[int, Any],
        type_map: Dict[int, str]
    ) -> FieldOutputState:
        """
        Processes a single field through the waterfall logic:
        1. Visibility
        2. Editability
        3. Mandatory
        4. Availability
        5. Validation
        """
        
        # Layer 1: Visibility
        is_visible = self._evaluate_visibility(field, all_rules, running_context, type_map)
        
        if not is_visible:
            return FieldOutputState(
                field_id=field.id,
                field_name=field.name,
                field_label=field.label,
                current_value=None,
                available_options=[],
                is_required=field.is_required,
                is_readonly=field.is_readonly,
                is_hidden=True,
                error_message=None
            )
        
        # Layer 2: Editability
        is_readonly = self._evaluate_editability(field, all_rules, running_context, type_map)
        
        # Layer 3: Mandatory
        is_required = self._evaluate_mandatory(field, all_rules, running_context, type_map)
        
        # Layer 4: Availability & Value selection
        final_value, available_options = self._evaluate_availability(
            field=field,
            values_by_field=values_by_field,
            rules_by_target_value=rules_by_target_value,
            user_input_map=user_input_map,
            running_context=running_context,
            type_map=type_map,
            is_required=is_required
        )
        
        # Update context before validation
        running_context[field.id] = final_value
        
        # Layer 5: Validation
        validation_error = self._evaluate_validation(
            field=field,
            all_rules=all_rules,
            final_value=final_value,
            running_context=running_context,
            type_map=type_map,
            is_required=is_required
        )
        
        return FieldOutputState(
            field_id=field.id,
            field_name=field.name,
            field_label=field.label,
            current_value=final_value,
            available_options=available_options,
            is_required=is_required,
            is_readonly=is_readonly,
            is_hidden=False,
            error_message=validation_error
        )
    

    # ============================================================
    # RULE EVALUATION LAYERS (DRY Pattern)
    # ============================================================
    
    def _get_rules_by_type(
        self, 
        field_id: int, 
        rule_type: RuleType, 
        all_rules: List[Rule]
    ) -> List[Rule]:
        """
        Helper to filter rules by field and type.
        Eliminates repetitive list comprehensions.
        """
        return [
            r for r in all_rules
            if r.target_field_id == field_id 
            and r.rule_type == rule_type
        ]
    
    def _evaluate_visibility(
        self,
        field: Field,
        all_rules: List[Rule],
        running_context: Dict[int, Any],
        type_map: Dict[int, str]
    ) -> bool:
        """
        Layer 1: Determines if field is visible.
        Logic: Hidden unless a VISIBILITY rule passes.
        """
        visibility_rules = self._get_rules_by_type(
            field.id, RuleType.VISIBILITY, all_rules
        )
        
        if not visibility_rules:
            return not field.is_hidden
        
        # Field is hidden unless a rule passes
        for rule in visibility_rules:
            if self._evaluate_rule(rule.conditions, running_context, type_map):
                return True  # Visible
        
        return False  # Hidden
    
    def _evaluate_editability(
        self,
        field: Field,
        all_rules: List[Rule],
        running_context: Dict[int, Any],
        type_map: Dict[int, str]
    ) -> bool:
        """
        Layer 2: Determines if field is readonly.
        Logic: Readonly unless an EDITABILITY rule passes.
        """
        editability_rules = self._get_rules_by_type(
            field.id, RuleType.EDITABILITY, all_rules
        )
        
        if not editability_rules:
            return field.is_readonly
        
        # Field is readonly unless a rule passes
        for rule in editability_rules:
            if self._evaluate_rule(rule.conditions, running_context, type_map):
                return False  # Editable
        
        return True  # Readonly
    
    def _evaluate_mandatory(
        self,
        field: Field,
        all_rules: List[Rule],
        running_context: Dict[int, Any],
        type_map: Dict[int, str]
    ) -> bool:
        """
        Layer 3: Determines if field is required.
        Logic: Starts from field.is_required, becomes required if a MANDATORY rule passes.
        """
        mandatory_rules = self._get_rules_by_type(
            field.id, RuleType.MANDATORY, all_rules
        )
        
        is_required = field.is_required
        
        for rule in mandatory_rules:
            if self._evaluate_rule(rule.conditions, running_context, type_map):
                is_required = True
                break
        
        return is_required
    
    def _evaluate_availability(
        self,
        field: Field,
        values_by_field: Dict[int, List[Value]],
        rules_by_target_value: Dict[int, List[Rule]],
        user_input_map: Dict[int, Any],
        running_context: Dict[int, Any],
        type_map: Dict[int, str],
        is_required: bool
    ) -> Tuple[Any, List[ValueOption]]:
        """
        Layer 4: Determines available values and selects final value.
        
        Returns Tuple of (final_value, available_options)
        """
        
        if field.is_free_value:
            return self._handle_free_value_field(
                field, user_input_map, is_required
            )
        
        return self._handle_restricted_value_field(
            field=field,
            values_by_field=values_by_field,
            rules_by_target_value=rules_by_target_value,
            user_input_map=user_input_map,
            running_context=running_context,
            type_map=type_map,
            is_required=is_required
        )
    
    def _handle_free_value_field(
        self,
        field: Field,
        user_input_map: Dict[int, Any],
        is_required: bool
    ) -> Tuple[Any, List[ValueOption]]:
        """Handles fields with free-text input."""
        raw_input = user_input_map.get(field.id)
        final_value = raw_input
        
        # Apply default if required and empty
        if is_required and final_value is None and field.default_value is not None:
            final_value = field.default_value
        
        return final_value, []
    
    def _handle_restricted_value_field(
        self,
        field: Field,
        values_by_field: Dict[int, List[Value]],
        rules_by_target_value: Dict[int, List[Rule]],
        user_input_map: Dict[int, Any],
        running_context: Dict[int, Any],
        type_map: Dict[int, str],
        is_required: bool
    ) -> Tuple[Any, List[ValueOption]]:
        """Handles fields with predefined value options."""
        
        possible_values = values_by_field.get(field.id, [])
        available_values: List[Value] = []
        
        # Filter available values based on rules
        for val_obj in possible_values:
            if self._is_value_available(
                val_obj, rules_by_target_value, running_context, type_map
            ):
                available_values.append(val_obj)
        
        # Select final value
        raw_input = user_input_map.get(field.id)
        valid_str_values = [v.value for v in available_values]
        
        final_value = None
        if raw_input is not None and raw_input in valid_str_values:
            final_value = raw_input
        
        # Auto-selection logic for required fields
        if final_value is None and is_required:
            final_value = self._auto_select_value(available_values)
        
        # Build output options
        out_options = [
            ValueOption(
                id=v.id, 
                value=v.value, 
                label=v.label, 
                is_default=v.is_default
            )
            for v in available_values
        ]
        
        return final_value, out_options
    
    def _is_value_available(
        self,
        value: Value,
        rules_by_target_value: Dict[int, List[Rule]],
        running_context: Dict[int, Any],
        type_map: Dict[int, str]
    ) -> bool:
        """
        Determines if a specific Value is available based on AVAILABILITY rules.
        Logic: Available unless explicit rules exist, then at least one must pass (OR).
        """
        rules_for_value = [
            r for r in rules_by_target_value.get(value.id, [])
            if r.rule_type == RuleType.AVAILABILITY
        ]
        
        if not rules_for_value:
            return True  # No rules = available by default
        
        # OR logic: at least one rule must pass
        for rule in rules_for_value:
            if self._evaluate_rule(rule.conditions, running_context, type_map):
                return True  # Value available
        
        return False  # Value not available
    
    def _auto_select_value(self, available_values: List[Value]) -> Optional[Any]:
        """
        Auto-selects a value for required fields.
        Priority: single option > default value > None
        """
        if len(available_values) == 1:
            return available_values[0].value
        
        # Find first default value
        return next(
            (v.value for v in available_values if v.is_default), 
            None
        )
    
    def _evaluate_validation(
        self,
        field: Field,
        all_rules: List[Rule],
        final_value: Any,
        running_context: Dict[int, Any],
        type_map: Dict[int, str],
        is_required: bool
    ) -> Optional[str]:
        """
        Layer 5: Validates the final value.
        Logic: If a VALIDATION rule passes, return error message (negative pattern).
        """
        
        if final_value is not None:
            validation_rules = self._get_rules_by_type(
                field.id, RuleType.VALIDATION, all_rules
            )
            
            for rule in validation_rules:
                if self._evaluate_rule(rule.conditions, running_context, type_map):
                    return rule.error_message or "Validation error."
        
        # Required field check
        if is_required and final_value is None:
            return "Required field."
        
        return None
    

    # ============================================================
    # RULE EVALUATION ENGINE
    # ============================================================
    
    def _evaluate_rule(
        self, 
        conditions: Dict[str, Any], 
        context: Dict[int, Any], 
        type_map: Dict[int, str]
    ) -> bool:
        """
        Evaluates a single rule.
        Logic: All criteria are ANDed together.
        """
        criteria_list = conditions.get("criteria", [])
        
        if not criteria_list:
            return True  # Empty rule = always passes
        
        for criterion in criteria_list:
            if not self._check_criterion(criterion, context, type_map):
                return False  # One failed criterion invalidates the AND
        
        return True
    
    def _check_criterion(
        self, 
        criterion: Dict[str, Any], 
        context: Dict[int, Any], 
        type_map: Dict[int, str]
    ) -> bool:
        """
        Evaluates a single criterion within a rule.
        Handles type-specific comparisons (string, number, date).
        """
        target_field_id = criterion.get("field_id")
        operator = criterion.get("operator")
        expected_val = criterion.get("value")
        
        # Guard checks: ensure all required fields are present
        if target_field_id is None:
            return False
        
        if operator is None or not isinstance(operator, str):
            return False  # operator must be a non-empty string
        
        actual_val = context.get(int(target_field_id))
        
        if actual_val is None:
            return False  # Dependent field has no value
        
        # Resolve field type
        f_type_raw = type_map.get(target_field_id, FieldType.STRING.value)
        f_type_val = getattr(f_type_raw, "value", f_type_raw)
        f_type = str(f_type_val).lower().strip()
        
        try:
            if f_type == FieldType.DATE.value:
                return self._compare_dates(actual_val, operator, expected_val)
            elif f_type == FieldType.NUMBER.value:
                return self._compare_numbers(actual_val, operator, expected_val)
            else:
                return self._compare_strings(actual_val, operator, expected_val)
        
        except (ValueError, TypeError):
            # Fallback to string comparison
            return self._compare_strings(actual_val, operator, expected_val)
    

    # ============================================================
    # TYPE-SPECIFIC COMPARISONS
    # ============================================================
    
    def _compare_strings(
        self, 
        actual: Any, 
        operator: str, 
        expected: Any
    ) -> bool:
        """String comparison logic."""
        s_actual, s_expected = str(actual), str(expected)
        
        if operator == "EQUALS":
            return s_actual == s_expected
        elif operator == "NOT_EQUALS":
            return s_actual != s_expected
        elif operator == "GREATER_THAN":
            return s_actual > s_expected
        elif operator == "LESS_THAN":
            return s_actual < s_expected
        elif operator == "IN":
            if isinstance(expected, list):
                return s_actual in [str(x) for x in expected]
            return s_actual in s_expected
        
        return False
    
    def _compare_numbers(
        self, 
        actual: Any, 
        operator: str, 
        expected: Any
    ) -> bool:
        """Number comparison logic."""
        if expected is None:
            return False
        
        n_actual = float(actual)
        
        if operator == "IN":
            if isinstance(expected, list):
                target_numbers = []
                for x in expected:
                    try:
                        target_numbers.append(float(x))
                    except (ValueError, TypeError):
                        continue
                return n_actual in target_numbers
            else:
                return n_actual == float(expected)
        
        n_expected = float(expected)
        
        if operator == "GREATER_THAN":
            return n_actual > n_expected
        elif operator == "LESS_THAN":
            return n_actual < n_expected
        elif operator == "EQUALS":
            return n_actual == n_expected
        elif operator == "NOT_EQUALS":
            return n_actual != n_expected
        
        return False
    
    def _compare_dates(
        self, 
        actual: Any, 
        operator: str, 
        expected: Any
    ) -> bool:
        """Date comparison logic."""
        if expected is None:
            return False
        
        # Parse actual date
        d_actual = actual
        if not isinstance(d_actual, (date, datetime)):
            d_actual = date.fromisoformat(str(actual).strip())
        
        if operator == "IN":
            if isinstance(expected, list):
                target_dates = []
                for x in expected:
                    try:
                        if isinstance(x, (date, datetime)):
                            target_dates.append(x)
                        else:
                            target_dates.append(date.fromisoformat(str(x)))
                    except ValueError:
                        continue
                return d_actual in target_dates
            else:
                return d_actual == date.fromisoformat(str(expected))
        
        # Parse expected date
        d_expected = expected
        if not isinstance(d_expected, (date, datetime)):
            d_expected = date.fromisoformat(str(expected))
        
        if operator == "GREATER_THAN":
            return d_actual > d_expected
        elif operator == "LESS_THAN":
            return d_actual < d_expected
        elif operator == "EQUALS":
            return d_actual == d_expected
        elif operator == "NOT_EQUALS":
            return d_actual != d_expected
        
        return False
    

    # ============================================================
    # UTILITY
    # ============================================================
    
    def _check_completeness(self, output_fields: List[FieldOutputState]) -> bool:
        """Checks if all required visible fields have values and validation errors."""
        for field in output_fields:
            # Missing mandatory Value
            if field.is_required and not field.is_hidden and field.current_value is None:
                return False
            
            # Check validation errors
            if field.error_message is not None:
                return False
            
        return True