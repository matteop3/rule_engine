# Code Quality Cleanup Plan

A standalone, agent-ready playbook for paying down readability and duplication
debt in the `rule_engine` codebase. Self-contained on purpose: a fresh
contributor (human or AI) should be able to pick up any phase by reading this
file alone, without replaying prior chats.

## Purpose

Mechanical and structural cleanup of the existing code under `app/`. No new
features, no architectural changes, no dependency changes, no semantic
changes. The goal is to make the codebase easier to read and maintain — for
humans and for AI assistants — and to remove accumulated tactical debt without
disturbing behavior.

## Working agreement

| Constraint | Rule |
|---|---|
| Scope | `app/` only (Tier A+B). `tests/` is out of scope, except surgical fixes if a refactor breaks a fixture. |
| Public behavior | Must remain unchanged. No API changes, no schema changes, no migration changes. |
| Architecture | Untouched. Models, services, routers, dependencies layout stays as-is. |
| Dependencies | No additions, no removals, no version changes. |
| Per-phase verification | `ruff check .`, `ruff format --check .`, `mypy app/`. Must be green before the next phase starts. |
| Final verification | One full `pytest` run after the last phase. Not run between phases. |
| Language in code | English everywhere — comments, docstrings, log messages, identifiers. |
| Comment style | Describe state as-is. No incremental-change language ("we changed", "previously", "now does"), no references to phase numbers, ADR decision numbers, or internal planning docs. |
| Docstring style | Concise. One-line summary plus optional bullets only when an edge case or surprise warrants it. Multi-paragraph rationale belongs in ADRs (`docs/ADR_*.md`), not in code. |
| Logging | Keep state-change `info` and real exception `error/critical`. Drop entry/exit `info` that duplicates the FastAPI access log. Drop `logger.warning` that immediately precedes a `raise HTTPException` for a 4xx. Drop narrative `debug` lines in the rule engine waterfall. |
| Defensive double-belt | The `status == Enum.X or status == Enum.X.value` pattern is preserved (kept once via a helper) — the redundancy was historically necessary; do not remove it. |

## In scope

- Naming consistency on guard helpers.
- Mechanical duplication removal where the duplication is structural (8 near-identical fetchers, 5 inlined finalized-checks, etc.).
- Unfolding two thin abstractions whose generality is not earning its complexity.
- Trimming docstrings that exceed ~6 lines and replicate ADR rationale.
- Stripping comments that reference internal planning documents or phase/decision numbers.
- Removing banner comments (`# === SECTION ===`) from files under ~400 LOC.
- Reducing redundant logging.
- One small structural move: lifecycle status guards from `app/routers/configurations.py` to `app/dependencies/validators.py`.

## Out of scope

The following items were considered and explicitly excluded:

- The `_aggregate_bom_items` re-parenting algorithm — semantically fragile, well covered by tests, no readability win is worth the regression risk.
- Mixed `BOMType.TECHNICAL.value` vs literal `"COMMERCIAL"` comparisons — left as-is by decision.
- `app/services/auth.py`, `app/core/security.py`, `app/core/cache.py`, `app/core/logging.py`, `app/core/rate_limit.py`, `app/core/config.py` — appear well-sized at first inspection. Revisit only if a Phase touches them transitively.
- Migrations under `alembic/`.
- Tests under `tests/`.
- Pagination metadata, API versioning, i18n, expression parsers, and other items already documented as deferred in the README "Intentional Scope Boundaries" table.

## Naming convention for guards

Two prefixes only, applied across `app/dependencies/` and any router-local
helpers that survive in place:

| Prefix | Meaning | Examples |
|---|---|---|
| `validate_*` | Input integrity check (shape/coherence of supplied data, FK existence, no-duplicate IDs). | `validate_input_data_integrity`, `validate_field_belongs_to_version`, `validate_catalog_reference` |
| `require_*` | Business precondition / lifecycle state guard. | `require_draft_status`, `require_complete_status`, `require_user_can_access_configuration` |

Existing `check_*` helpers fold into one of the two. No `assert_*` (collides
with the Python keyword and pytest idioms). Rename pure — signatures and
behavior unchanged.

## Phase plan

Phases are ordered by independence and review difficulty: each is mergeable on
its own. Earlier phases are mechanical, later phases touch business logic.

