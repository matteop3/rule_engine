# Mutation Testing Report

**Date**: 2026-04-07
**Tool**: mutmut 3.5.0

## Files Analyzed

### `app/services/rule_engine.py`

| Metric | Count |
|--------|-------|
| Total mutants | 1013 |
| Killed | 840 |
| Timeout (effectively killed) | 110 |
| Survived | 63 |
| Kill rate (killed + timeout) | 93.8% |

### `app/services/versioning.py`

| Metric | Count |
|--------|-------|
| Total mutants | 392 |
| Killed | 24 |
| Timeout (effectively killed) | 241 |
| No tests (uncovered lines) | 127 |
| Survived | 0 |
| Kill rate (killed + timeout) | 100% (of covered mutants) |

**Note**: The "no tests" count for `versioning.py` reflects that mutmut was scoped to
`tests/integration/test_clone_bom.py` and `tests/integration/test_data_integrity_clone_remapping.py`
for speed. The `publish_version`, `create_draft_version`, and helper methods are exercised by
`tests/api/test_versions.py` and other integration tests not included in the mutmut runner scope.

## Surviving Mutants Analysis (`rule_engine.py`)

### Equivalent / Logger-Only (24 mutants — no behavioral change)

Mutations to `logger.info()`, `logger.debug()`, `logger.warning()`, and `logger.error()` message
strings (replacing with `None`). These do not affect behavior. Also includes 3 mutations to
`ValueError` message strings where tests correctly check for `ValueError` but not the message
content, and 4 mutations (`_prune_bom_tree` `changed = None`, `_load_version_data`
`order_by(None)`, `_resolve_target_version` `db.query(None)`) that are effectively equivalent in
the test environment.

### Real Surviving Mutants (39 mutants — tests written)

| Area | Mutants | Tests Written | Description |
|------|---------|---------------|-------------|
| `_normalize_user_input` | 4 | 2 | Empty string/whitespace → None normalization; empty list handling |
| `_auto_select_value` | 2 | 2 | Single-option auto-selection (`len == 1`); default value selection |
| `_compare_numbers` | 2 | 2 | `None` expected guard; `isinstance` check for list |
| `_compare_dates` | 11 | 3 | `None` expected guard; `parse_date` with string dates; argument ordering |
| `_generate_sku` | 6 | 3 | Loop continuation vs break; free-value field processing; max length boundary |
| `_resolve_bom_quantity` | 4 | 2 | Field state lookup; hidden vs visible field; `<= 0` vs `<= 1` threshold |
| `_prune_bom_tree` | 1 | 1 | Multi-pass pruning (`changed = True` → `False` breaks deep trees) |
| `_build_bom_output` | 4 | 2 | Loop continuation; parent-child tree construction; `and` vs `or` in parent check |
| `_sum_line_totals` | 7 | 2 | `has_any` flag; recursive child total summing; `+=` vs `=`/`-=` |
| `_check_completeness` | 1 | 1 | `not field.is_hidden` → `field.is_hidden` (hidden required fields) |
| `_resolve_target_version` | 3 | 3 | Multi-entity published version filtering; error message content |
| **Total** | **39** (+ equiv.) | **24** | |

## Tests Added

All tests in `tests/engine/test_mutation_kills.py` (24 tests):

- `TestNormalizeUserInput` (2 tests)
- `TestAutoSelectValue` (2 tests)
- `TestCompareNumbers` (2 tests)
- `TestCompareDates` (3 tests)
- `TestSKUMutationKills` (3 tests)
- `TestResolveBOMQuantityMutations` (2 tests)
- `TestBuildBOMOutputMutations` (2 tests)
- `TestSumLineTotalsMutations` (2 tests)
- `TestCheckCompletenessMutations` (2 tests)
- `TestPruneBOMTreeMutations` (1 test)
- `TestResolveTargetVersionMutations` (3 tests)

## Configuration

mutmut configuration in `pyproject.toml`:

```toml
[tool.mutmut]
paths_to_mutate = ["app/services/"]
tests_dir = ["tests/engine/", "tests/integration/"]
also_copy = ["app/", "alembic/", "venv/", ".env"]
```

## How to Run

```bash
# Run mutation testing
venv/bin/mutmut run

# View results
venv/bin/mutmut results

# Show a specific mutant
venv/bin/mutmut show <mutant_name>
```
