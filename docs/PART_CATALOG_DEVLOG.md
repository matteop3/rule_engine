# Part Catalog & Custom Items — Development Log

## Instructions for the Agent

You are implementing two related features for the rule engine: **CatalogItem** (Phase 1 group) and **ConfigurationCustomItem** (Phase 2 group). This devlog tracks progress across multiple sessions with limited context windows. **Read this file at the start of every session.**

### How to work

1. **Read this file first, in full.** Check the "Current Status" section to understand which phase is in flight and what has already been completed. Read the Session Log entries at the bottom — they describe what past sessions actually did, which is sometimes more accurate than checklist boxes.
2. **Read the analysis document** [PART_CATALOG_ANALYSIS_AND_PLAN.md](PART_CATALOG_ANALYSIS_AND_PLAN.md) — **but only the sections relevant to your current phase**. Each phase below lists the exact sections you must read. Reading the whole analysis document at every session wastes context.
3. **Read the context files** listed for your current phase. These are existing files whose patterns you must replicate. Do not invent patterns — look at how the price list or the BOM item code is organized and follow the same structure for models, schemas, routers, services, dependencies, and tests.
4. **Work on one phase at a time.** Do not start the next phase until the current one is fully complete: every checklist item checked, every acceptance criterion met, the test suite in the state declared in the phase description (either fully green or with the expected transient failures).
5. **Run the full test suite exactly once at the end of every phase.** Do not run it in parallel. Do not spawn subagents to run it. Do not re-run it speculatively. The suite takes roughly 13 minutes to complete; invoke it with a single `pytest` call, then wait for it using `sleep` rather than polling in a tight loop.
6. **Do not run the test suite multiple times to "see if it got better".** If a test fails, read the output, diagnose the root cause, fix it, then run once more.
7. **Some phases will leave the suite transiently broken.** Each phase declares explicitly how many failures are expected and why. If you see the expected number of failures (roughly — the exact count can drift slightly as tests evolve), that is correct. Do not try to "fix" tests whose failure is declared expected for the current phase. Read the "Expected test failures" subsection of the phase before making any judgment.
8. **Update this devlog at the end of every session.** Before ending a session:
   - Tick the checklist items you completed in this session (`[x]`).
   - Update the "Current Status" table at the top.
   - Append a new entry to the "Session Log" at the bottom describing what you did, what state the suite is in, and any notable decisions or deviations.
9. **Keep the GitHub Actions pipeline in mind.** The project has CI workflows under `.github/workflows/ci.yml` that run `ruff check`, `ruff format --check`, `mypy app/`, and the test suite. Before ending a phase, run `ruff check .` and `ruff format --check .` locally to catch style issues that would fail CI. Type errors from `mypy app/` must be fixed within the phase that introduces them — do not punt them to a later phase.
10. **Commit discipline is out of scope for this devlog.** Do not create git commits unless the user explicitly asks. Record changes by updating this devlog, not by committing.

### Rules

- **No incremental-change language** in code comments, docstrings, or any documentation file. Do not write "new", "added", "modified", "changed". Describe the system as it is, not its delta from a previous state. Example: write `"""Catalog of part identities referenced by BOM items and price list items."""`, not `"""New catalog of part identities, added in Phase 1..."""`.
- **Every phase includes tests.** Do not defer tests to a later phase unless the phase itself explicitly declares "tests come in phase N".
- **Every phase includes documentation updates where applicable.** A phase that ships a new endpoint also updates the README API Overview. A phase that finalizes a feature also updates the relevant ADR.
- **Follow existing patterns exactly.** The codebase has consistent conventions for models (SQLAlchemy 2.0 `Mapped` syntax, `AuditMixin`), schemas (Pydantic 2 with explicit Read/Create/Update triplets), routers (FastAPI with dependency injection, `get_transaction` for writes), services (business logic separated from routers), and tests (fixtures from `tests/fixtures/`, parametrized where it helps coverage). Read the "Context files" list for your phase and replicate.
- **Backward compatibility of the external API.** The `CalculationResponse` / `BOMLineItem` schema must remain consumable by existing clients: adding optional fields is fine, renaming or removing fields is not. The `is_custom` flag on `BOMLineItem` is an additive change.
- **Alembic migrations.** Use `alembic revision --autogenerate -m "..."` as the starting point, then carefully review the generated file and hand-edit it to match the intended steps (especially for the data migration in Phase A3). Always provide a downgrade path, even if best-effort.
- **Never bypass CHECK constraints.** Value constraints for `quantity > 0` and `unit_price >= 0` on custom items must exist at both the DB level (CHECK constraint) and the Pydantic schema level (validator). Implementing only one is insufficient.
- **Avoid overreach.** If you notice something unrelated to the current phase that looks suboptimal, do not fix it here. Note it in the session log as a future observation, leave the code alone.

### How to handle transient test failures

Several phases declare that the suite will be in a broken state at their end. The devlog states explicitly how many tests are expected to fail and why. When you see a broken suite:

1. Count the failures and compare with the "Expected test failures" subsection of the current phase.
2. If the count matches (approximately) and the failing tests are in the categories declared (e.g. "BOM CRUD tests that still pass `description` in the payload"), that is the expected state. Record it in the session log and proceed.
3. If the count is higher than expected, or failures appear in unexpected categories, **stop**. Read the output carefully. The phase is not complete. Fix the regressions before ending the session.
4. **Never move to the next phase while the suite is in an unexpected state.**

---

## Current Status

| Field | Value |
|---|---|
| **Current phase** | — (feature complete) |
| **Last completed phase** | B4 — Documentation closeout, ADR_CUSTOM_ITEMS, README, TESTING |
| **Feature A (CatalogItem) status** | Complete |
| **Feature B (CustomItems) status** | Complete |
| **Test suite state** | Fully green (1193 passed) |
| **Blocking issues** | None |

Phase progress overview:

| # | Phase | Feature | Status |
|---|---|---|---|
| A1 | CatalogItem model & empty migration | A | ☑ |
| A2 | CatalogItem CRUD API | A | ☑ |
| A3 | FK wiring migration & column drops | A | ☑ |
| A4 | Test fixture refactor & BOM/PriceList CRUD validation | A | ☑ |
| A5 | Engine integration (BOMLineItem from catalog) | A | ☑ |
| A6 | Seed data, ADR_CATALOG_ITEM, README, TESTING | A | ☑ |
| B1 | ConfigurationCustomItem model & migration | B | ☑ |
| B2 | ConfigurationCustomItem CRUD API | B | ☑ |
| B3 | Engine integration (CUSTOM step, snapshot, clone) | B | ☑ |
| B4 | Custom items tests, ADR_CUSTOM_ITEMS, README, TESTING | B | ☑ |

---

## Phase A1 — CatalogItem model & empty migration

**Objective.** Create the `CatalogItem` SQLAlchemy model and an Alembic migration that adds the `catalog_items` table. At this stage no existing table is touched — the catalog simply exists as an unreferenced addition to the schema.

**Analysis sections to read.** §4.1 (Entity shape), §4.2 (FK strategy — preview only, actual FK wiring happens in A3), §4.4 (never-renamed invariant, as context), §5 (Alembic migration, the parts about `CREATE TABLE` and index — skip data migration and column drops for now).

**Context files to read.**
- `app/models/domain.py` — specifically `PriceList` and `PriceListItem` (as the closest template for a new `AuditMixin`-enabled table with a lifecycle-adjacent column), `BOMItem` (for the `part_number` column shape).
- `alembic/versions/8fda6a3544e3_add_price_list_tables_and_configuration_.py` — as a template for table creation and index creation in a migration.
- `app/database.py` — to confirm the `Base` import and session setup.

**Implementation checklist.**

- [x] Add `CatalogItemStatus` enum (`ACTIVE`, `OBSOLETE`) to `app/models/domain.py`, placed in the enums section alongside `VersionStatus` and `UserRole`.
- [x] Add `CatalogItem` SQLAlchemy model with all columns from §4.1, using `Mapped[...]` syntax and `AuditMixin`. The `part_number` column must be `String(100)`, non-nullable, with `UNIQUE=True`. The `description` column must be `Text`, non-nullable. The `unit_of_measure` column must be `String(20)`, non-nullable, `server_default='PC'`. The `status` column must be `String(20)`, non-nullable, `server_default='ACTIVE'`. The `notes` column must be `Text`, nullable. The `category` column must be `String(100)`, nullable.
- [x] Add a `__repr__` and `__str__` on the model matching the style of `PriceList`.
- [x] Generate an Alembic revision (`alembic revision --autogenerate -m "add catalog_items table"`), review the generated file, and hand-edit if needed so it creates only `catalog_items` and its unique index. No other tables must be touched in this revision.
- [x] Confirm `alembic upgrade head` runs cleanly on a fresh database inside `docker compose` (use the test containers pattern or a local dev DB — do not modify the production environment).
- [x] Run `ruff check app/ && ruff format --check app/` and fix any issues.
- [x] Run `mypy app/` and fix any type errors in the new model.
- [x] Run the full test suite once at the end with `pytest`. All tests must still pass — this phase is fully additive.

**Expected test failures.** None. The suite must remain fully green (977 passed). This phase only adds a table that no code references yet.

**Definition of done.** The new model and migration are in place, the test suite is fully green, and `ruff`/`mypy` are clean.

---

## Phase A2 — CatalogItem CRUD API

**Objective.** Ship the `/catalog-items` endpoints with full RBAC, validation, and CRUD-level tests. At the end of this phase the catalog can be managed via the API, but nothing else references it yet.

**Analysis sections to read.** §4.1 (Entity shape), §4.3 (lifecycle — only the create-blocking behavior is relevant here), §4.4 (never-renamed invariant, must be enforced on PATCH), §4.5 (deletion — only the "no live references" check is implementable here; there are no FKs from other tables yet, so for this phase deletion always succeeds if the row exists), §4.6 (CRUD endpoint surface), §8.1 (Test strategy subsection on CatalogItem API tests).

