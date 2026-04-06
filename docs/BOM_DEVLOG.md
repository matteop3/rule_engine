# BOM Feature — Development Log

## Instructions for the Agent

You are implementing the BOM (Bill of Materials) feature for the rule engine. This devlog tracks progress across multiple sessions with limited context windows. **Read this file at the start of every session.**

### How to work

1. **Read this file first.** Check the "Current Status" section to understand where you are.
2. **Read the analysis document** `docs/BOM_ANALYSIS_AND_PLAN.md` — but only the sections relevant to your current phase. Each phase below tells you which sections to read.
3. **Read the context files** listed for your current phase. These are existing files whose patterns you must follow. Do not invent patterns — replicate what exists.
4. **Work on one phase at a time.** Do not start the next phase until the current one is fully complete (all checklist items done, all tests passing).
5. **Run the full test suite** (`pytest`) at the end of every phase to catch regressions. If tests fail, fix them before moving on.
6. **Update this devlog** before ending your session:
   - Check off completed items (`[x]`).
   - Update "Current Status".
   - Add a session entry to the "Session Log" at the bottom.

### Rules

- **No incremental-change language** in code comments, docstrings, or documentation. Do not write "New", "Added", "Modified", "Changed". Describe code as if it has always existed. Example: write "BOM evaluation step" not "New BOM evaluation step".
- **Every phase includes tests.** Do not skip tests or defer them.
- **Every phase includes documentation updates** where applicable.
- **Follow existing patterns exactly.** The codebase has consistent conventions for models, schemas, routers, tests, and dependencies. Read the context files and replicate their style.
- **Backward compatibility.** All schema additions must be optional/nullable so existing tests continue to pass without modification.
- When creating Alembic migrations, use `alembic revision --autogenerate -m "description"` and review the generated file before running it.

### Key project commands

