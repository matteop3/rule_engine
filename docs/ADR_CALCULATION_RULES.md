# ADR: Calculation Rules (Derived Field Values)

## Status

**Accepted**

## Context

The rule engine supports rule types that control field *behavior*: visibility, availability, editability, mandatory state, and validation. However, none of these rules can control a field's *value*. There is no way to declaratively say: "when condition X is true, this field's value must be Y and the user cannot change it."

This gap matters in CPQ scenarios:

| Use Case | Example |
|----------|---------|
| Forced option | If chassis = "Compact", force cooling_system = "Passive" (no room for fans) |
| Derived default | If product_type = "Enterprise", force support_tier = "Premium" |
| Bundled component | If bundle = "Starter Pack", force warranty = "1 Year" |
| Auto-assignment | If region = "EU", force power_supply = "220V" |

Without a dedicated rule type, an author can approximate this by:
1. Using an AVAILABILITY rule to leave only one option, then relying on auto-selection for required fields
2. Combining EDITABILITY (readonly) with a default value on the field

Both are workarounds. Option 1 is fragile (auto-selection only triggers for required fields, and the intent is unclear to other authors). Option 2 is static (the default is always the same regardless of conditions).

A CALCULATION rule makes the intent explicit: "under these conditions, the system determines this field's value."

## Decision

The engine includes a **CALCULATION** rule type that, when its conditions are met, sets the target field's value to a static value and makes the field implicitly readonly.

### Rule definition

A CALCULATION rule uses the existing `conditions` JSON structure (same `criteria` array as other rules) plus a `set_value` column on the Rule model:

```json
{
  "rule_type": "calculation",
  "target_field_id": 8,
  "set_value": "Passive",
  "conditions": {
    "criteria": [
      {"field_id": 3, "operator": "EQUALS", "value": "Compact"}
    ]
  }
}
```

When the conditions evaluate to true, the engine:
1. Sets the field's `current_value` to `set_value`
2. Marks the field as `is_readonly = true` (the value is system-determined, not user-editable)
3. Ignores user input for this field (the calculated value takes precedence)

When no CALCULATION rule passes (or no CALCULATION rules exist), the field behaves normally.

### Position in the waterfall

CALCULATION is evaluated **after VISIBILITY and before EDITABILITY**. When a CALCULATION rule fires, the engine skips EDITABILITY and AVAILABILITY (since the value is system-determined and the user cannot interact with the field), but still evaluates MANDATORY and VALIDATION:

```
1. VISIBILITY    → is the field shown? If hidden → early return
2. CALCULATION   → is the value system-determined?
   If yes → set value, force readonly, skip to MANDATORY
3. EDITABILITY   → is the field readonly? (skipped if calculated)
4. AVAILABILITY  → which options are available? (skipped if calculated)
5. MANDATORY     → is the field required?
6. VALIDATION    → is the value valid?
```

Rationale for this position and skip behavior:
- **After VISIBILITY**: no point calculating a value for a hidden field
- **Skip EDITABILITY**: CALCULATION implies readonly by definition; evaluating EDITABILITY could contradict the calculated state (e.g., an EDITABILITY rule making the field editable would undermine the forced value)
- **Skip AVAILABILITY**: the user cannot choose between options on a calculated field. For non-free-value fields, `available_options` contains only the `set_value` entry (the forced value); for free-value fields, `available_options` remains `[]` (free-value fields never have options). This ensures frontends can populate a disabled dropdown with a valid value, consistent with keeping MANDATORY for visual indicators
- **Keep MANDATORY**: frontends may use `is_required` for visual indicators (e.g., asterisk) regardless of whether the field is calculated
- **Keep VALIDATION**: serves as a safety net against misconfigured rules, and becomes essential if CALCULATION is ever extended to support arithmetic expressions (where range validation would be needed)

### Storage: `set_value` column on Rule

A nullable `set_value` column on the Rule model follows the same pattern as `error_message` (used only for VALIDATION rules):

| Column | Used by | Purpose |
|--------|---------|---------|
| `error_message` | VALIDATION | Message to display when validation fails |
| `set_value` | CALCULATION | Value to assign when conditions are met |

Rule-type-specific data lives in dedicated nullable columns rather than being overloaded into the `conditions` JSON.

### API-layer validation for `set_value`

`set_value` follows the same consistency constraints as `error_message` and `target_value_id`:

| Column | Allowed with | Rejected for |
|--------|-------------|--------------|
| `target_value_id` | AVAILABILITY | all other rule types |
| `error_message` | VALIDATION | all other rule types |
| `set_value` | CALCULATION | all other rule types |

Additionally, when creating a CALCULATION rule on a non-free-value field, the API validates that `set_value` matches one of the field's defined Values. This follows the existing validation pattern where the router already checks that `target_field_id` belongs to the version and `target_value_id` belongs to the field.

