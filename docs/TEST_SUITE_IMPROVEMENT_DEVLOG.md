# Test Suite Improvement — Development Log

## Instructions for the Agent

You are implementing improvements to the test suite as described in `docs/TEST_SUITE_IMPROVEMENT_PLAN.md`. This devlog tracks progress across multiple sessions. **Read this file at the start of every session.**

### How to work

1. **Read this file first.** Check the "Current Status" section to understand where you are.
2. **Read `docs/TEST_SUITE_IMPROVEMENT_PLAN.md`** — but only the section relevant to your current improvement.
3. **Read the context files** listed for your current improvement. Do not invent patterns — replicate what exists.
4. **Work on one improvement at a time.** Do not start the next until the current one is fully complete (all checklist items done, all tests passing).
5. **Run the full test suite** (`pytest`) at the end of every improvement to catch regressions. If tests fail, fix them before moving on.
6. **Update this devlog** before ending your session:
   - Check off completed items (`[x]`).
   - Update "Current Status".
   - Add a session entry to the "Session Log" at the bottom.

### Rules

- **No incremental-change language** in code comments, docstrings, or documentation. Do not write "New", "Added", "Modified", "Changed". Describe code as if it has always existed.
- **Do not modify existing tests** unless working on Improvement 4 (RBAC consolidation).
- **Run `ruff check app/ tests/` and `ruff format app/ tests/`** before considering any improvement complete.
- **Every improvement includes a `pytest` run** — full suite, zero regressions.

### Key project commands

```bash
# Run full test suite
pytest

# Run specific test file
pytest tests/engine/test_bom_edge_cases.py -v

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run mutation testing
mutmut run --paths-to-mutate=app/services/rule_engine.py --tests-dir=tests/ --runner="pytest tests/engine/ tests/integration/ -x -q --no-header --tb=no"

# Lint
ruff check app/ tests/
ruff format app/ tests/
```

---

## Current Status

| Field | Value |
|-------|-------|
| **Current improvement** | 5 (next up) |
| **Last completed improvement** | 4 (consolidate RBAC tests with parametrize) |
| **Tests passing** | 978 passed (2026-04-07) |
| **Blocking issues** | None |

---

## Improvement 1: Mutation Testing with mutmut

**Goal**: Identify surviving mutants in the two highest-value service files and write tests to kill them.

**Plan doc section**: Improvement 1 (Steps 1a–1e).

**Checklist:**

- [x] Install `mutmut` (dev dependency)
- [x] Run mutmut on `app/services/rule_engine.py` — record total mutants, killed, survived
- [x] Run mutmut on `app/services/versioning.py` — record total mutants, killed, survived
- [x] Analyze surviving mutants — classify each as "equivalent" (no behavioral change) or "real" (missing test)
- [x] Write tests for all non-equivalent surviving mutants (add to existing test files in `tests/engine/` or `tests/integration/`)
- [x] Re-run mutmut to confirm previously surviving mutants are killed
- [x] Create `docs/MUTMUT_REPORT.md` with: date, files analyzed, total mutants, killed, survived, equivalent, tests added
- [x] Run `ruff check app/ tests/` — no errors
- [x] Run `pytest` — full suite passes, zero regressions

---

## Improvement 2: Numeric Edge Cases for BOM

**Goal**: Verify BOM calculations handle boundary values (precision limits, zero prices, large quantities, decimal accumulation).

**Plan doc section**: Improvement 2 (Tests 2a–2h).

**Checklist:**

- [x] Read context files: `app/models/domain.py` (BOMItem), `app/services/rule_engine.py` (BOM methods), `tests/engine/test_bom_evaluation.py` (pattern)
- [x] Create `tests/engine/test_bom_edge_cases.py`
- [x] Test 2a: Decimal precision at Numeric(12,4) boundary
- [x] Test 2b: Small decimal quantities (`0.0001`)
- [x] Test 2c: Zero price on COMMERCIAL item
- [x] Test 2d: Accumulation precision with 20 items
- [x] Test 2e: Aggregation with large quantities
- [x] Test 2f: Quantity from field with zero value (exclusion)
- [x] Test 2g: Quantity from field with negative value (exclusion)
- [x] Test 2h: Quantity from field with very large value
- [x] Document any discovered behavioral issues as comments in the test file
- [x] Run `ruff check app/ tests/` — no errors
- [x] Run `pytest` — full suite passes, zero regressions

---

## Improvement 3: Malformed Input Resilience

**Goal**: Verify API returns correct error responses for malformed payloads.

**Plan doc section**: Improvement 3 (Tests 3a–3d).

**Checklist:**

- [x] Read context files: `app/schemas/bom_item.py`, `app/schemas/rule.py`, `app/schemas/field.py`, `app/routers/bom_items.py`
- [x] Create `tests/api/test_input_validation.py`
- [x] Class `TestWrongTypes` — 5 tests (wrong type for data_type, quantity, unit_price, field_id in conditions, data)
- [x] Class `TestMissingFields` — 4 tests (missing name, part_number, conditions, entity_version_id)
- [x] Class `TestInvalidValues` — 5 tests (invalid data_type, bom_type, operator, empty criteria, negative quantity)
- [x] Class `TestEmptyPayloads` — 2 tests (empty body, null body)
- [x] Each test asserts status code AND that error body references the offending field
- [x] Run `ruff check app/ tests/` — no errors
- [x] Run `pytest` — full suite passes, zero regressions

---

