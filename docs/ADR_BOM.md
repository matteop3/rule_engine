# ADR: Bill of Materials (BOM) Generation

## Status

**Accepted**

## Context

Product configurators in CPQ systems produce two outputs beyond the field state: a **technical BOM** (components needed to build the product) and a **commercial BOM** (priced line items for quotes and invoices). The rule engine already evaluates field conditions and produces a calculation response — BOM generation is a natural extension of this pipeline.

The key design questions are:

1. How to store BOM items (separate table vs. embedded JSON)?
2. How to model conditional inclusion (reuse existing rule engine conditions or invent a new mechanism)?
3. How to handle quantities (static vs. dynamic)?
4. How to separate technical from commercial BOM concerns?
5. How to support hierarchical BOMs (sub-assemblies)?

## Decisions

### 1. Single BOM item table with `bom_type` discriminator

BOM items are stored in a single `bom_items` table with a `bom_type` column (`TECHNICAL` or `COMMERCIAL`) rather than separate tables per type.

**Rationale**: Both types share the same structure (part number, quantity, conditions, parent reference). The only difference is that COMMERCIAL items carry pricing. A single table simplifies queries, CRUD endpoints, and cloning logic. The `bom_type` discriminator enables type-specific validation at the CRUD layer (e.g., TECHNICAL items reject `unit_price`, COMMERCIAL items require it).

### 2. Separate BOM item rule table

Conditional inclusion is modeled via a separate `bom_item_rules` table rather than embedding conditions in the BOM item record. Each BOM item can have zero or more rules:

- **Zero rules**: item is unconditionally included.
- **One or more rules**: item is included if **any** rule passes (OR logic). Each rule's criteria use AND logic internally.

**Rationale**: This reuses the existing `conditions` JSON structure (`{"criteria": [...]}`) and the engine's `_evaluate_rule()` method without modification. A separate table enables OR logic across rules (the same pattern used for field rules) and keeps the BOM item record focused on product data rather than logic.

### 3. No expression parser for quantities

Quantities are either static (`quantity` column) or resolved from a single field reference (`quantity_from_field_id`). There is no expression language for computed quantities (e.g., `width * 2 + 1`).

**Rationale**: Consistent with the decision in [ADR: Rule Expressions](ADR_RULE_EXPRESSIONS.md) to avoid expression parsing. Field-referenced quantities cover the common CPQ case (quantity driven by a numeric input). For complex transformations, the consuming application can post-process the BOM output. If the referenced field is hidden (by a visibility rule), the engine falls back to the static `quantity` value, ensuring the BOM remains valid regardless of field state.

### 4. TECHNICAL hierarchy, COMMERCIAL flat

TECHNICAL BOM items support hierarchical nesting via a self-referential `parent_bom_item_id` foreign key (sub-assemblies, multi-level BOMs). COMMERCIAL BOM items are root-level only — no hierarchy.

**Rationale**: In ERP/CPQ standards (SAP, Oracle, Tacton), the technical BOM represents the manufacturing structure (which naturally nests), while the commercial BOM represents the pricing structure (a flat list of priced line items on a quote or invoice). Enforcing COMMERCIAL-is-root at the CRUD layer eliminates an entire class of output ambiguity.

### 5. Two-enum model without BOTH

A component that appears in both the technical and commercial BOM is modeled as **two separate BOM items** with the same `part_number` but different `bom_type` values, rather than a single item with `bom_type = BOTH`.

**Rationale**: TECHNICAL and COMMERCIAL items carry different metadata (TECHNICAL has no pricing; COMMERCIAL has pricing, no hierarchy). A `BOTH` type would require the item to satisfy conflicting constraints. Separate items allow independent conditions, quantities, and metadata per context — standard practice in ERP systems.

### 6. Aggregation key includes `bom_type`

When multiple BOM items share the same `part_number` and parent, the engine aggregates them by summing quantities. The aggregation key is `(part_number, parent_bom_item_id, bom_type)`, ensuring TECHNICAL and COMMERCIAL items with the same part number remain separate.

**Rationale**: A TECHNICAL item "BOLT-M8" (no pricing) and a COMMERCIAL item "BOLT-M8" ($0.50 each) represent different concerns and must not be merged.

### 7. COMMERCIAL price consistency validation

COMMERCIAL items with the same `part_number` in the same version must have identical `unit_price`. This is enforced at CRUD time (HTTP 409 on conflict).

**Rationale**: During aggregation, quantities are summed but `unit_price` is taken from the first item. If two items with the same part number had different prices, one price would be silently lost. CRUD-level validation prevents this. A future centralized BOM catalog/price list is planned to replace per-item pricing entirely.

### 8. Position in the evaluation waterfall

BOM evaluation runs **after** SKU generation and **after** all field states are resolved. It is a post-calculation output layer that reads the resolved field states but does not modify them.

```
1. VISIBILITY    → is the field shown?
2. CALCULATION   → is the value system-determined?
3. EDITABILITY   → is the field readonly?
4. AVAILABILITY  → which options are available?
5. MANDATORY     → is the field required?
6. VALIDATION    → is the value valid?
7. Completeness  → are all required fields filled?
8. SKU           → generate product code
9. BOM           → evaluate inclusion, resolve quantities, compute totals
```

**Rationale**: BOM conditions reference field values from the running context. All field rules must be resolved first so the BOM sees the final state. BOM output is independent of field state — it does not modify fields, only produces a parallel output structure.

## Consequences

- **Positive**: BOM generation reuses existing condition evaluation, field map, and cache infrastructure. No changes to the field evaluation waterfall.
- **Positive**: CRUD validations (pricing by type, COMMERCIAL-is-root, price consistency) catch configuration errors early, before they reach the engine.
- **Positive**: Version cloning handles BOM data with the same ID-remapping pattern used for fields, values, and rules.
- **Negative**: The `quantity_from_field_id` column requires explicit remapping during version clone (easy to overlook since it is not inside the `conditions` JSON).
- **Negative**: No expression parser limits quantity logic to single-field references. Complex formulas require post-processing by the consuming application.

## Related

- [ADR: Rule Expressions](ADR_RULE_EXPRESSIONS.md) — Why rules use single-field conditions
- [ADR: Calculation Rules](ADR_CALCULATION_RULES.md) — How CALCULATION rules derive field values
- [ADR: Re-hydration](ADR_REHYDRATION.md) — Why configurations store raw inputs and recalculate on read
