# Price List Feature — Development Log

> **Source of truth**: [PRICE_LIST_ANALYSIS.md](PRICE_LIST_ANALYSIS.md)
> **Target**: ~30 minutes per phase. Each phase is self-contained and completable in a single Claude Code session.

## Current Status

| Field | Value |
|---|---|
| Current phase | Phase 4 — not started |
| Last completed phase | Phase 3 |
| Tests passing | 978 (all passing after Phase 3) |
| Blocking issues | None |

---

## Key Project Commands

```bash
# Tests (uses testcontainers — requires Docker running)
pytest -q                          # Run all tests
pytest tests/api/ -q               # API tests only
pytest tests/engine/ -q            # Engine tests only
pytest --cov=app --cov-report=html # Tests with coverage report

# Database migrations
alembic upgrade head               # Apply all migrations
alembic downgrade -1               # Rollback last migration
alembic revision --autogenerate -m "description"  # Generate new migration

# Code quality (must pass — enforced by CI)
ruff check .                       # Linter
ruff format .                      # Formatter
make check                         # All quality checks (lint + format + typecheck)

# Demo data & app
python seed_data.py                # Load demo data
make build                         # Rebuild and start Docker services
make openapi                       # Regenerate openapi.json
```

### CI Pipeline (`.github/workflows/ci.yml`)

The CI pipeline runs on every push/PR to `main` and enforces three checks:
1. **Lint & Format**: `ruff check .` + `ruff format --check .`
2. **Type Check**: `mypy app/`
3. **Test & Coverage**: `pytest --cov=app --cov-report=xml -q` + Codecov upload

All code produced in every phase **must pass all three CI checks**. Run `ruff check .`, `ruff format .`, and `mypy app/` locally before considering a phase complete.

### Test Suite Warning

**The full test suite takes ~10 minutes** (testcontainers spins up a real PostgreSQL instance). **Never run multiple test suite instances in parallel** — they compete for Docker resources and will fail or hang. Run the suite once, wait for it to finish, then iterate if needed. For faster feedback during development, run targeted subsets first (e.g., `pytest tests/engine/test_bom_evaluation.py -q`) and only run the full suite as a final validation at the end of the phase.

---

## How to Use This Devlog

### For the agent starting a new session

1. Read this file (`docs/PRICE_LIST_DEVLOG.md`) to find your current phase
2. Read the analysis (`docs/PRICE_LIST_ANALYSIS.md`) for full design context
3. Read the **Context Files** listed in your phase — these are the minimum files needed to understand the current state
4. Complete the **Checklist** items in order
5. Mark completed items with `[x]` and update the **Session History** at the bottom of your phase
6. Run the test suite to verify no regressions before marking the phase complete
7. Do NOT commit or push — the user handles git operations manually

### Phase status key

- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete

---

## Phase 1: Database Models and Migration

**Goal**: Create PriceList and PriceListItem SQLAlchemy models, add price_list_id/price_date/snapshot to Configuration, create Alembic migration.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — decisions #1, #2, #7, #16, #17, #20, #21
- `app/models/domain.py` — existing models, AuditMixin pattern, BOMItem for reference
- `app/database.py` — Base class, session setup
- `alembic/` — existing migrations for naming/structure conventions

**Checklist**:
- [x] Add `PriceList` model to `app/models/domain.py`:
  - `id` (int PK), `name` (String(100), unique), `description` (Text, nullable)
  - `valid_from` (Date, required), `valid_to` (Date, required, default `9999-12-31`)
  - `AuditMixin`
  - Relationship: `items` → PriceListItem (cascade all, delete-orphan)
- [x] Add `PriceListItem` model to `app/models/domain.py`:
  - `id` (int PK), `price_list_id` (int FK → price_lists)
  - `part_number` (String(100)), `description` (Text, nullable)
  - `unit_price` (Numeric(12,4), required)
  - `valid_from` (Date, required), `valid_to` (Date, required)
  - `AuditMixin`
  - Relationship: `price_list` → PriceList
  - Index on `(price_list_id, part_number)` for lookup performance
- [x] Modify `Configuration` model:
  - Add `price_list_id` (int FK → price_lists, nullable, `ondelete="SET NULL"`)
  - Add `price_date` (Date, nullable)
  - Add `snapshot` (JSON, nullable, comment: "Full CalculationResponse snapshot for FINALIZED configs")
  - Add relationship: `price_list` → PriceList