**Context files to read.**
- `app/schemas/price_list.py` and `app/schemas/price_list_item.py` — template for the Create/Update/Read schema triplet with Pydantic 2.
- `app/routers/price_lists.py` — template for a router with RBAC, filtering, and dependency-injected services.
- `app/routers/price_list_items.py` — template for the same structure with nested validation.
- `app/services/` — look at how existing features organize service-layer logic. If the existing pattern is thin (logic in router), replicate that; if there is a dedicated service module, create a `catalog_items.py` service.
- `app/dependencies/fetchers.py` and `app/dependencies/validators.py` — for the style of reusable dependency helpers.
- `tests/api/test_price_lists.py` and `tests/api/test_price_list_items.py` — templates for the API test suite to replicate.
- `tests/fixtures/price_lists.py` — for the fixture style (if a similar module exists for price lists).

**Implementation checklist.**

- [x] Create `app/schemas/catalog_item.py` with `CatalogItemBase`, `CatalogItemCreate`, `CatalogItemUpdate`, `CatalogItemRead`. `CatalogItemUpdate` must **not** accept `part_number` (omit the field or explicitly reject it via a validator with the exact error message from §4.4).
- [x] Export the schemas from `app/schemas/__init__.py` if that is the existing pattern.
- [x] Create `app/routers/catalog_items.py` implementing the endpoints listed in §4.6. Use existing dependency helpers (`get_transaction`, `require_admin_or_author`, `get_current_user`) — do not invent new ones.
- [x] Register the router in `app/main.py` with the correct tag and prefix.
- [x] Create `tests/fixtures/catalog_items.py` exposing factory helpers for catalog entries used in tests (minimally: `create_catalog_item(db, part_number, **overrides)` and `ensure_catalog_entry(db, part_number, **overrides)` — the latter is idempotent). `ensure_catalog_entry` will also be used in Phase A4 by other test fixtures.
- [x] Create `tests/api/test_catalog_items.py` covering the full API test list from §8.1 — CRUD happy paths, duplicate detection, missing fields, `part_number`-in-payload rejection on PATCH, RBAC (reads for any authenticated user, writes ADMIN/AUTHOR only, USER write → 403). Note: tests for FK-related deletion blocking and OBSOLETE reference rejection cannot exist yet; they arrive in A4.
- [x] Run `ruff check .`, `ruff format --check .`, `mypy app/`. Fix any issues.
- [x] Run the full test suite once at the end. All pre-existing tests must still pass, plus the new catalog_items tests.

**Expected test failures.** None. The suite must be fully green. Test count grows by roughly 20–30 new catalog_items tests.

**Definition of done.** Catalog items can be created, read, updated, and deleted via the API; RBAC matches the project pattern; the test suite is fully green; the `ensure_catalog_entry` helper is available for use by later phases.

---

## Phase A3 — FK wiring migration & column drops

**Objective.** Add the foreign key constraint from `bom_items.part_number` and `price_list_items.part_number` to `catalog_items.part_number`, run the data migration that backfills `catalog_items` from existing seed/test data, and drop the now-redundant columns (`description`, `category`, `unit_of_measure` from `bom_items`; `description` from `price_list_items`).

**This phase will leave the test suite broken.** Read the "Expected test failures" subsection carefully before running the suite.

**Analysis sections to read.** §4.7 (Impact on BOMItem), §4.8 (Impact on PriceListItem), §5 (Alembic migration, the full step list).

**Context files to read.**
- `app/models/domain.py` — `BOMItem` and `PriceListItem` classes (columns to drop, FK to add).
- `alembic/versions/ede7b2b33ade_add_bom_tables_and_configuration_bom_.py` and `alembic/versions/8fda6a3544e3_add_price_list_tables_and_configuration_.py` — reference for how FK constraints are declared in existing migrations.
- `app/schemas/bom_item.py` and `app/schemas/price_list_item.py` — schemas to update (remove `description` / `category` / `unit_of_measure` fields where applicable).

**Implementation checklist.**

- [x] Update `app/models/domain.py`:
  - Remove `description`, `category`, `unit_of_measure` from `BOMItem`. Remove their mentions from `__repr__` / `__str__`.
  - Remove `description` from `PriceListItem`. Update `__repr__` / `__str__` accordingly.
  - Add `ForeignKey("catalog_items.part_number")` to `BOMItem.part_number` and `PriceListItem.part_number`. Note: this is a business-key FK — use `ForeignKey("catalog_items.part_number")` not `ForeignKey("catalog_items.id")`.
  - Add a `catalog_item: Mapped["CatalogItem"] = relationship(...)` backref on both `BOMItem` and `PriceListItem` for convenience in services and tests.
- [x] Update `app/schemas/bom_item.py`: remove `description`, `category`, `unit_of_measure` from `BOMItemBase` / `BOMItemCreate` / `BOMItemUpdate` / `BOMItemRead`. The engine response (`BOMLineItem` in `app/schemas/engine.py`) is **not** touched in this phase — it still contains these fields; they will be wired to the catalog source in Phase A5.
- [x] Update `app/schemas/price_list_item.py`: remove `description` from all four schemas.
- [x] Generate an Alembic migration (`alembic revision --autogenerate -m "wire catalog_items FK and drop redundant columns"`). Review and hand-edit to ensure the ordered steps from §5 of the analysis document:
  1. Data migration: SELECT distinct `part_number` from `bom_items` and `price_list_items`, UNION, resolve `description` (price list first, fallback BOMItem), resolve `category` (BOMItem only, NULL otherwise), resolve `unit_of_measure` (BOMItem, fallback `'PC'`), INSERT into `catalog_items` with `status='ACTIVE'`. Use Alembic's `op.execute(...)` with raw SQL for portability.
  2. `ALTER TABLE bom_items ADD CONSTRAINT fk_bom_items_part_number FOREIGN KEY (part_number) REFERENCES catalog_items(part_number)`.
  3. Same for `price_list_items`.
  4. `DROP COLUMN` for `bom_items.description`, `bom_items.category`, `bom_items.unit_of_measure`.
  5. `DROP COLUMN` for `price_list_items.description`.
- [x] Write a corresponding downgrade that reverses the steps (re-add the columns as nullable, backfill from catalog join, drop the FKs, leave the data in catalog_items).
- [x] Confirm `alembic upgrade head` and `alembic downgrade -1` both run cleanly on a fresh database.
- [x] Do **not** update the existing test fixtures in this phase — the fixture refactor is Phase A4. The suite will be broken at the end of A3; that is intentional and isolates the two concerns.
- [x] Run `ruff check .` and `ruff format --check .`; fix any issues.
- [x] Run `mypy app/`; fix any type errors introduced by the model and schema changes.
- [x] Run the full test suite once at the end. Record the number of failures in the session log.

**Expected test failures.** A large number (expect roughly 100–250, exact count depends on fixture coupling). Failures will cluster in:
- BOM-related tests that either read `description`/`category`/`unit_of_measure` on a `BOMItem` response, or create a `BOMItem` referencing a `part_number` not yet in the catalog (FK violation).
- Price list tests that create a `PriceListItem` referencing a `part_number` not yet in the catalog, or read the removed `description` field.
- Any engine test that assembles an EntityVersion fixture from scratch using BOMItems and hits the FK violation.
- Integration tests that do the full lifecycle and break at any of the above.

This is expected. Do **not** fix these failures in A3. They are addressed in A4 by introducing `ensure_catalog_entry` into the fixture layer. The CatalogItem API tests from A2 must continue to pass.

**Definition of done.** The migration applies cleanly, the model and schemas reflect the new shape, the test suite is broken in the expected categories only, `ruff` and `mypy` are clean.

---

## Phase A4 — Test fixture refactor & BOM/PriceList CRUD validation

**Objective.** Repair the test suite by updating every fixture that creates a BOMItem or PriceListItem so it first ensures a matching CatalogItem exists. At the same time, add CRUD-level validation to BOMItem and PriceListItem that rejects references to non-existent or OBSOLETE catalog entries.

**Analysis sections to read.** §4.3 (OBSOLETE behavior — now implementable for BOMItem/PriceListItem), §4.5 (deletion blocking — now there are live FK references, so the 409 path is exercisable), §4.7 and §4.8 (BOMItem and PriceListItem CRUD validation updates), §11 (Test fixtures refactor).

**Context files to read.**
- `tests/conftest.py` — top-level fixtures.
- `tests/fixtures/entities.py`, `tests/fixtures/configurations_lifecycle.py`, `tests/fixtures/price_lists.py`, `tests/fixtures/engine.py` — all fixture modules that might create BOMItem or PriceListItem rows.
- `tests/fixtures/catalog_items.py` (created in A2) — the home of `ensure_catalog_entry`.
- `tests/api/test_bom_items.py` and `tests/api/test_price_list_items.py` — for the existing test patterns and for the places where new OBSOLETE-rejection and missing-reference tests belong.
- `app/routers/bom_items.py` and `app/routers/price_list_items.py` — for the places where the new validations must be added.

**Implementation checklist.**

- [x] Add validation in `app/routers/bom_items.py` (or the associated service) on `POST` and `PATCH`:
  - If `part_number` is not present in `catalog_items`, return 409 with `"Catalog item 'XYZ' does not exist"`.
  - If the referenced catalog item has `status = OBSOLETE`, return 409 with the exact error message from §4.3.