### Phase 1 — Mechanical comment cleanup

**Touches**: any file under `app/` containing the patterns below.

**Actions**:
- Delete every comment referencing internal planning documents:
  `PART_CATALOG_ANALYSIS_AND_PLAN`, `CATALOG_*_PLAN`, `CUSTOM_ITEMS_PLAN`,
  `BOM_ANALYSIS_AND_PLAN`, `ENGINEERING_BOM_*_PLAN`, or any `# (Phase N)` /
  `# (Analysis Section N.N)` / `# (decision #N)` markers. ADRs are the canonical
  reference; cross-references to them inside code add nothing.
- Remove banner comments (lines matching `^# =====+$` plus their title line) in
  files under ~400 LOC. Keep them in `app/services/rule_engine.py`,
  `app/models/domain.py`, and `app/routers/configurations.py` where the file
  size justifies the navigation aid.

**Find by**: `grep -RnE '(PLAN|Phase [0-9]|Analysis Section|decision #[0-9])' app/`
and `grep -RnE '^# ====' app/`.

**Done when**: ruff+mypy green, no remaining matches for the patterns above
outside the three large files.

### Phase 2 — Logging cleanup

**Touches**: routers (`app/routers/*.py`) and services (`app/services/*.py`).

**Actions**:
- Remove `logger.warning(...)` calls whose only purpose is to precede a
  `raise HTTPException(status_code=4xx, ...)` in the same control-flow branch.
  4xx outcomes are normal user errors and the access log already records them.
- Remove `logger.info(f"Creating/Updating/Deleting/Listing/Reading X by user Y")`
  lines at the entry of CRUD endpoints — duplicates the FastAPI access log.
- Remove narrative `logger.debug` calls in
  `app/services/rule_engine.py` (e.g. `Processing field {x}`,
  `Field {x} processed: ...`). Keep diagnostic `debug` lines that report
  cache hits/misses, version resolution, and BOM/SKU outcomes.

**Keep**:
- `logger.error(..., exc_info=True)` on real exceptions.
- `logger.critical(...)` on unexpected paths.
- `logger.info(...)` on actual state changes (publish, archive, version cloned,
  BOM materialized, configuration finalized).

**Done when**: ruff+mypy green; spot-check one router and one service to
confirm log output still tells a useful operational story.

### Phase 3 — Docstring trim (with calibration checkpoint)

**Touches**: classes and functions whose docstring exceeds ~6 lines.

**Actions**:
- Apply the trim to **three samples first** as a calibration commit:
  - `AuditMixin` in [app/models/domain.py](../app/models/domain.py)
  - `BOMItem` class in the same file
  - `create_configuration` endpoint in [app/routers/configurations.py](../app/routers/configurations.py)
- Pause after the calibration commit and surface the diff for review of style
  and length. Adjust the target tightness if the reviewer wants tighter or
  looser.
- After confirmation, sweep the rest:
  - All `domain.py` model classes (rationale already in ADRs).
  - `RuleEngineService.calculate_state`, `_generate_sku`,
    `_evaluate_*` family — keep one-line intent only.
  - Endpoint docstrings in `configurations.py` and other routers — keep what
    surfaces in OpenAPI as user-facing description, drop sections that
    duplicate the README or ADRs (Use Cases, Workflow, Access Control bullets).

**Target shape**: one-line summary, optional `Args`/`Returns`/`Raises` only when
not obvious, optional one bullet on a non-obvious edge case. Architectural
rationale lives in ADRs.

**Done when**: ruff+mypy green; calibration was approved; no docstring in
`app/` exceeds ~6 lines except where the function's own complexity (e.g.,
`_aggregate_bom_items`) warrants it.

### Phase 4 — Guard naming convergence

**Touches**: `app/dependencies/validators.py`,
`app/dependencies/fetchers.py`, `app/routers/configurations.py`, any caller of
the renamed helpers.

**Actions**:
- Rename `check_*` helpers raising `HTTPException` to either `validate_*`
  (input integrity) or `require_*` (state precondition) per the convention
  table above. Concrete renames:
  - `check_user_can_access_configuration` → `require_user_can_access_configuration`
  - `check_soft_delete_permission` → `require_soft_delete_permission`