- [x] Create Alembic migration:
  - Create `price_lists` table
  - Create `price_list_items` table
  - Add `price_list_id`, `price_date`, `snapshot` columns to `configurations`
  - Remove `unit_price` column from `bom_items`
- [x] Verify migration runs forward and backward cleanly (upgrade + downgrade)
- [x] Update `app/models/domain.py` module docstring to mention new models

**Do NOT do in this phase**: schema changes, router changes, engine changes, test changes.

**Session History**:
| Date | Status | Notes |
|---|---|---|
| 2026-04-09 | Complete | Added PriceList, PriceListItem models; modified Configuration (price_list_id, price_date, snapshot); created migration with unit_price removal from bom_items; updated alembic env.py imports; 978 tests passing |

---

## Phase 2: Pydantic Schemas and PriceList CRUD Router

**Goal**: Create Pydantic schemas for PriceList and PriceListItem. Implement full CRUD for PriceList (header) with validation.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — decisions #6, #7, #9, #14
- `app/models/domain.py` — PriceList model (created in Phase 1)
- `app/schemas/bom_item.py` — schema pattern reference (Base/Create/Read/Update)
- `app/schemas/base_schema.py` — BaseSchema and AuditSchemaMixin
- `app/routers/bom_items.py` — router pattern reference (RBAC, validation, transactions)
- `app/dependencies/` — existing dependency injection patterns
- `app/main.py` — router registration

**Checklist**:
- [x] Create `app/schemas/price_list.py`:
  - `PriceListBase`: `name` (str, max_length=100), `description` (str | None), `valid_from` (date), `valid_to` (date, default 9999-12-31)
  - `PriceListCreate(PriceListBase)`: all fields from base
  - `PriceListRead(PriceListBase, AuditSchemaMixin)`: + `id` (int)
  - `PriceListUpdate(BaseSchema)`: all fields optional
  - Pydantic validator: `valid_from < valid_to`
- [x] Create `app/schemas/price_list_item.py`:
  - `PriceListItemBase`: `part_number` (str, max_length=100), `description` (str | None), `unit_price` (Decimal), `valid_from` (date | None = None), `valid_to` (date | None = None)
  - `PriceListItemCreate(PriceListItemBase)`: + `price_list_id` (int)
  - `PriceListItemRead(PriceListItemBase, AuditSchemaMixin)`: + `id`, `price_list_id`, with `valid_from` and `valid_to` as required (date)
  - `PriceListItemUpdate(BaseSchema)`: all fields optional
  - Pydantic validator: `valid_from < valid_to` (when both are present)
- [x] Create `app/routers/price_lists.py`:
  - `GET /price-lists` — list with `valid_at` filter (default: today), skip/limit pagination
  - `POST /price-lists` — create (ADMIN/AUTHOR only), validate `valid_from < valid_to`, unique name
  - `GET /price-lists/{id}` — get by ID
  - `PATCH /price-lists/{id}` — update header, validate dates, validate bounding box constraint (existing items must still fit within new dates)
  - `DELETE /price-lists/{id}` — delete with FINALIZED protection (query configs with this `price_list_id` and FINALIZED status → HTTP 409 if any exist)
- [x] Register router in `app/main.py`
- [x] Update `app/schemas/__init__.py` if it re-exports schemas

**Validation rules for PriceList**:
- `valid_from` must be strictly less than `valid_to`
- `name` must be unique (DB constraint handles this, return 409 on conflict)
- On PATCH: if changing dates, verify all existing PriceListItems still fall within the new bounding box. If not → HTTP 409 with details
- On DELETE: query `Configuration` for any FINALIZED config with this `price_list_id` → HTTP 409 if found

**Session History**:
| Date | Status | Notes |
|---|---|---|
| 2026-04-10 | Complete | Created PriceList/PriceListItem Pydantic schemas (Base/Create/Read/Update with validators); created price_lists router with full CRUD (GET list with valid_at filter, POST with unique name check, GET by ID, PATCH with bounding box validation, DELETE with FINALIZED protection); registered router in main.py; updated schemas __init__.py exports; 978 tests passing |

---

## Phase 3: PriceListItem CRUD Router