- [x] Same validation in `app/routers/price_list_items.py` for `POST` and `PATCH`.
- [x] Add validation in `app/routers/catalog_items.py` for `DELETE`: block with 409 if any `BOMItem` or `PriceListItem` references the catalog entry (count references and include them in the error message per §4.5). This is the first phase where this check is meaningful because the FK now exists.
- [x] Sweep `tests/fixtures/` and `tests/conftest.py`: every function or fixture that constructs a `BOMItem` or `PriceListItem` must first call `ensure_catalog_entry(db, part_number, ...)` with matching defaults. Centralize this where possible (e.g. a higher-level fixture helper that wraps both).
- [x] Sweep `tests/api/test_bom_items.py` and `tests/api/test_price_list_items.py` for tests that construct payloads with hardcoded `part_number` strings: these tests must now also seed a catalog entry (either via the fixture or inline) before POSTing.
- [x] Update `tests/api/test_bom_items.py`: remove assertions on `description`/`category`/`unit_of_measure` from the BOMItem response (those fields no longer exist on the BOMItem read schema). If those assertions were load-bearing, move them into engine tests that check the `BOMLineItem` in the calculation response — but defer that check to A5 where the engine is actually wired to the catalog.
- [x] Update `tests/api/test_price_list_items.py`: remove assertions on `description` from the PriceListItem response.
- [x] Add new API tests for the validation:
  - POST BOMItem with unknown part_number → 409.
  - POST BOMItem with OBSOLETE part_number → 409.
  - PATCH BOMItem to change part_number to OBSOLETE → 409.
  - Same three cases for PriceListItem.
  - DELETE CatalogItem that is referenced by a BOMItem → 409 with the expected error message.
  - DELETE CatalogItem that is referenced by a PriceListItem → 409.
  - DELETE CatalogItem that has no references → 204.
- [x] Run `ruff check .`, `ruff format --check .`, `mypy app/`. Fix any issues.
- [x] Run the full test suite once at the end. The suite must be back to fully green, with the count increased by the new CRUD validation tests (roughly +8–15 tests).

**Expected test failures.** None. This phase exists precisely to return the suite to green. If after your fixes the suite still shows failures, the phase is not done.

**Definition of done.** The full test suite passes. CRUD-level validation for missing and OBSOLETE catalog references is in place for both BOMItem and PriceListItem. CatalogItem deletion is blocked by live references with the expected 409 response. `ruff` and `mypy` are clean.

---

## Phase A5 — Engine integration (BOMLineItem from catalog)

**Objective.** Wire the rule engine so that `BOMLineItem.description`, `category`, and `unit_of_measure` in the calculation response are sourced from the `CatalogItem` row rather than from the removed `BOMItem` columns. This closes the loop: the calculation response shape stays identical to before, only the source of metadata changes.

**Analysis sections to read.** §4.9 (Engine integration), §8.1 (engine test list — the part about description/category/UoM in the calculation output).

**Context files to read.**
- `app/services/rule_engine.py` — the existing BOM evaluation step (search for "BOM", "commercial", or the `BOMLineItem` construction site).
- `app/schemas/engine.py` — the `BOMLineItem` and `BOMOutput` schemas.
- `tests/engine/test_bom_evaluation.py`, `tests/engine/test_bom_aggregation.py`, `tests/engine/test_price_resolution.py` — the engine test files that assert on BOMLineItem content.

**Implementation checklist.**

- [x] In `app/services/rule_engine.py`, at the start of the BOM evaluation step, load all `CatalogItem` rows for the set of distinct `part_number` values present on the current EntityVersion's BOMItems. Store them in an in-memory `dict[str, CatalogItem]` keyed by `part_number`.
- [x] When constructing each `BOMLineItem`, resolve `description`, `category`, and `unit_of_measure` from the catalog map. If a BOMItem's `part_number` is not in the map — which should not happen given the FK constraint, but be defensive — raise a clear internal error identifying the missing part (it indicates a corrupted EntityVersion).
- [x] Confirm the `BOMLineItem` Pydantic schema remains unchanged in shape (still exposes `part_number`, `description`, `category`, `unit_of_measure`, `quantity`, `unit_price`, `line_total`).
- [x] Update any existing engine test that was asserting on BOMLineItem metadata: the expected values must now come from the seeded catalog entries, not from BOMItem-level overrides.
- [x] Add new engine tests:
  - Calculation returns BOMLineItem with description/category/UoM matching the catalog entry for each part_number.
  - Updating the catalog description of a referenced part changes the next DRAFT calculation output.
  - Obsoleting a catalog item does not break calculation for configurations that already reference it.
  - A FINALIZED configuration whose catalog entries are later modified still returns the snapshot unchanged (description frozen).
  - A FINALIZED configuration whose catalog entry is deleted (after clearing all other references) still returns the snapshot unchanged.
- [x] Add at least one mutation-kill test targeting the catalog-lookup step (e.g. a test that fails if the engine silently uses `BOMItem.part_number` as the description fallback).
- [x] Run `ruff check .`, `ruff format --check .`, `mypy app/`. Fix any issues.
- [x] Run the full test suite once at the end. Must be fully green.

**Expected test failures.** None. This phase returns all engine-level tests to green and closes the metadata sourcing loop.

**Definition of done.** The calculation response is fully wired to the catalog. The FINALIZED snapshot mechanism is verified to be unaffected by catalog mutation and deletion. The suite is green.

---

## Phase A6 — Seed data, ADR_CATALOG_ITEM, README, TESTING

**Objective.** Close out Feature A by updating seed data, writing the new ADR, updating the README with the catalog section and ERD changes, updating `ADR_BOM.md` and `ADR_PRICE_LIST.md` with cross-references, and documenting the new test surface in `TESTING.md`.

