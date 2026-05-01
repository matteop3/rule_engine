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

**Rationale**: Both types share the same structure (part number, quantity, conditions, parent reference). A single table simplifies queries, CRUD endpoints, and cloning logic. The `bom_type` discriminator enables type-specific validation at the CRUD layer (e.g., COMMERCIAL items must be root-level). Pricing for COMMERCIAL items is resolved at calculation time from the centralized price list (see [ADR: Price List](ADR_PRICE_LIST.md)).

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

The hierarchy is authored two ways: hand-written `BOMItem` rows on a DRAFT `EntityVersion`, or **materialization from an engineering template** attached to the part's `CatalogItem` — see [ADR: Engineering BOM](ADR_ENGINEERING_BOM.md). Both paths produce the same `BOMItem` shape; the calculation engine cannot tell them apart.

### 5. Two-enum model without BOTH

A component that appears in both the technical and commercial BOM is modeled as **two separate BOM items** with the same `part_number` but different `bom_type` values, rather than a single item with `bom_type = BOTH`.

**Rationale**: TECHNICAL and COMMERCIAL items serve different purposes (TECHNICAL represents the manufacturing structure; COMMERCIAL represents the pricing/quoting structure). A `BOTH` type would require the item to satisfy conflicting constraints (e.g., hierarchy rules). Separate items allow independent conditions, quantities, and metadata per context — standard practice in ERP systems.

### 6. Aggregation key includes `bom_type`

When multiple BOM items share the same `part_number` and parent, the engine aggregates them by summing quantities. The aggregation key is `(part_number, parent_bom_item_id, bom_type)`, ensuring TECHNICAL and COMMERCIAL items with the same part number remain separate.

**Rationale**: A TECHNICAL item "BOLT-M8" (no pricing) and a COMMERCIAL item "BOLT-M8" ($0.50 each) represent different concerns and must not be merged.

Aggregation also re-parents the children of every non-representative member of a merged sibling group under the surviving representative, then recurses so identical children of merged parents collapse into one line with summed quantity. Without re-parenting, those children kept their original `parent_bom_item_id` (pointing to a now-excluded sibling) and surfaced as spurious roots in `technical`. See [ADR: Engineering BOM](ADR_ENGINEERING_BOM.md) decision 15 for the full algorithm.

### 7. ~~COMMERCIAL price consistency validation~~ (Superseded)

~~COMMERCIAL items with the same `part_number` in the same version must have identical `unit_price`. This is enforced at CRUD time (HTTP 409 on conflict).~~

**Superseded**: Per-item pricing on BOM items has been replaced by the centralized price list. Pricing is resolved at calculation time from the price list, not stored on individual BOM items. Price consistency is guaranteed by the price list's no-overlap constraint for `(price_list_id, part_number)` date ranges. See [ADR: Price List](ADR_PRICE_LIST.md) for the new pricing design.

### 8. Part metadata sourced from the catalog

`BOMItem` stores only the structural fields — `part_number`, `quantity`, `parent_bom_item_id`, `bom_type`, `quantity_from_field_id`, `sequence`. Canonical description, category, and unit of measure live on `CatalogItem` and are joined at calculation time to populate `BOMLineItem.description`, `category`, and `unit_of_measure` in the response. `BOMItem.part_number` is a foreign key to `CatalogItem.part_number`; CRUD validation rejects BOM items that reference a missing or `OBSOLETE` catalog entry. The response schema `BOMItemRead` exposes only the structural fields — clients that want metadata look it up through the catalog endpoints or read it off the calculation response.

See [ADR: Catalog Item](ADR_CATALOG_ITEM.md) for the full design.

### 9. Cascade-aggregated `technical_flat` view

Every `BOMOutput` carries a `technical_flat: list[BOMFlatLineItem]` field alongside the indented `technical` tree. It is an alphabetically sorted, cross-branch aggregated view computed by the engine on every calculation:

- For each technical node, the contribution is `ancestor_product × node.quantity`, where `ancestor_product` is `1` at the roots and `ancestor_product × parent.quantity` at descendants.
- Same `part_number` reachable through multiple branches sums into a single row.
- The output is sorted by `part_number`; the field is empty when the technical tree is empty.

`BOMFlatLineItem` carries the same metadata as `BOMLineItem` minus pricing and hierarchy: `part_number`, `description`, `category`, `unit_of_measure`, `total_quantity`. Catalog metadata is sourced from the in-memory `catalog_map` already loaded for the indented tree — no extra DB roundtrip.

**Rationale**: The indented tree intentionally records `BOMItem.quantity` as **stoichiometric, per unit of parent** (preserving the existing semantics and avoiding invasive engine changes). That representation answers "how many of this child go into one parent?" but not "how many of this leaf does one configuration consume?". The flat view answers the procurement question in O(tree size) at calculation time, with snapshot immunity inheriting from the existing `Configuration.snapshot` mechanism — `technical_flat` survives finalization automatically.

### 10. Position in the evaluation waterfall

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
- [ADR: Price List](ADR_PRICE_LIST.md) — Centralized pricing via price list (supersedes per-item `unit_price` on BOM items)
- [ADR: Catalog Item](ADR_CATALOG_ITEM.md) — Canonical part identity and metadata (supersedes `description`, `category`, `unit_of_measure` on BOM items)
- [ADR: Engineering BOM](ADR_ENGINEERING_BOM.md) — Engineering templates as the authoring path for hierarchical TECHNICAL BOMs, the corrected aggregation algorithm, and the `technical_flat` view
