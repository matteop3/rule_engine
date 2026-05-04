# Architectural Refinement Plan

A standalone, agent-ready playbook for three independent architectural
refinements in the `rule_engine` codebase. Each phase below is self-contained:
read its own "Background to read" list, modify only its "Files to modify"
list, and verify with the per-phase "Done when" criteria. The phases share no
state and can be picked up in any order, or one without the others.

These items are **architectural changes** (they shift contracts or replace
mechanisms) — unlike a pure readability cleanup, the diff is not
behavior-equivalent at the seam being changed. Each phase therefore has its
own dedicated test gate.

## Working agreement

| Constraint | Rule |
|---|---|
| Scope | One phase per PR. Do not bundle two phases into a single diff — they target different concerns. |
| Per-phase verification | `ruff check .`, `ruff format --check .`, `mypy app/`, full `pytest -q`. All four must be green before the phase is considered complete. |
| Public HTTP behavior | Must remain unchanged for happy paths. Error-path response codes/messages may shift slightly where called out explicitly in the phase; if a test fails, **update the test only if the new behavior is documented in this plan as intended**. Otherwise the change is wrong, not the test. |
| Architecture | Each phase changes one architectural contract. Limit changes to the contract under refactor; do not opportunistically restructure unrelated code. |
| Dependencies | No additions, no removals, no version changes. |
| Language in code | English everywhere — comments, docstrings, log messages, identifiers. |
| Comment style | Describe state as-is. No incremental-change language ("we changed", "previously"). No references to phase letters or this plan in code. |
| Test suite | Full `pytest -q` (~18 minutes) is the final gate of every phase. Do not split the suite or skip tests to ship faster. |

---

## Phase A — Transactional contract consistency

### Problem

Two services in `app/services/` commit transactions internally; the rest follow
the "caller owns the transaction" contract. Specifically:

- **Internal commit** (out of band): `AuthService` (`app/services/auth.py`)
  and `UserService` (`app/services/users.py`) call `db.commit()` and
  `db.rollback()` inside their methods.
- **Caller owns transaction** (canonical pattern): `RuleEngineService`,
  `VersioningService`, and the engineering-template service module neither
  commit nor rollback. Their docstrings say so explicitly. Routers wrap
  mutations in the `db_transaction(db, "...")` context manager from
  `app/dependencies/services.py`.

The inconsistency has two concrete consequences:

1. **No multi-step atomicity through `AuthService` / `UserService`.** A
   router that needs to revoke an old refresh token *and* create a new one
   atomically (the rotation path in `POST /auth/refresh`) cannot, because
   both calls commit independently. The current code accepts this race; with
   caller-owns it would be a single transaction.
2. **Two error-handling styles**: `users.py` raises a custom `DatabaseError`
   that the routers translate to HTTP 500; the canonical pattern lets
   `db_transaction` raise `HTTPException(500)` directly.

The goal of this phase is to make `AuthService` and `UserService` follow the
caller-owns contract, and to update their callers to wrap mutations in
`db_transaction`.

### Background to read

Read these files (and only these) before touching any code:

- `app/services/auth.py` — current internal-commit pattern.
- `app/services/users.py` — current internal-commit pattern.
- `app/services/rule_engine.py` — the `RuleEngineService` class docstring is
  the canonical statement of the caller-owns contract.
- `app/services/versioning.py` — same contract, applied to a service that
  performs DB writes.
- `app/services/engineering_template.py` — same contract, module-level
  functions instead of a service class.
- `app/dependencies/services.py` — definition of `db_transaction`. This is
  the context manager every caller will use. Note that it already maps
  `SQLAlchemyError` to `HTTPException(500)`.
- `app/routers/auth.py` — callers of `AuthService`. Endpoints involved:
  `login_for_access_token`, `refresh_access_token`.
- `app/routers/users.py` — callers of `UserService`. Endpoints involved:
  `create_user`, `update_user`, `delete_user`.
- `app/exceptions.py` — defines `DatabaseError`. Check whether anything
  outside `users.py` and its routers references it before deleting.

### Files to modify

- `app/services/auth.py`
- `app/services/users.py`
- `app/routers/auth.py`
- `app/routers/users.py`
- Possibly `app/exceptions.py` (drop `DatabaseError` if unreferenced)

### Actions

1. **Add a class-level docstring contract to `AuthService` and `UserService`**
   matching the wording in `RuleEngineService` and `VersioningService`:
   "Caller owns the transaction. This service does not commit or rollback."