```bash
# Run full test suite
pytest

# Run specific test file
pytest tests/engine/test_bom_evaluation.py

# Run tests with coverage
pytest --cov=app --cov-report=html

# Run linter and type checker
ruff check app/ tests/
mypy app/

# Generate Alembic migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

---

## Current Status

| Field | Value |
|-------|-------|
| **Current phase** | Complete — all 10 phases done |
| **Last completed phase** | Phase 10 (integration tests and final validation) |
| **Tests passing** | 929 passed (2026-04-06) |
| **Blocking issues** | None |

---

## Phase 1: Database Foundation

**Goal**: Create the database schema and ORM models.

**Analysis doc sections to read**: Section 3 (Domain Model), Section 10 (Database Migration).

**Context files to read** (study the patterns, then replicate):

| File | Why |
|------|-----|
| `app/models/domain.py` | All existing models, enums, AuditMixin, relationship patterns, docstring style. Your BOMItem and BOMItemRule models go here. |
| `alembic/versions/` (latest file) | Migration file pattern and naming convention. |

**Checklist:**

- [x] Add `BOMType` enum to `app/models/domain.py` with values `TECHNICAL`, `COMMERCIAL` ~~, `BOTH`~~ (`BOTH` removed in Phase 6a refactor)
- [x] Add `BOMItem` model to `app/models/domain.py`:
  - All columns as specified in analysis Section 3.1
  - Self-referential `parent_bom_item_id` FK with `ondelete="CASCADE"`
  - `quantity_from_field_id` FK with `ondelete="SET NULL"`
  - Relationships: `entity_version`, `parent`, `children`, `quantity_field`, `rules`
  - Indexes: `ix_bom_version`, `ix_bom_parent`
  - Class docstring following the style of existing models
- [x] Add `BOMItemRule` model to `app/models/domain.py`:
  - All columns as specified in analysis Section 3.2
  - `bom_item_id` FK with `ondelete="CASCADE"`
  - Relationships: `bom_item`, `entity_version`
  - Indexes: `ix_bomrule_item`, `ix_bomrule_version`
  - Class docstring following the style of existing models
- [x] Add `bom_total_price` column to `Configuration` model (`Numeric(12, 4)`, nullable, indexed)
- [x] Add `bom_items` relationship to `EntityVersion` (one-to-many, cascade delete)
- [x] Add `bom_item_rules` relationship to `EntityVersion` (one-to-many, cascade delete) — optional, evaluate if direct access from version is needed or if access through `BOMItem.rules` is sufficient. **Decision: skipped direct relationship on EntityVersion for BOMItemRule — access via BOMItem.rules is sufficient and avoids redundancy.**
- [x] Generate Alembic migration: `alembic revision --autogenerate -m "add bom tables and configuration bom total price"`
- [x] Review the generated migration file — verify it matches analysis Section 10
- [x] Run `pytest` — full existing test suite must pass with zero failures

---

## Phase 2: Cached Data Models

**Goal**: Extend the cache layer to include BOM data.

**Analysis doc sections to read**: Section 4 (Cached Data Models).

**Context files to read:**

| File | Why |
|------|-----|
| `app/core/cache.py` | Existing `CachedField`, `CachedValue`, `CachedRule`, `VersionData` frozen dataclasses. Add `CachedBOMItem` and `CachedBOMItemRule` following the same pattern. |
| `app/services/rule_engine.py` — method `_load_version_data()` (around line 146) | This is where version data is queried, converted to cached dataclasses, and stored. You must extend this method to also load BOM items and BOM item rules. |
| `tests/engine/test_cache.py` | Existing cache tests. Add BOM-specific cache tests in this file or a dedicated file. |

**Checklist:**

- [x] Add `CachedBOMItem` frozen dataclass to `app/core/cache.py`
- [x] Add `CachedBOMItemRule` frozen dataclass to `app/core/cache.py`
- [x] Add `bom_items: list[CachedBOMItem]` and `bom_item_rules: list[CachedBOMItemRule]` fields to `VersionData`
- [x] Update `_load_version_data()` in `app/services/rule_engine.py`:
  - Query `BOMItem` records for the version
  - Query `BOMItemRule` records for the version
  - Convert to cached dataclasses
  - Include in `VersionData` construction
- [x] Update all existing places that construct `VersionData` directly (search for `VersionData(` across the codebase — only in `_load_version_data`, confirmed)
- [x] Write cache tests: cached `VersionData` contains BOM data, DRAFT BOM not cached, invalidation clears BOM data
- [x] Run `pytest` — all existing cache tests must still pass

---

## Phase 3: Pydantic Schemas

**Goal**: Define all input/output schemas for BOM.

**Analysis doc sections to read**: Section 9 (Pydantic Schemas), Section 5.3 (Calculation Response Changes).

**Context files to read:**

| File | Why |
|------|-----|
| `app/schemas/field.py` | Pattern for `Create`, `Update`, `Read` schemas. Follow the same structure. |
| `app/schemas/rule.py` | Pattern for schemas with JSON conditions. Follow the same structure for BOM item rule schemas. |
| `app/schemas/engine.py` | `CalculationResponse`, `FieldOutputState`, `ValueOption`. You will add `BOMLineItem`, `BOMOutput` here and extend `CalculationResponse`. |
| `app/schemas/configuration.py` | `ConfigurationRead`, `ConfigurationCloneResponse`. You will add `bom_total_price` here. |
| `app/schemas/__init__.py` | Re-export hub. Register your schemas here. |

**Checklist:**

- [x] Create `app/schemas/bom_item.py` with `BOMItemCreate`, `BOMItemUpdate`, `BOMItemRead`
- [x] Create `app/schemas/bom_item_rule.py` with `BOMItemRuleCreate`, `BOMItemRuleUpdate`, `BOMItemRuleRead`
- [x] Add `BOMLineItem` and `BOMOutput` to `app/schemas/engine.py`
- [x] Add `bom: BOMOutput | None = None` to `CalculationResponse`
- [x] Add `bom_total_price: Decimal | None = None` to `ConfigurationRead` and `ConfigurationCloneResponse`
- [x] Register all schemas in `app/schemas/__init__.py`
- [x] Run `pytest` — all existing tests must pass (additions are optional/nullable, so backward-compatible)

---

## Phase 4: BOM Item CRUD Router

**Goal**: Implement CRUD endpoints for BOM items.

**Analysis doc sections to read**: Section 5.1 (BOM Item CRUD), Section 12.4 (API Tests — BOM Item CRUD).

**Context files to read:**

| File | Why |
|------|-----|
| `app/routers/fields.py` | CRUD router pattern with DRAFT-only enforcement, RBAC, dependency injection. Your BOM item router follows this pattern closely. |
| `app/routers/values.py` | Another CRUD router — useful for seeing the pattern for entities that belong to a parent (Values belong to Fields, BOM items belong to EntityVersions). |
| `app/routers/rules.py` | CRUD router with JSON conditions validation. Relevant for understanding how conditions are validated at creation time. |
| `app/dependencies/__init__.py` | Central re-export of all dependencies. You may need to add BOM-specific fetchers/validators here. |
| `app/dependencies/validators.py` | Existing validators (`validate_version_is_draft`, `get_editable_field`, etc.). Add BOM-specific validators following these patterns. |
| `app/dependencies/fetchers.py` | Existing fetchers (`fetch_field_by_id`, etc.). Add BOM-specific fetchers following these patterns. |
| `app/main.py` | Router registration. You must register the BOM item router here. |
| `tests/api/test_fields.py` | Test pattern for CRUD API tests. Follow this class structure and naming convention. |
| `tests/api/test_values.py` | Test pattern for child-entity CRUD. |

**Checklist:**

- [x] Create `app/routers/bom_items.py` with endpoints: list, read, create, update, delete
- [x] Implement DRAFT-only enforcement (HTTP 409 on PUBLISHED/ARCHIVED)
- [x] Implement RBAC (ADMIN and AUTHOR only, HTTP 403 for USER)
- [x] Implement pricing validation by `bom_type`:
  - TECHNICAL → `unit_price` must be null
  - COMMERCIAL → `unit_price` must be non-null
- [x] Implement `quantity > 0` validation
- [x] Implement `quantity_from_field_id` validation: field must exist in same version, `data_type = NUMBER`
- [x] Implement `parent_bom_item_id` validation: must exist in same version, no circular references
- [x] Implement cascade delete of children when parent is deleted
- [x] Add BOM-specific fetchers to `app/dependencies/fetchers.py` (e.g., `fetch_bom_item_by_id`)
- [x] Add BOM-specific validators to `app/dependencies/validators.py` (e.g., `get_editable_bom_item`)
- [x] Re-export from `app/dependencies/__init__.py`
- [x] Register router in `app/main.py`
- [x] Create `tests/api/test_bom_items.py` with tests for all CRUD operations, validations, and RBAC (30 tests)
- [x] Run `pytest` — full suite must pass (841 passed)

---

## Phase 5: BOM Item Rule CRUD Router

**Goal**: Implement CRUD endpoints for BOM item rules.

**Analysis doc sections to read**: Section 5.2 (BOM Item Rule CRUD), Section 12.5 (API Tests — BOM Item Rule CRUD).

**Context files to read:**

| File | Why |
|------|-----|
| `app/routers/rules.py` | Existing rule CRUD with conditions validation. The BOM item rule router is similar but simpler (no `target_field_id`, no `set_value`, no `error_message`). |
| `app/routers/bom_items.py` | Your Phase 4 output. BOM item rules depend on BOM items existing. |
| `tests/api/test_rules_crud.py` | Test pattern for rule CRUD tests. |

**Checklist:**

- [x] Create `app/routers/bom_item_rules.py` with endpoints: list (by `bom_item_id` and by `entity_version_id`), read, create, update, delete
- [x] Implement DRAFT-only enforcement
- [x] Implement RBAC (ADMIN and AUTHOR only)
- [x] Implement validation: `bom_item_id` must belong to specified `entity_version_id`
- [x] Implement validation: all `field_id` values inside `conditions.criteria` must belong to the same `entity_version_id`
- [x] Register router in `app/main.py`
- [x] Create `tests/api/test_bom_item_rules.py` with tests for all CRUD operations, validations, and RBAC (28 tests)
- [x] Run `pytest` — full suite must pass (869 passed)

---

## Phase 6: BOM Evaluation Engine

**Goal**: Implement the BOM evaluation logic in the rule engine.

**Analysis doc sections to read**: Section 6 (Engine Integration), Section 12.1 (BOM Evaluation Logic tests), Section 12.2 (Quantity Resolution tests), Section 12.3 (Tree Pruning tests).

**Context files to read:**

| File | Why |
|------|-----|
| `app/services/rule_engine.py` | The entire file. You must understand the waterfall flow, `calculate_state()`, `_evaluate_rule()`, `_any_rule_passes()`, `_build_index()`, `_generate_sku()`, and `_check_completeness()`. Your BOM evaluation goes after `_generate_sku()` in `calculate_state()`. |
| `app/schemas/engine.py` | `CalculationResponse` — you will populate the `bom` field here. |
| `tests/engine/test_logic.py` | Engine test patterns — how to set up fields, values, rules, and invoke the engine in tests. |
| `tests/engine/test_calculation.py` | CALCULATION rule tests — similar structure to what you need for BOM evaluation tests. |
| `tests/engine/test_sku_generation.py` | SKU tests — similar output-layer testing pattern. |
| `tests/fixtures/engine.py` | Engine test fixtures. You may need to add BOM-specific fixtures here. |

**Checklist:**

- [x] Add `_evaluate_bom()` method to `RuleEngineService`:
  - Build rules-by-bom-item index (reuse `_build_index()`)
  - Evaluate inclusion for each BOM item (reuse `_evaluate_rule()` with OR logic)
  - Resolve quantities (static or from field)
  - Prune tree (excluded parent → excluded subtree)
  - Build nested `BOMOutput` response
  - Compute `line_total` and `commercial_total`
- [x] Add helper methods: `_resolve_bom_quantity()`, `_prune_bom_tree()`, `_build_bom_output()`
- [x] Call `_evaluate_bom()` in `calculate_state()` after `_generate_sku()`
- [x] Include `bom` in the returned `CalculationResponse`
- [x] Create `tests/engine/test_bom_evaluation.py` — inclusion/exclusion, OR logic, AND logic, bom_type filtering, line totals, commercial total, empty version
- [x] Create `tests/engine/test_bom_quantity.py` — static quantity, field reference, null fallback, zero/negative exclusion, decimal support, hidden field fallback
- [x] Create `tests/engine/test_bom_tree.py` — parent/child cascade, three-level nesting, sibling independence, sequence ordering, nested totals
- [x] Run `pytest` — full suite must pass (896 passed)

---

## Phase 6a: BOM Design Refactor — Remove `BOTH`, COMMERCIAL flat-only

**Goal**: Simplify the BOM type model to align with ERP/CPQ standards. Remove the `BOTH` enum value, enforce COMMERCIAL items as root-level only (no hierarchy), and adjust the aggregation key to `(part_number, parent_bom_item_id, bom_type)`. This phase replaces the previous 6a (bom_type conflict validation) and 6b (aggregation) which were designed around the old `BOTH`-based model.

**Analysis doc sections to read**: Section 2.1 (enum rationale), Section 2.4 (pricing rules), Section 2.5 (hierarchy — COMMERCIAL flat-only), Section 2.6 (aggregation key), Section 5.1 (CRUD validations), Section 6.2 (algorithm steps 5–6), Section 12.1 (evaluation tests), Section 12.3b (aggregation tests), Section 12.4 (CRUD tests).

**Context files to read:**

| File | Why |
|------|-----|
| `app/models/domain.py` | `BOMType` enum — remove `BOTH` value. |
| `app/routers/bom_items.py` | Remove `_validate_bom_type_conflict()`, remove `BOTH` from pricing validation, add COMMERCIAL-must-be-root validation. |
| `app/services/rule_engine.py` | `_build_bom_output()` — split by type at every level, COMMERCIAL list is flat. `_aggregate_bom_items()` — change grouping key to include `bom_type`. |
| `app/schemas/engine.py` | `BOMLineItem`, `BOMOutput` — update docstrings/comments. |
| `tests/engine/test_bom_evaluation.py` | Update tests that use `BOTH` to use separate TECHNICAL + COMMERCIAL items. |
| `tests/engine/test_bom_tree.py` | Update tests referencing `BOTH`. |
| `tests/engine/test_bom_aggregation.py` | Rewrite: key now includes `bom_type`, add test for same part different types not aggregated. |
| `tests/api/test_bom_items.py` | Replace bom_type conflict tests with COMMERCIAL-no-parent tests. |

**Checklist:**

- [x] Remove `BOTH` from `BOMType` enum in `app/models/domain.py`
- [x] Update `_validate_pricing_by_type()` in `app/routers/bom_items.py`: remove `BOTH` branch (only TECHNICAL and COMMERCIAL) — already clean, `else` branch covers COMMERCIAL only now
- [x] Remove `_validate_bom_type_conflict()` from `app/routers/bom_items.py` and all calls to it in create/update endpoints
- [x] Add COMMERCIAL-must-be-root validation to create and update endpoints: if `bom_type` is COMMERCIAL and `parent_bom_item_id` is not null, return HTTP 400
- [x] Update `_aggregate_bom_items()` in `app/services/rule_engine.py`: change grouping key from `(part_number, parent_bom_item_id)` to `(part_number, parent_bom_item_id, bom_type)`
- [x] Update `_build_bom_output()` in `app/services/rule_engine.py`:
  - TECHNICAL items: build nested tree from `parent_bom_item_id` (as before)
  - COMMERCIAL items: build flat list (no children — guaranteed by CRUD)
  - Split happens by `bom_type` attribute, not by root-only filtering
- [x] Update `_sum_line_totals()` or simplify: commercial list is flat, so recursive sum is just a flat sum — kept recursive method (still correct), updated calling comment
- [x] Update all engine tests that reference `BOTH`:
  - `tests/engine/test_bom_evaluation.py` — replaced `BOTH` coating with separate TECHNICAL + COMMERCIAL items
  - `tests/engine/test_bom_tree.py` — converted entire fixture from COMMERCIAL hierarchy to TECHNICAL hierarchy
  - `tests/engine/test_bom_aggregation.py` — updated grouping key tests, added `test_same_part_different_types_not_aggregated`, converted different-parents test to TECHNICAL
  - `tests/engine/test_cache.py` — updated `_create_version_with_bom()` fixture from `BOTH` to `COMMERCIAL`
- [x] Update CRUD tests in `tests/api/test_bom_items.py`:
  - Removed 7 bom_type conflict tests (including `test_create_both_bom_item`)
  - Added 5 tests: COMMERCIAL with non-null parent → 400, COMMERCIAL with null parent → allowed, TECHNICAL with parent → allowed, update to COMMERCIAL with parent → 400, update COMMERCIAL to TECHNICAL → allowed
- [x] Update `tests/fixtures/entities.py` if any fixtures use `BOTH` — no fixtures used `BOTH`, no changes needed
- [x] Update `app/schemas/engine.py` comments/docstrings to remove `BOTH` references — no `BOTH` references found, already clean
- [x] Update `app/models/domain.py` docstring and column comment to remove `BOTH` references
- [x] Run `pytest` — 908 passed, 0 failures

---

## Phase 6b: BOM Line Aggregation (verification)

**Goal**: Verify that aggregation works correctly with the refactored model. The `_aggregate_bom_items()` method and tests were updated in Phase 6a (refactor). This phase is a verification checkpoint — if all aggregation tests pass after Phase 6a, this phase is already complete.

**Checklist:**

- [x] Verify `tests/engine/test_bom_aggregation.py` passes with the updated grouping key `(part_number, parent_bom_item_id, bom_type)` — 8/8 passed
- [x] Verify `test_same_part_different_types_not_aggregated` exists and passes
- [x] Run `pytest` — 908 passed (aggregation tests verified in isolation, full suite confirmed in Phase 6a)

---

## Phase 6c: COMMERCIAL Price Consistency Validation

**Goal**: Enforce that COMMERCIAL BOM items with the same `part_number` in the same version have identical `unit_price`. Prevents silent price loss during aggregation.

**Analysis doc sections to read**: Section 2.8 (Price consistency), Section 5.1 (CRUD validations — new row), Section 12.4 (API Tests — updated Create/Update groups), Section 14 Phase 6c.

**Context files to read:**

| File | Why |
|------|-----|
| `app/routers/bom_items.py` | Add `_validate_commercial_price_consistency()` helper, wire into create and update endpoints. Follow the pattern of existing validation helpers. |
| `tests/api/test_bom_items.py` | Add price consistency tests to `TestCreateBOMItem` and `TestUpdateBOMItem`. |

**Checklist:**

- [x] Add `_validate_commercial_price_consistency()` helper to `app/routers/bom_items.py`:
  - Query existing COMMERCIAL `BOMItem` records in the same version with the same `part_number`
  - If any exist with a different `unit_price`, raise HTTP 409
  - On update, exclude the item being updated (`exclude_id` parameter)
- [x] Call the validation in `create_bom_item()` (when `unit_price` is provided — only COMMERCIAL items pass pricing validation with non-null price)
- [x] Call the validation in `update_bom_item()` (when `bom_type` or `unit_price` or `part_number` changes and effective type is COMMERCIAL)
- [x] Add tests to `tests/api/test_bom_items.py`:
  - Create: same `part_number`, same price → allowed
  - Create: same `part_number`, different price → 409
  - Create: different `part_number`, different price → allowed
  - Update: change price to conflict → 409
  - Update: change price to match → allowed
  - TECHNICAL items with same `part_number` and different prices → allowed (no pricing constraint)
- [x] Run `pytest` — 914 passed, 0 failures (908 + 6 new tests)

---

## Phase 7: Configuration Lifecycle Integration

**Goal**: Persist `bom_total_price` and include BOM in configuration calculations.

**Analysis doc sections to read**: Section 8 (Configuration Lifecycle Impact), Section 12.6 (Calculation Response with BOM tests).

**Context files to read:**

| File | Why |
|------|-----|
| `app/routers/configurations.py` | The entire file. Search for where `calc_result.is_complete` and `calc_result.generated_sku` are assigned to the Configuration record. Add `bom_total_price` in every one of those places. Key methods: `create_configuration`, `update_configuration`, `upgrade_configuration`, `clone_configuration`. |
| `tests/api/test_configurations_generated_sku.py` | Test pattern for cached derived values on Configuration. Your `bom_total_price` tests follow this exact pattern. |
| `tests/api/test_configurations_clone.py` | Clone tests — verify `bom_total_price` is copied. |
| `tests/api/test_configurations_upgrade.py` | Upgrade tests — verify `bom_total_price` is recalculated. |

**Checklist:**

- [x] Update `create_configuration()`: extract `bom.commercial_total` from calculation result, store as `bom_total_price`
- [x] Update `update_configuration()`: recalculate and store `bom_total_price` when data changes
- [x] Update `upgrade_configuration()`: recalculate and store `bom_total_price` on version upgrade
- [x] Update `clone_configuration()`: copy `bom_total_price` from source configuration
- [x] Verify `load_and_calculate_configuration()` returns BOM in response (works automatically from Phase 6)
- [x] Create `tests/api/test_engine_bom.py` with tests:
  - Stateless `POST /engine/calculate` returns BOM output
  - Version without BOM items → `bom: null`
  - `GET /configurations/{id}/calculate` returns BOM
  - `bom_total_price` persisted on create
  - `bom_total_price` updated on data change
  - `bom_total_price` updated on version upgrade
  - `bom_total_price` copied on clone
- [x] Run `pytest` — 921 passed, 0 failures

---

## Phase 8: Version Clone

**Goal**: Extend version cloning to include BOM data.

**Analysis doc sections to read**: Section 7 (Version Clone Impact), Section 12.7 (Version Clone with BOM tests).

**Context files to read:**

| File | Why |
|------|-----|
| `app/services/versioning.py` | The entire file, especially `clone_version()`. Study how `field_map` and `value_map` are built and used. You will add `bom_item_map` following the same pattern. Pay attention to `_rewrite_conditions()` — you will reuse it for BOM rule conditions. |
| `tests/integration/test_data_integrity_clone_remapping.py` | Clone remapping test pattern. Your BOM clone tests follow this pattern. |

**Checklist:**

- [x] Update eager loading query in `clone_version()` to include `EntityVersion.bom_items` and `BOMItem.rules`
- [x] Clone BOM items (parents before children — sort by depth or iterate with parent_id=None first):
  - Create `bom_item_map: dict[int, int]` for old_id → new_id
  - Remap `parent_bom_item_id` using `bom_item_map`
  - Remap `quantity_from_field_id` using `field_map`
  - Set `entity_version_id` = new version ID
- [x] Clone BOM item rules:
  - Remap `bom_item_id` using `bom_item_map`
  - Rewrite `conditions` JSON using `_rewrite_conditions()` with `field_map`
  - Set `entity_version_id` = new version ID
- [x] Create `tests/integration/test_clone_bom.py` with tests:
  - Clone copies all BOM items
  - Clone copies all BOM item rules with remapped IDs
  - `parent_bom_item_id` remapped correctly
  - `quantity_from_field_id` remapped correctly
  - `field_id` inside BOM rule conditions remapped
  - Types, prices, quantities preserved exactly
- [x] Run `pytest` — 927 passed, 0 failures

---

## Phase 9: Seed Data and Documentation

**Goal**: Update demo data and all documentation.

**Analysis doc sections to read**: Section 11 (Seed Data), Section 13 (Documentation Maintenance).

**Context files to read:**

| File | Why |
|------|-----|
| `seed_data.py` | Existing seed data structure. Add BOM items and rules following the same pattern. |
| `README.md` | Sections to update: Features, Domain Model (ER diagram), Rule Evaluation Flow diagram, API Overview table, Project Structure tree. |
| `docs/TESTING.md` | Add BOM test categories. |
| `docs/SECURITY_FEATURES.md` | Add RBAC notes for BOM endpoints. |
| `api.http` | Add BOM example requests following existing format. |

**Checklist:**

- [x] Update `seed_data.py`:
  - Add BOM items covering: unconditional root items, conditional items, nested sub-assemblies (TECHNICAL only), dynamic quantity from field, both `bom_type` values (TECHNICAL, COMMERCIAL), same `part_number` as TECHNICAL and COMMERCIAL, multiple rules on one item (OR logic), commercial pricing
- [x] Create `docs/ADR_BOM.md` — Architecture Decision Record summarizing key decisions (single table, separate rule table, no expression parser for quantities, pricing constraints by type, hierarchical model). Follow the style of existing ADRs (e.g., `docs/ADR_CALCULATION_RULES.md`).
- [x] Update `README.md`:
  - Features section: add BOM generation (technical + commercial)
  - Domain Model diagram: add BOMItem and BOMItemRule entities
  - Rule Evaluation Flow diagram: add BOM evaluation step after SKU
  - API Overview: add BOM Item and BOM Item Rule endpoint tables
  - Project Structure: add BOM-related files
  - Documentation section: add link to ADR_BOM.md
- [x] Update `docs/TESTING.md` with BOM test categories and descriptions
- [x] Update `docs/SECURITY_FEATURES.md` with BOM endpoint RBAC (ADMIN/AUTHOR only)
- [x] Update `api.http` with BOM item and BOM item rule example requests
- [x] Regenerate `openapi.json` (run the app and export from `/openapi.json`)
- [x] Run `pytest` — 927 passed, 0 failures

---

## Phase 10: Integration Tests and Final Validation

**Goal**: End-to-end verification and coverage check.

**Analysis doc sections to read**: Section 12.8 (End-to-End BOM Workflow tests), Section 12.10 (Regression Safeguard).

**Context files to read:**

| File | Why |
|------|-----|
| `tests/integration/test_integration_entity_lifecycle.py` | End-to-end lifecycle test pattern. Your BOM workflow test follows this structure. |
| `tests/integration/test_configuration_lifecycle_flow.py` | Configuration lifecycle flow pattern. Your BOM + configuration workflow test follows this structure. |

**Checklist:**

- [x] Create `tests/integration/test_bom_workflow.py`:
  - Full BOM lifecycle: create version → add fields → add BOM items → add BOM rules → publish → calculate → verify BOM output
  - BOM with configuration lifecycle: create config → verify `bom_total_price` → update data → verify recalculation → finalize → clone → verify copy
- [x] Run `pytest --cov=app --cov-report=term-missing`
- [x] Verify coverage on BOM-related modules (models, schemas, routers, engine) is > 90%:
  - `routers/bom_items.py` 97%, `routers/bom_item_rules.py` 100%
  - `schemas/bom_item.py` 100%, `schemas/bom_item_rule.py` 100%, `schemas/engine.py` 100%
  - `services/rule_engine.py` 93%, `services/versioning.py` 97%
  - `models/domain.py` 90%, overall 91%
- [x] Verify zero regressions on existing modules
- [x] Review all documentation for accuracy (README, ADR, TESTING.md, SECURITY_FEATURES.md, api.http)
- [x] Final `pytest` run — 929 passed, 0 failures

---

## Session Log

<!-- Add a brief entry after each work session. Format:
### Session N — YYYY-MM-DD
- **Phase**: X
- **Completed**: steps A, B, C
- **Blocked**: (if any)
- **Next**: step D
-->

### Session 1 — 2026-04-03
- **Phase**: 1
- **Completed**: All Phase 1 checklist items — BOMType enum, BOMItem model, BOMItemRule model, bom_total_price on Configuration, bom_items relationship on EntityVersion, Alembic migration generated and reviewed, 806 tests passing
- **Decisions**: Skipped direct `bom_item_rules` relationship on EntityVersion — access through `BOMItem.rules` is sufficient
- **Notes**: Migration also picked up a harmless index rename (`ix_generated_sku` → `ix_configurations_generated_sku`) and comment additions on existing `rules` columns
- **Next**: Phase 2 — Cached Data Models

### Session 2 — 2026-04-03
- **Phase**: 2
- **Completed**: All Phase 2 checklist items — CachedBOMItem and CachedBOMItemRule dataclasses, VersionData extended, _load_version_data queries BOM tables, 5 BOM cache tests added, 811 tests passing
- **Notes**: Verified VersionData is only constructed in one place (_load_version_data). Updated unpacking in calculate_state to include bom_items and bom_item_rules.
- **Next**: Phase 3 — Pydantic Schemas

### Session 3 — 2026-04-03
- **Phase**: 3
- **Completed**: All Phase 3 checklist items — BOMItemCreate/Update/Read, BOMItemRuleCreate/Update/Read (reuses RuleConditions for validated conditions), BOMLineItem + BOMOutput in engine.py, bom field on CalculationResponse, bom_total_price on ConfigurationRead, all schemas registered in __init__.py, 811 tests passing
- **Notes**: BOMItemRuleCreate/Update reuse `RuleConditions` from rule.py for consistent condition validation. ConfigurationCloneResponse inherits bom_total_price from ConfigurationRead automatically.
- **Next**: Phase 4 — BOM Item CRUD Router

### Session 4 — 2026-04-03
- **Phase**: 4
- **Completed**: All Phase 4 checklist items — BOM Item CRUD router with all 5 endpoints, DRAFT-only enforcement, RBAC, pricing/quantity/field/parent validations with cycle detection, cascade delete, BOM fetchers and validators in dependencies, router registered in main.py, 30 API tests, 841 total tests passing
- **Notes**: Added `draft_bom_item` fixture to entities.py. Also added fetchers/validators for BOMItemRule (needed in Phase 5).
- **Next**: Phase 5 — BOM Item Rule CRUD Router

### Session 5 — 2026-04-04
- **Phase**: 5
- **Completed**: All Phase 5 checklist items — BOM Item Rule CRUD router with 5 endpoints (list by bom_item_id/entity_version_id, read, create, update, delete), DRAFT-only enforcement, RBAC, bom_item-to-version ownership validation, conditions field_id validation, router registered in main.py, 28 API tests, 869 total tests passing
- **Notes**: List endpoint requires at least one filter parameter (bom_item_id or entity_version_id). Leveraged existing `RuleConditions` schema which enforces non-empty criteria — BOM item rules always require at least one criterion (unconditional inclusion is modeled by having zero BOMItemRule rows, not by empty criteria). Fetchers/validators from Phase 4 reused directly.
- **Next**: Phase 6 — BOM Evaluation Engine

### Session 6 — 2026-04-04
- **Phase**: 6
- **Completed**: All Phase 6 checklist items — `_evaluate_bom()` with inclusion evaluation (OR logic across rules, AND within criteria), `_resolve_bom_quantity()` with field reference and hidden-field fallback, `_prune_bom_tree()` for parent-child cascade, `_build_bom_output()` with nested tree construction and type splitting, `_sum_line_totals()` for recursive commercial total. 27 tests across 3 files (13 evaluation, 7 quantity, 7 tree), 896 total tests passing
- **Notes**: Reused `_build_index()` and `_evaluate_rule()` without modification. BOM evaluation returns `None` when no BOM items exist (backward-compatible). Hidden field detection uses `field_states` dict to check `is_hidden` flag before reading from `running_context`.
- **Next**: Phase 7 — Configuration Lifecycle Integration

### Session 7 — 2026-04-04
- **Phase**: 6a (original — now superseded)
- **Completed**: Implemented `_validate_bom_type_conflict()` helper, validation wired into create and update endpoints, 6 tests. 902 total tests passing.
- **Notes**: This work is superseded by the design refactor (see Session 9). The bom_type conflict validation will be removed and replaced with COMMERCIAL-must-be-root validation.

### Session 8 — 2026-04-04
- **Phase**: 6b (original — now superseded)
- **Completed**: Implemented `_aggregate_bom_items()` with grouping key `(part_number, parent_bom_item_id)`, 7 aggregation tests. 909 total tests passing.
- **Notes**: This work is partially superseded. The aggregation method stays but the grouping key changes to `(part_number, parent_bom_item_id, bom_type)`. Tests need updating.

### Session 9 — 2026-04-05
- **Phase**: Design review
- **Completed**: Reviewed BOM type model against ERP/CPQ standards (SAP, Oracle, Tacton). Three design decisions made:
  1. **Remove `BOTH` enum value** — a component appearing in both lists is modeled as two separate BOM items (TECHNICAL + COMMERCIAL) with the same `part_number`. This allows different metadata per context and aligns with standard practice.
  2. **COMMERCIAL items are root-level only** — no hierarchy for commercial BOM. The commercial BOM is a flat list of priced line items (quotes/invoices). Hierarchy is only meaningful for the technical BOM (manufacturing/assembly).
  3. **Aggregation key includes `bom_type`** — `(part_number, parent_bom_item_id, bom_type)` so TECHNICAL and COMMERCIAL items with the same part_number remain separate.
- **Impact on existing code**: Phase 6a (bom_type conflict validation) and Phase 6b (aggregation key) need rework. Phases 1–6 (core engine) are structurally sound — the refactor is localized to enum removal, one CRUD validation swap, and output building logic.
- **Documents updated**: `docs/BOM_ANALYSIS_AND_PLAN.md` (Sections 2.1, 2.4, 2.5, 2.6, 2.6b, 3.1, 5.1, 5.3, 6.2, 9, 11, 12, 14) and `docs/BOM_DEVLOG.md` (Phase 6a/6b rewritten, status updated).
- **Next**: Phase 6a (refactor) — implement the design changes

### Session 10 — 2026-04-05
- **Phase**: 6a (BOM design refactor)
- **Completed**: All Phase 6a checklist items — removed `BOTH` from `BOMType` enum, replaced `_validate_bom_type_conflict()` with `_validate_commercial_is_root()` in CRUD router, updated aggregation key to `(part_number, parent_bom_item_id, bom_type)`, refactored `_build_bom_output()` to build nested tree for TECHNICAL and flat list for COMMERCIAL, updated all engine/CRUD/cache tests. 908 tests passing.
- **Test changes**: Removed 8 tests (BOTH-related), added 7 tests (COMMERCIAL-must-be-root, same-part-different-types, nested-technical-no-pricing). Net: 909 → 908.
- **Files modified**: `app/models/domain.py`, `app/routers/bom_items.py`, `app/services/rule_engine.py`, `tests/engine/test_bom_evaluation.py`, `tests/engine/test_bom_tree.py`, `tests/engine/test_bom_aggregation.py`, `tests/engine/test_cache.py`, `tests/api/test_bom_items.py`
- **Next**: Phase 6b (verification) — confirm aggregation tests pass with refactored model

### Session 11 — 2026-04-05
- **Phase**: 6b (aggregation verification)
- **Completed**: All 3 checklist items — `test_bom_aggregation.py` 8/8 passed with updated grouping key, `test_same_part_different_types_not_aggregated` confirmed present and passing. Phase was a verification checkpoint only (no code changes — all work done in Phase 6a).
- **Next**: Phase 6c — COMMERCIAL Price Consistency Validation

### Session 12 — 2026-04-05
- **Phase**: Planning
- **Completed**: Identified edge case — COMMERCIAL items with same `part_number` but different `unit_price` cause silent price loss during aggregation. Added Phase 6c (COMMERCIAL price consistency CRUD validation) to analysis and devlog. Updated `docs/BOM_ANALYSIS_AND_PLAN.md`: Section 2.8 (price consistency), Section 5.1 (validation table), Section 12.4 (test specs), Section 14 (Phase 6c), Non-Goals (future BOM catalog note).
- **Next**: Phase 6c — implement price consistency validation

### Session 13 — 2026-04-05
- **Phase**: 6c (COMMERCIAL price consistency)
- **Completed**: All Phase 6c checklist items — `_validate_commercial_price_consistency()` helper, wired into create (when `unit_price` is non-null) and update (when type/price/part_number changes and effective type is COMMERCIAL), 6 tests (4 create + 2 update). 914 tests passing.
- **Files modified**: `app/routers/bom_items.py`, `tests/api/test_bom_items.py`
- **Next**: Phase 7 — Configuration Lifecycle Integration

### Session 14 — 2026-04-05
- **Phase**: 7 (Configuration Lifecycle Integration)
- **Completed**: All Phase 7 checklist items — `bom_total_price` extracted from `calc_result.bom.commercial_total` and persisted in `create_configuration`, `update_configuration`, `upgrade_configuration`; copied in `clone_configuration` (both ORM constructor and manual `ConfigurationCloneResponse` builder); `load_and_calculate_configuration` returns BOM automatically (no changes needed). 7 API tests in `tests/api/test_engine_bom.py`. 921 tests passing.
- **Files modified**: `app/routers/configurations.py`, `tests/api/test_engine_bom.py` (new)
- **Next**: Phase 8 — Version Clone

### Session 15 — 2026-04-06
- **Phase**: 8 (Version Clone)
- **Completed**: All Phase 8 checklist items — eager loading extended to include `EntityVersion.bom_items` and `BOMItem.rules`, BOM items cloned with `bom_item_map` (roots first, then children), `parent_bom_item_id` remapped via `bom_item_map`, `quantity_from_field_id` remapped via `field_map`, BOM item rules cloned with `bom_item_id` remapping and `_rewrite_conditions()` for condition field IDs. 6 integration tests in `tests/integration/test_clone_bom.py`. 927 tests passing.
- **Files modified**: `app/services/versioning.py`, `tests/integration/test_clone_bom.py` (new)
- **Next**: Phase 9 — Seed Data and Documentation

### Session 16 — 2026-04-06
- **Phase**: 9 (Seed Data and Documentation)
- **Completed**: All Phase 9 checklist items:
  - `seed_data.py`: 8 BOM items (5 TECHNICAL incl. nested sub-assembly + dynamic quantity, 3 COMMERCIAL incl. same part_number as TECHNICAL), 4 BOM item rules (incl. OR logic with 2 rules on one item), cleanup order updated for FK dependencies
  - `docs/ADR_BOM.md`: 8 decisions documented (single table, separate rule table, no expression parser, TECHNICAL hierarchy / COMMERCIAL flat, two-enum without BOTH, aggregation key, price consistency, waterfall position)
  - `README.md`: Features (BOM generation section), ER diagram (BOMItem + BOMItemRule entities), evaluation flow (BOM step after SKU), API overview (BOM endpoints table), project structure, documentation links, seed data table, test count, deep cloning mention
  - `docs/TESTING.md`: Directory structure (BOM test files), DRAFT-only policy table (BOM rows), test coverage sections (BOM CRUD, engine, clone), fixture list, statistics table
  - `docs/SECURITY_FEATURES.md`: BOM endpoint RBAC section with role matrix and constraints
  - `api.http`: BOM item CRUD examples (TECHNICAL + COMMERCIAL), BOM item rule CRUD examples
  - `openapi.json`: Regenerated (29 paths)
- **Files modified**: `seed_data.py`, `README.md`, `api.http`, `openapi.json`, `docs/ADR_BOM.md` (new), `docs/TESTING.md`, `docs/SECURITY_FEATURES.md`
- **Tests**: 927 passed, 0 failures (no new tests — documentation phase)
- **Next**: Phase 10 — Integration Tests and Final Validation

### Session 17 — 2026-04-06
- **Phase**: 10 (Integration Tests and Final Validation)
- **Completed**: All Phase 10 checklist items — `tests/integration/test_bom_workflow.py` with 2 end-to-end tests (full BOM lifecycle with hierarchical TECHNICAL + conditional COMMERCIAL items + dynamic quantity from field, and configuration lifecycle with bom_total_price tracking across create/update/finalize/clone), full coverage run (91% overall, all BOM modules > 90%), documentation review (README, ADR_BOM, TESTING.md, SECURITY_FEATURES.md, api.http all accurate), zero regressions. 929 tests passing.
- **Files created**: `tests/integration/test_bom_workflow.py`
- **BOM feature complete**: All 10 phases implemented and validated.
