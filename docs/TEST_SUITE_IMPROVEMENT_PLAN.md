# Test Suite Improvement Plan

## Instructions for the Agent

This document describes four improvements to the test suite, ordered by priority. Each improvement is a self-contained task with clear scope, context files, and acceptance criteria.

### How to work

1. **Work on one improvement at a time.** Do not start the next until the current one is fully complete and all tests pass.
2. **Read the context files** listed for each improvement before writing any code. Follow existing patterns exactly.
3. **Run the full test suite** (`pytest`) after completing each improvement. Zero regressions.
4. **No incremental-change language** in code comments or docstrings. Do not write "New", "Added", "Modified". Describe code as if it has always existed.
5. **Do not modify existing tests** unless explicitly instructed (Improvement 4 is a refactor of existing tests).
6. **Run `ruff check app/ tests/` and `ruff format app/ tests/`** before considering any improvement complete.

### Key project commands

```bash
# Run full test suite
pytest

# Run specific test file
pytest tests/engine/test_bom_edge_cases.py -v

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run mutation testing (after installing mutmut)
mutmut run --paths-to-mutate=app/services/rule_engine.py --tests-dir=tests/engine/

# Lint
ruff check app/ tests/
ruff format app/ tests/
```

---

## Improvement 1: Mutation Testing with mutmut

**Goal**: Identify tests that execute code but fail to catch bugs. Mutation testing modifies the source code (e.g., flips `>` to `>=`, changes `True` to `False`) and checks if at least one test fails for each mutation. Surviving mutants indicate weak or missing assertions.

**Priority**: High — this reveals hidden weaknesses that line coverage cannot detect.

### Step 1a: Install mutmut

Add `mutmut` to dev dependencies:

```bash
pip install mutmut
```

Do NOT add it to `requirements.txt` (it is a dev-only tool). If the project has a `requirements-dev.txt` or `pyproject.toml` `[project.optional-dependencies]` section, add it there. Otherwise just install it locally.

### Step 1b: Run mutmut on the rule engine service

This is the highest-value target — it contains the waterfall logic, rule evaluation, BOM evaluation, SKU generation, and completeness check.

```bash
mutmut run \
  --paths-to-mutate=app/services/rule_engine.py \
  --tests-dir=tests/ \
  --runner="pytest tests/engine/ tests/integration/ -x -q --no-header --tb=no"
```

Notes:
- Use `-x` (stop on first failure) in the runner to speed up each mutation check.
- Scope the runner to `tests/engine/` and `tests/integration/` — these are the tests that exercise the rule engine. API tests are too slow and don't add signal here.
- This will take a long time (potentially 30-60 minutes depending on hardware). Run it once, analyze results, then fix.

### Step 1c: Run mutmut on the versioning service

```bash
mutmut run \
  --paths-to-mutate=app/services/versioning.py \
  --tests-dir=tests/ \
  --runner="pytest tests/integration/test_clone_bom.py tests/integration/test_data_integrity_clone_remapping.py -x -q --no-header --tb=no"
```

### Step 1d: Analyze results

```bash
mutmut results
mutmut show <mutant_id>  # For each surviving mutant
```