2. **Strip commit/rollback/refresh from `AuthService` methods**
   (`app/services/auth.py`):
   - `create_user_refresh_token`: remove `db.commit()` and `db.refresh(db_token)`.
     Replace with `db.add(db_token)` + `db.flush()` so the autoincrement id is
     populated before return.
   - `verify_user_refresh_token`: remove `db.commit()` after updating
     `last_used_at`. The mutation is now part of the caller's transaction.
   - `revoke_refresh_token`: remove `db.commit()`.
   - `revoke_all_user_refresh_tokens`: remove `db.commit()`.
   - `cleanup_expired_tokens`: remove `db.commit()`.

3. **Strip try/except/commit/rollback from `UserService` methods**
   (`app/services/users.py`):
   - `create_user`, `update_user`, `soft_delete_user`: remove the
     `try/except SQLAlchemyError` wrapper, the explicit `db.commit()`, the
     `db.refresh()` call, the `db.rollback()`, and the `raise DatabaseError(...)`.
     Each method becomes: build/mutate, `db.flush()` if an id is needed
     before return, return.

4. **Wrap router mutations in `db_transaction`** (`app/routers/auth.py`,
   `app/routers/users.py`). Concretely:
   - `login_for_access_token`: wrap the `create_user_refresh_token` call in
     `with db_transaction(db, "issue_refresh_token"):`. The
     `authenticate_user` call before it is read-only and stays outside.
   - `refresh_access_token`: wrap the `verify_user_refresh_token` +
     (when rotation is enabled) `revoke_refresh_token` +
     `create_user_refresh_token` block in **a single**
     `with db_transaction(db, "rotate_refresh_token"):`. This converts the
     current two-commit rotation into one atomic operation — a deliberate
     semantic improvement; flag it in the PR description.
   - `create_user`: wrap the `user_service.create_user(...)` call in
     `db_transaction`. Drop the `except DatabaseError` block and remove the
     `from app.exceptions import DatabaseError` import.
   - `update_user`: same pattern.
   - `delete_user`: same pattern.

5. **Refresh after commit**. `db.refresh(obj)` reloads the row after the
   transaction commits and is needed only when the caller will read
   server-defaulted fields (e.g., `created_at`) from the returned ORM object.
   Where the previous code called `db.refresh(...)`, evaluate:
   - If the route's response model is built from the ORM object (the
     dominant pattern, via FastAPI `response_model`), call `db.refresh(obj)`
     **after** the `with db_transaction(...)` block.
   - If the route returns a manually-built dict (e.g., the auth endpoints
     that return `{"access_token": ..., "refresh_token": ..., "token_type": "bearer"}`),
     no refresh is needed.

6. **Drop `DatabaseError` if it is now unreferenced.** Run
   `grep -RnE '\bDatabaseError\b' app/ tests/`. If the only matches are the
   definition site and tests asserting on it: remove the class from
   `app/exceptions.py` and its import from `users.py`. If tests still rely
   on it, keep the class (the test suite is the contract).

### Risks / gotchas

- **`db.flush()` vs `db.commit()`**: `flush()` runs the SQL but does not end
  the transaction. It is required when the caller reads an autogenerated id
  before the outer commit. Most existing patterns use `db.flush()` then
  `db.refresh()` after commit — keep this idiom.
- **Read-only methods need no transaction**. `authenticate_user`,
  `get_by_id`, `get_by_email` are pure reads; do not wrap their callers.
- **`verify_user_refresh_token` writes `last_used_at`**. It is *not*
  read-only. Routers that call it must wrap it in `db_transaction`.
- **Refresh-token rotation atomicity** (action 4). Today the rotation path
  performs two commits (`revoke` then `create`); a crash between them leaves
  the user with no valid refresh token. The single-transaction wrapping in
  this phase fixes that — it is a behavior change in the failure mode only.
  Mention it in the PR description so the reviewer expects it.
- **Existing test fixtures**. Some test fixtures (search `tests/fixtures/`)
  call `auth_service.create_user_refresh_token` directly without a
  `db_transaction` wrapper. After the conversion, those fixtures need
  wrapping too — either inline `with db_transaction(...)` or a manual
  `db.commit()` since they bypass the router layer.

### Done when

- `ruff check .`, `ruff format --check .`, `mypy app/` green.
- `pytest -q` green; the same total count as before this phase
  (currently **1337 tests passing**) — none deleted, none added by accident.
- `grep -nE 'db\.(commit|rollback)\(\)' app/services/auth.py app/services/users.py`
  returns zero matches.
- The refresh-token rotation endpoint (`POST /auth/refresh` with
  `REFRESH_TOKEN_ROTATION=true`) wraps both the revoke and the create-new
  calls in a single `db_transaction` block (visible in the diff).