**Goal**: Implement full CRUD for PriceListItem with overlap validation, bounding box enforcement, and date defaulting.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — decisions #2, #16
- `app/models/domain.py` — PriceListItem model
- `app/routers/price_lists.py` — PriceList router (created in Phase 2)
- `app/routers/bom_items.py` — CRUD pattern reference
- `app/main.py` — router registration

**Checklist**:
- [x] Create `app/routers/price_list_items.py`:
  - `GET /price-list-items?price_list_id={id}` — list items, skip/limit pagination, ADMIN/AUTHOR only
  - `GET /price-list-items/{id}` — get by ID
  - `POST /price-list-items` — create item (ADMIN/AUTHOR only)
  - `PATCH /price-list-items/{id}` — update item
  - `DELETE /price-list-items/{id}` — delete item
- [x] Implement date defaulting on create:
  - If `valid_from` is null → use parent PriceList's `valid_from`
  - If `valid_to` is null → use parent PriceList's `valid_to`
- [x] Implement bounding box validation:
  - `item.valid_from >= price_list.valid_from`
  - `item.valid_to <= price_list.valid_to`
  - Enforced on both CREATE and UPDATE
  - HTTP 400 with descriptive message on violation
- [x] Implement overlap validation:
  - For a given `(price_list_id, part_number)`, no two items may have overlapping date ranges
  - Overlap check: `a.valid_from < b.valid_to AND b.valid_from < a.valid_to`
  - On CREATE: check against all existing items with same `(price_list_id, part_number)`
  - On UPDATE: check against all existing items with same `(price_list_id, part_number)` excluding self
  - HTTP 409 with descriptive message on overlap
- [x] Validate `unit_price > 0`
- [x] Register router in `app/main.py`

**Session History**:
| Date | Status | Notes |
|---|---|---|
| 2026-04-10 | Complete | Created price_list_items router with full CRUD (GET list with price_list_id filter, GET by ID, POST with date defaulting from header, PATCH, DELETE); bounding box validation on CREATE/UPDATE (HTTP 400); overlap validation on CREATE/UPDATE with self-exclusion (HTTP 409); unit_price > 0 validation; registered in main.py; 978 tests passing |

---

## Phase 4: Engine Price Resolution

**Goal**: Modify the rule engine to resolve prices from the price list instead of BOMItem. Add warnings to BOMOutput.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — decisions #3, #5, #10, #11, #19
- `app/services/rule_engine.py` — `_build_bom_output()` (line ~1150), `_sum_line_totals()`, `calculate_state()`
- `app/schemas/engine.py` — `CalculationRequest`, `BOMOutput`, `BOMLineItem`
- `app/core/cache.py` — `CachedBOMItem` (has `unit_price` field to remove)
- `app/models/domain.py` — PriceList, PriceListItem models

**Checklist**:
- [ ] Update `CalculationRequest` in `app/schemas/engine.py`:
  - Add `price_list_id: int | None = None`
  - Add `price_date: date | None = None` (import date from datetime)
- [ ] Update `BOMOutput` in `app/schemas/engine.py`:
  - Add `warnings: list[str] = []`
- [ ] Remove `unit_price` from `CachedBOMItem` in `app/core/cache.py`
- [ ] Update `calculate_state()` in `app/services/rule_engine.py`:
  - Accept `price_list_id` and `price_date` from the request
  - If `price_list_id` is provided, load the PriceList header and validate:
    - PriceList exists → 404 if not
    - `price_date` defaults to `date.today()` if not provided
    - PriceList is valid at `price_date` (`valid_from <= price_date <= valid_to`) → 422 if not
  - Pass price data to `_build_bom_output()`
