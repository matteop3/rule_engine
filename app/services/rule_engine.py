import logging
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.cache import CachedBOMItem, CachedBOMItemRule, CachedField, CachedRule, CachedValue, TTLCache, VersionData
from app.core.config import settings
from app.models.domain import (
    BOMItem,
    BOMItemRule,
    CatalogItem,
    ConfigurationCustomItem,
    Entity,
    EntityVersion,
    Field,
    FieldType,
    PriceList,
    PriceListItem,
    Rule,
    RuleType,
    Value,
    VersionStatus,
)
from app.schemas.engine import (
    BOMFlatLineItem,
    BOMLineItem,
    BOMOutput,
    CalculationRequest,
    CalculationResponse,
    FieldOutputState,
    ValueOption,
)

logger = logging.getLogger(__name__)


class RuleEngineService:
    """
    CPQ Rule Engine: evaluates field states based on rules and user input.

    Note: This service does NOT handle database commits.
    """

    def __init__(self):
        self._cache: TTLCache[VersionData] = TTLCache(
            ttl_seconds=settings.CACHE_TTL_SECONDS,
            max_size=settings.CACHE_MAX_SIZE,
        )

    def calculate_state(self, db: Session, request: CalculationRequest) -> CalculationResponse:
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

        # Load all data for the version (with optimized queries + caching for PUBLISHED)
        fields_db, all_values, all_rules, all_bom_items, all_bom_item_rules = self._load_version_data(
            db, target_version.id, version_status=target_version.status
        )
        logger.debug(f"Loaded version data: {len(fields_db)} fields, {len(all_values)} values, {len(all_rules)} rules")

        # Build indexing structures
        type_map = self._build_type_map(fields_db)
        values_by_field = self._build_values_index(all_values)
        rules_by_target_value = self._build_rules_index(all_rules)
        user_input_map = self._normalize_user_input(request.current_state)

        # Execute waterfall
        running_context: dict[int, Any] = {}
        output_fields: list[FieldOutputState] = []
        field_states: dict[int, FieldOutputState] = {}

        for field in fields_db:
            field_state = self._process_field(
                field=field,
                all_rules=all_rules,
                values_by_field=values_by_field,
                rules_by_target_value=rules_by_target_value,
                user_input_map=user_input_map,
                running_context=running_context,
                type_map=type_map,
            )

            output_fields.append(field_state)
            field_states[field.id] = field_state
            running_context[field.id] = field_state.current_value

        # Check global completeness
        is_complete = self._check_completeness(output_fields)

        # Generate SKU
        generated_sku = self._generate_sku(
            version=target_version, fields=fields_db, field_states=field_states, values_by_field=values_by_field
        )

        # Resolve prices from price list
        price_map: dict[str, Decimal] | None = None
        price_list_name: str | None = None
        price_date: date | None = None
        known_parts: set[str] = set()
        if request.price_list_id is not None:
            price_date = request.price_date if request.price_date is not None else date.today()
            price_list = db.query(PriceList).filter(PriceList.id == request.price_list_id).first()
            if not price_list:
                raise ValueError(f"Price list {request.price_list_id} not found.")
            if not (price_list.valid_from <= price_date <= price_list.valid_to):
                raise ValueError(
                    f"Price list '{price_list.name}' is not valid at date {price_date} "
                    f"(valid {price_list.valid_from}..{price_list.valid_to})."
                )
            price_list_name = price_list.name
            # Collect COMMERCIAL part numbers for price resolution
            commercial_parts = {item.part_number for item in all_bom_items if item.bom_type == "COMMERCIAL"}
            if commercial_parts:
                price_map, known_parts = self._resolve_prices(db, request.price_list_id, price_date, commercial_parts)
            else:
                price_map = {}

        # Load catalog metadata for the part numbers referenced by this version's BOM
        catalog_map = self._load_catalog_map(db, all_bom_items)

        # Evaluate BOM
        bom_output = self._evaluate_bom(
            running_context=running_context,
            bom_items=all_bom_items,
            bom_item_rules=all_bom_item_rules,
            type_map=type_map,
            field_states=field_states,
            price_map=price_map,
            price_list_name=price_list_name,
            price_date=price_date,
            known_parts=known_parts,
            catalog_map=catalog_map,
        )

        # Append custom items (configuration-scoped commercial lines). Only
        # applies when calculating against a persisted Configuration; the
        # stateless /engine/calculate endpoint passes configuration_id=None
        # and never emits custom lines.
        if request.configuration_id is not None:
            bom_output = self._append_custom_items(db, request.configuration_id, bom_output)

        logger.info(
            f"State calculation completed for entity_id={request.entity_id}: "
            f"{len(output_fields)} fields processed, is_complete={is_complete}, "
            f"generated_sku={generated_sku}"
        )

        return CalculationResponse(
            entity_id=request.entity_id,
            fields=output_fields,
            is_complete=is_complete,
            generated_sku=generated_sku,
            bom=bom_output,
        )

    # ============================================================
    # DATA LOADING & INDEXING
    # ============================================================

    def _resolve_target_version(self, db: Session, request: CalculationRequest) -> EntityVersion:
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
                logger.debug(f"Preview mode: resolving explicit version {request.entity_version_id}")
                target_version = db.query(EntityVersion).filter(EntityVersion.id == request.entity_version_id).first()

                if not target_version:
                    logger.warning(f"Version {request.entity_version_id} not found")
                    raise ValueError(f"Version {request.entity_version_id} not found.")

                if target_version.entity_id != request.entity_id:
                    logger.warning(f"Version {request.entity_version_id} does not belong to entity {request.entity_id}")
                    raise ValueError(
                        f"Version {request.entity_version_id} does not belong to Entity {request.entity_id}."
                    )

                return target_version

            # Production mode
            logger.debug(f"Production mode: resolving PUBLISHED version for entity {request.entity_id}")
            target_version = (
                db.query(EntityVersion)
                .filter(EntityVersion.entity_id == request.entity_id, EntityVersion.status == VersionStatus.PUBLISHED)
                .first()
            )

            if not target_version:
                logger.warning(f"Entity {request.entity_id} has no PUBLISHED version")
                raise ValueError(f"Entity {request.entity_id} has no PUBLISHED version ready for calculation.")

            return target_version

        except SQLAlchemyError as e:
            logger.error(f"Database error while resolving version for entity {request.entity_id}: {str(e)}")
            raise

    def _load_version_data(
        self, db: Session, version_id: int, version_status: str
    ) -> tuple[list[CachedField], list[CachedValue], list[CachedRule], list[CachedBOMItem], list[CachedBOMItemRule]]:
        """
        Loads all Fields, Values, Rules, BOM Items, and BOM Item Rules for a given version.

        PUBLISHED versions are cached as frozen dataclasses (session-independent).
        DRAFT versions always hit the database (mutable data).

        Implementation: Batch loads with IN queries to avoid N+1 problem,
        then builds in-memory indexes for O(1) lookups during rule evaluation.
        """
        cache_key = str(version_id)

        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for version {version_id}")
            return cached.fields, cached.values, cached.rules, cached.bom_items, cached.bom_item_rules

        try:
            # Load fields ordered by execution sequence
            fields_db = (
                db.query(Field).filter(Field.entity_version_id == version_id).order_by(Field.step, Field.sequence).all()
            )

            field_ids = [f.id for f in fields_db]

            # Batch load all values
            all_values_db = db.query(Value).filter(Value.field_id.in_(field_ids)).all() if field_ids else []

            # Batch load all rules
            all_rules_db = db.query(Rule).filter(Rule.entity_version_id == version_id).all()

            # Batch load all BOM items
            all_bom_items_db = (
                db.query(BOMItem).filter(BOMItem.entity_version_id == version_id).order_by(BOMItem.sequence).all()
            )

            # Batch load all BOM item rules
            all_bom_item_rules_db = db.query(BOMItemRule).filter(BOMItemRule.entity_version_id == version_id).all()

            # Convert ORM instances to frozen dataclasses
            fields = [
                CachedField(
                    id=f.id,
                    entity_version_id=f.entity_version_id,
                    name=f.name,
                    label=f.label,
                    data_type=f.data_type,
                    is_required=f.is_required,
                    is_readonly=f.is_readonly,
                    is_hidden=f.is_hidden,
                    is_free_value=f.is_free_value,
                    default_value=f.default_value,
                    sku_modifier_when_filled=f.sku_modifier_when_filled,
                    step=f.step,
                    sequence=f.sequence,
                )
                for f in fields_db
            ]
            values = [
                CachedValue(
                    id=v.id,
                    field_id=v.field_id,
                    value=v.value,
                    label=v.label,
                    is_default=v.is_default,
                    sku_modifier=v.sku_modifier,
                )
                for v in all_values_db
            ]
            rules = [
                CachedRule(
                    id=r.id,
                    entity_version_id=r.entity_version_id,
                    target_field_id=r.target_field_id,
                    target_value_id=r.target_value_id,
                    rule_type=r.rule_type,
                    conditions=r.conditions,
                    error_message=r.error_message,
                    set_value=r.set_value,
                )
                for r in all_rules_db
            ]
            bom_items = [
                CachedBOMItem(
                    id=b.id,
                    entity_version_id=b.entity_version_id,
                    parent_bom_item_id=b.parent_bom_item_id,
                    bom_type=b.bom_type,
                    part_number=b.part_number,
                    quantity=b.quantity,
                    quantity_from_field_id=b.quantity_from_field_id,
                    sequence=b.sequence,
                )
                for b in all_bom_items_db
            ]
            bom_item_rules = [
                CachedBOMItemRule(
                    id=br.id,
                    bom_item_id=br.bom_item_id,
                    entity_version_id=br.entity_version_id,
                    conditions=br.conditions,
                    description=br.description,
                )
                for br in all_bom_item_rules_db
            ]

            version_data = VersionData(
                fields=fields,
                values=values,
                rules=rules,
                bom_items=bom_items,
                bom_item_rules=bom_item_rules,
            )

            # Only cache PUBLISHED versions (immutable)
            if version_status == VersionStatus.PUBLISHED.value:
                self._cache.set(cache_key, version_data)
                logger.debug(f"Cached version {version_id} (PUBLISHED)")

            return (
                version_data.fields,
                version_data.values,
                version_data.rules,
                version_data.bom_items,
                version_data.bom_item_rules,
            )

        except SQLAlchemyError as e:
            logger.error(f"Database error while loading version data for version {version_id}: {str(e)}")
            raise

    def _build_type_map(self, fields: list[CachedField]) -> dict[int, str]:
        """Creates a mapping of field_id -> data_type string."""
        return {f.id: f.data_type for f in fields}

    def _build_index(self, items: list[Any], key_extractor: Callable[[Any], int | None]) -> dict[int, list[Any]]:
        """
        Generic index builder - DRY pattern for grouping items by key.

        Args:
            items: List of objects to index
            key_extractor: Function to extract the grouping key from each item

        Returns:
            Dictionary mapping key -> list of items with that key
        """
        index: dict[int, list[Any]] = {}
        for item in items:
            key = key_extractor(item)
            if key is not None:
                if key not in index:
                    index[key] = []
                index[key].append(item)
        return index

    def _build_values_index(self, values: list[CachedValue]) -> dict[int, list[CachedValue]]:
        """Creates a mapping of field_id -> list of Value objects."""
        return self._build_index(values, lambda v: v.field_id)

    def _build_rules_index(self, rules: list[CachedRule]) -> dict[int, list[CachedRule]]:
        """
        Creates a mapping of target_value_id -> list of Rule objects.
        Only indexes rules with a target_value_id (availability rules).
        """
        return self._build_index(rules, lambda r: r.target_value_id)

    def _normalize_user_input(self, current_state: list[Any]) -> dict[int, Any]:
        """
        Normalizes user input by stripping strings and converting empty to None.
        """
        user_input_map: dict[int, Any] = {}
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
        field: CachedField,
        all_rules: list[CachedRule],
        values_by_field: dict[int, list[CachedValue]],
        rules_by_target_value: dict[int, list[CachedRule]],
        user_input_map: dict[int, Any],
        running_context: dict[int, Any],
        type_map: dict[int, str],
    ) -> FieldOutputState:
        """
        Processes a single field through the waterfall logic:
        1. Visibility    → if hidden, early return
        2. Calculation   → if calculated, set value + readonly, skip to Mandatory
        3. Editability   → skipped if calculated
        4. Availability  → skipped if calculated
        5. Mandatory
        6. Validation
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
                error_message=None,
            )

        # Layer 2: Calculation
        calculated_value = self._evaluate_calculation(field, all_rules, running_context, type_map)

        if calculated_value is not None:
            logger.debug(f"Field {field.name} is calculated: value={calculated_value}")

            # Build available_options: single entry for non-free, empty for free
            calc_options: list[ValueOption] = []
            if not field.is_free_value:
                possible_values = values_by_field.get(field.id, [])
                for v in possible_values:
                    if v.value == calculated_value:
                        calc_options = [ValueOption(id=v.id, value=v.value, label=v.label, is_default=v.is_default)]
                        break
                if not calc_options:
                    logger.warning(
                        f"Calculated value '{calculated_value}' for field '{field.name}' "
                        f"does not match any defined Value"
                    )
                    calculated_value = None

            # Update context with calculated value (None if invalidated above)
            running_context[field.id] = calculated_value

            # Skip EDITABILITY and AVAILABILITY, jump to MANDATORY
            is_required = self._evaluate_mandatory(field, all_rules, running_context, type_map)

            # VALIDATION as safety net
            validation_error = self._evaluate_validation(
                field=field,
                all_rules=all_rules,
                final_value=calculated_value,
                running_context=running_context,
                type_map=type_map,
                is_required=is_required,
            )

            if validation_error:
                logger.debug(f"Field {field.name} (calculated) has validation error: {validation_error}")

            return FieldOutputState(
                field_id=field.id,
                field_name=field.name,
                field_label=field.label,
                current_value=calculated_value,
                available_options=calc_options,
                is_required=is_required,
                is_readonly=True,
                is_hidden=False,
                error_message=validation_error,
            )

        # Layer 3: Editability
        is_readonly = self._evaluate_editability(field, all_rules, running_context, type_map)

        # Layer 4: Mandatory
        is_required = self._evaluate_mandatory(field, all_rules, running_context, type_map)

        # Layer 5: Availability & Value selection
        final_value, available_options = self._evaluate_availability(
            field=field,
            values_by_field=values_by_field,
            rules_by_target_value=rules_by_target_value,
            user_input_map=user_input_map,
            running_context=running_context,
            type_map=type_map,
            is_required=is_required,
        )

        # Update context before validation
        running_context[field.id] = final_value

        # Layer 6: Validation
        validation_error = self._evaluate_validation(
            field=field,
            all_rules=all_rules,
            final_value=final_value,
            running_context=running_context,
            type_map=type_map,
            is_required=is_required,
        )

        if validation_error:
            logger.debug(f"Field {field.name} has validation error: {validation_error}")

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
            error_message=validation_error,
        )

    # ============================================================
    # RULE EVALUATION LAYERS (DRY Pattern)
    # ============================================================

    def _get_rules_by_type(self, field_id: int, rule_type: RuleType, all_rules: list[CachedRule]) -> list[CachedRule]:
        """
        Helper to filter rules by field and type.
        Eliminates repetitive list comprehensions.
        """
        return [r for r in all_rules if r.target_field_id == field_id and r.rule_type == rule_type]

    def _any_rule_passes(
        self, rules: list[CachedRule], running_context: dict[int, Any], type_map: dict[int, str]
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
        field: CachedField,
        all_rules: list[CachedRule],
        running_context: dict[int, Any],
        type_map: dict[int, str],
        rule_type: RuleType,
        default_when_no_rules: bool,
        value_when_rule_passes: bool,
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
        self, field: CachedField, all_rules: list[CachedRule], running_context: dict[int, Any], type_map: dict[int, str]
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
            value_when_rule_passes=True,  # Visible when rule passes
        )

    def _evaluate_calculation(
        self, field: CachedField, all_rules: list[CachedRule], running_context: dict[int, Any], type_map: dict[int, str]
    ) -> str | None:
        """
        Layer 2: Determines if a field's value is system-determined.
        Returns the set_value if a CALCULATION rule passes, else None.
        First passing rule wins.
        """
        calc_rules = self._get_rules_by_type(field.id, RuleType.CALCULATION, all_rules)
        for rule in calc_rules:
            if self._evaluate_rule(rule.conditions, running_context, type_map):
                return rule.set_value
        return None

    def _evaluate_editability(
        self, field: CachedField, all_rules: list[CachedRule], running_context: dict[int, Any], type_map: dict[int, str]
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
            value_when_rule_passes=False,  # Editable (not readonly) when rule passes
        )

    def _evaluate_mandatory(
        self, field: CachedField, all_rules: list[CachedRule], running_context: dict[int, Any], type_map: dict[int, str]
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
            value_when_rule_passes=True,
        )

    def _evaluate_availability(
        self,
        field: CachedField,
        values_by_field: dict[int, list[CachedValue]],
        rules_by_target_value: dict[int, list[CachedRule]],
        user_input_map: dict[int, Any],
        running_context: dict[int, Any],
        type_map: dict[int, str],
        is_required: bool,
    ) -> tuple[Any, list[ValueOption]]:
        """
        Layer 4: Determines available values and selects final value.

        Returns Tuple of (final_value, available_options)
        """

        if field.is_free_value:
            return self._handle_free_value_field(field, user_input_map, is_required)

        return self._handle_restricted_value_field(
            field=field,
            values_by_field=values_by_field,
            rules_by_target_value=rules_by_target_value,
            user_input_map=user_input_map,
            running_context=running_context,
            type_map=type_map,
            is_required=is_required,
        )

    def _handle_free_value_field(
        self, field: CachedField, user_input_map: dict[int, Any], is_required: bool
    ) -> tuple[Any, list[ValueOption]]:
        """Handles fields with free-text input."""
        raw_input = user_input_map.get(field.id)
        final_value = raw_input

        # Apply default if required and empty
        if is_required and final_value is None and field.default_value is not None:
            final_value = field.default_value

        return final_value, []

    def _handle_restricted_value_field(
        self,
        field: CachedField,
        values_by_field: dict[int, list[CachedValue]],
        rules_by_target_value: dict[int, list[CachedRule]],
        user_input_map: dict[int, Any],
        running_context: dict[int, Any],
        type_map: dict[int, str],
        is_required: bool,
    ) -> tuple[Any, list[ValueOption]]:
        """Handles fields with predefined value options."""

        possible_values = values_by_field.get(field.id, [])
        available_values: list[CachedValue] = []

        # Filter available values based on rules
        for val_obj in possible_values:
            if self._is_value_available(val_obj, rules_by_target_value, running_context, type_map):
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
            ValueOption(id=v.id, value=v.value, label=v.label, is_default=v.is_default) for v in available_values
        ]

        return final_value, out_options

    def _is_value_available(
        self,
        value: CachedValue,
        rules_by_target_value: dict[int, list[CachedRule]],
        running_context: dict[int, Any],
        type_map: dict[int, str],
    ) -> bool:
        """
        Determines if a specific Value is available based on AVAILABILITY rules.
        Logic: Available unless explicit rules exist, then at least one must pass (OR).
        """
        rules_for_value = [r for r in rules_by_target_value.get(value.id, []) if r.rule_type == RuleType.AVAILABILITY]

        if not rules_for_value:
            return True  # No rules = available by default

        # OR logic: at least one rule must pass
        for rule in rules_for_value:
            if self._evaluate_rule(rule.conditions, running_context, type_map):
                return True  # Value available

        return False  # Value not available

    def _auto_select_value(self, available_values: list[CachedValue]) -> Any | None:
        """
        Auto-selects a value for required fields.
        Priority: single option > default value > None
        """
        if len(available_values) == 1:
            return available_values[0].value

        # Find first default value
        return next((v.value for v in available_values if v.is_default), None)

    def _evaluate_validation(
        self,
        field: CachedField,
        all_rules: list[CachedRule],
        final_value: Any,
        running_context: dict[int, Any],
        type_map: dict[int, str],
        is_required: bool,
    ) -> str | None:
        """
        Layer 5: Validates the final value.
        Logic: If a VALIDATION rule passes, return error message (negative pattern).
        """

        if final_value is not None:
            validation_rules = self._get_rules_by_type(field.id, RuleType.VALIDATION, all_rules)

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

    def _evaluate_rule(self, conditions: dict[str, Any], context: dict[int, Any], type_map: dict[int, str]) -> bool:
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

    def _check_criterion(self, criterion: dict[str, Any], context: dict[int, Any], type_map: dict[int, str]) -> bool:
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
    _COMPARISON_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
        "EQUALS": lambda a, e: a == e,
        "NOT_EQUALS": lambda a, e: a != e,
        "GREATER_THAN": lambda a, e: a > e,
        "GREATER_THAN_OR_EQUAL": lambda a, e: a >= e,
        "LESS_THAN": lambda a, e: a < e,
        "LESS_THAN_OR_EQUAL": lambda a, e: a <= e,
    }

    def _apply_operator(self, actual: Any, operator: str, expected: Any, convert_for_in: Callable[[Any], Any]) -> bool:
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
            return bool(actual == convert_for_in(expected))

        # Standard operators
        op_func = self._COMPARISON_OPERATORS.get(operator)
        if op_func:
            return op_func(actual, expected)

        return False

    def _compare_strings(self, actual: Any, operator: str, expected: Any) -> bool:
        """String comparison logic."""
        s_actual = str(actual)

        # Special case: IN for strings can also mean substring check
        if operator == "IN" and not isinstance(expected, list):
            return s_actual in str(expected)

        s_expected = str(expected) if not isinstance(expected, list) else expected
        return self._apply_operator(s_actual, operator, s_expected, str)

    def _compare_numbers(self, actual: Any, operator: str, expected: Any) -> bool:
        """Number comparison logic."""
        if expected is None:
            return False

        n_actual = float(actual)
        n_expected = float(expected) if not isinstance(expected, list) else expected
        return self._apply_operator(n_actual, operator, n_expected, float)

    def _compare_dates(self, actual: Any, operator: str, expected: Any) -> bool:
        """Date comparison logic."""
        if expected is None:
            return False

        def parse_date(val: Any) -> date:
            """Helper to parse date values."""
            if isinstance(val, date | datetime):
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
        fields: list[CachedField],
        field_states: dict[int, FieldOutputState],
        values_by_field: dict[int, list[CachedValue]],
    ) -> str | None:
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
            generated_sku = generated_sku[: self._MAX_SKU_LENGTH]

        return generated_sku

    # ============================================================
    # BOM EVALUATION
    # ============================================================

    def _resolve_prices(
        self,
        db: Session,
        price_list_id: int,
        price_date: date,
        part_numbers: set[str],
    ) -> tuple[dict[str, Decimal], set[str]]:
        """
        Resolves prices from the price list for a set of part numbers at a given date.

        Queries PriceListItem directly (no cache — decision #10).

        Returns:
            Tuple of (price_map, known_parts) where:
            - price_map: dict mapping part_number → unit_price for items valid at price_date
            - known_parts: set of part_numbers that exist in the price list (any date)
        """
        # Get prices valid at the given date
        valid_items = (
            db.query(PriceListItem)
            .filter(
                PriceListItem.price_list_id == price_list_id,
                PriceListItem.part_number.in_(part_numbers),
                PriceListItem.valid_from <= price_date,
                PriceListItem.valid_to >= price_date,
            )
            .all()
        )
        price_map = {item.part_number: item.unit_price for item in valid_items}

        # Get all part numbers that exist in this price list (for differentiated warnings)
        missing_parts = part_numbers - price_map.keys()
        known_parts: set[str] = set()
        if missing_parts:
            known_rows = (
                db.query(PriceListItem.part_number)
                .filter(
                    PriceListItem.price_list_id == price_list_id,
                    PriceListItem.part_number.in_(missing_parts),
                )
                .distinct()
                .all()
            )
            known_parts = {row[0] for row in known_rows}

        return price_map, known_parts

    def _append_custom_items(
        self,
        db: Session,
        configuration_id: str,
        bom_output: BOMOutput | None,
    ) -> BOMOutput | None:
        """
        Append configuration-scoped custom items to the commercial BOM output.

        Custom items are emitted as commercial `BOMLineItem` rows with
        ``is_custom=True``, ``part_number=custom_key``, and line totals from the
        row itself. They never produce warnings and never influence completeness;
        they contribute only to the commercial total.
        """
        custom_rows = (
            db.query(ConfigurationCustomItem)
            .filter(ConfigurationCustomItem.configuration_id == configuration_id)
            .order_by(ConfigurationCustomItem.sequence, ConfigurationCustomItem.id)
            .all()
        )
        if not custom_rows:
            return bom_output

        if bom_output is None:
            bom_output = BOMOutput(technical=[], commercial=[], commercial_total=None, warnings=[])

        custom_lines: list[BOMLineItem] = []
        custom_total = Decimal("0")
        for row in custom_rows:
            quantity = Decimal(row.quantity)
            unit_price = Decimal(row.unit_price)
            line_total = quantity * unit_price
            custom_total += line_total
            custom_lines.append(
                BOMLineItem(
                    bom_item_id=None,
                    bom_type="COMMERCIAL",
                    part_number=row.custom_key,
                    description=row.description,
                    category=None,
                    quantity=quantity,
                    unit_of_measure=row.unit_of_measure,
                    unit_price=unit_price,
                    line_total=line_total,
                    is_custom=True,
                    children=[],
                )
            )

        bom_output.commercial.extend(custom_lines)
        existing_total = bom_output.commercial_total
        bom_output.commercial_total = custom_total if existing_total is None else existing_total + custom_total
        return bom_output

    def _load_catalog_map(self, db: Session, bom_items: list[CachedBOMItem]) -> dict[str, CatalogItem]:
        """
        Loads CatalogItem rows for the part numbers referenced by the given BOM items.

        Returned as an in-memory map keyed by `part_number`. Performed per
        calculation (not cached): the catalog is mutable and the FK on
        `bom_items.part_number` guarantees every entry resolves.
        """
        if not bom_items:
            return {}
        part_numbers = {item.part_number for item in bom_items}
        rows = db.query(CatalogItem).filter(CatalogItem.part_number.in_(part_numbers)).all()
        return {row.part_number: row for row in rows}

    def _evaluate_bom(
        self,
        running_context: dict[int, Any],
        bom_items: list[CachedBOMItem],
        bom_item_rules: list[CachedBOMItemRule],
        type_map: dict[int, str],
        field_states: dict[int, FieldOutputState],
        price_map: dict[str, Decimal] | None = None,
        price_list_name: str | None = None,
        price_date: date | None = None,
        known_parts: set[str] | None = None,
        catalog_map: dict[str, CatalogItem] | None = None,
    ) -> BOMOutput | None:
        """
        Evaluates BOM items after the waterfall to produce technical and commercial line items.

        Algorithm:
        1. Build rules-by-bom-item index
        2. Evaluate inclusion for each BOM item (OR logic across rules)
        3. Resolve quantities (static or from field)
        4. Prune tree (excluded parent → excluded subtree)
        5. Aggregate by (part_number, parent_bom_item_id, bom_type) — sum quantities
        6. Build output: nested tree for TECHNICAL, flat list for COMMERCIAL
        """
        if not bom_items:
            return None

        # 1. Build index: bom_item_id → list of rules
        rules_by_bom_item: dict[int, list[CachedBOMItemRule]] = self._build_index(
            bom_item_rules, lambda r: r.bom_item_id
        )

        # 2. Evaluate inclusion (flat pass)
        included_set: set[int] = set()
        for item in bom_items:
            rules = rules_by_bom_item.get(item.id, [])
            if not rules or any(self._evaluate_rule(rule.conditions, running_context, type_map) for rule in rules):
                included_set.add(item.id)

        # 3. Resolve quantities
        resolved_quantities: dict[int, Decimal] = {}
        for item in bom_items:
            if item.id not in included_set:
                continue
            quantity = self._resolve_bom_quantity(item, running_context, field_states)
            if quantity is None:
                included_set.discard(item.id)
            else:
                resolved_quantities[item.id] = quantity

        # 4. Prune tree
        self._prune_bom_tree(bom_items, included_set)

        # 5. Aggregate by part number
        deduplicated = self._aggregate_bom_items(bom_items, included_set, resolved_quantities)

        # 6. Build output
        return self._build_bom_output(
            deduplicated,
            included_set,
            resolved_quantities,
            price_map=price_map,
            price_list_name=price_list_name,
            price_date=price_date,
            known_parts=known_parts,
            catalog_map=catalog_map or {},
        )

    def _resolve_bom_quantity(
        self,
        item: CachedBOMItem,
        running_context: dict[int, Any],
        field_states: dict[int, FieldOutputState],
    ) -> Decimal | None:
        """
        Resolves the effective quantity for a BOM item.

        Returns the resolved quantity, or None if the item should be excluded
        (field value is zero or negative).
        """
        if item.quantity_from_field_id is None:
            return item.quantity

        # Check if the referenced field is hidden — fall back to static quantity
        field_state = field_states.get(item.quantity_from_field_id)
        if field_state is not None and field_state.is_hidden:
            return item.quantity

        field_value = running_context.get(item.quantity_from_field_id)
        if field_value is None:
            return item.quantity

        try:
            decimal_value = Decimal(str(field_value))
        except (InvalidOperation, ValueError, TypeError):
            return item.quantity

        if decimal_value <= 0:
            return None  # Exclude item

        return decimal_value

    def _prune_bom_tree(self, bom_items: list[CachedBOMItem], included_set: set[int]) -> None:
        """
        Removes children whose parent has been excluded.

        Iterates top-down (items are ordered by sequence). If a parent is not in
        the included set, its children are removed as well.
        """
        changed = True
        while changed:
            changed = False
            for item in bom_items:
                if item.id not in included_set:
                    continue
                if item.parent_bom_item_id is not None and item.parent_bom_item_id not in included_set:
                    included_set.discard(item.id)
                    changed = True

    def _aggregate_bom_items(
        self,
        bom_items: list[CachedBOMItem],
        included_set: set[int],
        resolved_quantities: dict[int, Decimal],
    ) -> list[CachedBOMItem]:
        """
        Aggregates included BOM items by (part_number, parent_bom_item_id, bom_type).

        Items sharing the same part_number, parent context, and BOM type are
        merged into a single representative item (the first by sequence order).
        Quantities are summed across the group. TECHNICAL and COMMERCIAL items
        with the same part_number remain separate.

        Children of every non-representative member of a group are re-parented
        under the surviving representative and re-aggregated recursively, so
        identical children of merged siblings collapse into a single line with
        summed quantity. Re-parenting builds new `CachedBOMItem` instances via
        `dataclasses.replace`; the cache itself is untouched.

        Returns a deduplicated item list and updated resolved_quantities map,
        ordered depth-first so that `_build_bom_output` attaches children to
        parents in sequence order.
        """
        from collections import OrderedDict
        from dataclasses import replace

        children_of: dict[int | None, list[CachedBOMItem]] = {}
        for item in bom_items:
            if item.id not in included_set:
                continue
            children_of.setdefault(item.parent_bom_item_id, []).append(item)

        new_items: list[CachedBOMItem] = []
        new_quantities: dict[int, Decimal] = {}

        def _walk_level(level_items: list[CachedBOMItem]) -> None:
            level_sorted = sorted(level_items, key=lambda x: x.sequence)
            groups: OrderedDict[tuple[str, str], list[CachedBOMItem]] = OrderedDict()
            for sib in level_sorted:
                groups.setdefault((sib.part_number, sib.bom_type), []).append(sib)

            for group in groups.values():
                representative = group[0]
                total_quantity = sum((resolved_quantities[item.id] for item in group), Decimal("0"))

                merged_children: list[CachedBOMItem] = []
                for member in group:
                    for kid in children_of.get(member.id, []):
                        if kid.parent_bom_item_id != representative.id:
                            kid = replace(kid, parent_bom_item_id=representative.id)
                        merged_children.append(kid)

                new_items.append(representative)
                new_quantities[representative.id] = Decimal(total_quantity)

                _walk_level(merged_children)

        _walk_level(children_of.get(None, []))

        included_set.clear()
        included_set.update(item.id for item in new_items)
        resolved_quantities.clear()
        resolved_quantities.update(new_quantities)

        return new_items

    def _build_bom_output(
        self,
        bom_items: list[CachedBOMItem],
        included_set: set[int],
        resolved_quantities: dict[int, Decimal],
        price_map: dict[str, Decimal] | None = None,
        price_list_name: str | None = None,
        price_date: date | None = None,
        known_parts: set[str] | None = None,
        catalog_map: dict[str, CatalogItem] | None = None,
    ) -> BOMOutput:
        """
        Constructs the BOM output: nested tree for TECHNICAL, flat list for COMMERCIAL.

        TECHNICAL items support hierarchy (parent/child relationships).
        COMMERCIAL items are always root-level (guaranteed by CRUD validation).

        Price resolution: COMMERCIAL items get unit_price from price_map (if provided).
        Missing prices generate warnings; line_total is null for unpriced items.
        """
        warnings: list[str] = []
        catalog = catalog_map or {}

        # Build line items indexed by id
        line_items: dict[int, BOMLineItem] = {}
        for item in bom_items:
            if item.id not in included_set:
                continue
            quantity = resolved_quantities[item.id]

            # Price resolution
            unit_price: Decimal | None = None
            line_total: Decimal | None = None
            if item.bom_type == "COMMERCIAL" and price_map is not None:
                resolved_price = price_map.get(item.part_number)
                if resolved_price is not None:
                    unit_price = resolved_price
                    line_total = quantity * resolved_price
                else:
                    if price_list_name and price_date:
                        effective_known = known_parts or set()
                        if item.part_number in effective_known:
                            warnings.append(
                                f"Part '{item.part_number}' has no valid price "
                                f"at date {price_date} in price list '{price_list_name}'"
                            )
                        else:
                            warnings.append(f"Part '{item.part_number}' not found in price list '{price_list_name}'")

            # Metadata is sourced from the catalog (joined on part_number).
            # The FK on bom_items.part_number guarantees a row exists; a missing
            # entry here indicates a corrupted EntityVersion.
            catalog_entry = catalog.get(item.part_number)
            if catalog_entry is None:
                raise ValueError(
                    f"Catalog entry missing for part_number '{item.part_number}' "
                    f"on bom_item {item.id}; EntityVersion is inconsistent."
                )

            line_items[item.id] = BOMLineItem(
                bom_item_id=item.id,
                bom_type=item.bom_type,
                part_number=item.part_number,
                description=catalog_entry.description,
                category=catalog_entry.category,
                quantity=quantity,
                unit_of_measure=catalog_entry.unit_of_measure,
                unit_price=unit_price,
                line_total=line_total,
                children=[],
            )

        # Build tree for TECHNICAL items (attach children to parents)
        technical: list[BOMLineItem] = []
        commercial: list[BOMLineItem] = []
        for item in bom_items:
            if item.id not in included_set:
                continue
            line_item = line_items[item.id]
            if item.bom_type == "COMMERCIAL":
                # COMMERCIAL items are always root-level (flat list)
                commercial.append(line_item)
            else:
                # TECHNICAL items: build nested tree
                if item.parent_bom_item_id is not None and item.parent_bom_item_id in line_items:
                    line_items[item.parent_bom_item_id].children.append(line_item)
                else:
                    technical.append(line_item)

        # Compute commercial total (partial sum of non-null line_totals)
        commercial_total = self._sum_line_totals(commercial)

        technical_flat = self._build_technical_flat(technical, catalog)

        return BOMOutput(
            technical=technical,
            commercial=commercial,
            technical_flat=technical_flat,
            commercial_total=commercial_total,
            warnings=warnings,
        )

    def _build_technical_flat(
        self,
        technical_tree: list[BOMLineItem],
        catalog_map: dict[str, "CatalogItem"],
    ) -> list[BOMFlatLineItem]:
        """
        Cascade-aggregate the technical sub-tree into an alphabetic flat list.

        For each node, the contribution is `ancestor_product × node.quantity`,
        where `ancestor_product` is the running product of all ancestor
        quantities from the root down to the parent (1 at the roots). Same
        `part_number` appearing in multiple branches is summed across them.

        Returns one `BOMFlatLineItem` per distinct `part_number`, sorted by
        `part_number` ascending. Empty when the technical tree is empty.
        """
        totals: dict[str, Decimal] = {}

        def _walk(nodes: list[BOMLineItem], ancestor_product: Decimal) -> None:
            for node in nodes:
                contribution = ancestor_product * node.quantity
                totals[node.part_number] = totals.get(node.part_number, Decimal("0")) + contribution
                if node.children:
                    _walk(node.children, contribution)

        _walk(technical_tree, Decimal("1"))

        flat: list[BOMFlatLineItem] = []
        for part_number in sorted(totals):
            catalog_entry = catalog_map.get(part_number)
            flat.append(
                BOMFlatLineItem(
                    part_number=part_number,
                    description=catalog_entry.description if catalog_entry is not None else None,
                    category=catalog_entry.category if catalog_entry is not None else None,
                    unit_of_measure=catalog_entry.unit_of_measure if catalog_entry is not None else None,
                    total_quantity=totals[part_number],
                )
            )
        return flat

    def _sum_line_totals(self, items: list[BOMLineItem]) -> Decimal | None:
        """Recursively sums line_total across a list of BOMLineItems and their children."""
        total = Decimal("0")
        has_any = False
        for item in items:
            if item.line_total is not None:
                total += item.line_total
                has_any = True
            child_total = self._sum_line_totals(item.children)
            if child_total is not None:
                total += child_total
                has_any = True
        return total if has_any else None

    # ============================================================
    # UTILITY
    # ============================================================

    def _check_completeness(self, output_fields: list[FieldOutputState]) -> bool:
        """Checks if all required visible fields have values and validation errors."""
        for field in output_fields:
            # Missing mandatory Value
            if field.is_required and not field.is_hidden and field.current_value is None:
                return False

            # Check validation errors
            if field.error_message is not None:
                return False

        return True