### Documentation impact

- Read `docs/ADR_REHYDRATION.md` and `docs/SECURITY_FEATURES.md` to confirm
  neither asserts the old internal-commit behavior. If `SECURITY_FEATURES.md`
  describes the rotation flow, append one sentence noting that revoke +
  create-new-token are now atomic.
- No new ADR needed; the caller-owns contract is already canonical, this
  phase only extends it to two laggard services.

---

## Phase B — `TTLCache` O(1) eviction

### Problem

`app/core/cache.py` houses `TTLCache[T]`, a small in-memory TTL cache used
exclusively by `RuleEngineService` to cache PUBLISHED `EntityVersion` data.
The eviction logic, when the cache is full and a new key arrives:

```python
if len(self._store) >= self._max_size and key not in self._store:
    oldest_key = min(self._store, key=lambda k: self._store[k][0])
    del self._store[oldest_key]
```

`min(...)` over the dict keys is **O(N)** per insert when the cache is at
capacity. At the current `CACHE_MAX_SIZE = 100` (see `app/core/config.py`)
the cost is negligible. The concern is twofold:

1. The eviction policy is "smallest `expires_at`". With a uniform per-cache
   TTL (the only caller pattern), this equals "first inserted" — i.e., FIFO.
   FIFO can be implemented in O(1) with `dict`'s native insertion-order
   guarantee.
2. The current implementation makes `CACHE_MAX_SIZE` a soft scaling limit;
   raising it costs proportionally more per insert.

The goal of this phase is to switch eviction to O(1) while preserving the
existing semantics ("evict the oldest entry by insertion order"), so that
raising `CACHE_MAX_SIZE` is a free configuration change.

### Background to read

- `app/core/cache.py` — the cache implementation, ~140 LOC.
- `app/services/rule_engine.py` — the only consumer. Look at
  `_load_version_data` (the cache hit path) and `calculate_state` (where the
  cache instance is held).
- `tests/engine/` — search for tests asserting cache behavior. The likely
  files are anything that touches `version_cache` or `_cache.invalidate`.
  Run: `grep -RnE 'TTLCache|_cache\.|cache\.stats' tests/`.
- `app/services/versioning.py` — the only other site that interacts with the
  cache (via `get_rule_engine_service()._cache.invalidate(...)` on
  archival). Ensure invalidation continues to work.

### Files to modify

- `app/core/cache.py` — only the body of `TTLCache.set`. The public surface
  (`get`, `set`, `invalidate`, `clear`, `stats`, the `hits`/`misses`
  counters) remains identical.

### Actions

1. **Replace the eviction line** in `TTLCache.set`:

   ```python
   # Before:
   if len(self._store) >= self._max_size and key not in self._store:
       oldest_key = min(self._store, key=lambda k: self._store[k][0])
       del self._store[oldest_key]

   # After:
   if len(self._store) >= self._max_size and key not in self._store:
       # Python dicts preserve insertion order; the first key is the oldest.
       oldest_key = next(iter(self._store))
       del self._store[oldest_key]
   ```

2. **Document the eviction policy** in the `TTLCache` class docstring with
   one extra sentence: "Eviction is FIFO on insertion order; updating an
   existing key does not refresh its eviction position."

3. **Verify semantics** of `set()` when called with a key already in
   `self._store`. The current code overwrites the entry with a fresh
   `expires_at`. It does *not* move the key to the end of insertion order
   (plain `dict[k] = v` on an existing key keeps its position). The new
   eviction logic preserves this exactly. Add a one-line test if none of
   the existing tests assert this — see "Done when".

### Risks / gotchas

- **Insertion order vs. expiration time**. With a single uniform TTL the
  two are equivalent. If a future caller starts using non-uniform TTLs
  (different cache instances with different `ttl_seconds`), eviction by
  insertion-order would diverge from "smallest `expires_at`". This phase
  does not change that future behavior — both old and new implementations
  evict by insertion-order in the single-TTL case — but flag it in the
  class docstring.
- **No locking changes**. The `threading.Lock()` already protects the
  read-modify-write. The new eviction is strictly faster under the same
  lock; do not relax the locking.

### Done when

- `ruff check .`, `ruff format --check .`, `mypy app/` green.
- `pytest -q` green; same total count.
- `grep -n 'min(self._store' app/core/cache.py` returns zero matches.
- A focused unit test exists (or already existed) that:
  - fills `TTLCache` to `max_size` capacity,
  - inserts one more key,
  - asserts that the **first-inserted** key is no longer present and the
    new key is.
  If no such test exists, add one in the appropriate `tests/` location
  (likely `tests/engine/test_cache.py` or wherever `TTLCache` is currently
  tested; create the file if needed).