- [ ] Create a `_resolve_prices()` method in `RuleEngineService`:
  - Input: `db` session, `price_list_id`, `price_date`, list of COMMERCIAL BOM part_numbers
  - Query `PriceListItem` where `price_list_id` matches AND `part_number` IN (part_numbers) AND `valid_from <= price_date <= valid_to`
  - Return a `dict[str, Decimal]` mapping `part_number → unit_price`
  - Note: this queries the DB directly (no cache — decision #10)
- [ ] Update `_build_bom_output()`:
  - Accept price map (`dict[str, Decimal] | None`) and price list name + price_date (for warning messages)
  - For COMMERCIAL items: look up `unit_price` from the price map
  - If not found → `unit_price = None`, `line_total = None`, add warning to list
  - For TECHNICAL items: no change (no pricing)
  - Pass warnings to BOMOutput
- [ ] Update `_sum_line_totals()`:
  - Sum all non-null `line_total` values (partial total, not null propagation)
  - Return `Decimal("0")` if no items have line_total (was already handling this)
- [ ] Remove `unit_price` mapping from the BOM item loading section (where `CachedBOMItem` is constructed, line ~262-275)
- [ ] Update `POST /engine/calculate` in `app/routers/engine.py`:
  - Pass `price_list_id` and `price_date` from request to engine service

**Key logic for `_build_bom_output()` change**:
```python
# Before (current):
line_total = quantity * item.unit_price if item.unit_price is not None else None

# After:
if item.bom_type == "COMMERCIAL" and price_map is not None:
    resolved_price = price_map.get(item.part_number)
    if resolved_price is None:
        # Add warning, price not found
        line_total = None
    else:
        line_total = quantity * resolved_price
else:
    resolved_price = None
    line_total = None
```

**Session History**:
| Date | Status | Notes |
|---|---|---|
| | | |

---

## Phase 5: Configuration Integration

**Goal**: Wire `price_list_id` and `price_date` into Configuration CRUD endpoints. Handle inheritance on clone/upgrade.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — decisions #5, #8, #13, #21
- `app/routers/configurations.py` — all endpoints (create, update, calculate, clone, upgrade, finalize)
- `app/schemas/configuration.py` — ConfigurationCreate, ConfigurationRead, ConfigurationUpdate
- `app/schemas/engine.py` — CalculationRequest (updated in Phase 4)
- `app/models/domain.py` — Configuration model (updated in Phase 1)

**Checklist**:
- [ ] Update `ConfigurationCreate` schema:
  - Add `price_list_id: int` (required)
- [ ] Update `ConfigurationRead` schema:
  - Add `price_list_id: int | None = None`
  - Add `price_date: date | None = None`
- [ ] Update `ConfigurationUpdate` schema:
  - Add `price_list_id: int | None = None` (allow changing the price list on a DRAFT)
- [ ] Update `create_configuration` endpoint:
  - Validate `price_list_id` references an existing PriceList
  - Pass `price_list_id` and `price_date=date.today()` to the CalculationRequest
  - Save `price_list_id` on the new Configuration
- [ ] Update `update_configuration` endpoint:
  - If `price_list_id` is in the update data, validate it references an existing PriceList
  - Pass `price_list_id` and `price_date=date.today()` to recalculation
- [ ] Update `load_and_calculate_configuration` endpoint:
  - For DRAFT configs: pass `price_list_id` from config and `price_date=date.today()` to recalculation
  - For FINALIZED configs: this will be handled in Phase 6 (snapshot)
  - If `price_list_id` is null → return 422 "Configuration has no price list assigned"
- [ ] Update `clone_configuration` endpoint:
  - Inherit `price_list_id` from source configuration
- [ ] Update `upgrade_configuration` endpoint:
  - Inherit `price_list_id` from current configuration
  - Pass `price_list_id` and `price_date=date.today()` to recalculation
- [ ] Update `finalize_configuration` endpoint:
  - Recalculate with `price_date=date.today()` (decision #8)
  - Save `price_date` on the configuration record
  - (Snapshot storage will be added in Phase 6)
- [ ] Update `list_configurations` endpoint:
  - Add optional `price_list_id` query filter

**Session History**:
| Date | Status | Notes |
|---|---|---|
| | | |

---

## Phase 6: Hybrid Rehydration (FINALIZED Snapshot)

**Goal**: Implement snapshot storage at finalization. Return snapshot directly for FINALIZED configuration reads.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — decision #17
- `docs/ADR_REHYDRATION.md` — current rehydration ADR (to be updated)
- `app/routers/configurations.py` — `finalize_configuration` and `load_and_calculate_configuration`
- `app/schemas/engine.py` — `CalculationResponse` (the schema to snapshot)
- `app/schemas/configuration.py` — ConfigurationRead
- `app/models/domain.py` — Configuration model (`snapshot` column added in Phase 1)

**Checklist**:
- [ ] Update `finalize_configuration` endpoint:
  - Before transitioning to FINALIZED, perform a full recalculation with `price_date=date.today()`
  - Serialize the `CalculationResponse` to dict (`result.model_dump(mode="json")`)
  - Store in `config.snapshot`
  - Save `price_date` on the configuration
  - Update `is_complete`, `generated_sku`, `bom_total_price` from the fresh calculation
- [ ] Update `load_and_calculate_configuration` endpoint:
  - If config status is FINALIZED and `snapshot` is not null → return snapshot directly (deserialize to `CalculationResponse`)
  - If config status is FINALIZED and `snapshot` is null → fall back to rehydration (backward compatibility for configs finalized before this feature)
  - If config status is DRAFT → rehydrate as before (with `price_list_id` and `price_date=date.today()`)
- [ ] Update `ADR_REHYDRATION.md`:
  - Change status from "Accepted" to "Amended"
  - Add a new "Amendment: Hybrid Rehydration for FINALIZED Configurations" section
  - Document the dilemma: pure rehydration vs snapshot vs immutable price lists
  - Explain why the hybrid approach was chosen (mutable price list + snapshot = structural guarantee)
  - Document that DRAFT configurations continue with pure rehydration
  - Keep the existing content intact, add the amendment as a new section

**Important**: the snapshot must include the full `CalculationResponse` — all fields, available_options, BOM with prices, SKU, warnings. The FINALIZED configuration is a self-contained document.

**Session History**:
| Date | Status | Notes |
|---|---|---|
| | | |

---

## Phase 7: BOM Cleanup (Remove `unit_price` from BOMItem)

**Goal**: Remove all traces of `unit_price` from BOMItem CRUD, schemas, cache, and versioning logic.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — decision #4
- `app/routers/bom_items.py` — `_validate_pricing_by_type()`, `_validate_commercial_price_consistency()`
- `app/schemas/bom_item.py` — BOMItemBase, BOMItemCreate, BOMItemUpdate, BOMItemRead
- `app/core/cache.py` — CachedBOMItem (already updated in Phase 4, verify)
- `app/services/versioning.py` — version cloning logic (line ~265, copies `unit_price`)
- `app/services/rule_engine.py` — BOM item loading (verify Phase 4 changes)

**Checklist**:
- [ ] Update `app/schemas/bom_item.py`:
  - Remove `unit_price` from `BOMItemBase`
  - Remove `unit_price` from `BOMItemUpdate`
  - Remove `unit_price` from `BOMItemRead`
- [ ] Update `app/routers/bom_items.py`:
  - Remove `_validate_pricing_by_type()` function entirely
  - Remove `_validate_commercial_price_consistency()` function entirely
  - Remove all calls to these functions in `create_bom_item` and `update_bom_item`
  - Remove the import of `Decimal` if no longer used
- [ ] Update `app/services/versioning.py`:
  - Remove `unit_price=old_bom_item.unit_price` from the clone mapping
- [ ] Verify `CachedBOMItem` in `app/core/cache.py` no longer has `unit_price` (done in Phase 4)
- [ ] Verify `_build_bom_output()` in `app/services/rule_engine.py` no longer reads `item.unit_price` (done in Phase 4)
- [ ] Update `app/models/domain.py`:
  - Remove `unit_price` field from `BOMItem` model
  - Update `BOMItem` docstring (remove pricing constraint documentation)
  - Update `BOMType` docstring (remove "requires unit_price" from COMMERCIAL description)
- [ ] Update `docs/ADR_BOM.md`:
  - Update decision #1 (remove mention of COMMERCIAL carrying pricing)
  - Update decision #5 (remove mention of pricing differences between types)
  - Update decision #7 (mark as superseded — price consistency now handled by price list)
  - Add a note pointing to `PRICE_LIST_ANALYSIS.md` for the new pricing design

**Session History**:
| Date | Status | Notes |
|---|---|---|
| | | |

---

## Phase 8: Seed Data and Fix Existing Tests

**Goal**: Update seed_data.py with a demo price list. Fix all existing tests broken by the removal of `unit_price` from BOMItem and the addition of `price_list_id` to Configuration/CalculationRequest.

**Context Files** (read these first):
- `seed_data.py` — current seed data (BOM section creates items with `unit_price`)
- `tests/conftest.py` — shared fixtures
- `tests/fixtures/` — all fixture files
- `tests/engine/test_bom_*.py` — BOM engine tests (these will break)
- `tests/api/test_bom_items.py` — BOM CRUD tests (these will break)
- `tests/api/test_engine_bom.py` — engine BOM API tests
- `tests/api/test_configurations_*.py` — configuration tests (need `price_list_id`)
- `tests/integration/test_bom_workflow.py`, `tests/integration/test_clone_bom.py`

**Checklist**:
- [ ] Update `seed_data.py`:
  - Import PriceList, PriceListItem models
  - Add cleanup for new tables (PriceListItem, PriceList — in FK order)
  - Create a demo price list: "Auto Insurance Price List 2026" with `valid_from=2026-01-01`, `valid_to=2026-12-31`
  - Create PriceListItem entries for all COMMERCIAL BOM part numbers used in the seed
  - Remove `unit_price` from all BOMItem creation calls
  - Update Configuration creation to include `price_list_id`
  - Update the summary table printed at the end
- [ ] Add a shared test fixture for creating a price list + items:
  - In `tests/conftest.py` or a new `tests/fixtures/price_lists.py`
  - Fixture: `price_list` — creates a PriceList with broad validity
  - Fixture: `price_list_item` — creates a PriceListItem for a given part_number
  - Helper: `create_price_list_with_items(db, items: dict[str, Decimal])` — batch creation
- [ ] Fix `tests/engine/test_bom_evaluation.py`:
  - Remove `unit_price` from BOMItem creation
  - Add price list setup where pricing is tested
  - Pass `price_list_id` to CalculationRequest where needed
- [ ] Fix `tests/engine/test_bom_aggregation.py` — same pattern
- [ ] Fix `tests/engine/test_bom_quantity.py` — same pattern
- [ ] Fix `tests/engine/test_bom_tree.py` — same pattern
- [ ] Fix `tests/engine/test_bom_edge_cases.py` — same pattern
- [ ] Fix `tests/api/test_bom_items.py`:
  - Remove unit_price from create/update payloads
  - Remove tests for pricing validation (type-based, consistency)
  - Adjust assertions that check for unit_price in responses
- [ ] Fix `tests/api/test_engine_bom.py` — add price list setup
- [ ] Fix `tests/api/test_configurations_*.py` — add `price_list_id` to configuration creation
- [ ] Fix `tests/integration/test_bom_workflow.py` — add price list setup
- [ ] Fix `tests/integration/test_clone_bom.py` — add price list setup
- [ ] Run full test suite — verify zero failures

**This is the largest phase.** If it takes more than one session, split into 8a (seed + fixtures + engine tests) and 8b (API + integration tests).

**Session History**:
| Date | Status | Notes |
|---|---|---|
| | | |

---

## Phase 9: New Test Suite for Price List Feature

**Goal**: Comprehensive tests for all new price list functionality.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — all decisions
- `tests/api/test_bom_items.py` — CRUD test pattern reference
- `tests/engine/test_bom_evaluation.py` — engine test pattern reference
- `tests/integration/test_bom_workflow.py` — integration test pattern reference
- `tests/api/test_configurations_finalize.py` — finalization test pattern
- `app/routers/price_lists.py` — endpoints to test
- `app/routers/price_list_items.py` — endpoints to test

**Checklist**:
- [ ] Create `tests/api/test_price_lists.py`:
  - CRUD: create, read, list, update, delete
  - Validation: `valid_from >= valid_to` rejected, unique name, empty name
  - `valid_at` filter: returns only lists valid at given date, default today
  - Delete protection: cannot delete if referenced by FINALIZED config
  - Delete allowed: if referenced only by DRAFT config (price_list_id set to null)
  - Delete allowed: if not referenced at all
  - RBAC: USER role cannot create/update/delete
  - Bounding box update: cannot shrink dates if items fall outside new range
- [ ] Create `tests/api/test_price_list_items.py`:
  - CRUD: create, read, list, update, delete
  - Date defaulting: item inherits dates from header when not specified
  - Bounding box: item dates must be within header range
  - Overlap: two items with same (price_list_id, part_number) and overlapping dates → 409
  - Overlap: non-overlapping ranges for same part_number → allowed
  - Overlap: same dates but different part_number → allowed
  - Price validation: unit_price must be > 0
  - RBAC: USER role cannot create/update/delete
- [ ] Create `tests/engine/test_price_resolution.py`:
  - Price resolved correctly from price list for COMMERCIAL items
  - TECHNICAL items: no price resolution, no warnings
  - Missing part_number: warning generated, line_total null, commercial_total is partial
  - Expired price (valid_to < price_date): warning generated
  - Future price (valid_from > price_date): warning generated
  - Multiple part_numbers, some missing: partial total, multiple warnings
  - All prices missing: commercial_total = 0, all warnings
  - price_list_id not provided: BOM has no pricing (unit_price null, no warnings)
  - Invalid price_list_id: 404 or appropriate error
  - Price list not valid at price_date: 422
  - price_date defaults to today when not provided
  - Different prices at different dates (temporal versioning works)
- [ ] Create `tests/integration/test_price_list_workflow.py`:
  - End-to-end: create price list → add items → create entity with BOM → calculate → verify prices
  - Temporal: create two price periods → calculate at different dates → verify different prices
  - Config lifecycle: create config with price list → finalize → verify snapshot has prices
  - Config upgrade: upgrade config → inherited price_list_id → recalculate
  - Config clone: clone FINALIZED → DRAFT with inherited price_list_id
  - Delete price list → verify DRAFT configs have price_list_id = null
- [ ] Create `tests/api/test_configurations_snapshot.py`:
  - Finalize stores snapshot
  - Load FINALIZED config returns snapshot directly (no recalculation)
  - Snapshot contains full CalculationResponse (fields, options, BOM, SKU)
  - Modify price list after finalization → FINALIZED config still returns original prices (from snapshot)
  - Config finalized before snapshot feature (snapshot=null) → falls back to rehydration
- [ ] Run full test suite — verify all pass

**Session History**:
| Date | Status | Notes |
|---|---|---|
| | | |

---

## Phase 10: Documentation Updates

**Goal**: Update all documentation to reflect the price list feature.

**Context Files** (read these first):
- `docs/PRICE_LIST_ANALYSIS.md` — reference for all changes
- `README.md` — needs feature description, API table, ER diagram, project structure updates
- `docs/ADR_BOM.md` — needs amendment for pricing changes
- `docs/ADR_REHYDRATION.md` — updated in Phase 6, verify completeness
- `docs/TESTING.md` — add new test categories
- `app/main.py` — verify all routers registered
- `openapi.json` — regenerate if manually maintained

**Important**: `PRICE_LIST_ANALYSIS.md` and `PRICE_LIST_DEVLOG.md` are working documents that will NOT be committed to the repository. All design decisions, rationale, and context must be captured directly in the permanent documentation (README, ADRs). These documents must be self-sufficient — a reader who has never seen the analysis document must be able to understand the full design from README + ADRs alone.

**Checklist**:
- [ ] Create `docs/ADR_PRICE_LIST.md` — a new ADR for the Price List feature:
  - Context: why per-item pricing on BOMItem was insufficient
  - Decisions: global price list, temporal validity (SAP 9999-12-31 convention), no-overlap constraint, bounding box, graceful price resolution (partial total + warnings), price_list_id mandatory in requests, price_date optional (default today), finalization always recalculates with today, deletion protection for FINALIZED references, no caching, BOM and price list independence, item date defaults from header
  - Trade-offs and consequences
  - Out of scope: cost price, discounts, margins, multi-currency, price override, price lock
  - Related ADRs: ADR_BOM, ADR_REHYDRATION
- [ ] Update `docs/ADR_BOM.md`:
  - Amend decision #1: COMMERCIAL items no longer carry `unit_price` — pricing resolved from price list
  - Amend decision #7: mark as superseded — price consistency validation replaced by centralized price list
  - Add reference to `docs/ADR_PRICE_LIST.md`
- [ ] Verify `docs/ADR_REHYDRATION.md` amendments from Phase 6 are complete and accurate
- [ ] Update `README.md`:
  - **Features section**: add "Price List Management" subsection under BOM Generation, with enough detail to explain the feature (temporal validity, price resolution, warnings, partial totals)
  - **Domain Model (ER diagram)**: add PriceList, PriceListItem entities and relationships
  - **API Overview**: add Price Lists and Price List Items endpoint tables
  - **Seed data table**: update counts (add price list, price list items)
  - **Project Structure**: add new router/schema files
  - **Design Decisions table**: add Price List row with brief rationale (not a link to analysis)
  - **Documentation section**: add link to `docs/ADR_PRICE_LIST.md`
  - **Key Architectural Choices**: add paragraph on hybrid rehydration and price list design
  - **Testing section**: update test count
- [ ] Update `docs/TESTING.md`:
  - Add new test file descriptions
  - Update test organization table
- [ ] Update `openapi.json` if manually maintained (or regenerate)
- [ ] Verify `api.http` (VS Code REST Client examples) — add price list examples if this file exists
- [ ] Final review: search codebase for any remaining references to `unit_price` on BOMItem (should be zero)
- [ ] Final review: search codebase for any references to `PRICE_LIST_ANALYSIS.md` or `PRICE_LIST_DEVLOG.md` — remove any found (these files will not be in the repo)

**Session History**:
| Date | Status | Notes |
|---|---|---|
| | | |

---

## Global Verification Checklist

Run this after all phases are complete:

- [ ] `pytest` — full suite passes with zero failures
- [ ] `pytest --cov=app --cov-report=term-missing` — coverage maintained or improved
- [ ] `alembic upgrade head` — migration runs cleanly
- [ ] `alembic downgrade -1 && alembic upgrade head` — migration is reversible
- [ ] `python seed_data.py` — seed script runs without errors
- [ ] `grep -r "unit_price" app/models/domain.py` — no hits on BOMItem (PriceListItem is fine)
- [ ] `grep -r "unit_price" app/schemas/bom_item.py` — no hits
- [ ] `grep -r "_validate_pricing_by_type\|_validate_commercial_price_consistency" app/` — no hits
- [ ] Manual smoke test: start app, create price list, create entity with BOM, calculate with price list, finalize config, verify snapshot

---

## Architecture Reference

### Files Created
| File | Phase | Description |
|---|---|---|
| `docs/ADR_PRICE_LIST.md` | 10 | Price List architecture decision record |
| `app/schemas/price_list.py` | 2 | Pydantic schemas for PriceList |
| `app/schemas/price_list_item.py` | 2 | Pydantic schemas for PriceListItem |
| `app/routers/price_lists.py` | 2 | PriceList CRUD endpoints |
| `app/routers/price_list_items.py` | 3 | PriceListItem CRUD endpoints |
| `tests/api/test_price_lists.py` | 9 | PriceList CRUD tests |
| `tests/api/test_price_list_items.py` | 9 | PriceListItem CRUD tests |
| `tests/engine/test_price_resolution.py` | 9 | Engine price resolution tests |
| `tests/integration/test_price_list_workflow.py` | 9 | End-to-end price list tests |
| `tests/api/test_configurations_snapshot.py` | 9 | Snapshot/rehydration tests |

### Files Modified
| File | Phase(s) | Changes |
|---|---|---|
| `app/models/domain.py` | 1, 7 | Add PriceList/PriceListItem models, modify Configuration, modify BOMItem |
| `app/schemas/engine.py` | 4 | Add price_list_id/price_date to request, warnings to BOMOutput |
| `app/schemas/configuration.py` | 5 | Add price_list_id, price_date to schemas |
| `app/schemas/bom_item.py` | 7 | Remove unit_price |
| `app/core/cache.py` | 4 | Remove unit_price from CachedBOMItem |
| `app/services/rule_engine.py` | 4 | Price resolution logic, updated _build_bom_output |
| `app/services/versioning.py` | 7 | Remove unit_price from clone |
| `app/routers/engine.py` | 4 | Pass price params to engine |
| `app/routers/configurations.py` | 5, 6 | price_list_id handling, snapshot logic |
| `app/routers/bom_items.py` | 7 | Remove pricing validations |
| `app/main.py` | 2, 3 | Register new routers |
| `seed_data.py` | 8 | Add price list demo data |
| `docs/ADR_REHYDRATION.md` | 6 | Hybrid rehydration amendment |
| `docs/ADR_BOM.md` | 10 | Pricing amendments |
| `README.md` | 10 | Feature docs, ER diagram, API table |
| `docs/TESTING.md` | 10 | New test descriptions |
| `tests/conftest.py` | 8 | Price list fixtures |
| `tests/engine/test_bom_*.py` | 8 | Remove unit_price, add price list |
| `tests/api/test_bom_items.py` | 8 | Remove pricing tests |
| `tests/api/test_engine_bom.py` | 8 | Add price list setup |
| `tests/api/test_configurations_*.py` | 8 | Add price_list_id |
| `tests/integration/test_bom_*.py` | 8 | Add price list setup |