This prevents an author from setting an arbitrary value (e.g., `"380V"`) on a field that only accepts predefined options (e.g., `["220V", "110V", "Universal"]`). Without this check, a downstream system (e.g., an ERP) receiving the configuration output could reject the value, causing silent integration failures.

For free-value fields, `set_value` is accepted as-is (any string is valid, consistent with how free-value fields accept arbitrary user input).

### Defensive validation at engine level

API-layer validation is the primary safeguard, but data inconsistencies can still occur (e.g., a Value deleted after the rule was created, direct DB modifications, migrations). To prevent the frontend from receiving a dropdown field with a `current_value` that does not appear in its `available_options`, the engine applies a defensive check at evaluation time:

- For non-free-value fields, if `set_value` does not match any of the field's defined Values, the engine logs a warning and blanks `current_value` to `null`
- The `running_context` is updated **after** this check, so downstream fields see `null` (not the invalid value) in their conditions
- The field remains `is_readonly = true` (it is still a calculated field, just with an unresolvable value)

## Rationale

### Why static value mapping only?

Consistent with the decision in [ADR: Rule Expressions](ADR_RULE_EXPRESSIONS.md), CALCULATION rules use **static value assignment** rather than computed expressions:

```
Supported:    set_value = "Passive"        (static)
Not supported: set_value = "field_3 * 0.1"  (expression)
```

This means:
- No expression parser needed
- No risk of circular dependencies between calculated fields
- Rules remain declarative and inspectable (an author can read the rule and immediately understand the outcome)
- The engine stays simple: it matches conditions and assigns a value, no evaluation of formulas

For cases requiring arithmetic (e.g., `total = quantity × price`), the recommendation remains the same as in the Rule Expressions ADR: handle it at the application layer.

### Why implicit readonly?

A calculated field is readonly by definition: the system determined its value, so user modification would be contradictory. Making this implicit (rather than requiring a separate EDITABILITY rule) ensures:
- **Correctness**: impossible to forget the EDITABILITY rule and end up with a user-editable calculated field
- **Author simplicity**: one rule instead of two
- **Clear semantics**: "calculated" inherently means "not user-editable"

### Conflict resolution: multiple CALCULATION rules

If multiple CALCULATION rules target the same field, the **first passing rule wins** (evaluated in rule creation order). This is simple and predictable, matching the OR logic used by other rule types.

## Alternatives Considered

### A. Overload AVAILABILITY to force single option

Use AVAILABILITY rules to filter down to exactly one option, relying on auto-selection.

**Rejected**: This is a side-effect, not an explicit intent. Auto-selection only works for required fields, and an author reading the rules won't understand that the *intent* is to force a specific value.

### B. Add a `computed_value` expression field

Support expressions like `"field_3 + field_5"` or `"CONCAT(field_1, '-', field_2)"`.

**Rejected**: Requires an expression parser, introduces security and circular-dependency risks, and contradicts the Rule Expressions ADR. The static mapping covers the vast majority of CPQ use cases where a value is *determined* by a condition, not *computed* from other values.

### C. Store `set_value` inside conditions JSON

```json
{"criteria": [...], "set_value": "Passive"}
```

**Rejected**: Mixing behavioral data (`set_value`) with condition logic (`criteria`) muddies the schema. A dedicated column is more explicit, queryable, and consistent with how `error_message` is handled for VALIDATION rules.

### D. Evaluate all waterfall layers even when CALCULATION fires

Run EDITABILITY and AVAILABILITY normally after CALCULATION.

**Rejected**: EDITABILITY could override the implicit readonly (making the calculated value user-editable), and AVAILABILITY could present options the user cannot act on. Skipping these layers when CALCULATION fires avoids contradictory states and is consistent with how VISIBILITY already triggers an early return for hidden fields.

## Consequences

**Positive:**
- Closes a real gap in the rule model (controlling field values, not just behavior)
- Intent is explicit and readable ("when X, set Y to Z")
- Minimal model change (one new column, one new enum value)
- No expression parser or new evaluation paradigm needed
- Consistent with existing architectural decisions
- API-layer validation prevents invalid `set_value` on non-free-value fields

**Negative:**
- `set_value` column is null for most rule types (same trade-off as `error_message`)
- Static-only values cannot cover arithmetic/concatenation use cases

**Neutral:**
- VALIDATION rules still apply to calculated values, providing a safety net against misconfigured rules
- SKU generation works unchanged: the calculated value feeds into SKU modifiers like any other value

## References

- [ADR: Rule Expressions](ADR_RULE_EXPRESSIONS.md) — why single-field conditions only
- [ADR: Inference Tree](ADR_INFERENCE_TREE.md) — why waterfall evaluation
- [Rule Engine Implementation](../app/services/rule_engine.py) — waterfall logic in `_process_field`
- [Rule Model](../app/models/domain.py) — `Rule` class and `RuleType` enum