### Documentation impact

- None. `TTLCache` is internal; no public documentation references its
  eviction policy.

---

## Phase C — Database datetime timezone consistency

### Problem

`app/services/auth.py:verify_user_refresh_token` contains:

```python
expires_at = db_token.expires_at
if expires_at.tzinfo is None:
    expires_at = expires_at.replace(tzinfo=UTC)
if expires_at < now_utc:
    return None
```

The `tzinfo is None` branch coerces a naive datetime to UTC. This handles
the fact that **SQLite ignores timezone information** stored on
`DateTime(timezone=True)` columns — the column on `RefreshToken.expires_at`
is declared timezone-aware in `app/models/domain.py`, but SQLite returns it
naive at read time. PostgreSQL returns it aware.

The workaround is correct under the current schema, but it has two issues:

1. **It leaks SQLite-specific behavior into a security verifier.** The
   token-expiry check is sensitive code; reading it should not require
   knowing the storage layer.
2. **The fix is local but the problem is not.** Any other code path that
   compares a DB datetime to `datetime.now(UTC)` has the same exposure. An
   audit is part of the phase.

The goal is to centralize the coercion so that consumers receive
timezone-aware datetimes regardless of the underlying engine, and remove
the inline workaround.

### Background to read

- `app/services/auth.py` — the call site of the workaround
  (`verify_user_refresh_token`).
- `app/models/domain.py` — every column declared `DateTime(timezone=True)`.
  The relevant ones are on `AuditMixin`, `EntityVersion.published_at`
  (note: declared `DateTime` *without* `timezone=True` — a separate
  inconsistency to flag, see "Risks"), `RefreshToken.expires_at`,
  `revoked_at`, `created_at`, `last_used_at`.
- `app/database.py` — the SQLAlchemy engine and session factory. The phase
  may add a session-level event listener here.
- `app/services/versioning.py` — sets `version.published_at = datetime.now(UTC)`.
  Confirm whether this is later compared to anything via `now()`.
- `tests/conftest.py` and `tests/fixtures/` — the test stack uses SQLite
  (testcontainers in CI per `docs/TESTING.md`; SQLite locally for unit
  tests). The fixtures determine whether the workaround was masking a test
  artifact or production behavior.
- `docs/SECURITY_FEATURES.md` and `docs/ROTATION_DEMO.md` — referenced for
  documentation impact.

### Files to modify

- `app/services/auth.py` — remove the inline coercion in
  `verify_user_refresh_token`.
- One of the following, depending on the chosen approach (see Actions step 1):
  - `app/database.py` — add a session-level `attribute_loaded` /
    `loaded_as_persistent` event that coerces naive datetimes to UTC.
  - **OR** `app/core/datetimes.py` (new file, ~10 LOC) — a single helper
    `as_utc(dt)` reused at every comparison site.
- Any other file that compares a DB datetime to `datetime.now(...)`, found
  by the audit in Actions step 2.

### Actions

1. **Choose the approach** between two options, document the choice in the
   PR description, then execute:

   - **Option 1 (recommended): session-level normalization.** Register a
     SQLAlchemy event listener in `app/database.py` that hooks on column
     load and, for any value that is a naive `datetime`, replaces it with
     the same value annotated `tzinfo=UTC`. This solves the problem at the
     boundary; consumer code stays oblivious. The listener should be
     registered against `Base` (or every model with a `DateTime(timezone=True)`
     column) once at module import time.

   - **Option 2 (smaller blast radius): explicit helper.** Add
     `app/core/datetimes.py`:

     ```python
     """Datetime helpers."""
     from datetime import UTC, datetime

     def as_utc(dt: datetime) -> datetime:
         """Annotate a naive datetime as UTC; return aware datetimes unchanged."""
         return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
     ```

     Use `as_utc(...)` at every comparison site identified in step 2.

   Option 1 is cleaner architecturally (single point of fix, callers stay
   simple). Option 2 is more conservative (no SQLAlchemy machinery, fewer
   surprises, easier to revert). Pick one and do not mix.

2. **Audit comparison sites**. Before modifying any file, run:

   ```
   grep -RnE 'datetime\.now\(' app/
   grep -RnE 'tzinfo' app/
   ```

   Inspect every result. For each one that compares a DB-loaded datetime
   to `now`, decide whether the chosen approach (step 1) covers it
   automatically (Option 1) or whether it needs an explicit `as_utc(...)`
   call (Option 2).