For each surviving mutant:
1. Read the mutation (what was changed).
2. Determine if the mutation is semantically equivalent (i.e., the change doesn't actually affect behavior). If so, ignore it.
3. If the mutation is meaningful (e.g., flipping a comparison operator in rule evaluation), write a test that fails on the mutated code. Add it to the appropriate existing test file.

### Step 1e: Re-run mutmut to confirm

After writing new tests, re-run mutmut on the same files. The previously surviving mutants should now be killed.

### Acceptance criteria

- [ ] mutmut installed and runnable
- [ ] `app/services/rule_engine.py` analyzed — surviving mutants documented
- [ ] `app/services/versioning.py` analyzed — surviving mutants documented
- [ ] Tests written for all non-equivalent surviving mutants
- [ ] `pytest` — full suite passes, zero regressions
- [ ] Create a brief report in `docs/MUTMUT_REPORT.md` with: date, files analyzed, total mutants, killed, survived, equivalent, tests added

---

## Improvement 2: Numeric Edge Cases for BOM

**Goal**: Verify that BOM calculations handle boundary values correctly — precision limits, zero prices, large quantities, decimal accumulation.

**Priority**: Medium — prevents silent data corruption in production.

### Context files to read

| File | Why |
|------|-----|
| `app/models/domain.py` — `BOMItem` model | Column definitions: `quantity Numeric(12,4)`, `unit_price Numeric(12,4)`. Understand the precision limits. |
| `app/services/rule_engine.py` — `_evaluate_bom()`, `_resolve_bom_quantity()`, `_build_bom_output()`, `_aggregate_bom_items()` | The code that performs arithmetic on quantities and prices. |
| `tests/engine/test_bom_evaluation.py` | Existing BOM evaluation test pattern. Follow the same fixture and assertion style. |
| `tests/engine/test_bom_quantity.py` | Existing quantity resolution tests. |
| `app/schemas/engine.py` — `BOMLineItem`, `BOMOutput` | Response schema — `line_total` and `commercial_total` are `Decimal | None`. |

### Test file

Create `tests/engine/test_bom_edge_cases.py`.

### Tests to write

Each test needs its own fixture scenario (or a shared one with enough BOM items to cover the cases). Follow the pattern in `test_bom_evaluation.py`: create entity, version, fields, values, BOM items, BOM item rules directly via ORM, then call `RuleEngineService().calculate_state()`.

#### 2a. Decimal precision at Numeric(12,4) boundary

Create a COMMERCIAL BOM item with `unit_price = Decimal("99999999.9999")` (max for 12,4) and `quantity = Decimal("1")`. Verify `line_total` equals the price exactly, with no truncation or overflow.

Then test `quantity = Decimal("99999999.9999")` with `unit_price = Decimal("1")`. Same verification.

#### 2b. Small decimal quantities

Create a BOM item with `quantity = Decimal("0.0001")` (minimum non-zero for 4 decimal places) and `unit_price = Decimal("10000.0000")`. Verify `line_total = Decimal("1.0000")`.

#### 2c. Zero price on COMMERCIAL item

Create a COMMERCIAL BOM item with `unit_price = Decimal("0.0000")` and `quantity = Decimal("5")`. Verify `line_total = Decimal("0.0000")`. This tests that zero is a valid price (legitimate for promotional items).

Note: the CRUD router requires `unit_price` to be non-null for COMMERCIAL items, but does not reject zero. If this should be rejected, this test will reveal the missing validation — document the finding.

#### 2d. Accumulation precision with many items

Create 20 COMMERCIAL BOM items, each with `unit_price = Decimal("0.0001")` and `quantity = Decimal("1")`. Verify `commercial_total = Decimal("0.0020")` exactly (not `0.0019999...`). This catches floating-point accumulation errors if `Decimal` is accidentally converted to `float` somewhere in the chain.

#### 2e. Aggregation with large quantities

Create 3 COMMERCIAL BOM items with the same `part_number`, each `quantity = Decimal("33333333.3333")`, `unit_price = Decimal("1.0000")`. After aggregation, the total quantity should be `Decimal("99999999.9999")`. Verify `line_total` equals this value.

#### 2f. Quantity from field with zero value

Create a BOM item with `quantity_from_field_id` pointing to a NUMBER field. Provide `value = 0` in the input state. Verify the item is **excluded** from the BOM output (zero quantity means exclusion — verify this is the current behavior by reading `_resolve_bom_quantity()`).

#### 2g. Quantity from field with negative value

Same setup, provide `value = -5`. Verify the item is excluded (negative quantity means exclusion).

#### 2h. Quantity from field with very large value

Provide `value = 99999999.9999`. Verify the item is included with the correct quantity.

### Acceptance criteria

- [ ] `tests/engine/test_bom_edge_cases.py` created with 8 tests
- [ ] All tests pass
- [ ] Any discovered behavioral issues documented as comments in the test file (e.g., "zero price is accepted — intentional or should be validated?")
- [ ] `pytest` — full suite passes, zero regressions

---

## Improvement 3: Malformed Input Resilience

**Goal**: Verify that the API returns clear, correct error responses when receiving malformed payloads. Pydantic handles most of this, but without tests there is no guarantee that a future schema change doesn't silently accept bad data.

**Priority**: Medium — hardens the API boundary.

### Context files to read

| File | Why |
|------|-----|
| `app/schemas/bom_item.py` | BOM item create/update schemas — field types, required fields, constraints. |
| `app/schemas/rule.py` | `RuleConditions` schema — criteria validation, operator enum. |
| `app/schemas/field.py` | Field create schema — data_type enum, is_free_value constraint. |
| `app/routers/bom_items.py` | BOM item router — see which validations happen at router level vs schema level. |
| `tests/api/test_fields.py` | Existing API test pattern. |

### Test file

Create `tests/api/test_input_validation.py`.

### Tests to write

All tests use the `client` and `admin_headers` fixtures. They POST or PATCH with malformed payloads and assert `422` (Pydantic validation error) or `400` (router-level validation).

#### 3a. Wrong types

```python
class TestWrongTypes:
```

| Test | Payload | Expected |
|------|---------|----------|
| `test_field_create_non_string_data_type` | `{"data_type": 123, ...}` | 422 |
| `test_bom_item_create_non_numeric_quantity` | `{"quantity": "abc", ...}` | 422 |
| `test_bom_item_create_non_numeric_unit_price` | `{"unit_price": "free", ...}` | 422 |
| `test_rule_create_non_integer_field_id_in_conditions` | `{"conditions": {"criteria": [{"field_id": "abc", ...}]}}` | 422 |
| `test_configuration_create_non_list_data` | `{"data": "not a list", ...}` | 422 |

#### 3b. Missing required fields

```python
class TestMissingFields:
```

| Test | Payload | Expected |
|------|---------|----------|
| `test_field_create_missing_name` | `{"entity_version_id": X, "data_type": "string", "is_free_value": true}` (no `name`) | 422 |
| `test_bom_item_create_missing_part_number` | BOM item payload without `part_number` | 422 |
| `test_rule_create_missing_conditions` | Rule payload without `conditions` | 422 |
| `test_configuration_create_missing_entity_version_id` | Config payload without `entity_version_id` | 422 |

#### 3c. Invalid enum/constraint values

```python
class TestInvalidValues:
```

| Test | Payload | Expected |
|------|---------|----------|
| `test_field_create_invalid_data_type` | `{"data_type": "xml", ...}` | 422 |
| `test_bom_item_create_invalid_bom_type` | `{"bom_type": "HYBRID", ...}` | 422 |
| `test_rule_create_invalid_operator` | `{"conditions": {"criteria": [{"operator": "LIKE", ...}]}}` | 422 |
| `test_rule_create_empty_criteria` | `{"conditions": {"criteria": []}}` | 422 |
| `test_bom_item_create_negative_quantity` | `{"quantity": "-5", ...}` | 400 (router validation) |

#### 3d. Empty and null payloads

```python
class TestEmptyPayloads:
```

| Test | Action | Expected |
|------|--------|----------|
| `test_field_create_empty_body` | `POST /fields/` with `{}` | 422 |
| `test_bom_item_create_null_body` | `POST /bom-items/` with `None` | 422 |

### Acceptance criteria

- [ ] `tests/api/test_input_validation.py` created with ~15 tests
- [ ] All tests pass with correct status codes
- [ ] Each test asserts both the status code and that the error response body contains a meaningful field reference (e.g., `"quantity"` appears in the validation error for bad quantity)
- [ ] `pytest` — full suite passes, zero regressions

---

## Improvement 4: Consolidate RBAC Tests with Parametrize

**Goal**: Reduce test count by ~80-100 without losing coverage. Currently every CRUD endpoint has 3-4 separate test methods for RBAC (admin OK, author OK, user 403, unauthenticated 401). These can be collapsed into parametrized tests.

**Priority**: Low — this is maintenance/cleanup, not new coverage. Do it incrementally when touching these files for other reasons.

**Risk**: Medium — refactoring tests can introduce false greens. Run `pytest` after each file change.

### Pattern to follow

Before (current — 4 separate tests):
```python
def test_admin_can_list_fields(self, client, admin_headers, draft_field):
    response = client.get(f"/fields/?entity_version_id={draft_field.entity_version_id}", headers=admin_headers)
    assert response.status_code == 200

def test_author_can_list_fields(self, client, author_headers, draft_field):
    response = client.get(f"/fields/?entity_version_id={draft_field.entity_version_id}", headers=author_headers)
    assert response.status_code == 200

def test_regular_user_cannot_list_fields(self, client, user_headers, draft_field):
    response = client.get(f"/fields/?entity_version_id={draft_field.entity_version_id}", headers=user_headers)
    assert response.status_code == 403

def test_unauthenticated_cannot_list_fields(self, client, draft_field):
    response = client.get(f"/fields/?entity_version_id={draft_field.entity_version_id}")
    assert response.status_code == 401
```

After (1 parametrized test):
```python
@pytest.mark.parametrize(
    "headers_fixture, expected_status",
    [
        ("admin_headers", 200),
        ("author_headers", 200),
        ("user_headers", 403),
        (None, 401),
    ],
)
def test_list_fields_rbac(self, client, headers_fixture, expected_status, request, draft_field):
    """RBAC: admin/author can list fields, user gets 403, unauthenticated gets 401."""
    headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
    response = client.get(
        f"/fields/?entity_version_id={draft_field.entity_version_id}",
        headers=headers,
    )
    assert response.status_code == expected_status
```

### Files to refactor (in order)

Apply the pattern to these files. Each file should be committed separately.

| File | Approx. tests removed | Notes |
|------|----------------------|-------|
| `tests/api/test_fields.py` | ~8 → 2 parametrized | List + Read RBAC, Create + Delete RBAC |
| `tests/api/test_values.py` | ~8 → 2 parametrized | Same pattern |
| `tests/api/test_rules_crud.py` | ~10 → 3 parametrized | List, Read, Create RBAC |
| `tests/api/test_entities.py` | ~6 → 2 parametrized | List, Read RBAC |
| `tests/api/test_bom_items.py` | ~8 → 2 parametrized | List, Read RBAC |
| `tests/api/test_bom_item_rules.py` | ~8 → 2 parametrized | List, Read RBAC |
| `tests/api/test_versions.py` | ~6 → 2 parametrized | List, Read RBAC |

### Rules

- **Only collapse pure RBAC tests** (same endpoint, same payload, different role → different status code). Do NOT collapse tests that verify different business logic (e.g., "admin can create" and "admin cannot create in PUBLISHED version" are NOT the same test).
- Keep the DRAFT-only enforcement tests (`409` on PUBLISHED/ARCHIVED) as separate tests — they test a different dimension than RBAC.
- Keep edge case tests, validation tests, and business rule tests as-is.
- After refactoring each file, run `pytest <that_file> -v` to verify the parametrized test generates the same number of test cases as before (4 cases per parametrized test).

### Acceptance criteria

- [ ] Each file refactored one at a time, with `pytest` run after each
- [ ] Total test count is lower but parametrized test cases cover the same scenarios
- [ ] `pytest` — full suite passes, zero regressions
- [ ] No business logic tests were accidentally collapsed into RBAC parametrize

---

## Summary

| # | Improvement | New tests | Effort | Value |
|---|------------|-----------|--------|-------|
| 1 | Mutation testing (mutmut) | Variable (depends on findings) | Medium-High | High |
| 2 | Numeric edge cases BOM | ~8 | Low | Medium |
| 3 | Malformed input resilience | ~15 | Low | Medium |
| 4 | RBAC parametrize consolidation | 0 (refactor) | Medium | Low |
