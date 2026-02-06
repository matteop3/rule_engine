import logging
from typing import List, Dict, Any, Optional, Tuple, Callable
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import SQLAlchemyError
from app.models.domain import Entity, Field, FieldType, Value, Rule, RuleType, EntityVersion, VersionStatus
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldOutputState, ValueOption
from datetime import date, datetime

logger = logging.getLogger(__name__)


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
        logger.info(
            f"Starting state calculation for entity_id={request.entity_id}, version_id={request.entity_version_id}"
        )

        # Resolve target version
        target_version = self._resolve_target_version(db, request)
        logger.debug(f"Resolved target version: {target_version.id}")
        
        # Load all data for the version (with optimized queries)
        fields_db, all_values, all_rules = self._load_version_data(db, target_version.id)
        logger.debug(
            f"Loaded version data: {len(fields_db)} fields, {len(all_values)} values, {len(all_rules)} rules"
        )

        # Build indexing structures
        type_map = self._build_type_map(fields_db)
        values_by_field = self._build_values_index(all_values)
        rules_by_target_value = self._build_rules_index(all_rules)
        user_input_map = self._normalize_user_input(request.current_state)
        
        # Execute waterfall
        running_context: Dict[int, Any] = {}
        output_fields: List[FieldOutputState] = []
        field_states: Dict[int, FieldOutputState] = {}

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
            field_states[field.id] = field_state
            running_context[field.id] = field_state.current_value

        # Check global completeness
        is_complete = self._check_completeness(output_fields)

        # Generate SKU
        generated_sku = self._generate_sku(
            version=target_version,
            fields=fields_db,
            field_states=field_states,
            values_by_field=values_by_field
        )

        logger.info(
            f"State calculation completed for entity_id={request.entity_id}: "
            f"{len(output_fields)} fields processed, is_complete={is_complete}, "
            f"generated_sku={generated_sku}"
        )

        return CalculationResponse(
            entity_id=request.entity_id,
            fields=output_fields,
            is_complete=is_complete,
            generated_sku=generated_sku
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
        try:
            # Check entity existence
            entity = db.query(Entity).filter(Entity.id == request.entity_id).first()
            if not entity:
                logger.warning(f"Entity {request.entity_id} not found")
                raise ValueError(f"Entity {request.entity_id} not found.")

            # Preview mode
            if request.entity_version_id is not None:
                logger.debug(
                    f"Preview mode: resolving explicit version {request.entity_version_id}"
                )
                target_version = db.query(EntityVersion).filter(
                    EntityVersion.id == request.entity_version_id
                ).first()

                if not target_version:
                    logger.warning(f"Version {request.entity_version_id} not found")
                    raise ValueError(f"Version {request.entity_version_id} not found.")

                if target_version.entity_id != request.entity_id:
                    logger.warning(
                        f"Version {request.entity_version_id} does not belong to entity {request.entity_id}"
                    )
                    raise ValueError(
                        f"Version {request.entity_version_id} does not belong to "
                        f"Entity {request.entity_id}."
                    )

                return target_version

            # Production mode
            logger.debug(
                f"Production mode: resolving PUBLISHED version for entity {request.entity_id}"
            )
            target_version = db.query(EntityVersion).filter(
                EntityVersion.entity_id == request.entity_id,
                EntityVersion.status == VersionStatus.PUBLISHED
            ).first()

            if not target_version:
                logger.warning(
                    f"Entity {request.entity_id} has no PUBLISHED version"
                )
                raise ValueError(
                    f"Entity {request.entity_id} has no PUBLISHED version ready for calculation."
                )

            return target_version

        except SQLAlchemyError as e:
            logger.error(
                f"Database error while resolving version for entity {request.entity_id}: {str(e)}"
            )
            raise
    
    def _load_version_data(
        self,
        db: Session,
        version_id: int
    ) -> Tuple[List[Field], List[Value], List[Rule]]:
        """
        Loads all Fields, Values, and Rules for a given version.

        Design note: Loads everything in memory per-request. This is intentional -
        the data volume per version is small (typically <1000 rules) and the
        simplicity outweighs caching complexity. If this becomes a bottleneck,
        consider Redis caching with version-based invalidation.

        Implementation: Batch loads with IN queries to avoid N+1 problem,
        then builds in-memory indexes for O(1) lookups during rule evaluation.
        """
        try:
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

        except SQLAlchemyError as e:
            logger.error(
                f"Database error while loading version data for version {version_id}: {str(e)}"
            )
            raise
    
    def _build_type_map(self, fields: List[Field]) -> Dict[int, str]:
        """Creates a mapping of field_id -> data_type string."""
        return {f.id: f.data_type for f in fields}

    def _build_index(
        self,
        items: List[Any],
        key_extractor: Callable[[Any], Optional[int]]
    ) -> Dict[int, List[Any]]:
        """
        Generic index builder - DRY pattern for grouping items by key.

        Args:
            items: List of objects to index
            key_extractor: Function to extract the grouping key from each item

        Returns:
            Dictionary mapping key -> list of items with that key
        """
        index: Dict[int, List[Any]] = {}
        for item in items:
            key = key_extractor(item)
            if key is not None:
                if key not in index:
                    index[key] = []
                index[key].append(item)
        return index

    def _build_values_index(self, values: List[Value]) -> Dict[int, List[Value]]:
        """Creates a mapping of field_id -> list of Value objects."""
        return self._build_index(values, lambda v: v.field_id)

    def _build_rules_index(self, rules: List[Rule]) -> Dict[int, List[Rule]]:
        """
        Creates a mapping of target_value_id -> list of Rule objects.
        Only indexes rules with a target_value_id (availability rules).
        """
        return self._build_index(rules, lambda r: r.target_value_id)
    
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
        logger.debug(f"Processing field {field.name} (id={field.id})")

        # Layer 1: Visibility
        is_visible = self._evaluate_visibility(field, all_rules, running_context, type_map)

        if not is_visible:
            logger.debug(f"Field {field.name} is hidden")
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

        if validation_error:
            logger.debug(
                f"Field {field.name} has validation error: {validation_error}"
            )

        logger.debug(
            f"Field {field.name} processed: value={final_value}, required={is_required}, readonly={is_readonly}"
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

    def _any_rule_passes(
        self,
        rules: List[Rule],
        running_context: Dict[int, Any],
        type_map: Dict[int, str]
    ) -> bool:
        """
        DRY helper: checks if at least one rule passes (OR logic).

        Returns True if any rule's conditions are satisfied.
        """
        for rule in rules:
            if self._evaluate_rule(rule.conditions, running_context, type_map):
                return True
        return False

    def _evaluate_boolean_layer(
        self,
        field: Field,
        all_rules: List[Rule],
        running_context: Dict[int, Any],
        type_map: Dict[int, str],
        rule_type: RuleType,
        default_when_no_rules: bool,
        value_when_rule_passes: bool
    ) -> bool:
        """
        Generic boolean layer evaluation - DRY pattern for visibility/editability/mandatory.

        Args:
            field: The field being evaluated
            all_rules: All rules for the version
            running_context: Current field values
            type_map: Field type mapping
            rule_type: The type of rules to evaluate
            default_when_no_rules: Value to return when no rules exist
            value_when_rule_passes: Value to return when a rule passes

        Returns:
            Boolean result of the layer evaluation
        """
        rules = self._get_rules_by_type(field.id, rule_type, all_rules)

        if not rules:
            return default_when_no_rules

        if self._any_rule_passes(rules, running_context, type_map):
            return value_when_rule_passes

        return not value_when_rule_passes

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
        return self._evaluate_boolean_layer(
            field=field,
            all_rules=all_rules,
            running_context=running_context,
            type_map=type_map,
            rule_type=RuleType.VISIBILITY,
            default_when_no_rules=not field.is_hidden,
            value_when_rule_passes=True  # Visible when rule passes
        )

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
        return self._evaluate_boolean_layer(
            field=field,
            all_rules=all_rules,
            running_context=running_context,
            type_map=type_map,
            rule_type=RuleType.EDITABILITY,
            default_when_no_rules=field.is_readonly,
            value_when_rule_passes=False  # Editable (not readonly) when rule passes
        )

    def _evaluate_mandatory(
        self,
        field: Field,
        all_rules: List[Rule],
        running_context: Dict[int, Any],
        type_map: Dict[int, str]
    ) -> bool:
        """
        Layer 3: Determines if field is required.
        Logic: If no MANDATORY rules exist, uses field.is_required as default.
        If MANDATORY rules exist, they fully govern the outcome:
        rule passes = required, no rule passes = not required.
        """
        return self._evaluate_boolean_layer(
            field=field,
            all_rules=all_rules,
            running_context=running_context,
            type_map=type_map,
            rule_type=RuleType.MANDATORY,
            default_when_no_rules=field.is_required,
            value_when_rule_passes=True
        )
    
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

        except (ValueError, TypeError) as e:
            logger.debug(
                f"Type conversion error for field {target_field_id}, falling back to string comparison: {str(e)}"
            )
            return self._compare_strings(actual_val, operator, expected_val)
    

    # ============================================================
    # TYPE-SPECIFIC COMPARISONS (DRY Pattern)
    # ============================================================

    # Operator mapping - DRY pattern for comparison operations
    _COMPARISON_OPERATORS: Dict[str, Callable[[Any, Any], bool]] = {
        "EQUALS": lambda a, e: a == e,
        "NOT_EQUALS": lambda a, e: a != e,
        "GREATER_THAN": lambda a, e: a > e,
        "GREATER_THAN_OR_EQUAL": lambda a, e: a >= e,
        "LESS_THAN": lambda a, e: a < e,
        "LESS_THAN_OR_EQUAL": lambda a, e: a <= e,
    }

    def _apply_operator(
        self,
        actual: Any,
        operator: str,
        expected: Any,
        convert_for_in: Callable[[Any], Any]
    ) -> bool:
        """
        Generic operator application - DRY pattern for all comparisons.

        Args:
            actual: The actual value (already converted to target type)
            operator: The comparison operator
            expected: The expected value(s)
            convert_for_in: Function to convert items for IN operator
        """
        # Handle IN operator specially
        if operator == "IN":
            if isinstance(expected, list):
                converted_list = []
                for x in expected:
                    try:
                        converted_list.append(convert_for_in(x))
                    except (ValueError, TypeError):
                        continue
                return actual in converted_list
            return actual == convert_for_in(expected)

        # Standard operators
        op_func = self._COMPARISON_OPERATORS.get(operator)
        if op_func:
            return op_func(actual, expected)

        return False

    def _compare_strings(
        self,
        actual: Any,
        operator: str,
        expected: Any
    ) -> bool:
        """String comparison logic."""
        s_actual = str(actual)

        # Special case: IN for strings can also mean substring check
        if operator == "IN" and not isinstance(expected, list):
            return s_actual in str(expected)

        s_expected = str(expected) if not isinstance(expected, list) else expected
        return self._apply_operator(s_actual, operator, s_expected, str)

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
        n_expected = float(expected) if not isinstance(expected, list) else expected
        return self._apply_operator(n_actual, operator, n_expected, float)

    def _compare_dates(
        self,
        actual: Any,
        operator: str,
        expected: Any
    ) -> bool:
        """Date comparison logic."""
        if expected is None:
            return False

        def parse_date(val: Any) -> date:
            """Helper to parse date values."""
            if isinstance(val, (date, datetime)):
                return val if isinstance(val, date) else val.date()
            return date.fromisoformat(str(val).strip())

        d_actual = parse_date(actual)
        d_expected = parse_date(expected) if not isinstance(expected, list) else expected
        return self._apply_operator(d_actual, operator, d_expected, parse_date)
    

    # ============================================================
    # SKU GENERATION
    # ============================================================

    # Maximum length for generated SKU (common ERP/E-commerce limit)
    _MAX_SKU_LENGTH = 100

    def _generate_sku(
        self,
        version: EntityVersion,
        fields: List[Field],
        field_states: Dict[int, FieldOutputState],
        values_by_field: Dict[int, List[Value]]
    ) -> Optional[str]:
        """
        Generates a Smart SKU by concatenating base + modifiers from selected values.

        Algorithm:
        1. Check if sku_base exists (otherwise return None)
        2. Initialize: sku_parts = [sku_base]
        3. Iterate fields (ordered by step, sequence):
           - If hidden -> skip
           - If no value selected -> skip
           - If free-value field -> skip (no modifier possible)
           - Lookup Value object, if has sku_modifier -> append
        4. Join with delimiter and enforce max length

        Args:
            version: The EntityVersion with sku_base and sku_delimiter
            fields: Ordered list of Fields
            field_states: Map of field_id -> FieldOutputState
            values_by_field: Map of field_id -> list of Values

        Returns:
            Generated SKU string or None if sku_base is not set
        """
        if not version.sku_base:
            return None

        sku_parts = [version.sku_base]
        delimiter = version.sku_delimiter or "-"

        for field in fields:
            state = field_states.get(field.id)
            if not state:
                continue

            # Skip hidden fields
            if state.is_hidden:
                continue

            # Skip fields without a value
            if state.current_value is None:
                continue

            # Handle free-value fields: append modifier only if configured and field has a value
            if field.is_free_value:
                if field.sku_modifier_when_filled and state.current_value is not None:
                    sku_parts.append(field.sku_modifier_when_filled)
                continue

            # Find the Value object for the selected value
            field_values = values_by_field.get(field.id, [])
            for value in field_values:
                if value.value == state.current_value and value.sku_modifier:
                    sku_parts.append(value.sku_modifier)
                    break

        generated_sku = delimiter.join(sku_parts)

        # Enforce max length
        if len(generated_sku) > self._MAX_SKU_LENGTH:
            logger.warning(
                f"Generated SKU exceeds max length ({len(generated_sku)} > {self._MAX_SKU_LENGTH}), truncating"
            )
            generated_sku = generated_sku[:self._MAX_SKU_LENGTH]

        return generated_sku

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