3. **Remove the inline workaround** from `verify_user_refresh_token` in
   `app/services/auth.py`. After this phase, the body should simply do:

   ```python
   if db_token.expires_at < now_utc:
       return None
   ```

   (with `db_token.expires_at` either guaranteed aware by the listener, or
   wrapped via `as_utc(db_token.expires_at)`).

4. **Verify `EntityVersion.published_at`**. The column is declared
   `DateTime` (no `timezone=True`). This is a pre-existing inconsistency
   with the rest of the codebase. It is **out of scope** for this phase
   unless the audit in step 2 reveals an actual comparison site that
   currently bugs. If it does, the fix is to add `timezone=True` to the
   column declaration and write a migration in `alembic/`. Defer that work
   to a separate plan; flag it in this PR's description as a known
   follow-up.

5. **Test coverage**. Add a focused test that calls
   `verify_user_refresh_token` against an SQLite-backed session where
   `RefreshToken.expires_at` is in the past, and assert the function
   returns `None` without raising a `TypeError` (the failure mode if the
   coercion stops working). The existing tests likely already cover this
   path implicitly; verify by running the suite first, then adding the
   focused test only if no existing test exercises the SQLite-naive path.

### Risks / gotchas

- **SQLAlchemy event listeners run on every load**. Option 1 adds a small
  per-row cost; profile if this is a hot path. For the scale of this
  application it is negligible.
- **Mixed timezone handling in tests**. Some test fixtures may construct
  `datetime.utcnow()` (naive) instead of `datetime.now(UTC)`. After this
  phase, naive comparisons inside tests start raising `TypeError`. Search
  `tests/` for `datetime.utcnow(` and `datetime.now()` (no arg) and
  replace with `datetime.now(UTC)` in any test that compares to
  DB-loaded data.
- **`EntityVersion.published_at`** as flagged in step 4. Do not migrate
  the column in this phase — schema migrations are out of scope here.

### Done when

- `ruff check .`, `ruff format --check .`, `mypy app/` green.
- `pytest -q` green; same total count.
- `grep -n 'tzinfo is None' app/services/auth.py` returns zero matches.
- The `verify_user_refresh_token` body has no inline coercion of
  `expires_at` (visible in the diff).
- The chosen approach (Option 1 or Option 2) is named in the PR
  description, and the audit list from Actions step 2 is included as a
  short bullet list confirming every site is handled.

### Documentation impact

- If Option 1 (session listener) is chosen, add one paragraph to
  `docs/SECURITY_FEATURES.md` (or a new short ADR
  `docs/ADR_DATETIME_HANDLING.md` — agent's choice) explaining that all
  loaded datetimes are normalized to UTC at the session boundary, so
  application code can compare them to `datetime.now(UTC)` directly.
- If Option 2 (explicit helper) is chosen, no documentation update needed;
  the helper's docstring is enough.

---

## Verification matrix

| Phase | Commands run | Pass criteria |
|---|---|---|
| A | `ruff check .`, `ruff format --check .`, `mypy app/`, `pytest -q` | All green; 0 `db.commit()`/`db.rollback()` in `services/auth.py` and `services/users.py`; refresh-token rotation wrapped in a single `db_transaction`. |
| B | same | All green; `min(self._store` removed; FIFO eviction test in place. |
| C | same | All green; inline `tzinfo is None` workaround removed from `verify_user_refresh_token`; comparison-site audit attached to the PR. |

## Notes for a fresh agent

- The codebase has saved memories at
  `~/.claude/projects/-home-matteop3-Workspace-rule-engine/memory/`. Read
  `MEMORY.md` first — it captures user preferences (docstring style,
  test execution discipline, commit conventions).
- The architectural decision records under `docs/ADR_*.md` are
  authoritative for behavior. Each phase calls out which ADRs to read for
  documentation impact; do not modify ADRs without explicit user approval.
- The CI pipeline at `.github/workflows/ci.yml` runs `ruff check`,
  `ruff format --check`, `mypy app/`, and `pytest --cov`. Each phase commit
  must pass all four.
- Full `pytest` runs take ~18 minutes locally and ~10–11 minutes in CI. Do
  not poll while it runs; wait for completion.
- If a phase reveals a bug unrelated to its scope, surface it as a
  separate issue. Do not opportunistically fix it inside the phase — the
  diff stays reviewable precisely because it is scoped.
- These phases are independent. A reviewer looking at any single phase's
  diff should be able to evaluate it without context from the other two.
