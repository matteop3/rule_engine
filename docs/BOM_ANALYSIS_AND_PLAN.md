# Bill of Materials (BOM) — Analysis and Development Plan

## Status

**Approved** — Ready for implementation.

## 1. Overview

This document describes the addition of **Bill of Materials (BOM) generation** to the rule engine. After calculating field states and SKU, the engine will also produce two parallel output lists:

- **Technical BOM**: Physical components and parts required to build/assemble the configured product.
- **Commercial BOM**: Line items that appear on quotes and invoices, with pricing.

BOM items are evaluated using the same condition logic already used by field rules. The feature is a natural extension of the existing waterfall — it adds a post-calculation output layer without modifying the field evaluation flow.

### Goals

- Allow authors to define BOM items at the EntityVersion level, with conditions that determine when each item is included.
- Support hierarchical BOM (parent–child relationships for sub-assemblies).
- Compute line totals and a BOM total price for commercial items.
- Persist `bom_total_price` on the Configuration record (like `is_complete` and `generated_sku`) for efficient querying.

### Non-Goals

- Discount and margin management (deferred to a future iteration).
- Multi-currency support (prices are plain decimals; currency is the consuming application's responsibility, same rationale as the i18n deferral).
- Snapshot of full BOM state on FINALIZED configurations (not needed at current scale).
- Centralized BOM catalog / price list (planned for a future iteration — prices are currently authored per BOM item, with CRUD-level consistency validation as a stopgap).

---

## 2. Design Decisions

### 2.1 Single table with `bom_type` enum

BOM items live in a single `bom_items` table with a `bom_type` column (`TECHNICAL`, `COMMERCIAL`). A component that must appear in both lists is modeled as **two separate BOM items** with the same `part_number` — one TECHNICAL (no price, can be nested) and one COMMERCIAL (with price, always root-level). This allows each record to carry metadata appropriate to its context (e.g., a production-oriented description vs. a customer-facing one) and aligns with standard ERP/CPQ practice (SAP eBOM/sBOM, Oracle CPQ).

If the commercial BOM grows significantly richer in the future (discounts, margins, tax categories), it can be extracted into a dedicated table without breaking the technical BOM.

### 2.2 Conditions via separate `BOMItemRule` table

BOM item inclusion is governed by a dedicated `bom_item_rules` table, **not** by extending the existing `rules` table. Rationale:

- The existing `Rule` model requires `target_field_id` (a field FK). BOM rules do not target fields.
- Adding `target_bom_item_id` to `Rule` would introduce mutually exclusive nullable FKs, muddying the model.
- BOM rules do not participate in the waterfall — they are evaluated in a separate pass after all fields are processed.

The `bom_item_rules` table uses the **exact same** `conditions` JSON format (`{"criteria": [{"field_id": ..., "operator": ..., "value": ...}]}`) and the same AND/OR logic:

- **AND**: All criteria within a single `BOMItemRule` must pass.
- **OR**: Multiple `BOMItemRule` rows targeting the same `BOMItem` — the item is included if **at least one** rule passes.
- **No rules**: A `BOMItem` with zero associated `BOMItemRule` rows is **always included** (unconditional component).

This mirrors the AVAILABILITY pattern used for field values.

### 2.3 Quantity: static + field reference (no arithmetic)

Each BOM item has:

- `quantity` (Decimal, required, default `1`): Static quantity, always present.
- `quantity_from_field_id` (FK to `fields.id`, nullable): If set, the quantity is read directly from the referenced numeric field's current value, overriding the static `quantity`.

This is **not** an expression — it is a single value lookup in the running context, identical in nature to how `_evaluate_conditions()` reads field values. No parser is needed.

**Limitations** (intentional, consistent with [ADR: Rule Expressions](ADR_RULE_EXPRESSIONS.md)):

- Arithmetic on quantities (`field_value × 2`, `field_a + field_b`) is not supported.
- If such computation is needed, the consuming application should handle it or the author should model an intermediate calculated field.

**Fallback behavior for `quantity_from_field_id`:**

| Field state | Behavior |
|-------------|----------|
| Field has a valid numeric value > 0 | Use that value as quantity |
| Field value is `null` (not yet filled) | Fall back to static `quantity` |
| Field value is ≤ 0 | Exclude the BOM item from output |
| Field is hidden by VISIBILITY rules | Fall back to static `quantity` |

### 2.4 Pricing rules by BOM type

| `bom_type` | `unit_price` | Enforcement |
|------------|-------------|-------------|
| `TECHNICAL` | Must be `null` | CRUD rejects any non-null value |
| `COMMERCIAL` | Required (non-null) | CRUD rejects null |

A BOM item participates in pricing **if and only if** it has a `unit_price`. This is enforced by the type constraint above, so there is no ambiguity at evaluation time.

### 2.5 Hierarchical BOM (nested sub-assemblies)

BOM items support a `parent_bom_item_id` self-referential FK (nullable). A null parent means the item is a root-level component.

**Hierarchy is for TECHNICAL items only.** COMMERCIAL items are always root-level (`parent_bom_item_id` must be `null`). This mirrors standard ERP/CPQ practice: the technical BOM represents the assembly structure for manufacturing, while the commercial BOM is a flat list of priced line items for quotes and invoices. Nesting has no meaning in a commercial context.

**Evaluation logic:**

1. Evaluate conditions for **all** BOM items in a flat pass (same as if they were a flat list).
2. Build in-memory tree from `parent_bom_item_id` relationships (TECHNICAL items only).
3. **Prune**: If a parent item is excluded (conditions not met), exclude the entire subtree.
4. Compute line totals and aggregate prices.
5. Return nested structure for technical, flat list for commercial.

The key insight is that **nesting does not complicate condition evaluation** — it only adds a post-evaluation tree-pruning step.

**`sequence` is per-level** (among siblings), not global. This allows reordering children of a sub-assembly without affecting other parts of the tree.

**CRUD validations for hierarchy:**

- `parent_bom_item_id` must be `null` for COMMERCIAL items (HTTP 400).
- `parent_bom_item_id` must reference a `BOMItem` in the **same** `entity_version_id`.
- Circular references are rejected (traverse parent chain to verify no cycles).
- Deleting a parent **cascade-deletes** all children (consistent with `Field` → `Value` behavior).

### 2.6 Line aggregation by `part_number`

When multiple BOM items share the same `part_number`, `parent_bom_item_id`, and `bom_type`, the engine aggregates them into a single output line:

- **Quantity**: sum of all resolved quantities for the matching items.
- **`unit_price`**, **`description`**, **`category`**, **`unit_of_measure`**: taken from the first matching item (by `sequence` order). These properties are inherent to the part and must be consistent across items with the same `part_number`.
- **`line_total`**: aggregated quantity × `unit_price`.
- **`bom_item_id`**: the ID of the first contributing item (for traceability).

Items are grouped by the tuple `(part_number, parent_bom_item_id, bom_type)`. Including `bom_type` in the key ensures that a TECHNICAL and a COMMERCIAL item with the same `part_number` remain separate — they carry different metadata and appear in different output lists.

**Why aggregation is the correct behavior**: the BOM answers "how many units of ABC do I need?", not "how many rules generated ABC". This is consistent with standard ERP/CPQ practice (SAP, Oracle, Tacton). Without aggregation, the same part could appear multiple times in the output, producing misleading procurement and costing data.

**Why same-parent grouping**: the BOM is a nested tree. The same `part_number` under different parents represents the part in different assembly contexts. Merging across parents would break the tree structure and lose assembly context.

### 2.7 Persisted `bom_total_price` on Configuration

`bom_total_price` (Decimal, nullable) is stored on the `Configuration` record alongside `is_complete` and `generated_sku`. It is recalculated on every mutation:

| Operation | Recalculates `bom_total_price`? |
|-----------|-------------------------------|
| Create configuration | Yes |
| Update configuration data | Yes |
| Upgrade to latest version | Yes |
| Clone configuration | Copied from source |
| Finalize configuration | No (already up to date) |

This follows the exact same pattern established for `is_complete` and `generated_sku` — pragmatic caching of derived values for queryability.

The total includes only items with `bom_type` = `COMMERCIAL`. Items with `bom_type` = `TECHNICAL` do not contribute (they have no `unit_price` by constraint).

### 2.8 Price consistency for COMMERCIAL items

When multiple COMMERCIAL BOM items share the same `part_number` (root-level, since COMMERCIAL is always flat), the `unit_price` must be identical. The CRUD layer validates this on create and update — if an existing COMMERCIAL item with the same `part_number` in the same version has a different `unit_price`, the request is rejected (HTTP 409).

**Rationale**: The aggregation engine merges same-`part_number` items into a single output line using the first item's `unit_price` (by sequence). If prices differ, the discarded price represents a silent data loss — a dangerous behavior for pricing. Standard CPQ systems avoid this by resolving prices from a centralized price list rather than per-line definitions. Since this engine stores `unit_price` on the BOM item itself, consistency must be enforced at the CRUD boundary.

**Future direction**: A centralized BOM catalog / price list is planned as a future feature. When implemented, `unit_price` on COMMERCIAL items will be resolved from the catalog rather than authored directly, eliminating this validation entirely.

### 2.9 Decimal precision

All monetary and quantity fields use `Numeric(12, 4)` in the database. Four decimal places accommodate industrial pricing while standard currency formatting (2 decimals) is left to the frontend.

---

## 3. Domain Model

### 3.1 BOMItem

```
Table: bom_items

id                      Integer, PK, auto-increment
entity_version_id       Integer, FK → entity_versions.id, NOT NULL
parent_bom_item_id      Integer, FK → bom_items.id, NULLABLE (self-referential, cascade delete)

bom_type                String(20), NOT NULL — enum: TECHNICAL, COMMERCIAL
part_number             String(100), NOT NULL
description             Text, NULLABLE
category                String(100), NULLABLE — grouping label (e.g., "Chassis", "Electronics")

quantity                Numeric(12,4), NOT NULL, default 1, CHECK > 0
quantity_from_field_id  Integer, FK → fields.id, NULLABLE
unit_of_measure         String(20), NULLABLE — e.g., "pcs", "m", "kg"
unit_price              Numeric(12,4), NULLABLE — required for COMMERCIAL, rejected for TECHNICAL

sequence                Integer, NOT NULL, default 0 — ordering among siblings
```

**Relationships:**

- `entity_version` → Many-to-one with `EntityVersion` (cascade delete from version)
- `parent` → Many-to-one self-referential (cascade delete children)
- `children` → One-to-many self-referential
- `quantity_field` → Many-to-one with `Field` (SET NULL on field deletion — falls back to static quantity)
- `rules` → One-to-many with `BOMItemRule` (cascade delete)

**Indexes:**

- `ix_bom_version` on `entity_version_id` (list queries)
- `ix_bom_parent` on `parent_bom_item_id` (tree building)

### 3.2 BOMItemRule

```
Table: bom_item_rules

id                      Integer, PK, auto-increment
bom_item_id             Integer, FK → bom_items.id, NOT NULL (cascade delete)
entity_version_id       Integer, FK → entity_versions.id, NOT NULL

conditions              JSON, NOT NULL — same format: {"criteria": [{...}, ...]}
description             Text, NULLABLE
```

**Indexes:**

- `ix_bomrule_item` on `bom_item_id` (rule lookup per item)
- `ix_bomrule_version` on `entity_version_id` (batch loading + clone queries)

### 3.3 Configuration changes

Add one column to the `configurations` table:

```
bom_total_price         Numeric(12,4), NULLABLE, indexed
```

Add index `ix_bom_total_price` on `bom_total_price` for query support.

### 3.4 ER relationships (additions only)

```
EntityVersion ||--o{ BOMItem : "contains"
BOMItem ||--o{ BOMItemRule : "governed by"
BOMItem ||--o{ BOMItem : "parent of"
BOMItem }o--o| Field : "quantity from (optional)"
```

---

## 4. Cached Data Models

Add frozen dataclasses to `app/core/cache.py` for session-independent caching:

```python
@dataclass(frozen=True)
class CachedBOMItem:
    id: int
    entity_version_id: int
    parent_bom_item_id: int | None
    bom_type: str
    part_number: str
    description: str | None
    category: str | None
    quantity: Decimal
    quantity_from_field_id: int | None
    unit_of_measure: str | None
    unit_price: Decimal | None
    sequence: int


@dataclass(frozen=True)
class CachedBOMItemRule:
    id: int
    bom_item_id: int
    entity_version_id: int
    conditions: dict
    description: str | None
```

Update `VersionData` to include BOM data:

```python
@dataclass(frozen=True)
class VersionData:
    fields: list[CachedField]
    values: list[CachedValue]
    rules: list[CachedRule]
    bom_items: list[CachedBOMItem]
    bom_item_rules: list[CachedBOMItemRule]
```

This change requires updating `_load_version_data()` in `RuleEngineService` to also query and convert `BOMItem` and `BOMItemRule` records.

---

## 5. API Endpoints

### 5.1 BOM Item CRUD

All BOM item mutations follow the **DRAFT-only policy** (same as fields, values, and rules).

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/bom-items?entity_version_id={id}` | List BOM items for a version | ADMIN, AUTHOR |
| GET | `/bom-items/{id}` | Read single BOM item | ADMIN, AUTHOR |
| POST | `/bom-items` | Create BOM item (DRAFT only) | ADMIN, AUTHOR |
| PATCH | `/bom-items/{id}` | Update BOM item (DRAFT only) | ADMIN, AUTHOR |
| DELETE | `/bom-items/{id}` | Delete BOM item + children (DRAFT only) | ADMIN, AUTHOR |

**CRUD validations (create and update):**

| Validation | Rule |
|------------|------|
| Version status | Must be DRAFT (HTTP 409 otherwise) |
| `bom_type` = `TECHNICAL` | `unit_price` must be null (HTTP 400) |
| `bom_type` = `COMMERCIAL` | `unit_price` must be non-null (HTTP 400) |
| `bom_type` = `COMMERCIAL` | `parent_bom_item_id` must be null — commercial items are root-level only (HTTP 400). See Section 2.5. |
| `quantity` | Must be > 0 (HTTP 400) |
| `quantity_from_field_id` (if set) | Must reference a `Field` in the same `entity_version_id` with `data_type = NUMBER` (HTTP 400) |
| `parent_bom_item_id` (if set) | Must reference a `BOMItem` in the same `entity_version_id` (HTTP 400) |
| `parent_bom_item_id` (if set) | Must not create a circular reference (HTTP 400) |
| `unit_price` (COMMERCIAL) | Must match existing COMMERCIAL items with same `part_number` in the same version (HTTP 409). See Section 2.8. |

### 5.2 BOM Item Rule CRUD

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | `/bom-item-rules?bom_item_id={id}` | List rules for a BOM item | ADMIN, AUTHOR |
| GET | `/bom-item-rules?entity_version_id={id}` | List all BOM rules for a version | ADMIN, AUTHOR |
| POST | `/bom-item-rules` | Create BOM item rule (DRAFT only) | ADMIN, AUTHOR |
| PATCH | `/bom-item-rules/{id}` | Update BOM item rule (DRAFT only) | ADMIN, AUTHOR |
| DELETE | `/bom-item-rules/{id}` | Delete BOM item rule (DRAFT only) | ADMIN, AUTHOR |

**CRUD validations:**

| Validation | Rule |
|------------|------|
| Version status | Must be DRAFT (HTTP 409) |
| `bom_item_id` | Must reference a `BOMItem` in the same `entity_version_id` (HTTP 400) |
| `conditions.criteria[].field_id` | Each must reference a `Field` in the same `entity_version_id` (HTTP 400) |

### 5.3 Calculation Response Changes

The `CalculationResponse` schema is extended with BOM output:

```python
class BOMLineItem(BaseModel):
    bom_item_id: int
    bom_type: str                         # "TECHNICAL", "COMMERCIAL"
    part_number: str
    description: str | None
    category: str | None
    quantity: Decimal
    unit_of_measure: str | None
    unit_price: Decimal | None            # null for TECHNICAL
    line_total: Decimal | None            # quantity × unit_price, null for TECHNICAL
    children: list["BOMLineItem"]         # nested sub-assembly items (TECHNICAL only)


class BOMOutput(BaseModel):
    technical: list[BOMLineItem]          # items where bom_type = TECHNICAL (hierarchical)
    commercial: list[BOMLineItem]         # items where bom_type = COMMERCIAL (flat, no children)
    commercial_total: Decimal | None      # sum of line_total for commercial items


class CalculationResponse(BaseModel):
    entity_id: int
    fields: list[FieldOutputState]
    is_complete: bool
    generated_sku: str | None
    bom: BOMOutput | None                 # null if no BOM items defined for version
```

TECHNICAL items form a hierarchical tree (sub-assemblies). COMMERCIAL items are always root-level with no children — `commercial` is a flat list. The `commercial_total` is the sum of all `line_total` values in the `commercial` list.

### 5.4 Configuration Response Changes

The `ConfigurationRead` schema gains the persisted field:

```python
class ConfigurationRead(BaseModel):
    # ... existing fields ...
    bom_total_price: Decimal | None       # cached commercial BOM total
```

---

## 6. Engine Integration

### 6.1 Position in the evaluation flow

BOM evaluation happens **after** the existing waterfall, once the full running context is available:

```
Waterfall (per field):
  1. VISIBILITY
  2. CALCULATION
  3. EDITABILITY
  4. AVAILABILITY
  5. MANDATORY
  6. VALIDATION

Post-waterfall:
  7. is_complete check
  8. SKU generation
  9. BOM evaluation    ← NEW
```

### 6.2 BOM evaluation algorithm

```
Input:
  - running_context: dict[int, Any]         (field_id → final value, from waterfall)
  - bom_items: list[CachedBOMItem]          (all items for the version)
  - bom_item_rules: list[CachedBOMItemRule] (all BOM rules for the version)
  - type_map: dict[int, str]                (field_id → data_type, from waterfall)

Algorithm:

  1. BUILD INDEX
     - rules_by_bom_item: dict[int, list[CachedBOMItemRule]]
       Group bom_item_rules by bom_item_id for O(1) lookup.

  2. EVALUATE INCLUSION (flat pass)
     For each bom_item:
       rules = rules_by_bom_item.get(bom_item.id, [])
       if no rules:
         included = True                      # unconditional item
       else:
         included = any(
           _evaluate_rule(rule.conditions, running_context, type_map)
           for rule in rules
         )                                     # OR logic across rules

     Result: included_set: set[int]            # set of included bom_item IDs

  3. RESOLVE QUANTITIES
     For each included bom_item:
       if bom_item.quantity_from_field_id is not None:
         field_value = running_context.get(bom_item.quantity_from_field_id)
         if field_value is not None and Decimal(field_value) > 0:
           resolved_quantity = Decimal(field_value)
         elif field_value is not None and Decimal(field_value) <= 0:
           remove from included_set            # non-positive quantity → exclude
           continue
         else:
           resolved_quantity = bom_item.quantity  # fallback to static
       else:
         resolved_quantity = bom_item.quantity

  4. PRUNE TREE
     For each included bom_item with a parent_bom_item_id:
       if parent not in included_set:
         remove bom_item from included_set
     Repeat until stable (or iterate bottom-up from leaves — but simpler
     to iterate top-down: process items ordered by depth, excluding any
     whose parent was already excluded).

  5. AGGREGATE BY PART NUMBER
     - Group included items by (part_number, parent_bom_item_id, bom_type).
     - For each group with more than one item:
       - Sum resolved quantities.
       - Take unit_price, description, category, unit_of_measure, bom_type
         from the first item in sequence order.
       - Use the first item's id as the representative bom_item_id.
     - Replace the group with a single merged item.

  6. BUILD OUTPUT
     - Split items by bom_type into TECHNICAL and COMMERCIAL sets.
     - TECHNICAL: construct nested BOMLineItem trees from parent_bom_item_id.
     - COMMERCIAL: build flat list (no children — hierarchy is forbidden by CRUD).
     - Compute line_total = quantity × unit_price for COMMERCIAL items.
     - Compute commercial_total = sum of all line_total in commercial list.

  7. RETURN BOMOutput
```

### 6.3 Reused infrastructure

The following existing functions are reused **without modification**:

| Function | Used for |
|----------|----------|
| `_evaluate_rule(conditions, context, type_map)` | Evaluating each `BOMItemRule`'s conditions |
| `_check_criterion(criterion, context, type_map)` | Individual criterion checks within BOM rules |
| `_compare_strings()`, `_compare_numbers()`, `_compare_dates()` | Type-specific comparisons |
| `_build_index(items, key_extractor)` | Building `rules_by_bom_item` index |

No changes to the waterfall logic or existing rule evaluation are required.

---

## 7. Version Clone Impact

The `clone_version()` method in `VersioningService` must be extended to include BOM items and their rules.

### Cloning steps (after existing field/value/rule cloning):

```
1. Clone BOM Items
   - Iterate source version's BOM items ordered by depth (parents before children)
   - For each BOM item:
     a. Create a copy with entity_version_id = new_version.id
     b. Remap parent_bom_item_id using bom_item_map (old_id → new_id)
     c. Remap quantity_from_field_id using field_map (old_id → new_id)
     d. Store old_id → new_id in bom_item_map
     e. db.add() + db.flush() to get the new ID

2. Clone BOM Item Rules
   - For each BOM item rule in the source version:
     a. Remap bom_item_id using bom_item_map
     b. Remap field_ids inside conditions JSON using field_map
        (reuse existing _rewrite_conditions() method)
     c. Set entity_version_id = new_version.id
     d. db.add()
```

**Important**: `quantity_from_field_id` must be remapped through `field_map`. This is easy to overlook because it is not inside the `conditions` JSON — it is a direct column FK.

### Eager loading update

The `clone_version()` query must be extended to eager-load BOM data:

```python
db.query(EntityVersion).options(
    joinedload(EntityVersion.fields).joinedload(Field.values),
    joinedload(EntityVersion.rules),
    joinedload(EntityVersion.bom_items).joinedload(BOMItem.rules),  # add this
)
```

---

## 8. Configuration Lifecycle Impact

Every Configuration mutation that triggers a recalculation must also extract and persist `bom_total_price`.

### Affected endpoints:

| Endpoint | Change |
|----------|--------|
| `POST /configurations/` (create) | Extract `bom_total_price` from `CalculationResponse.bom.commercial_total` and store on record |
| `PATCH /configurations/{id}` (update data) | Same as create — recalculate and update `bom_total_price` |
| `POST /configurations/{id}/upgrade` | Same — recalculate with new version and update `bom_total_price` |
| `POST /configurations/{id}/clone` | Copy `bom_total_price` from source (same as `is_complete` and `generated_sku`) |
| `GET /configurations/{id}/calculate` | No persistence change — `bom_total_price` is in the `CalculationResponse.bom` output |

The pattern is identical to how `is_complete` and `generated_sku` are handled today. The implementation should follow the exact same code paths — look for where `calc_result.is_complete` and `calc_result.generated_sku` are assigned to the Configuration object and add `calc_result.bom.commercial_total` there.

---

## 9. Pydantic Schemas

### 9.1 BOM Item schemas (`app/schemas/bom_item.py`)

```python
# --- Input ---

class BOMItemCreate(BaseModel):
    entity_version_id: int
    parent_bom_item_id: int | None = None
    bom_type: str                          # "TECHNICAL", "COMMERCIAL"
    part_number: str
    description: str | None = None
    category: str | None = None
    quantity: Decimal = Decimal("1")
    quantity_from_field_id: int | None = None
    unit_of_measure: str | None = None
    unit_price: Decimal | None = None
    sequence: int = 0


class BOMItemUpdate(BaseModel):
    parent_bom_item_id: int | None = None
    bom_type: str | None = None
    part_number: str | None = None
    description: str | None = None
    category: str | None = None
    quantity: Decimal | None = None
    quantity_from_field_id: int | None = None
    unit_of_measure: str | None = None
    unit_price: Decimal | None = None
    sequence: int | None = None


# --- Output ---

class BOMItemRead(BaseModel):
    id: int
    entity_version_id: int
    parent_bom_item_id: int | None
    bom_type: str
    part_number: str
    description: str | None
    category: str | None
    quantity: Decimal
    quantity_from_field_id: int | None
    unit_of_measure: str | None
    unit_price: Decimal | None
    sequence: int

    model_config = ConfigDict(from_attributes=True)
```

### 9.2 BOM Item Rule schemas (`app/schemas/bom_item_rule.py`)

```python
class BOMItemRuleCreate(BaseModel):
    bom_item_id: int
    entity_version_id: int
    conditions: dict                       # {"criteria": [...]}
    description: str | None = None


class BOMItemRuleUpdate(BaseModel):
    conditions: dict | None = None
    description: str | None = None


class BOMItemRuleRead(BaseModel):
    id: int
    bom_item_id: int
    entity_version_id: int
    conditions: dict
    description: str | None

    model_config = ConfigDict(from_attributes=True)
```

### 9.3 Engine output schemas (extend `app/schemas/engine.py`)

```python
class BOMLineItem(BaseModel):
    bom_item_id: int
    bom_type: str                          # "TECHNICAL", "COMMERCIAL"
    part_number: str
    description: str | None
    category: str | None
    quantity: Decimal
    unit_of_measure: str | None
    unit_price: Decimal | None
    line_total: Decimal | None
    children: list["BOMLineItem"] = []     # TECHNICAL only; always empty for COMMERCIAL


class BOMOutput(BaseModel):
    technical: list[BOMLineItem]           # hierarchical tree
    commercial: list[BOMLineItem]          # flat list (no children)
    commercial_total: Decimal | None
```

---

## 10. Database Migration

A single Alembic migration creates the two tables and adds the column:

```python
# alembic/versions/xxx_add_bom_tables.py

def upgrade():
    # 1. bom_items table
    op.create_table(
        "bom_items",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("entity_version_id", sa.Integer, sa.ForeignKey("entity_versions.id"), nullable=False),
        sa.Column("parent_bom_item_id", sa.Integer, sa.ForeignKey("bom_items.id", ondelete="CASCADE"), nullable=True),
        sa.Column("bom_type", sa.String(20), nullable=False),
        sa.Column("part_number", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("quantity", sa.Numeric(12, 4), nullable=False, server_default="1"),
        sa.Column("quantity_from_field_id", sa.Integer, sa.ForeignKey("fields.id", ondelete="SET NULL"), nullable=True),
        sa.Column("unit_of_measure", sa.String(20), nullable=True),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=True),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_bom_version", "bom_items", ["entity_version_id"])
    op.create_index("ix_bom_parent", "bom_items", ["parent_bom_item_id"])

    # 2. bom_item_rules table
    op.create_table(
        "bom_item_rules",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("bom_item_id", sa.Integer, sa.ForeignKey("bom_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_version_id", sa.Integer, sa.ForeignKey("entity_versions.id"), nullable=False),
        sa.Column("conditions", sa.JSON, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
    )
    op.create_index("ix_bomrule_item", "bom_item_rules", ["bom_item_id"])
    op.create_index("ix_bomrule_version", "bom_item_rules", ["entity_version_id"])

    # 3. Add bom_total_price to configurations
    op.add_column("configurations", sa.Column("bom_total_price", sa.Numeric(12, 4), nullable=True))
    op.create_index("ix_bom_total_price", "configurations", ["bom_total_price"])


def downgrade():
    op.drop_index("ix_bom_total_price", table_name="configurations")
    op.drop_column("configurations", "bom_total_price")
    op.drop_table("bom_item_rules")
    op.drop_table("bom_items")
```

---

## 11. Seed Data

Update `seed_data.py` to include representative BOM items for the "Auto Insurance Gold" entity (or create a secondary example entity better suited to physical BOM, such as a laptop configurator). The seed should demonstrate:

- Root-level items (unconditional, always included)
- Conditional items (included only when specific field values are selected)
- Nested sub-assemblies (parent with children)
- Items with `quantity_from_field_id` (dynamic quantity from a numeric field)
- Both `bom_type` values (TECHNICAL, COMMERCIAL)
- Multiple `BOMItemRule` rows on one item (OR logic)
- Commercial pricing with computed totals

---

## 12. Testing Plan

All tests use the existing test infrastructure: `pytest` + `testcontainers` + in-memory DB fixtures. Tests must not break any existing test.

### 12.1 Unit Tests — BOM Evaluation Logic

Location: `tests/engine/test_bom_evaluation.py`

| Test | Description |
|------|-------------|
| `test_bom_item_no_rules_always_included` | BOM item with zero rules is present in output |
| `test_bom_item_single_rule_passes` | Item included when its one rule's conditions are met |
| `test_bom_item_single_rule_fails` | Item excluded when its one rule's conditions are not met |
| `test_bom_item_multiple_rules_or_logic` | Item included if any one of multiple rules passes |
| `test_bom_item_multiple_rules_all_fail` | Item excluded when all rules fail |
| `test_bom_item_criteria_and_logic` | All criteria within a single rule must pass (AND) |
| `test_bom_type_technical_in_technical_list` | TECHNICAL item appears only in `bom.technical` |
| `test_bom_type_commercial_in_commercial_list` | COMMERCIAL item appears in `bom.commercial` only |
| `test_bom_commercial_items_are_flat` | COMMERCIAL items have no children in output |
| `test_bom_same_part_both_types` | Same `part_number` as TECHNICAL and COMMERCIAL appears in both lists independently |
| `test_bom_line_total_calculation` | `line_total = quantity × unit_price` for commercial items |
| `test_bom_commercial_total` | `commercial_total` sums all commercial line totals |
| `test_bom_technical_no_pricing` | TECHNICAL items have `unit_price = null`, `line_total = null` |
| `test_bom_empty_version` | Version with no BOM items → `bom` is null in response |

### 12.2 Unit Tests — Quantity Resolution

Location: `tests/engine/test_bom_quantity.py`

| Test | Description |
|------|-------------|
| `test_static_quantity` | Uses `quantity` when `quantity_from_field_id` is null |
| `test_quantity_from_field_valid` | Reads quantity from referenced numeric field |
| `test_quantity_from_field_null_fallback` | Falls back to static when field value is null |
| `test_quantity_from_field_zero_excludes` | Item excluded when field value is 0 |
| `test_quantity_from_field_negative_excludes` | Item excluded when field value is negative |
| `test_quantity_from_field_decimal` | Decimal field values are supported |
| `test_quantity_from_hidden_field_fallback` | Falls back to static when referenced field is hidden |

### 12.3 Unit Tests — Tree Pruning

Location: `tests/engine/test_bom_tree.py`

| Test | Description |
|------|-------------|
| `test_nested_items_parent_included` | Parent included → children evaluated normally |
| `test_nested_items_parent_excluded` | Parent excluded → entire subtree excluded |
| `test_three_level_nesting` | Grandparent → Parent → Child cascade works |
| `test_sibling_independence` | Excluding one sibling does not affect others |
| `test_child_excluded_independently` | Child's own conditions can exclude it even if parent is included |
| `test_sequence_ordering_among_siblings` | Items ordered by `sequence` within each level |
| `test_nested_commercial_total` | Total price sums all levels of nested commercial items |

### 12.3b Unit Tests — Line Aggregation

Location: `tests/engine/test_bom_aggregation.py`

| Test | Description |
|------|-------------|
| `test_same_part_same_parent_same_type_aggregated` | Two items with same `part_number`, `parent_bom_item_id`, and `bom_type` produce one output line with summed quantity |
| `test_same_part_different_parents_not_aggregated` | Same `part_number` under different parents produces separate lines |
| `test_same_part_different_types_not_aggregated` | Same `part_number` as TECHNICAL and COMMERCIAL remain separate |
| `test_aggregated_line_total` | `line_total` = aggregated quantity × `unit_price` |
| `test_aggregated_commercial_total` | `commercial_total` reflects aggregated quantities |
| `test_aggregation_preserves_first_item_metadata` | `description`, `category`, `unit_of_measure` come from the first item by sequence |
| `test_three_items_same_part_aggregated` | Three items with same key aggregate into one line |
| `test_no_aggregation_when_unique_parts` | Items with distinct `part_number` remain separate (baseline) |

### 12.4 API Tests — BOM Item CRUD

Location: `tests/api/test_bom_items.py`

| Test Group | Tests |
|------------|-------|
| **Create** | Valid creation (both bom_types), DRAFT-only enforcement (409 on PUBLISHED/ARCHIVED), pricing validation by type, quantity > 0 validation, `quantity_from_field_id` must be NUMBER type, `quantity_from_field_id` must belong to same version, `parent_bom_item_id` must belong to same version, circular parent reference rejected, COMMERCIAL with non-null `parent_bom_item_id` rejected (400), COMMERCIAL price consistency (same part+price allowed, different price → 409) |
| **Read** | List by `entity_version_id`, read single item, 404 on missing |
| **Update** | Partial update, DRAFT-only enforcement, pricing validation on type change, parent change with cycle detection, COMMERCIAL with non-null `parent_bom_item_id` on update rejected (400), COMMERCIAL price conflict on update rejected (409) |
| **Delete** | Delete item, cascade deletes children, DRAFT-only enforcement |
| **RBAC** | ADMIN and AUTHOR can CRUD, USER gets 403 |

### 12.5 API Tests — BOM Item Rule CRUD

Location: `tests/api/test_bom_item_rules.py`

| Test Group | Tests |
|------------|-------|
| **Create** | Valid creation, DRAFT-only enforcement, `bom_item_id` must belong to same version, `field_id` in conditions must belong to same version |
| **Read** | List by `bom_item_id`, list by `entity_version_id`, read single |
| **Update** | Partial update, DRAFT-only enforcement, conditions validation |
| **Delete** | Delete rule, DRAFT-only enforcement |
| **RBAC** | ADMIN and AUTHOR can CRUD, USER gets 403 |

### 12.6 API Tests — Calculation Response with BOM

Location: `tests/api/test_engine_bom.py`

| Test | Description |
|------|-------------|
| `test_calculate_includes_bom` | Stateless `POST /engine/calculate` returns BOM output |
| `test_calculate_no_bom_items` | Version without BOM items → `bom: null` |
| `test_configuration_calculate_includes_bom` | `GET /configurations/{id}/calculate` returns BOM |
| `test_configuration_create_stores_bom_total` | `bom_total_price` persisted on create |
| `test_configuration_update_recalculates_bom_total` | `bom_total_price` updated on data change |
| `test_configuration_upgrade_recalculates_bom_total` | `bom_total_price` updated on version upgrade |
| `test_configuration_clone_copies_bom_total` | `bom_total_price` copied from source |

### 12.7 Integration Tests — Version Clone with BOM

Location: `tests/integration/test_clone_bom.py`

| Test | Description |
|------|-------------|
| `test_clone_copies_bom_items` | All BOM items present in cloned version |
| `test_clone_copies_bom_item_rules` | All BOM rules present with remapped IDs |
| `test_clone_remaps_parent_bom_item_id` | Parent references point to cloned items |
| `test_clone_remaps_quantity_from_field_id` | Field references point to cloned fields |
| `test_clone_remaps_conditions_field_ids` | `field_id` inside BOM rule conditions remapped |
| `test_clone_preserves_bom_type_and_pricing` | Types, prices, quantities preserved exactly |

### 12.8 Integration Tests — End-to-End BOM Workflow

Location: `tests/integration/test_bom_workflow.py`

| Test | Description |
|------|-------------|
| `test_full_bom_lifecycle` | Create version → add fields → add BOM items → add BOM rules → publish → calculate → verify BOM output |
| `test_bom_with_configuration_lifecycle` | Create config → verify `bom_total_price` → update data → verify recalculation → finalize → clone → verify copy |

### 12.9 Cache Tests

Location: extend `tests/engine/test_caching.py`

| Test | Description |
|------|-------------|
| `test_cache_includes_bom_data` | Cached `VersionData` contains `bom_items` and `bom_item_rules` |
| `test_draft_bom_not_cached` | BOM data for DRAFT versions is not cached |
| `test_bom_cache_invalidation_on_publish` | Archiving a version clears its cached BOM data |

### 12.10 Regression Safeguard

- Run the **full existing test suite** after implementation to verify no regressions.
- The `CalculationResponse` change (adding optional `bom` field) must be backward-compatible: existing tests that check `CalculationResponse` fields should continue to pass because `bom` defaults to `None`.
- The `ConfigurationRead` change (adding optional `bom_total_price` field) is similarly backward-compatible.

---

## 13. Documentation Maintenance

Every implementation step must be accompanied by corresponding documentation updates. Nothing ships without docs.

### 13.1 Files to update

| File | Changes |
|------|---------|
| `README.md` | Add BOM to Features section, update Domain Model diagram (ER), update Rule Evaluation Flow diagram (add BOM step), add BOM endpoints to API Overview table, update Project Structure tree |
| `docs/TESTING.md` | Add BOM test categories and descriptions |
| `docs/SECURITY_FEATURES.md` | Add RBAC notes for BOM endpoints (ADMIN/AUTHOR only) |
| `openapi.json` | Regenerate after all endpoints are implemented |
| `api.http` | Add BOM item and BOM rule example requests |
| `seed_data.py` | Document BOM demo data in inline comments |

### 13.2 Files to create

| File | Content |
|------|---------|
| `docs/ADR_BOM.md` | Architecture Decision Record summarizing the decisions in this document (single table, separate rule table, no expression parser for quantities, pricing constraints by type, hierarchical model) |

### 13.3 Code documentation standards

- All SQLAlchemy models must have class-level docstrings explaining relationships, constraints, and usage context (follow the style of existing models in `domain.py`).
- All Pydantic schemas must have field-level descriptions where the purpose is not self-evident.
- All router endpoints must have docstrings explaining behavior, access control, status constraints, and return values (follow the style of `configurations.py`).
- All service methods must have docstrings explaining the algorithm, parameters, return values, and side effects.
- Comments must be descriptive of what the code does and why. Do not use language that implies incremental changes (avoid words like "new", "added", "changed", "modified"). Describe the code as if it has always existed.

---

## 14. Development Plan

The implementation is divided into sequential phases. Each phase builds on the previous one and includes its own tests and documentation. Do not proceed to the next phase until the current one is green (all tests pass, no regressions).

### Phase 1: Database Foundation

**Goal**: Create the database schema and ORM models.

1. Add `BOMType` enum to `app/models/domain.py` (`TECHNICAL`, `COMMERCIAL`).
2. Add `BOMItem` model to `app/models/domain.py` with all columns, relationships, and indexes as specified in Section 3.1.
3. Add `BOMItemRule` model to `app/models/domain.py` with all columns, relationships, and indexes as specified in Section 3.2.
4. Add `bom_total_price` column to the `Configuration` model.
5. Add `bom_items` and `bom_item_rules` relationships to `EntityVersion`.
6. Add `rules` relationship to `BOMItem` (cascade delete).
7. Generate and review the Alembic migration (`alembic revision --autogenerate`).
8. Run the migration against a test database and verify tables/columns.
9. Run the full existing test suite to confirm no regressions.

### Phase 2: Cached Data Models

**Goal**: Extend the cache layer to include BOM data.

1. Add `CachedBOMItem` and `CachedBOMItemRule` frozen dataclasses to `app/core/cache.py`.
2. Update `VersionData` to include `bom_items` and `bom_item_rules` fields.
3. Update `_load_version_data()` in `RuleEngineService` to query, convert, and include BOM items and rules.
4. Update all places that construct `VersionData` (should only be `_load_version_data`).
5. Write cache tests (Section 12.9).
6. Run full test suite — existing cache tests must still pass.

### Phase 3: Pydantic Schemas

**Goal**: Define all input/output schemas for BOM.

1. Create `app/schemas/bom_item.py` with `BOMItemCreate`, `BOMItemUpdate`, `BOMItemRead`.
2. Create `app/schemas/bom_item_rule.py` with `BOMItemRuleCreate`, `BOMItemRuleUpdate`, `BOMItemRuleRead`.
3. Add `BOMLineItem`, `BOMOutput` to `app/schemas/engine.py`.
4. Add `bom: BOMOutput | None = None` to `CalculationResponse`.
5. Add `bom_total_price: Decimal | None = None` to `ConfigurationRead` (and `ConfigurationCloneResponse`).
6. Run full test suite — existing tests must still pass (all additions are optional/nullable).

### Phase 4: BOM Item CRUD Router

**Goal**: Implement CRUD endpoints for BOM items.

1. Create `app/routers/bom_items.py` with all endpoints (Section 5.1).
2. Implement DRAFT-only enforcement (reuse or follow the pattern from field/value/rule routers).
3. Implement all CRUD validations (pricing by type, quantity > 0, field reference validation, parent validation, cycle detection).
4. Register the router in `app/main.py`.
5. Write all CRUD tests (Section 12.4).
6. Run full test suite.

### Phase 5: BOM Item Rule CRUD Router

**Goal**: Implement CRUD endpoints for BOM item rules.

1. Create `app/routers/bom_item_rules.py` with all endpoints (Section 5.2).
2. Implement DRAFT-only enforcement.
3. Implement validations (bom_item reference, conditions field_id validation).
4. Register the router in `app/main.py`.
5. Write all CRUD tests (Section 12.5).
6. Run full test suite.

### Phase 6: BOM Evaluation Engine

**Goal**: Implement the BOM evaluation logic in the rule engine.

1. Add `_evaluate_bom()` method to `RuleEngineService` implementing the algorithm in Section 6.2.
2. Add `_resolve_bom_quantity()` helper for quantity resolution logic.
3. Add `_prune_bom_tree()` helper for parent-child cascade exclusion.
4. Add `_build_bom_output()` helper for constructing the nested `BOMOutput` response.
5. Call `_evaluate_bom()` in `calculate_state()` after SKU generation.
6. Include `bom` in the returned `CalculationResponse`.
7. Write all BOM evaluation unit tests (Sections 12.1, 12.2, 12.3).
8. Write calculation response tests (Section 12.6 — the stateless endpoint tests).
9. Run full test suite.

### Phase 6a: BOM Design Refactor — Remove `BOTH`, COMMERCIAL flat-only

**Goal**: Simplify the BOM type model to align with ERP/CPQ standards. Remove the `BOTH` enum value, enforce COMMERCIAL items as root-level only (no hierarchy), and adjust the aggregation key to `(part_number, parent_bom_item_id, bom_type)`.

1. Remove `BOTH` from `BOMType` enum in `app/models/domain.py`.
2. Replace `_validate_bom_type_conflict()` in `app/routers/bom_items.py` with a validation that rejects COMMERCIAL items with non-null `parent_bom_item_id` (HTTP 400).
3. Update pricing validation to remove the `BOTH` branch.
4. Update `_build_bom_output()` in `app/services/rule_engine.py`:
   - TECHNICAL items: build nested tree as before.
   - COMMERCIAL items: build flat list (no children).
5. Update `_aggregate_bom_items()`: change grouping key from `(part_number, parent_bom_item_id)` to `(part_number, parent_bom_item_id, bom_type)`.
6. Update all existing tests that reference `BOTH` to use separate TECHNICAL + COMMERCIAL items.
7. Add tests for the new COMMERCIAL-must-be-root validation.
8. Run `pytest` — full suite must pass.

### Phase 6b: BOM Line Aggregation

**Goal**: Aggregate BOM output lines by `part_number` within the same parent context.

1. Add `_aggregate_bom_items()` helper method to `RuleEngineService`.
   - Input: list of included items with resolved quantities.
   - Group by `(part_number, parent_bom_item_id, bom_type)`.
   - For each group: sum quantities, keep first item's metadata (`unit_price`, `description`, `category`, `unit_of_measure`, `bom_type`, `id`).
   - Return deduplicated list.
2. Call `_aggregate_bom_items()` in `_evaluate_bom()` after tree pruning (step 4) and before building output (step 6).
3. Write all aggregation unit tests (Section 12.3b).
4. Run full test suite — existing BOM tests must still pass (aggregation is transparent when all `part_number` values are unique).

### Phase 6c: COMMERCIAL Price Consistency Validation

**Goal**: Enforce that COMMERCIAL BOM items with the same `part_number` in the same version have identical `unit_price`. See Section 2.8.

1. Add `_validate_commercial_price_consistency()` helper to `app/routers/bom_items.py`:
   - Query existing COMMERCIAL `BOMItem` records in the same version with the same `part_number`.
   - If any exist with a different `unit_price`, raise HTTP 409.
   - On update, exclude the item being updated from the query.
2. Call the validation in create and update endpoints (only when `bom_type` is COMMERCIAL and `unit_price` is provided).
3. Write CRUD tests in `tests/api/test_bom_items.py`:
   - Same `part_number`, same price → allowed (aggregation use case).
   - Same `part_number`, different price → 409.
   - Different `part_number`, different price → allowed (independent items).
   - Update price to conflict → 409.
   - Update price to match → allowed.
   - TECHNICAL items with same `part_number` and different prices → allowed (no pricing on TECHNICAL).
4. Run `pytest` — full suite must pass.

### Phase 7: Configuration Lifecycle Integration

**Goal**: Persist `bom_total_price` and include BOM in configuration calculations.

1. Update `create_configuration()` to extract and store `bom_total_price` from calculation result.
2. Update `update_configuration()` to recalculate and store `bom_total_price` on data change.
3. Update `upgrade_configuration()` to recalculate and store `bom_total_price`.
4. Update `clone_configuration()` to copy `bom_total_price` from source.
5. Verify `load_and_calculate_configuration()` returns BOM in response (should work automatically from Phase 6).
6. Write all configuration BOM tests (Section 12.6 — the configuration-specific tests).
7. Run full test suite.

### Phase 8: Version Clone

**Goal**: Extend version cloning to include BOM data.

1. Update eager loading query in `clone_version()` to include BOM items and rules.
2. Add BOM item cloning logic after existing rule cloning (with `bom_item_map` for ID remapping).
3. Add BOM item rule cloning logic (remap `bom_item_id` + rewrite `conditions` JSON).
4. Ensure `quantity_from_field_id` is remapped through `field_map`.
5. Ensure `parent_bom_item_id` is remapped through `bom_item_map` (process parents before children).
6. Write all clone tests (Section 12.7).
7. Run full test suite.

### Phase 9: Seed Data and Documentation

**Goal**: Update demo data and all documentation.

1. Update `seed_data.py` with BOM items and rules for the demo entity.
2. Update `README.md` (Features, Domain Model, Evaluation Flow, API Overview, Project Structure).
3. Update `docs/TESTING.md` with BOM test categories.
4. Update `docs/SECURITY_FEATURES.md` with BOM RBAC.
5. Create `docs/ADR_BOM.md`.
6. Update `api.http` with BOM example requests.
7. Regenerate `openapi.json`.
8. Run full test suite one final time.

### Phase 10: Integration Tests and Final Validation

**Goal**: End-to-end verification.

1. Write end-to-end BOM workflow tests (Section 12.8).
2. Run the full test suite with coverage: `pytest --cov=app --cov-report=html`.
3. Verify coverage on all BOM-related modules is > 90%.
4. Verify no regression on existing modules.
5. Review all documentation changes for accuracy and completeness.

---

## 15. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| `VersionData` change breaks existing cache tests | Medium | Phase 2 adds default empty lists; existing tests don't inspect `bom_items`/`bom_item_rules` |
| `CalculationResponse` change breaks existing API tests | Medium | `bom` is optional (`None` default); existing tests that don't assert on `bom` pass unchanged |
| Circular parent references in BOM items | Low | CRUD validation traverses parent chain before accepting; tested in Phase 4 |
| `quantity_from_field_id` not remapped during clone | High (silent data corruption) | Explicitly called out in Phase 8 step 4; dedicated test in Section 12.7 |
| Performance degradation with large BOM trees | Low | BOM evaluation is a single flat pass + in-memory tree pruning; data volumes are small (dozens of items) |

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **BOM** | Bill of Materials — list of components or line items derived from a configuration |
| **Technical BOM** | Physical parts list for manufacturing/assembly (no pricing) |
| **Commercial BOM** | Line items for quotes/invoices (with pricing) |
| **BOM Item** | A single entry in the BOM, optionally nested under a parent |
| **BOM Item Rule** | A condition set that governs whether a BOM item is included |
| **`bom_total_price`** | Sum of `line_total` for all COMMERCIAL items in the evaluated BOM |

## Appendix B: Related ADRs

- [ADR: Rule Expressions](ADR_RULE_EXPRESSIONS.md) — why single-field conditions only (applies to BOM rules too)
- [ADR: Inference Tree](ADR_INFERENCE_TREE.md) — waterfall model (BOM evaluates after the waterfall, not inside it)
- [ADR: Calculation Rules](ADR_CALCULATION_RULES.md) — static value mapping (same rationale for static BOM quantities)
- [ADR: Re-hydration](ADR_REHYDRATION.md) — raw inputs + recalculation strategy (BOM is recalculated on every read, `bom_total_price` is cached like `is_complete`)