- Update every call site. No signature changes, no behavior changes.
- Skip imports in `tests/` unless the test fails to compile after the rename.

**Done when**: ruff+mypy green; `grep -RnE 'def (check|verify|ensure)_' app/`
returns nothing except cycle/graph detection helpers in
`app/services/engineering_template.py` (those are not HTTP guards and stay).

### Phase 5 — Fetcher consolidation

**Touches**: [app/dependencies/fetchers.py](../app/dependencies/fetchers.py).

**Actions**:
- Introduce a private generic helper:

  ```python
  def _fetch_or_404(db: Session, model: type[T], ident: int | str, label: str) -> T:
      ...
  ```

  with the existing `id > 0` guard for integer IDs and the missing-row 404 raise.
- Reduce each `fetch_*_by_id` function to a one-line shim that delegates to
  `_fetch_or_404`. The public functions stay (they are imported elsewhere) —
  only their bodies shrink.
- The `Path(..., gt=0)` HTTP dependency wrappers (`get_*_or_404`) are unchanged.

**Done when**: ruff+mypy green; the file dropped from ~234 LOC to ~80 LOC; all
existing imports of `fetch_*_by_id` and `get_*_or_404` still resolve.

### Phase 6 — Configuration helpers consolidation

**Touches**: [app/routers/configurations.py](../app/routers/configurations.py),
[app/dependencies/validators.py](../app/dependencies/validators.py).

**Actions**:
- Introduce a `_is_finalized(config: Configuration) -> bool` helper at the top of
  `configurations.py`. Body keeps the historical defensive form:

  ```python
  return (
      config.status == ConfigurationStatus.FINALIZED
      or config.status == ConfigurationStatus.FINALIZED.value
  )
  ```

  Replace every inlined occurrence of that double-belt with a `_is_finalized(config)`
  call. The defensive `or` lives in exactly one place from now on.
- Make `calculate_configuration_state` the single constructor of
  `CalculationRequest`. Refactor `load_and_calculate_configuration` to call it
  instead of building a `CalculationRequest` inline. The snapshot short-circuit
  for FINALIZED configurations stays in the endpoint.
- Move `require_draft_status` and `require_complete_status` from
  `configurations.py` to `app/dependencies/validators.py` (lifecycle status
  guards are generic and the module already hosts equivalents like
  `validate_version_is_draft`). Re-export from `app/dependencies/__init__.py`
  if other callers exist; update imports in `configurations.py`.
- Leave the configuration-input-specific validators
  (`validate_input_data_integrity`, `validate_user_can_save_version`,
  `validate_price_list_exists`, `validate_version_not_orphaned`,
  `get_configuration_or_404`, `convert_to_field_input_states`,
  `calculate_configuration_state`, `get_latest_published_version`) where they
  are. They are router-local concerns and moving them earns nothing.

**Done when**: ruff+mypy green; `grep -n 'FINALIZED.value' app/routers/configurations.py`
returns one match (inside `_is_finalized`); `CalculationRequest(` is constructed
in exactly one place.

### Phase 7 — Rule engine abstraction unfold

**Touches**: [app/services/rule_engine.py](../app/services/rule_engine.py).

**Actions**:
- Remove `_evaluate_boolean_layer`. Inline its body into the three callers as
  short, explicit methods:
  - `_evaluate_visibility(field, all_rules, running_context, type_map) -> bool`
  - `_evaluate_editability(field, all_rules, running_context, type_map) -> bool`
  - `_evaluate_mandatory(field, all_rules, running_context, type_map) -> bool`
  Each method stays ~6 lines: filter rules by type, return field default if no
  rules, OR-evaluate the rules with the layer's specific true/false mapping.
  No flag parameters, no general helper.
- Remove `_build_index`. Replace its three usages with three named indexers:
  - `_index_values_by_field(values: list[CachedValue]) -> dict[int, list[CachedValue]]`
  - `_index_rules_by_target_value(rules: list[CachedRule]) -> dict[int, list[CachedRule]]`
  - `_index_bom_rules_by_item(bom_rules: list[CachedBOMItemRule]) -> dict[int, list[CachedBOMItemRule]]`
  Strongly typed signatures, no `Any`, no `lambda`.
