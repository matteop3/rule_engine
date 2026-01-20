# ADR: Rule Expression Complexity

## Status

**Accepted**

## Context

The rule engine evaluates conditions to control field behavior (visibility, availability, validation, etc.). Each condition compares a single field's value against a static value using operators like `EQUALS`, `GREATER_THAN`, `IN`, etc.

Real-world configurators sometimes require more complex validations:

| Use Case | Expression Type | Example |
|----------|-----------------|---------|
| Budget validation | Arithmetic | `base_price + options_total <= budget` |
| Capacity check | Aggregation | `SUM(ssd_count, hdd_count) <= chassis_slots` |
| Date range | Cross-field comparison | `end_date > start_date` |
| Percentage split | Arithmetic | `allocation_a + allocation_b == 100` |

This raises the question of whether the rule engine should support cross-field operations and arithmetic expressions.

## Decision

The rule engine supports **single-field conditions only**. Cross-field comparisons, arithmetic operations, and aggregation functions are **not supported**.

Supported:
```json
{"field_id": 5, "operator": "GREATER_THAN", "value": 1000}
```

Not supported:
```json
{"expression": "field_5 + field_6 > 5000"}
{"field_id": 5, "operator": "GREATER_THAN", "field_ref": 6}
```

## Rationale

### Why exclude cross-field operations?

1. **Simplicity over flexibility**: Single-field conditions are easy to understand, validate, and debug. Authors can reason about each condition independently.

2. **Predictable evaluation**: The waterfall model processes fields in order. Cross-field references would require dependency analysis to prevent circular references and ensure referenced fields are evaluated first.

3. **No expression parser needed**: Arithmetic expressions require a parser, type coercion logic, and error handling for malformed expressions. This adds significant complexity.

4. **Sufficient for most CPQ use cases**: Product configurators primarily need:
   - Show/hide fields based on selections (covered by VISIBILITY)
   - Filter options based on other selections (covered by AVAILABILITY)
   - Validate individual field constraints (covered by VALIDATION)

   Complex cross-field calculations are typically handled at the application layer.

5. **Security considerations**: Expression evaluation introduces risks (injection, infinite loops, resource exhaustion) that require careful sandboxing.

### What about legitimate cross-field needs?

For cases where cross-field validation is genuinely required:

| Approach | When to Use |
|----------|-------------|
| **Application-layer validation** | Business logic that doesn't fit the rule model |
| **Computed fields** | Add a read-only field that calculates totals server-side |
| **Pre-submission hooks** | Validate complex constraints before finalizing |

## Alternatives Considered

### A. Cross-field references (field_ref)

```json
{"field_id": 5, "operator": "GREATER_THAN", "field_ref": 6}
```

**Rejected**: Requires dependency tracking, complicates the condition schema, and opens the door to circular references.

### B. Expression DSL

```json
{"expression": "SUM(field_5, field_6) <= field_7"}
```

**Rejected**: Requires a full expression parser, introduces security risks, and significantly increases complexity. This would be a separate project in itself.

### C. Calculated/virtual fields

Add a field type that computes its value from other fields, then validate against that.

**Deferred**: This is a reasonable future enhancement but adds complexity to the field model and evaluation order. Could be reconsidered if demand arises.

## Consequences

**Positive:**
- Rule conditions remain simple and declarative
- No expression parsing or security sandboxing required
- Evaluation order is straightforward (field sequence)
- Easy to validate rule conditions at creation time

**Negative:**
- Some validation scenarios require application-layer logic
- Cannot express "total must not exceed X" directly in rules
- Users expecting a full expression language may find it limiting

**Neutral:**
- Complex cross-field logic is pushed to the consuming application, which has full context and can implement domain-specific validation

## References

- [Rule Engine Implementation](../app/services/rule_engine.py)
- [Condition Schema](../app/schemas/rule.py)