## Improvement 4: Consolidate RBAC Tests with Parametrize

**Goal**: Collapse repetitive RBAC tests into `@pytest.mark.parametrize`, reducing test count by ~80-100 without losing coverage.

**Plan doc section**: Improvement 4 (pattern, file list, rules).

**Checklist:**

Refactor one file at a time. Run `pytest <file> -v` after each to verify parametrized tests produce the same number of test cases.

- [x] `tests/api/test_fields.py` — collapse RBAC tests, run `pytest tests/api/test_fields.py -v`
- [x] `tests/api/test_values.py` — collapse RBAC tests, run `pytest tests/api/test_values.py -v`
- [x] `tests/api/test_rules_crud.py` — collapse RBAC tests, run `pytest tests/api/test_rules_crud.py -v`
- [x] `tests/api/test_entities.py` — collapse RBAC tests, run `pytest tests/api/test_entities.py -v`
- [x] `tests/api/test_bom_items.py` — collapse RBAC tests, run `pytest tests/api/test_bom_items.py -v`
- [x] `tests/api/test_bom_item_rules.py` — collapse RBAC tests, run `pytest tests/api/test_bom_item_rules.py -v`
- [x] `tests/api/test_versions.py` — collapse RBAC tests, run `pytest tests/api/test_versions.py -v`
- [x] Verify: no business logic tests were collapsed (only pure role → status code tests)
- [x] Run `ruff check app/ tests/` — no errors
- [x] Run `pytest` — full suite passes, zero regressions
- [x] Update test count in `docs/TESTING.md`

---

## Session Log

### Session 1 — 2026-04-07
- **Improvement**: 1 (mutation testing with mutmut)
- **Completed**: All checklist items (1a–1e)
- **Findings**:
  - `rule_engine.py`: 1013 mutants, 840 killed, 110 timeout, 63 survived. 24 equivalent (logger/message), 39 real.
  - `versioning.py`: 392 mutants, 24 killed, 241 timeout, 127 no-tests (uncovered by scoped runner), 0 survived.
  - Key gaps found: `_normalize_user_input` empty string/list handling, `_auto_select_value` single-option logic, `_compare_dates` with string dates, `_sum_line_totals` recursive child totals, `_check_completeness` hidden field logic, `_resolve_target_version` multi-entity filtering.
  - mutmut v3 requires `also_copy` for `app/` directory (copies tests to `mutants/` dir).
  - mutmut configuration added to `pyproject.toml` under `[tool.mutmut]`.
- **Blocked**: None
- **Next**: Improvement 2 (numeric edge cases for BOM)

### Session 2 — 2026-04-07
- **Improvement**: 2 (numeric edge cases for BOM)
- **Completed**: All checklist items (2a–2h)
- **Findings**:
  - All 9 tests pass (2a split into two: max_unit_price and max_quantity).
  - Decimal precision is correctly preserved at Numeric(12,4) boundaries — no truncation or overflow.
  - Zero unit_price is accepted for COMMERCIAL items (intentional for promotional items — documented in test).
  - Accumulation of 20 items at 0.0001 produces exact 0.0020 — no float conversion issues.
  - Aggregation of 3 large-quantity items (33333333.3333 each) correctly sums to 99999999.9999.
  - Zero and negative field values correctly exclude items (confirmed `_resolve_bom_quantity` returns None for `<= 0`).
  - No behavioral issues discovered — all edge cases behave as expected.
- **Blocked**: None
- **Next**: Improvement 3 (malformed input resilience)

### Session 3 — 2026-04-07
- **Improvement**: 3 (malformed input resilience)
- **Completed**: All checklist items (3a–3d)
- **Findings**:
  - 16 tests written across 4 classes: TestWrongTypes (5), TestMissingFields (4), TestInvalidValues (5), TestEmptyPayloads (2).
  - All Pydantic validation errors return 422 with field-specific error references.
  - Negative quantity is correctly caught at router level with 400 (not Pydantic 422).
  - Empty criteria list is rejected by the `check_not_empty` field validator on `RuleConditions`.
  - Null body (`content="null"`) correctly returns 422.
  - No behavioral issues discovered — all malformed inputs are properly rejected.
- **Blocked**: None
- **Next**: Improvement 4 (consolidate RBAC tests with parametrize)

### Session 4 — 2026-04-07
- **Improvement**: 4 (consolidate RBAC tests with parametrize)
- **Completed**: All checklist items
- **Findings**:
  - 7 test files refactored: `test_fields.py`, `test_values.py`, `test_rules_crud.py`, `test_entities.py`, `test_bom_items.py`, `test_bom_item_rules.py`, `test_versions.py`.
  - ~80 standalone RBAC test methods collapsed into ~25 parametrized methods using `@pytest.mark.parametrize` + `request.getfixturevalue()`.
  - Test case count preserved at 978 — parametrize generates the same number of test cases, just fewer methods.
  - Pattern: `("headers_fixture", "expected_status")` tuples with `(None, 401)` for unauthenticated where applicable.
  - Entities have `user_headers → 200` for list/read (unlike other resources which give 403).
  - `test_bom_item_rules.py` used a different structure (lifecycle tests) — parametrized `admin_headers`/`author_headers` for the full-access test.
  - Only pure RBAC tests (role → status code) were collapsed; all business logic tests remain as standalone methods.
  - ruff reformatted 2 files (whitespace only).
- **Blocked**: None
- **Next**: Improvement 5 (if defined in plan)