- Behavior is unchanged. The aggregation algorithm `_aggregate_bom_items`,
  `_prune_bom_tree`, `_resolve_bom_quantity`, `_evaluate_bom`,
  `_build_bom_output`, `_build_technical_flat`, `_sum_line_totals`,
  `_evaluate_rule`, `_check_criterion`, the comparison helpers, and the SKU
  pipeline are not touched in this phase.

**Done when**: ruff+mypy green; both removed helpers no longer appear in the
file; the three new indexers and three explicit boolean-layer methods replace
them.

### Phase 8 — Final verification

**Actions**:
- `ruff check .`, `ruff format --check .`, `mypy app/` — should already be
  green per phase, run once more for coverage.
- Full `pytest` run (`pytest -q`). Expected runtime ~10–11 minutes.
- Inspect coverage report (`pytest --cov=app --cov-report=term-missing`) for any
  newly uncovered branches caused by the dedup work.
- If anything fails, the failure points to a missed semantic-equivalence in a
  prior phase — fix in place, do not skip the test.

**Done when**: full pytest green, lint green, type-check green; commit history
shows one PR per phase (or one stacked PR with one commit per phase) for review.

## Verification matrix

| Phase | Commands run | Pass criteria |
|---|---|---|
| 1 | `ruff check .`, `ruff format --check .`, `mypy app/` | All green; targeted greps return zero internal-doc references and zero banners under 400 LOC. |
| 2 | same + manual log spot-check | All green; one router and one service still emit useful state-change logs at INFO. |
| 3 | same + reviewer sign-off on calibration | All green; calibration approved; no docstring >6 lines except justified ones. |
| 4 | same + targeted grep for `def check_` | All green; no remaining `check_*` HTTP guards. |
| 5 | same | All green; LOC reduction in `fetchers.py` ≈ 60%. |
| 6 | same + targeted greps | All green; `_is_finalized` exists and is the only place with `FINALIZED.value` defensive check; one `CalculationRequest(` construction site. |
| 7 | same | All green; `_evaluate_boolean_layer` and `_build_index` gone; three explicit boolean methods and three typed indexers in place. |
| 8 | full `pytest`, `ruff`, `mypy` | All green. |

## Notes for a fresh agent

- The codebase has saved memories at `~/.claude/projects/-home-matteop3-Workspace-rule-engine/memory/` that capture user preferences (e.g., docstring/comment style, test execution discipline). Read `MEMORY.md` first.
- The architectural decision records under `docs/ADR_*.md` are authoritative for behavior. This plan does **not** change anything documented there. If a phase's mechanical work appears to alter ADR-described semantics, stop and re-read the relevant ADR — the change should be reverted, not pursued.
- The CI pipeline at `.github/workflows/ci.yml` runs `ruff check`, `ruff format --check`, `mypy app/`, and `pytest --cov`. Each phase commit must pass the first three; the full suite is green-checked at Phase 8 only.
- Full pytest runs take roughly ~10–11 minutes. Do not poll. Run once at Phase 8 and wait for the result.
- If a refactor reveals a bug, surface it as a separate issue. Do not fix bugs inside a quality cleanup phase — the diff must remain semantically null for the cleanup PRs to be reviewable.
- The user prefers one bundled PR for tightly coupled refactors and one PR per independent phase for cleanly separable work. When in doubt, ask before merging strategy decisions.

## Out-of-scope inventory (do not touch)

For unambiguous handoff: the following identifiers were reviewed and are
deliberately untouched by every phase above. A future agent that wants to
modify them should open a separate plan, not extend this one.

- `RuleEngineService._aggregate_bom_items`, `._prune_bom_tree`,
  `._resolve_bom_quantity`, `._build_technical_flat` — semantic core, fragile.
- `BOMType` enum and any `bom_type == "COMMERCIAL"` literal comparisons.
- `app/services/auth.py`, `app/services/users.py`,
  `app/core/security.py`, `app/core/cache.py`, `app/core/logging.py`,
  `app/core/rate_limit.py`, `app/core/config.py`.
- `alembic/`, `tests/`, `seed_data.py`.
- All schemas under `app/schemas/`.
- `app/middleware/request_id.py`.
- `app/main.py`, `app/database.py`, `app/exceptions.py`.

If a phase transitively requires changes here, stop and consult the user.