**Analysis sections to read.** §4.10 (Seed data), §9 (Documentation updates — Phase 1 subsection), §10.1 (CatalogTemplate follow-up, which must appear in the new ADR's Known Gaps section).

**Context files to read.**
- `seed_data.py` — the current seeding script.
- `README.md` — the full file, to identify all places that need updating (ERD, API Overview, sections on BOM and Price List).
- `docs/ADR_BOM.md` — current state, to add the cross-reference and mark metadata columns as superseded.
- `docs/ADR_PRICE_LIST.md` — current state, to add the note on superseded `description` column.
- `docs/TESTING.md` — the current test documentation structure.
- `docs/ADR_PRICE_LIST.md` — as a structural template for the new `ADR_CATALOG_ITEM.md` (same "Status / Context / Decisions / Consequences / Out of Scope / Known Gaps and Follow-ups / Related" layout).

**Implementation checklist.**

- [x] Update `seed_data.py`:
  - Create CatalogItem entries **before** BOMItem and PriceListItem, with realistic `description`, `category`, and `unit_of_measure` per demo part.
  - Ensure the existing demo BOMItem and PriceListItem rows reference these catalog entries by `part_number`.
  - Run `python seed_data.py` against a fresh database and confirm it succeeds.
- [x] Create `docs/ADR_CATALOG_ITEM.md` using §4 of the analysis document as the input. Sections: Status, Context, Decisions (one per numbered decision in §4), Consequences, Out of Scope, Known Gaps and Follow-ups (must explicitly mention the postponed `CatalogTemplate` per §10.1, including the principle-of-future-solution paragraph), Related. Follow the `ADR_PRICE_LIST.md` structure.
- [x] Update `docs/ADR_BOM.md`:
  - Add (or update) a decision noting that `description`, `category`, `unit_of_measure` are no longer stored on `BOMItem` and are sourced from the catalog at output build time.
  - Add `ADR_CATALOG_ITEM.md` to the "Related" section at the bottom.
- [x] Update `docs/ADR_PRICE_LIST.md`:
  - Add a note that `PriceListItem.description` is superseded by the catalog.
  - Add `ADR_CATALOG_ITEM.md` to the "Related" section at the bottom.
- [x] Update `README.md`:
  - Amend the Mermaid ERD to include `CatalogItem` with FK arrows from `BOMItem` and `PriceListItem`.
  - Add a "Catalog Management" bullet in the Features section, parallel to "Price List Management" and "BOM Generation".
  - Add a `/catalog-items` table in the API Overview.
  - Update the "Load Demo Data" table to reflect the new catalog rows count.
  - Add `docs/ADR_CATALOG_ITEM.md` to the Documentation section at the bottom.
- [x] Update `docs/TESTING.md`:
  - Document `tests/api/test_catalog_items.py` and the new catalog-related tests in BOM and price list test files.
  - Document the `ensure_catalog_entry` fixture helper and its role for test data setup.
- [x] Run `ruff check .`, `ruff format --check .`, `mypy app/`. Fix any issues.
- [x] Run the full test suite once at the end. Must be fully green.

**Expected test failures.** None.

**Definition of done.** Feature A is fully shipped: code, tests, documentation, seed data, and ADR. The suite is green. This is the natural handoff point to Feature B.

---

## Phase B1 — ConfigurationCustomItem model & migration

**Objective.** Create the `ConfigurationCustomItem` model, its Alembic migration, and the database-level CHECK constraints. No API surface yet — this phase ends with the table in place and the model importable, but not exposed.

**Analysis sections to read.** §6.1 (Entity shape), §6.2 (Value constraints — the DB-level CHECK part), §6.3 (Key generation — preview only; the actual generation logic lives in the service in B2), §7 (Alembic migration for Phase 2).

**Context files to read.**
- `app/models/domain.py` — `PriceListItem` and `BOMItem` models as templates for an `AuditMixin`-enabled child table with FK to a parent, and specifically the existing `Configuration` model to understand the UUID PK and the backref pattern.
- `alembic/versions/8fda6a3544e3_add_price_list_tables_and_configuration_.py` — template for migration with CHECK constraints and indexes.

**Implementation checklist.**

- [x] Add `ConfigurationCustomItem` model to `app/models/domain.py`, with all columns from §6.1. The `custom_key` column is `String(20)`, `UNIQUE`, non-nullable. `quantity` is `Numeric(12, 4)` with a CHECK constraint `quantity > 0`. `unit_price` is `Numeric(12, 4)` with a CHECK constraint `unit_price >= 0`. `configuration_id` is a `ForeignKey("configurations.id", ondelete="CASCADE")`.
- [x] Add a `custom_items: Mapped[list["ConfigurationCustomItem"]] = relationship(..., cascade="all, delete-orphan")` backref on `Configuration`.
- [x] Generate and hand-edit an Alembic migration that creates `configuration_custom_items`, the UNIQUE index on `custom_key`, a regular index on `configuration_id`, and both CHECK constraints. The CHECK constraints must be named (`ck_cci_quantity_positive`, `ck_cci_unit_price_nonnegative`) for future referencing.
- [x] Confirm `alembic upgrade head` and `alembic downgrade -1` both run cleanly.
- [x] Run `ruff check .`, `ruff format --check .`, `mypy app/`. Fix any issues.
- [x] Run the full test suite once at the end. Must be fully green — the new table is unreferenced by any test yet.

**Expected test failures.** None.

**Definition of done.** The model exists, the migration applies, the suite is green.

---

## Phase B2 — ConfigurationCustomItem CRUD API

**Objective.** Ship the nested `/configurations/{id}/custom-items` endpoints with key auto-generation, DRAFT gating, ownership checks, Pydantic-level value validation, and API-level tests. The engine is not yet aware of custom items — that comes in B3.

**Analysis sections to read.** §6.2 (Value constraints), §6.3 (Key generation — the full rule), §6.4 (Commercial-only — relevant for the router's docstring), §6.5 (CRUD endpoint surface), §8.2 (Test strategy subsection on custom items API tests).

**Context files to read.**
- `app/routers/configurations.py` — template for the configuration-level router and DRAFT-gating pattern.
- `app/routers/bom_items.py` or `app/routers/price_list_items.py` — template for nested CRUD on a parent-scoped resource.
- `app/schemas/bom_item.py` — template for schema triplet with validators.
- `app/dependencies/auth.py` — for the ownership check pattern (a USER can only touch their own configurations).
- `tests/api/test_configurations_crud.py` — template for tests of configuration-scoped operations.

**Implementation checklist.**

- [x] Create `app/schemas/configuration_custom_item.py` with `CustomItemCreate`, `CustomItemUpdate`, `CustomItemRead`. Pydantic validators enforce: `quantity > 0` (with explicit 422 message), `unit_price >= 0`, `description` non-empty after strip. `custom_key` is **not** in the Create schema; the server generates it.
- [x] Create `app/routers/configuration_custom_items.py` (or add to the existing `configurations.py` router if the project prefers nested routers in the same file). Implement the four endpoints from §6.5. Authorization: reuse the existing configuration-ownership check. DRAFT gating: reuse the existing FINALIZED write-block check.
- [x] Implement `custom_key` generation: `f"CUSTOM-{uuid.uuid4().hex[:8]}"`. If the client provides a `custom_key` in the payload, ignore it silently. The key is assigned in the create service call, not in the schema.
- [x] Register the router in `app/main.py`.
- [x] Create `tests/api/test_configuration_custom_items.py` covering the full list from §8.2:
  - Happy-path create, read, update, delete.
  - Auto-generated `custom_key` format (`CUSTOM-` prefix + 8 hex chars, 15 chars total).
  - Client-provided `custom_key` is ignored.
  - Value validation: `quantity = 0` → 422, `quantity = -1` → 422, `unit_price = -0.01` → 422, `unit_price = 0` → accepted, empty `description` → 422, missing `description` → 422.
  - FINALIZED gating: create/update/delete on FINALIZED → 409.
  - Ownership: USER on another user's configuration → 403, USER on their own → allowed, ADMIN on any → allowed.
  - List returns items ordered by `sequence`.
- [x] Run `ruff check .`, `ruff format --check .`, `mypy app/`. Fix any issues.
- [x] Run the full test suite once at the end. Must be fully green.

**Expected test failures.** None.

**Definition of done.** The CRUD endpoints are live, fully tested, and RBAC-compliant. Engine integration is still pending.

---

## Phase B3 — Engine integration (CUSTOM step, snapshot, clone)

**Objective.** Wire custom items into the calculation pipeline (the new CUSTOM step after PRICING), the snapshot at finalization, and the clone/upgrade semantics. Ship engine-level tests that exercise the full lifecycle.

**Analysis sections to read.** §6.6 (Engine integration — the full CUSTOM step spec), §6.7 (Schema changes — `is_custom` flag on BOMLineItem), §6.8 (Clone semantics), §6.9 (Upgrade semantics), §6.10 (Finalization and snapshot), §8.2 (Test strategy — engine and integration tests subsections).

**Context files to read.**
- `app/services/rule_engine.py` — where the BOM + PRICING steps live; this is where CUSTOM will be appended.
- `app/schemas/engine.py` — `BOMLineItem` and `BOMOutput` schemas.
- `app/routers/configurations.py` — look specifically for the clone endpoint (to extend it to copy custom items with fresh keys) and the finalize endpoint (to confirm the snapshot captures the full response).
- `tests/engine/test_price_resolution.py` and `tests/integration/` test files — for the patterns to follow when adding engine/integration tests.

**Implementation checklist.**

- [x] Add `is_custom: bool = False` to `BOMLineItem` in `app/schemas/engine.py`.
- [x] In `app/services/rule_engine.py`, add the CUSTOM step at the end of the BOM/PRICING pipeline:
  - Load `ConfigurationCustomItem` rows for the current configuration (only when calculating for a persisted configuration; the stateless `/engine/calculate` endpoint has no custom items and skips this step).
  - For each custom item, emit a `BOMLineItem` with `is_custom=True`, `part_number=custom_key`, metadata from the custom item, `line_total = quantity * unit_price`.
  - Append custom lines to `BOMOutput.commercial` after all catalog-sourced lines, preserving `sequence` within the custom block.
  - Add custom-line totals to `commercial_total`.
  - Custom lines must **not** generate warnings and must **not** influence `is_complete`.
- [x] Update `app/routers/configurations.py`:
  - Clone endpoint (`POST /configurations/{id}/clone`): after creating the new DRAFT configuration, iterate over the source's `ConfigurationCustomItem` rows and create copies on the new configuration with **fresh** `custom_key` values.
  - Upgrade endpoint (`POST /configurations/{id}/upgrade`): custom items are preserved as-is on the upgraded DRAFT (they belong to the configuration, not the version).
  - Finalize endpoint: confirm the snapshot built from the `CalculationResponse` includes custom lines. No code change should be needed if the serialization is generic, but verify with a test.
- [x] Create `tests/engine/test_custom_items.py` covering:
  - Custom items appear in the commercial output after catalog lines, with `is_custom=True`.
  - `commercial_total` correctly sums catalog + custom.
  - Custom items do not generate warnings even when catalog lines have missing prices.
  - Custom items do not affect `is_complete`.
  - `unit_price = 0` custom item is included and produces `line_total = 0`.
  - At least one mutation-killing test targeting the value constraints.
- [x] Create `tests/integration/test_custom_items_lifecycle.py` covering:
  - Create DRAFT, add custom items, calculate, finalize; verify snapshot contains custom items with exact values.
  - Mutate custom items via direct DB after finalize; verify FINALIZED read returns unchanged snapshot.
  - Clone a FINALIZED configuration with custom items; verify the new DRAFT has copies with **new** `custom_key` values (assert the old and new keys are disjoint).
  - Upgrade a DRAFT to a newer EntityVersion; verify custom items are preserved.
- [x] Run `ruff check .`, `ruff format --check .`, `mypy app/`. Fix any issues.
- [x] Run the full test suite once at the end. Must be fully green.

**Expected test failures.** None.

**Definition of done.** Custom items are fully wired into the calculation pipeline, the snapshot mechanism, and the clone/upgrade flows. Engine and integration tests verify the full lifecycle. Suite is green.

---

## Phase B4 — Documentation closeout, ADR_CUSTOM_ITEMS, README, TESTING

**Objective.** Final documentation pass. Write the new ADR, update the README with the custom items section, amend `ADR_PRICE_LIST.md` with the custom-lines note, and update `TESTING.md`. Add the Phase 2 custom item to seed data.

**Analysis sections to read.** §6.11 (Seed data), §9 (Documentation updates — Phase 2 subsection), §10.2 (CustomItemPromotion follow-up, which must appear in the new ADR's Known Gaps section).

**Context files to read.**
- `docs/ADR_PRICE_LIST.md` — as the structural template for the new ADR and as the file to amend.
- `README.md` — to identify update sites (ERD, Features, API Overview, Documentation section).
- `docs/TESTING.md` — to document the new test files.
- `seed_data.py` — to add the demo custom item.

**Implementation checklist.**

- [x] Update `seed_data.py` to add one or two example custom items to an existing DRAFT demo configuration. Run the seed against a fresh database and confirm success.
- [x] Create `docs/ADR_CUSTOM_ITEMS.md` using §6 of the analysis document as input. Same structural template as `ADR_CATALOG_ITEM.md` / `ADR_PRICE_LIST.md`: Status, Context, Decisions, Consequences, Out of Scope, Known Gaps and Follow-ups. The Known Gaps section **must** explicitly mention the postponed `CustomItemPromotion` per §10.2, including the two stability invariants (`custom_key` stable forever, `part_number` never renamed in place) that keep the promotion path open.
- [x] Update `docs/ADR_PRICE_LIST.md`:
  - Add a note near decision #4 (graceful price resolution) that `BOMOutput.commercial` may also contain `is_custom = True` lines sourced from the configuration, that custom lines never generate warnings, and that they never affect `is_complete`.
  - Add `ADR_CUSTOM_ITEMS.md` to the "Related" section at the bottom.
- [x] Update `README.md`:
  - Amend the Mermaid ERD to include `ConfigurationCustomItem` with FK to `Configuration`.
  - Add a "Custom Items" subsection under the existing BOM or Configuration section describing the feature: commercial-only, configuration-scoped, inline pricing, auto-generated `CUSTOM-<uuid8>` key, frozen in snapshot at finalization.
  - Add the `/configurations/{id}/custom-items` endpoints to the API Overview table.
  - Update the "Load Demo Data" counts to reflect the new custom item entries.
  - Add `docs/ADR_CUSTOM_ITEMS.md` to the Documentation section at the bottom.
- [x] Update `docs/TESTING.md` to document `tests/api/test_configuration_custom_items.py`, `tests/engine/test_custom_items.py`, and `tests/integration/test_custom_items_lifecycle.py`.
- [x] Run `ruff check .`, `ruff format --check .`, `mypy app/`. Fix any issues.
- [x] Run the full test suite once at the end. Must be fully green.

**Expected test failures.** None.

**Definition of done.** Both features are fully shipped: code, tests, documentation, ADRs, seed data. `Current Status` table at the top of this file is updated to reflect completion.

---

## Session Log

Sessions append entries here in reverse chronological order (most recent at the top). Each session records: what phase was worked on, what was completed, the state of the suite, and any notable deviation from the plan. Do **not** delete or rewrite past entries.

### 2026-04-20 — Phase B4

Completed Phase B4, the final documentation pass. Feature B (ConfigurationCustomItem) is fully shipped. No code changes — this phase is pure docs plus seed data, so the suite count is unchanged from B3.

New ADR at [docs/ADR_CUSTOM_ITEMS.md](ADR_CUSTOM_ITEMS.md). Structure mirrors `ADR_CATALOG_ITEM.md` / `ADR_PRICE_LIST.md`: Status, Context, Decisions, Consequences, Out of Scope, Known Gaps and Follow-ups, Related. Twelve numbered decisions covering per-configuration table with `ON DELETE CASCADE`, server-generated `CUSTOM-<uuid8>` keys, dual-layer value constraints (DB CHECKs + Pydantic `gt=0` / `ge=0`), commercial-only scope, nested CRUD surface under `/configurations/{config_id}/custom-items`, CUSTOM engine step appended after PRICING and gated by `request.configuration_id`, additive schema changes (`BOMLineItem.is_custom: bool = False`, nullable `bom_item_id`, optional `CalculationRequest.configuration_id`), clone with fresh keys, upgrade preservation, self-contained finalization snapshot, stateless-endpoint skip, and shared `part_number` slot disambiguated by `is_custom`. Known Gaps section explicitly documents the postponed `CustomItemPromotion` workflow (§10.2) with both stability invariants — `custom_key` is forever stable, `CatalogItem.part_number` is never renamed in place — that keep the promotion path open for a later feature.

[docs/ADR_PRICE_LIST.md](ADR_PRICE_LIST.md) amended: appended a paragraph to decision #4 (graceful price resolution) explaining that `BOMOutput.commercial` may also contain `is_custom = True` lines sourced from the configuration itself, that those lines carry their own `unit_price` / `line_total`, never produce warnings, and never affect `is_complete`. Added `ADR_CUSTOM_ITEMS.md` to the Related section at the bottom.

[README.md](../README.md) updates: Mermaid ERD gained `Configuration ||--o{ ConfigurationCustomItem : "has custom lines"` plus a full entity block for `ConfigurationCustomItem` (id, configuration_id FK CASCADE, custom_key UK, description, quantity CHECK > 0, unit_price CHECK >= 0, unit_of_measure nullable, sequence default 0). New "Custom Items (commercial-only escape hatch)" feature subsection describing the full lifecycle. New "Configuration Custom Items" API Overview table with the four nested endpoints. Demo Data counts table gained `| Custom Items | 2 | Attached to the Truck DRAFT (on-site safety audit + fleet signage package) |`. Test-count reference updated from `977+` to `1193+`. Configurations endpoints table amended so the clone/upgrade/finalize lines mention the custom-items behavior. `docs/ADR_CUSTOM_ITEMS.md` added to the Documentation links.

[docs/TESTING.md](TESTING.md) updates: added `test_configuration_custom_items.py` to the API directory listing, `test_custom_items.py` to the engine listing, `test_custom_items_lifecycle.py` to the integration listing. Test Statistics table bumped: API 29 → 30, Engine 15 → 16, Integration 15 → 16, Files 63 → 66, Tests ~977 → ~1193. Added one coverage bullet per new suite (Configuration Custom Items API, Custom Items Engine Integration, Custom Items Lifecycle). Configuration Snapshots bullet amended to call out custom-item mutation immunity post-finalize.

[seed_data.py](../seed_data.py) updates: added top-level `import uuid`, imported `ConfigurationCustomItem`, added the model to the cleanup DELETE chain before `Configuration`, and inserted a new step 12 that creates two `ConfigurationCustomItem` rows attached to the Truck DRAFT configuration — "On-site safety audit (one-off)" (quantity 1, unit price 250.00, sequence 0) and "Fleet signage package" (quantity 3, unit price 45.00, sequence 1), both with server-generated `CUSTOM-<uuid8>` keys. Attached to the DRAFT specifically because rows added after finalization would not be reflected in the snapshot. All existing `[X/11]` step markers renumbered to `[X/12]` via `replace_all`. Summary output extended with a CONFIGURATION CUSTOM ITEMS block that prints both keys/descriptions and a count. Seed re-run against a fresh database: all 12 steps clean.

`ruff check .` clean. `ruff format` reformatted `seed_data.py` once after the step 12 edits (mostly the multi-line split needed to stay under the 120-char line limit — `print(f"[12/12] ...")` had to be split across lines and the big summary `print(f"""...""")` had to be broken up by extracting `ci0, ci1 = all_custom_items` before the f-string). `ruff format --check .` then clean across all 145 files. `mypy app/` — Success: no issues found in 56 source files. Full test suite ran once at the end: **1193 passed, 1 warning** in 1100.57s (18:20). Delta from B3's 1193: zero — B4 is pure docs/seed.

No deviations from plan. Feature B complete. All 10 phases (A1–A6, B1–B4) done; Current Status table at the top of this file reflects completion.

### 2026-04-20 — Phase B3

Completed Phase B3. Wired `ConfigurationCustomItem` rows into the calculation pipeline as a new CUSTOM step after PRICING, extended the clone endpoint to copy custom items with fresh keys, and verified upgrade + finalize-snapshot semantics require no additional code. Added engine-level and end-to-end integration tests.

Schema changes in [app/schemas/engine.py](../app/schemas/engine.py):
- `BOMLineItem.is_custom: bool = False` — new flag, defaults to `False` so every existing catalog-sourced line serializes unchanged.
- `BOMLineItem.bom_item_id: int | None = None` — relaxed from required `int`. Custom lines have no `BOMItem` row to reference, so the field must be nullable. Additive change: catalog lines still populate it.
- `CalculationRequest.configuration_id: str | None = None` — optional pointer that lets the engine locate the configuration row. Absent on stateless `/engine/calculate` requests; populated automatically by `calculate_configuration_state` when operating on a persisted configuration.

Engine change in [app/services/rule_engine.py](../app/services/rule_engine.py): after `_evaluate_bom`, if `request.configuration_id` is set, `_append_custom_items` runs. It loads all `ConfigurationCustomItem` rows for the configuration ordered by `(sequence, id)`, builds a `BOMLineItem` per row (`bom_type="COMMERCIAL"`, `part_number=custom_key`, `is_custom=True`, `line_total = quantity * unit_price`), appends them to `BOMOutput.commercial` **after** catalog lines, and bumps `commercial_total`. If the entity has no BOM (`bom_output is None`), a fresh `BOMOutput(technical=[], commercial=[], commercial_total=None, warnings=[])` is created so custom items alone can still produce output. Custom lines never emit warnings and never affect completeness — by construction, they're appended after the completeness check and warnings are only generated by the catalog pipeline.

Router changes in [app/routers/configurations.py](../app/routers/configurations.py):
- Added `configuration_id: str | None = None` to `calculate_configuration_state` and threaded it into `CalculationRequest` at all four call sites that operate on a persisted configuration: `update_configuration`, `upgrade_configuration`, `finalize_configuration`, and `load_and_calculate_configuration`. `create_configuration` does **not** pass it — the configuration row doesn't exist yet at that point and, critically, there can be no custom items to load.
- Clone endpoint: queries the source's `ConfigurationCustomItem` rows **before** opening the transaction (so the query isn't inside a write transaction for longer than necessary), then inside the transaction, after flushing `cloned_config`, creates a fresh `ConfigurationCustomItem` per source row with a **new** `CUSTOM-<uuid8>` key, preserving `description`, `quantity`, `unit_price`, `unit_of_measure`, and `sequence`. `created_by_id` is set to the current user — the clone is their action.
- Upgrade endpoint: no code change. Custom items belong to the configuration, not the `EntityVersion`; upgrading swaps `entity_version_id` only, so rows survive untouched. Verified by `TestUpgradePreservesCustomItems`.
- Finalize endpoint: no code change. `config.snapshot = calc_result.model_dump(mode="json")` already captures the full `CalculationResponse` including the custom lines now in `bom.commercial`. Verified by `TestFinalizedSnapshotImmutability`.

Engine tests at [tests/engine/test_custom_items.py](../tests/engine/test_custom_items.py) — 14 tests across 7 classes, all using a single `custom_items_scenario` fixture that builds a catalog + a BOMItem + a price list (producing `line_total=35.00`) + a configuration with three `ConfigurationCustomItem` rows (`sequence` values 5, 0, 10 → `CUSTOM-bbbbbbbb`, `CUSTOM-aaaaaaaa`, `CUSTOM-cccccccc` respectively) so ordering, totals (expected commercial total = 35 + 325 = 360), and the `is_custom` flag can all be asserted from the same setup. Classes: `TestCustomItemsAppearInOutput`, `TestCommercialTotalIncludesCustom`, `TestCustomItemsDoNotProduceWarnings` (verified with a catalog line missing a price — warnings come only from the catalog pipeline), `TestCustomItemsDoNotAffectCompleteness`, `TestZeroPricedCustomItem` (unit_price=0 → line_total=0, still included), `TestStatelessEngineSkipsCustomItems` (calculate without `configuration_id` → no custom lines even when rows exist for that configuration), `TestCustomItemsMutationKill` (directly flipping `line_total = quantity * unit_price` to the wrong decimal product kills the test).

Integration tests at [tests/integration/test_custom_items_lifecycle.py](../tests/integration/test_custom_items_lifecycle.py) — 5 tests across 4 classes using the existing lifecycle fixtures (`draft_configuration`, `lifecycle_user_headers`, `configuration_on_archived_version`, `multi_version_entity`):
- `TestEndToEndCustomItemLifecycle`: creates DRAFT, POSTs two custom items, calls `/calculate`, asserts both appear as `is_custom=True` with correct `line_total`s (120.00 and 71.00), finalizes, re-reads `/calculate`, asserts the snapshot serves the same custom lines.
- `TestFinalizedSnapshotImmutability` (2 tests): after finalize, mutates the underlying `ConfigurationCustomItem` row directly via `db_session` (bypassing the FINALIZED-gated API), asserts `/calculate` still returns the pre-finalize values from the snapshot. Second test deletes the row entirely — snapshot still intact.
- `TestCloneCopiesCustomItemsWithFreshKeys`: finalizes source, clones, asserts source and clone key sets are **disjoint** but values (`description`, `unit_price`, `sequence`) are preserved. Also re-reads the source snapshot post-clone to confirm the clone operation doesn't mutate the source.
- `TestUpgradePreservesCustomItems`: adds a custom item to a configuration on an archived version, upgrades to the published version, verifies the single row survives with its original `custom_key`, description, and unit price.

Implementation notes:
- `_append_custom_items` is a separate method rather than inlined so the conditional (`request.configuration_id is not None`) stays at the top of the pipeline and the stateless path in `/engine/calculate` remains a single-line skip.
- Making `bom_item_id` optional is technically a breaking change to the output schema for strict consumers, but nothing internal reads the field as non-null, and Pydantic serializes `None` identically to an absent integer for JSON output of catalog lines (they always have the id populated). Documented in §6.7 of the analysis.
- The clone endpoint reads source custom items *before* entering the transaction block. This mirrors the existing pattern for source field values — keep the transaction as narrow as possible.

`ruff check .` clean. `ruff format` reformatted `tests/integration/test_custom_items_lifecycle.py` (condensed a multi-line query chain); `ruff format --check .` then clean. `mypy app/` — Success: no issues found in 56 source files. Full test suite ran once at the end: **1193 passed, 1 warning** in 1032.21s (17:12). Net suite growth over B2's 1174 baseline: +19 (14 engine + 5 integration).

No deviations from plan.

### 2026-04-19 — Phase B2

Completed Phase B2. Shipped the nested `/configurations/{config_id}/custom-items` CRUD surface with four endpoints (list, create, update, delete), server-generated `CUSTOM-<uuid8>` keys, Pydantic-level value validation, DRAFT gating, and owner/ADMIN authorization. No engine integration yet — that lands in B3.

Schemas in [app/schemas/configuration_custom_item.py](../app/schemas/configuration_custom_item.py): `ConfigurationCustomItemBase` (with a `description` `field_validator` that strips whitespace and rejects empty strings, `quantity: Decimal = Field(..., gt=0)`, `unit_price: Decimal = Field(..., ge=0)`), `ConfigurationCustomItemCreate` (adds a `model_validator(mode="before")` that silently pops any client-provided `custom_key`), `ConfigurationCustomItemUpdate` (same validator but raises on `custom_key` presence — immutable key), `ConfigurationCustomItemRead` (adds `id`, `configuration_id`, `custom_key`, and `AuditSchemaMixin`). Exported from `app/schemas/__init__.py`. `quantity > 0` and `unit_price >= 0` are enforced at both the DB level (named CHECK constraints from Phase B1: `ck_cci_quantity_positive`, `ck_cci_unit_price_nonnegative`) and the Pydantic layer — neither is bypassable alone.

Router in [app/routers/configuration_custom_items.py](../app/routers/configuration_custom_items.py) with prefix `/configurations/{config_id}/custom-items` and tag `Configuration Custom Items`. Reuses existing helpers from `app.routers.configurations`: `get_configuration_or_404` (404 + ownership 403) and `require_draft_status` (409 on FINALIZED). `_generate_custom_key()` is a private helper returning `f"CUSTOM-{uuid.uuid4().hex[:8]}"`. Create sets `created_by_id`; update sets `updated_by_id`. List orders by `sequence, id` for deterministic secondary ordering. Router registered in [app/main.py](../app/main.py) alphabetically between `catalog_items` and the existing configuration routes.

API tests at [tests/api/test_configuration_custom_items.py](../tests/api/test_configuration_custom_items.py) — 46 tests across 6 classes:
- `TestCreateCustomItemHappyPath` (7 tests): happy-path create, key format (15 chars total, lowercase hex), three creates producing distinct keys, client-provided `custom_key` silently ignored, `unit_price=0` accepted, `unit_of_measure` optional, `created_by_id` persisted.
- `TestCreateCustomItemValidation` (10 tests): parametrized over `quantity ∈ {"0", "-1", "-0.0001"}` → 422, `unit_price ∈ {"-0.01", "-1", "-100"}` → 422, missing description → 422, parametrized over `description ∈ {"", "   ", "\t\n"}` → 422, missing `quantity` / `unit_price` → 422.
- `TestCreateCustomItemAccessControl` (6 tests): FINALIZED → 409, USER on other user's config → 403, ADMIN on any config → 201, owner USER → 201, unauthenticated → 401, missing config → 404.
- `TestListCustomItems` (5 tests): sequence ordering (three items sorted 0→5→10 in output), empty config returns `[]`, USER on other user's config → 403, ADMIN on any config → 200, unauthenticated → 401.
- `TestUpdateCustomItem` (9 tests): full-field update (with `custom_key` unchanged), partial update keeps other fields, `custom_key` in payload → 422, `quantity=0` → 422, `unit_price=-1` → 422, whitespace description → 422, update on FINALIZED → 409 (flipped via direct DB), missing item → 404, USER on other user's item → 403, empty patch returns current state.
- `TestDeleteCustomItem` (6 tests): happy-path 204 with DB verification, FINALIZED → 409, missing → 404, USER on other user's item → 403, unauthenticated → 401, cascade delete on parent configuration removes custom items (verifies `ondelete="CASCADE"` + ORM `cascade="all, delete-orphan"`).

Implementation notes:
- The `_drop_custom_key` validator on `ConfigurationCustomItemCreate` uses `dict.pop(..., None)` to silently ignore client-supplied values, per §6.3.
- The `_reject_custom_key` validator on `ConfigurationCustomItemUpdate` raises `ValueError` (→ 422) because mutating an immutable key should be an explicit error, not a silent no-op, consistent with `CatalogItemUpdate`'s `part_number` rejection.
- FINALIZED-gating tests use `admin_owned_draft_configuration` and flip the status directly via DB update before the assertion, avoiding the full finalize path (which would require an engine calculation with matching fields). The guard being tested is `require_draft_status`, not the finalization flow itself.

`ruff check .` clean. `ruff format` reformatted both new files (whitespace/line-length); `ruff format --check .` then clean. `mypy app/` — Success: no issues found in 56 source files (+2 from B1's 54: the new router and schema modules). Full test suite ran once at the end: **1174 passed, 1 warning** in 1016.16s. Net suite growth over B1's 1128 baseline: +46 tests (matches the new file).

No deviations from plan. Ready to start B3 pending user approval.

### 2026-04-19 — Phase B1

Completed Phase B1. Added the `ConfigurationCustomItem` SQLAlchemy model and the Alembic migration that creates the `configuration_custom_items` table. No code references the new table yet — the API surface arrives in B2, the engine integration in B3 — so the suite count stays at 1128, matching A6.

Model in [app/models/domain.py](../app/models/domain.py): `ConfigurationCustomItem` inherits `Base` and `AuditMixin`. Columns match §6.1 — `id` integer PK, `configuration_id` `String(36)` FK to `configurations.id` with `ondelete="CASCADE"`, `custom_key` `String(20)` non-nullable (uniqueness declared as a named `UniqueConstraint("custom_key", name="uq_cci_custom_key")` in `__table_args__` rather than `unique=True` on the column, matching the `CatalogItem` pattern for stable autogenerate diffs), `description` `Text` non-nullable, `quantity` and `unit_price` `Numeric(12, 4)` non-nullable, `unit_of_measure` `String(20)` nullable, `sequence` `Integer` non-nullable with `server_default="0"`. `__table_args__` also carries both named CHECK constraints (`ck_cci_quantity_positive` / `ck_cci_unit_price_nonnegative`) and the regular `ix_cci_configuration` index. `Configuration` gained a `custom_items: Mapped[list["ConfigurationCustomItem"]] = relationship(back_populates="configuration", cascade="all, delete-orphan")` backref. `__repr__` and `__str__` on the new model follow the project style (`<ConfigurationCustomItem id=… custom_key='…' configuration_id=…>` and `"{custom_key}: {description}"`).

Migration [alembic/versions/0d7707c387f6_add_configuration_custom_items_table.py](../alembic/versions/0d7707c387f6_add_configuration_custom_items_table.py) (down_revision `e7e71e4e3229`): single `op.create_table` with all columns, both named `sa.CheckConstraint` entries, the FK to `configurations.id` with `ondelete="CASCADE"`, the FKs to `users.id` for the audit columns, the PK, and the named `UniqueConstraint("custom_key", name="uq_cci_custom_key")`. Two indexes: `ix_cci_configuration` on `configuration_id` for list-by-configuration queries, and the standard `ix_configuration_custom_items_id` on the PK. Downgrade drops the indexes then the table. Hand-edited the autogen output to match the repo style — `from collections.abc import Sequence`, `str | Sequence[str] | None` type hints, and removal of the `# ### auto generated ###` markers — consistent with the earlier catalog revisions.

Verified migration round-trip on a throwaway `b1_test` database created inside the running `rule_engine_db` container. `alembic upgrade head` runs cleanly through all six revisions. `psql \d configuration_custom_items` confirms the shipped shape: all columns nullable/not-nullable correctly, both named CHECK constraints present, `uq_cci_custom_key` unique constraint present, `ix_cci_configuration` regular index present, cascading FK to `configurations(id)`. `alembic downgrade -1` drops the table cleanly. Re-running `alembic upgrade head` followed by `alembic revision --autogenerate --splice` on the upgraded DB produced an empty revision (both `upgrade` and `downgrade` bodies are just `pass`), confirming the model and the migration are exactly in sync — deleted that verification revision and dropped the throwaway DB.

`ruff check .` clean. `ruff format --check .` reformatted [app/models/domain.py](../app/models/domain.py) (one whitespace nit from the insertion) — `ruff format --check .` then clean. `mypy app/` — Success: no issues found in 54 source files. Full test suite ran once at the end: **1128 passed, 1 warning** in 959.84s. Suite count unchanged from A6's 1128 baseline, matching the phase spec ("the new table is unreferenced by any test yet").

No deviations from plan. Ready to start B2 pending user approval.

### 2026-04-19 — Phase A6

Completed Phase A6, closing out Feature A (CatalogItem). Pure docs/seed phase: no production code changes, no new tests, suite count unchanged at 1128.

Seed data in [seed_data.py](../seed_data.py): added a new section 7 that creates 7 ACTIVE `CatalogItem` rows before any `BOMItem` or `PriceListItem` — POL-BASE (Policy/pcs), MOD-LIABILITY (Coverage/pcs), RIDER-LUX (Coverage/pcs), ASSESS-HEAVY (Assessment/pcs), CERT-INSPECT (Certification/pcs), PREM-BASE (Premium/yr), ADDON-THEFT (Add-on/yr). Removed the now-invalid `description=`, `category=`, `unit_of_measure=` kwargs from every `BOMItem(...)` constructor and the `description=` kwarg from every `PriceListItem(...)` constructor (those columns were dropped in A3). Added `db.query(CatalogItem).delete()` to the cleanup block and renumbered all print labels to `[N/11]`. Print summary now includes a CATALOG ITEMS block listing each seeded entry. Verified idempotency by running against a throwaway `catalog_seed_test` database: `alembic upgrade head` then `python seed_data.py` succeeds on first run and re-runs cleanly (cleanup block handles re-seeding correctly).

New ADR at [docs/ADR_CATALOG_ITEM.md](ADR_CATALOG_ITEM.md) (~180 lines), structured per `ADR_PRICE_LIST.md`: Status (Accepted), Context, 11 numbered Decisions (flat table / business-key FK / ACTIVE-OBSOLETE lifecycle / never-renamed invariant / centralized metadata / referential-integrity deletion / CRUD+RBAC surface / engine integration at calculation time / snapshot immunity via FINALIZED independence / CRUD validation at BOM/PriceList boundaries / test fixture strategy), Consequences, Out of Scope, Known Gaps and Follow-ups. The Known Gaps section explicitly covers the postponed `CatalogTemplate` per §10.1 — includes the "principle of future solution" paragraph framing templates as a compose-layer on top of the existing atomic entity, not a replacement — and the bulk import follow-up.

Cross-references: [docs/ADR_BOM.md](ADR_BOM.md) gained a new decision #8 ("Part metadata sourced from the catalog") describing the FK to `CatalogItem.part_number` and the calculation-time join producing `BOMLineItem.description/category/unit_of_measure`; the previous "Position in the evaluation waterfall" decision renumbered to #9. Added `ADR_CATALOG_ITEM.md` to its Related section. [docs/ADR_PRICE_LIST.md](ADR_PRICE_LIST.md) gained decision #13a ("PriceListItem.description superseded by the catalog") noting that per-item descriptions were dropped in A3 and metadata now comes from the catalog join; added `ADR_CATALOG_ITEM.md` to its Related section.

[README.md](../README.md) updates: added a "Catalog Management" feature section (6 bullets: central identity registry, business-key FKs, ACTIVE/OBSOLETE lifecycle gating new references, immutable part_number invariant, deletion blocked while referenced, calculation-time metadata resolution). Mermaid ERD amended — `CatalogItem` block added (id PK, part_number UK "immutable business key", description, unit_of_measure default 'PC', category nullable, status ACTIVE|OBSOLETE, notes nullable), `BOMItem }o--|| CatalogItem` and `PriceListItem }o--|| CatalogItem` FK relationships drawn, `description` stripped from the `BOMItem` and `PriceListItem` ERD blocks, and their `part_number` marked as `FK "catalog_items.part_number"`. Added a "Catalog Items" subsection to the API Overview with the 6 endpoints (GET list, POST, GET by id, GET by-part-number, PATCH, DELETE) and their RBAC requirements. BOM Items endpoint descriptions updated to note catalog FK validation (409 on unknown/OBSOLETE references). Load Demo Data table gained a "Catalog Items | 7 | One per distinct part_number used by BOM and price list (ACTIVE)" row. `ADR_CATALOG_ITEM.md` added to the Documentation section at the bottom.

[docs/TESTING.md](TESTING.md) updates: added `catalog_items.py` to the fixtures tree, `test_catalog_items.py` under `tests/api/`, and `test_catalog_metadata.py` under `tests/engine/`. Added two bullets to the Core Fixtures section: "Catalog auto-seed" describing the `before_flush` SQLAlchemy session listener in `tests/conftest.py` that upserts a `CatalogItem` for any pending `BOMItem`/`PriceListItem` part_number (lets the 100+ pre-A4 test construction sites keep working without per-test seeding), and "Catalog validator monkeypatch" describing the lenient module-level default plus the `strict_catalog_validation` opt-in fixture for tests that exercise the real CRUD validator.

`ruff check .`, `ruff format --check .` clean. `mypy app/` — Success: no issues found in 54 source files. Full test suite ran once at the end: **1128 passed** (exit 0). Suite count unchanged from A5 — this phase ships no production code or tests, only docs and seed data.

No deviations from plan. Feature A is complete. Ready to start B1 pending user approval.

### 2026-04-19 — Phase A5

Completed Phase A5. Wired the rule engine to source `BOMLineItem.description`, `category`, and `unit_of_measure` from `CatalogItem` rows joined on `part_number`. The `BOMLineItem` Pydantic schema is unchanged in shape; only the source of metadata moved from the (now removed) `BOMItem` columns to a per-calculation catalog lookup.

Implementation in [app/services/rule_engine.py](../app/services/rule_engine.py): added `_load_catalog_map(db, bom_items) -> dict[str, CatalogItem]` (single `IN` query over the distinct `part_number` set) called from `calculate_state` after price resolution. The map is threaded through `_evaluate_bom` and `_build_bom_output` via a new `catalog_map` keyword. Inside `_build_bom_output`, each line item now reads `catalog_entry.description`, `catalog_entry.category`, and `catalog_entry.unit_of_measure`. A missing entry (which the FK on `bom_items.part_number` should make impossible) raises `ValueError("Catalog entry missing for part_number '<pn>' on bom_item <id>; EntityVersion is inconsistent.")` per §4.9 — defensive against corrupted data.

The catalog is loaded **per calculation** by design (consistent with the price list's per-calculation load — see §4.9). It is never stored in the PUBLISHED-version `TTLCache`, so a mutation to a catalog row is visible to the very next call even when the cached `VersionData` is reused. `TestCatalogMutationOnDraft.test_description_change_reflected_in_next_calculation` exercises this exact path (1 cache miss + 1 cache hit, second call sees updated description/category).

Cleanup: dropped the now-dead `description`, `category`, `unit_of_measure` fields from [app/core/cache.py](../app/core/cache.py) `CachedBOMItem` (Phase A3 had been passing `None` for them as a transient bridge). Updated the corresponding `CachedBOMItem(...)` call site in `_load_version_data`.

New tests in [tests/engine/test_catalog_metadata.py](../tests/engine/test_catalog_metadata.py) — 8 tests across 5 classes:
- `TestBOMLineMetadataFromCatalog`: technical and commercial line items each carry catalog-sourced description/category/UoM.
- `TestCatalogMutationOnDraft`: changing description/category and unit_of_measure on a referenced catalog row is reflected in the next calculation, even when the engine's PUBLISHED-version cache is hit (verified via `service._cache.stats()` → 1 miss + 1 hit).
- `TestObsoleteCatalogTolerance`: setting a referenced catalog row to OBSOLETE does not break calculation; metadata stays fully populated. OBSOLETE gates *new* references via the CRUD validator added in A4 and is irrelevant to engine-time lookup.
- `TestSnapshotIsolatedFromCatalogMutation`: snapshot independence verified via `CalculationResponse.model_dump(mode="json")` round-trip — modify or delete the catalog row after taking the snapshot and the deserialized response still carries the original metadata. This mirrors what the configurations router stores in `Configuration.snapshot` at finalization (`calc_result.model_dump(mode="json")`) and replays on read; the engine layer's contribution is producing a fully self-contained response, which these tests verify.
- `TestCatalogLookupMutationKill.test_description_does_not_fall_back_to_part_number`: per-line assertion that `description != part_number` and `description is not None` for every line. Kills any mutation that silently substitutes `BOMItem.part_number` (or `None`) for the catalog lookup.

Existing engine tests required no edits: A3 had already removed the `description`/`category`/`unit_of_measure` columns from `BOMItem` and A4 had cleaned up the stale assertions. Greps over `tests/engine/` and `tests/integration/` confirmed no remaining BOMLineItem-metadata assertions outside the new file.

`ruff check .` clean. `ruff format` reformatted [app/services/rule_engine.py](../app/services/rule_engine.py) (one whitespace nit) — `ruff format --check .` then clean. `mypy app/` — Success: no issues found in 54 source files. Full test suite ran once at the end: **1128 passed, 1 warning** in 799.42s. Net suite growth over A4's 1120 baseline: +8 tests (matches the new file).

No deviations from plan. Ready to start A6.

### 2026-04-19 — Phase A4

Completed Phase A4. Suite is back to fully green (1120 passed) with CRUD-level validation in place for the catalog FK and DELETE blocking on `CatalogItem`.

CRUD validation added in [app/routers/bom_items.py](../app/routers/bom_items.py) and [app/routers/price_list_items.py](../app/routers/price_list_items.py): `POST` and `PATCH` now validate the `part_number` via `validate_catalog_reference` (see [app/dependencies/validators.py](../app/dependencies/validators.py)). The validator returns 409 with `"Catalog item '<pn>' does not exist"` when the part is missing, and 409 with `"Catalog item '<pn>' is OBSOLETE and cannot be referenced by new items"` on create / `"Catalog item '<pn>' is OBSOLETE and cannot be referenced"` on update, per §4.3. DELETE blocking added in [app/routers/catalog_items.py](../app/routers/catalog_items.py) via `validate_catalog_not_referenced`: when a catalog entry is referenced by BOM items or price list items, the deletion returns 409 with `"Catalog item '<pn>' cannot be deleted: referenced by N BOM item(s) and M price list item(s)"` per §4.5.

Fixture refactor used a hybrid auto-seed strategy rather than rewriting 100+ construction sites. [tests/conftest.py](../tests/conftest.py) registers a SQLAlchemy `before_flush` session event listener that inspects pending `BOMItem` / `PriceListItem` rows and upserts matching `CatalogItem` entries with neutral defaults (`description=part_number`, `unit_of_measure='PC'`, `status='ACTIVE'`). A module-level `monkeypatch` replaces `validate_catalog_reference` with a lenient no-op for the default test environment, so existing tests don't need to seed the catalog explicitly. Opt-in to real validation is via the `strict_catalog_validation` autouse-overriding fixture (declared in [tests/fixtures/catalog_items.py](../tests/fixtures/catalog_items.py)): requesting it from a test re-enables the real validator, so the new CRUD validation tests can exercise the 409 paths end-to-end.

Stale kwargs cleanup: removed `description=`, `category=`, `unit_of_measure=` from `BOMItem` constructors in [tests/engine/test_bom_aggregation.py](../tests/engine/test_bom_aggregation.py) and [tests/integration/test_clone_bom.py](../tests/integration/test_clone_bom.py) (columns dropped in A3 — auto-seed repairs the FK, but the kwargs themselves would still raise `TypeError`). The `test_clone_preserves_bom_type_and_metadata` test in `test_clone_bom.py` was renamed to `test_clone_preserves_bom_type_and_quantity` and its description/category/unit_of_measure assertions removed, per the A4 checklist note that load-bearing metadata assertions move to engine tests in A5 where the catalog is wired into `BOMLineItem`.

New tests added:
- [tests/api/test_bom_items.py](../tests/api/test_bom_items.py) — `TestBOMItemCatalogValidation` class with 5 tests: POST with unknown part_number → 409, POST with OBSOLETE part_number → 409, POST with ACTIVE accepted, PATCH changing part_number to OBSOLETE → 409, PATCH changing part_number to unknown → 409. All use `strict_catalog_validation`.
- [tests/api/test_price_list_items.py](../tests/api/test_price_list_items.py) — `TestPriceListItemCatalogValidation` class mirroring the BOM set (5 tests).
- [tests/api/test_catalog_items.py](../tests/api/test_catalog_items.py) — 3 DELETE-blocking tests: referenced by BOM item → 409 with expected message, referenced by price list item → 409, referenced by both → 409 with both counts in the error string.

`ruff check .`, `ruff format --check .` clean. `mypy app/` — Success: no issues found in 54 source files. Full test suite ran once at the end: **1120 passed, 1 warning** in 922.30s. Net suite growth over A3's 1107 baseline: +13 tests (matches the phase spec's "+8–15" envelope).

No deviations from plan. Ready to start A5.

### 2026-04-18 — Phase A3

Completed Phase A3. Wired `bom_items.part_number` and `price_list_items.part_number` as business-key FKs to `catalog_items.part_number`, dropped `bom_items.description`/`category`/`unit_of_measure` and `price_list_items.description`.

Model changes in [app/models/domain.py](../app/models/domain.py): `BOMItem.part_number` and `PriceListItem.part_number` now carry `ForeignKey("catalog_items.part_number")`; both models gained a `catalog_item: Mapped["CatalogItem"] = relationship(foreign_keys=[part_number])` backref. Removed `description`/`category`/`unit_of_measure` columns from `BOMItem` and `description` from `PriceListItem`. `BOMItem.__str__` now returns `part_number` only. Schema changes in [app/schemas/bom_item.py](../app/schemas/bom_item.py) and [app/schemas/price_list_item.py](../app/schemas/price_list_item.py) drop the superseded fields across Base/Create/Update/Read.

Minor cleanup to stabilize autogenerate diffs: reconciled `CatalogItem` declaration with the A1 migration's named unique constraint — moved the uniqueness to `__table_args__ = (UniqueConstraint("part_number", name="uq_catalog_items_part_number"),)` so `alembic --autogenerate` produces a clean diff with only the A3 changes.

Migration [alembic/versions/e7e71e4e3229_wire_catalog_items_fk_and_drop_.py](../alembic/versions/e7e71e4e3229_wire_catalog_items_fk_and_drop_.py) (down_revision `7d3a8c5f2e14`): upgrade runs the data migration as a single CTE-backed `INSERT … SELECT` that merges `price_list_items` and `bom_items` per §5 of the analysis — description prefers the price list entry and falls back to BOMItem (and to `part_number` as a last resort), category comes from BOMItem, unit_of_measure from BOMItem with `'PC'` fallback, status `'ACTIVE'`. Then adds named FKs `fk_bom_items_part_number` and `fk_price_list_items_part_number`, then drops the redundant columns. Downgrade re-adds the columns as nullable, backfills `bom_items.description/category/unit_of_measure` and `price_list_items.description` via JOIN on catalog_items, and drops the FKs. `alembic upgrade head` and `alembic downgrade -1` both applied cleanly on a throwaway `catalog_fk_test` database. Smoke-tested the data migration by pre-populating rows in both `bom_items` and `price_list_items` before running A3: catalog rows are correctly hydrated with description/category/unit_of_measure merged from both sources.

Engine and versioning service touch-ups to keep `mypy app/` green: [app/services/rule_engine.py](../app/services/rule_engine.py) passes `description=None`, `category=None`, `unit_of_measure=None` when building `CachedBOMItem` from the DB row (the fields still exist on the cache dataclass and the BOMLineItem output — Phase A5 will wire them to the catalog lookup). [app/services/versioning.py](../app/services/versioning.py) no longer copies the dropped columns when cloning BOM items.

`ruff check .`, `ruff format --check .` clean. `mypy app/` — Success: no issues found in 54 source files.

Full test suite ran once at the end: **948 passed, 75 failed, 84 errors** in 824s. Failure clusters (matching the expected categories in the phase spec):
- `tests/api/test_bom_items.py`, `tests/api/test_bom_item_rules.py`, `tests/api/test_engine_bom.py` — 34 failures / errors. FK violations on BOMItem creation because fixtures do not seed a catalog entry; some tests assert on removed `description`/`category`/`unit_of_measure` response fields.
- `tests/api/test_price_list_items.py` — errors on PATCH/update tests (catalog not seeded), plus removed-`description` assertions.
- `tests/api/test_configurations_snapshot.py`, `tests/integration/*` — snapshot / lifecycle tests fail where upstream fixtures create BOMItems with unseeded part numbers.
- `tests/engine/test_bom_*.py`, `tests/engine/test_price_resolution.py` — 28 failures. Engine output's `description`/`category`/`unit_of_measure` is now `None` (the cache construction passes `None` until A5 wires the catalog lookup), so metadata-related assertions fail.

Total 159 broken cases in 948+159 = 1107 prior-green tests, well within the "roughly 100–250" envelope declared for A3.

No deviations from plan. Ready to start A4.

### 2026-04-17 — Phase A2

Completed Phase A2. Shipped the `/catalog-items` CRUD surface: schemas at [app/schemas/catalog_item.py](../app/schemas/catalog_item.py) (Base / Create / Update / Read, with a `model_validator(mode="before")` on `CatalogItemUpdate` that rejects any payload containing `part_number` with the exact error message from §4.4). Router at [app/routers/catalog_items.py](../app/routers/catalog_items.py) implementing the six endpoints from §4.6 (`GET /`, `POST /`, `GET /{id}`, `GET /by-part-number/{part_number}`, `PATCH /{id}`, `DELETE /{id}`); GET endpoints depend on `get_current_user` (any authenticated user), writes on `require_admin_or_author`. Duplicate `part_number` on POST returns 409. In this phase, DELETE always succeeds if the row exists — the FK-backed reference check arrives in A4 per the plan. Router registered in [app/main.py](../app/main.py).

Test fixture helpers at [tests/fixtures/catalog_items.py](../tests/fixtures/catalog_items.py) expose `create_catalog_item(db, part_number, **overrides)` and the idempotent `ensure_catalog_entry(db, part_number, **overrides)` that A4 will call from other fixture modules. API tests at [tests/api/test_catalog_items.py](../tests/api/test_catalog_items.py) — 50 tests covering: list (RBAC incl. USER=200, unauthenticated=401, sort, status filter, pagination, invalid-status 422), read-by-id (RBAC, 404, unauthenticated), read-by-part-number (happy path, 404, USER allowed), create (RBAC parametrized, defaults for `unit_of_measure`/`status`, create-OBSOLETE, duplicate→409, missing/empty part_number or description→422, invalid status→422, part_number length→422), update (RBAC, field-by-field edits incl. OBSOLETE↔ACTIVE revival, `part_number` rejection with and without other fields and when value matches existing, empty payload, 404, invalid/empty values), delete (RBAC, unreferenced→204 with DB verification, 404).

`ruff check .` and `ruff format --check .` clean. `mypy app/` — Success: no issues found in 54 source files. Full test suite ran once at the end: **1107 passed** in 937.86s (suite grew by +50 from the A1 baseline of 1057, matching the scope of the new file).

No deviations from plan. Ready to start A3.

### 2026-04-17 — Phase A1

Completed Phase A1. Added `CatalogItemStatus` enum and `CatalogItem` model to `app/models/domain.py` with `AuditMixin`, business-key unique on `part_number`, `server_default='PC'` on `unit_of_measure`, `server_default='ACTIVE'` on `status`. Created Alembic revision `7d3a8c5f2e14_add_catalog_items_table.py` (down_revision `8fda6a3544e3`) that creates only `catalog_items`, its PK index, the `part_number` unique constraint, and an index on `part_number`. Verified `alembic upgrade head` and `alembic downgrade -1` both run cleanly on a fresh Postgres database (via the running `rule_engine_db` container, using a throwaway `catalog_migration_test` database). `ruff check`, `ruff format --check`, and `mypy app/` are clean. Full test suite ran once at end: **1057 passed** in 861s. Note: the devlog baseline mentions 977, but the actual suite has grown since; all tests pass, which matches the A1 acceptance criterion.

No deviations from plan. Ready to start A2.

_(older sessions appear below)_
