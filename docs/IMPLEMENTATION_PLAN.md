# Implementation Plan: Dependencies Refactor, Caching, Structured Logging

Three improvements to address code review feedback. Each should be a separate commit. The recommended execution order is explained at the end.

---

## 1. Split `dependencies.py` into a package

**Goal**: Break the 544-line monolith into focused modules with balanced sizes.

### Target structure

```
app/dependencies/
├── __init__.py          # Re-exports everything (backward compatibility)
├── auth.py              # Authentication & authorization
├── services.py          # Service factories + transaction helper
├── fetchers.py          # fetch_*_by_id helpers + get_*_or_404 HTTP deps
└── validators.py        # validate_* helpers + get_editable_* HTTP deps
```

### Module contents

**`auth.py`** (~60 lines)
- `oauth2_scheme`
- `get_current_user()`
- `require_role()`
- `require_admin_or_author()`

**`services.py`** (~60 lines)
- `get_auth_service()`
- `get_user_service()`
- `get_rule_engine_service()`
- `get_versioning_service()`
- `db_transaction()` — lives here because it's a service-level concern (transaction management), not domain logic

**`fetchers.py`** (~150 lines) — data retrieval
- All `fetch_*_by_id()` functions (6: user, entity, field, rule, value, version)
- All `get_*_or_404()` HTTP dependencies (6: same resources)
- These are pure "find or fail" functions with no business logic

**`validators.py`** (~200 lines) — business rule enforcement
- `validate_version_is_draft()`
- `validate_field_belongs_to_version()`
- `validate_value_belongs_to_field()`
- `validate_value_not_used_in_rules()`
- All `get_editable_*()` HTTP dependencies (field, rule, value, version) — these compose a fetcher + a validation, so they live with validators

**`__init__.py`** — re-exports every public name so that existing `from app.dependencies import X` continues to work unchanged. This is critical: **no router file should need modification**.

```python
from app.dependencies.auth import (
    get_current_user,
    oauth2_scheme,
    require_admin_or_author,
    require_role,
)
from app.dependencies.fetchers import (
    fetch_entity_by_id,
    fetch_field_by_id,
    fetch_rule_by_id,
    fetch_user_by_id,
    fetch_value_by_id,
    fetch_version_by_id,
    get_entity_or_404,
    get_field_or_404,
    get_rule_or_404,
    get_user_or_404,
    get_value_or_404,
    get_version_or_404,
)
from app.dependencies.services import (
    db_transaction,
    get_auth_service,
    get_rule_engine_service,
    get_user_service,
    get_versioning_service,
)
from app.dependencies.validators import (
    get_editable_field,
    get_editable_rule,
    get_editable_value,
    get_editable_version,
    validate_field_belongs_to_version,
    validate_value_belongs_to_field,
    validate_value_not_used_in_rules,
    validate_version_is_draft,
)

__all__ = [
    # auth
    "oauth2_scheme",
    "get_current_user",
    "require_role",
    "require_admin_or_author",
    # services
    "get_auth_service",
    "get_user_service",
    "get_rule_engine_service",
    "get_versioning_service",
    "db_transaction",
    # fetchers
    "fetch_user_by_id",
    "fetch_entity_by_id",
    "fetch_field_by_id",
    "fetch_rule_by_id",
    "fetch_value_by_id",
    "fetch_version_by_id",
    "get_user_or_404",
    "get_entity_or_404",
    "get_field_or_404",
    "get_rule_or_404",
    "get_value_or_404",
    "get_version_or_404",
    # validators
    "validate_field_belongs_to_version",
    "validate_value_belongs_to_field",
    "validate_value_not_used_in_rules",
    "validate_version_is_draft",
    "get_editable_version",
    "get_editable_field",
    "get_editable_rule",
    "get_editable_value",
]
```

### Steps

1. Create `app/dependencies/` directory with `__init__.py`
2. Move functions into the four modules, preserving imports and logic exactly
3. Write `__init__.py` with re-exports as shown above
4. Delete old `app/dependencies.py`
5. Run `grep -r "from app.dependencies" app/ tests/` — verify every import resolves
6. Run full test suite — zero changes expected since all imports are backward-compatible

### Internal dependencies between modules

- `auth.py` imports `fetch_user_by_id` from `fetchers.py`
- `validators.py` imports `fetch_version_by_id` from `fetchers.py` and `validate_version_is_draft` internally
- No circular dependency risk: `fetchers.py` imports from neither `auth.py` nor `validators.py`

### Pitfall

The old `app/dependencies.py` file **must be deleted** before creating the `app/dependencies/` package. If both exist, Python will prefer the package (directory), but the stale `.py` file can cause confusion. Delete it first.

### Documentation updates

**`README.md` — Project Structure section**: Replace the single `dependencies.py` line:

```
│   ├── dependencies/          # Dependency injection (package)
│   │   ├── __init__.py        # Re-exports for backward compatibility
│   │   ├── auth.py            # Authentication & authorization deps
│   │   ├── services.py        # Service factories + transaction helper
│   │   ├── fetchers.py        # Data retrieval helpers
│   │   └── validators.py      # Business rule validation helpers
```

No other doc updates needed — this is a pure internal reorganization.

### Test updates

No new tests needed. The existing full test suite is the verification — if any import breaks, tests will fail with `ImportError`.

### Definition of done

- [ ] Old `app/dependencies.py` deleted, `app/dependencies/` package exists with 5 files
- [ ] `grep -r "from app.dependencies" app/ tests/` shows zero broken imports
- [ ] No module exceeds 200 lines
- [ ] Full test suite passes with zero modifications to any test file
- [ ] README project structure section updated

---

## 2. In-Memory Cache for PUBLISHED EntityVersion Data

**Goal**: Cache the fields/values/rules loaded by `_load_version_data()` in `rule_engine.py` for PUBLISHED versions, avoiding repeated DB queries for immutable data.

### Why it's safe

PUBLISHED versions are **immutable** — once published, fields, values, and rules cannot be modified. The only transition is PUBLISHED → ARCHIVED (which means the version is no longer active, but the cached data is still valid if accessed). There is **no cache invalidation problem** for PUBLISHED versions.

DRAFT versions must **not** be cached — they are mutable and change frequently.

### Design decisions

**Decision 1: Cache plain dicts, not ORM instances.** SQLAlchemy model instances carry session state, identity map references, and lazy-loading proxies. Once the session closes, they become detached — any lazy attribute access raises `DetachedInstanceError`. Even though the current code avoids lazy access, this is fragile: a future `relationship()` addition or a new code path could silently break. Caching plain dicts/dataclasses eliminates this class of bugs entirely and makes the cache truly session-independent.

**Decision 2: The cache is an instance attribute of `RuleEngineService`, not a module-level global.** `RuleEngineService` is already a singleton (via `@lru_cache` in `dependencies/services.py`), so the cache lifetime is the same. But making it an attribute means tests can access and clear it via the service instance, and there's no hidden global state to manage in `conftest.py`.

**Decision 3: The version status is passed from the caller, not queried again inside `_load_version_data`.** `calculate_state` already resolves the `target_version` object (including its `.status`) via `_resolve_target_version`. Passing `version_status` as a parameter avoids an extra DB query just to check if we should cache.

**Decision 4: Add hit/miss counters** for observability. Without metrics, you can't know if the cache is effective. Simple atomic counters (hits, misses) exposed via a `stats()` method, loggable on demand.

### Cache value format

`_load_version_data` currently returns `tuple[list[Field], list[Value], list[Rule]]` (ORM instances). The cached version returns plain dicts derived from these:

```python
from dataclasses import dataclass, field as dc_field

@dataclass(frozen=True)
class CachedField:
    """Immutable snapshot of a Field for cache storage."""
    id: int
    entity_version_id: int
    name: str
    label: str
    data_type: str
    is_required: bool
    is_readonly: bool
    is_hidden: bool
    is_free_value: bool
    default_value: str | None
    sku_modifier_when_filled: str | None
    step: int
    sequence: int

@dataclass(frozen=True)
class CachedValue:
    """Immutable snapshot of a Value for cache storage."""
    id: int
    field_id: int
    value: str
    label: str
    is_default: bool
    sku_modifier: str | None

@dataclass(frozen=True)
class CachedRule:
    """Immutable snapshot of a Rule for cache storage."""
    id: int
    entity_version_id: int
    target_field_id: int
    target_value_id: int | None
    rule_type: str
    conditions: dict
    error_message: str | None
    set_value: str | None

@dataclass(frozen=True)
class VersionData:
    """All data needed to evaluate rules for a version."""
    fields: list[CachedField]
    values: list[CachedValue]
    rules: list[CachedRule]
```

The conversion from ORM → dataclass happens once at cache-write time, inside `_load_version_data`.

**Impact on downstream code**: `calculate_state`, `_process_field`, `_generate_sku`, etc. currently access attributes like `field.id`, `field.data_type`, `value.field_id`, `rule.conditions`. These are identical on the dataclasses. However, any code path that accesses ORM-only attributes (e.g., `field.entity_version` relationship, `field.values` relationship) will break at the call site — which is exactly what we want: it surfaces hidden coupling at development time, not in production.

**Review all attribute access paths before implementing.** Specifically, check every `field.`, `value.`, and `rule.` access in:
- `_process_field()`
- `_generate_sku()`
- `_build_type_map()`, `_build_values_index()`, `_build_rules_index()`
- `_check_completeness()`

If any uses ORM relationships, refactor that code path to use the indexed dicts (`values_by_field`, etc.) instead.

### TTL Cache implementation

**`app/core/cache.py`** (~60 lines) — generic TTL cache

```python
import threading
import time
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Thread-safe in-memory cache with TTL and max size."""

    def __init__(self, ttl_seconds: int = 300, max_size: int = 100):
        self._store: dict[str, tuple[float, T]] = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
        self._lock = threading.Lock()
        self.hits: int = 0
        self.misses: int = 0

    def get(self, key: str) -> T | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: str, value: T) -> None:
        with self._lock:
            if len(self._store) >= self._max_size and key not in self._store:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]
            self._store[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "size": len(self._store)}
```

### Changes to `app/services/rule_engine.py`

The cache becomes an instance attribute. `_load_version_data` gains a `version_status` parameter:

```python
from app.core.cache import TTLCache
from app.core.config import settings

class RuleEngineService:
    def __init__(self):
        self._cache: TTLCache[VersionData] = TTLCache(
            ttl_seconds=settings.CACHE_TTL_SECONDS,
            max_size=settings.CACHE_MAX_SIZE,
        )

    def calculate_state(self, db, request):
        target_version = self._resolve_target_version(db, request)

        # Pass status so _load_version_data can decide whether to cache
        fields_db, all_values, all_rules = self._load_version_data(
            db, target_version.id, version_status=target_version.status
        )
        # ... rest unchanged ...

    def _load_version_data(self, db, version_id, version_status):
        cache_key = str(version_id)

        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for version {version_id}")
            return cached.fields, cached.values, cached.rules

        # ... existing DB loading logic ...
        # Convert ORM instances to dataclasses
        version_data = VersionData(
            fields=[CachedField(...) for f in fields_db],
            values=[CachedValue(...) for v in all_values],
            rules=[CachedRule(...) for r in all_rules],
        )

        # Only cache PUBLISHED versions (immutable)
        if version_status == VersionStatus.PUBLISHED.value:
            self._cache.set(cache_key, version_data)
            logger.debug(f"Cached version {version_id} (PUBLISHED)")

        return version_data.fields, version_data.values, version_data.rules
```

### Changes to `app/core/config.py`

```python
# Caching
CACHE_TTL_SECONDS: int = 300
CACHE_MAX_SIZE: int = 100
```

### Changes to `app/services/versioning.py`

When publishing archives the old PUBLISHED version, invalidate it:

```python
# In the publish logic, after archiving the old version:
# Access the cache via the RuleEngineService singleton
from app.dependencies.services import get_rule_engine_service
engine = get_rule_engine_service()
engine._cache.invalidate(str(old_version_id))
```

This is a courtesy invalidation — TTL would eventually evict it, and serving data for an ARCHIVED version is harmless. But it keeps memory clean.

### Steps

1. Create the dataclasses (`CachedField`, `CachedValue`, `CachedRule`, `VersionData`) — either in `app/core/cache.py` or in a dedicated `app/schemas/cache.py`
2. Create `app/core/cache.py` with `TTLCache` (with hit/miss counters)
3. Add `CACHE_TTL_SECONDS` and `CACHE_MAX_SIZE` to `app/core/config.py`
4. **Audit all attribute access** on Field/Value/Rule objects in `rule_engine.py` — verify every accessed attribute exists on the dataclass. Fix any code that uses ORM relationships to use the indexed dicts instead
5. Modify `_load_version_data()`: add `version_status` parameter, convert ORM → dataclass, cache on PUBLISHED
6. Make cache an instance attribute of `RuleEngineService.__init__`
7. Add invalidation call in `app/services/versioning.py` publish logic
8. Write tests (see below)
9. Run full test suite

### Pitfall: `@lru_cache` on `get_rule_engine_service()`

`RuleEngineService` is a singleton via `@lru_cache` in `dependencies/services.py`. Since the cache is now an instance attribute, the `@lru_cache` ensures there's exactly one cache. However, in tests the `@lru_cache` may persist across tests. Either:
- Call `get_rule_engine_service.cache_clear()` in the autouse fixture, or
- Access the service instance and call `service._cache.clear()` in teardown

Both approaches work; choose one and be consistent.

### Documentation updates

**`README.md`**:

1. **Intentional Scope Boundaries table** — update the "Redis caching" row:
   ```
   | Redis caching | In-memory TTL cache | PUBLISHED version data cached in-process. Redis not needed at current scale; upgrade path documented if multi-instance is needed. |
   ```

2. **Features section** — add after `### SKU Generation`:
   ```markdown
   ### Performance
   - **Version data caching**: PUBLISHED EntityVersion data cached in-memory with configurable TTL
   - **Safe by design**: Only immutable PUBLISHED versions are cached; DRAFT versions always hit the database
   - **Observable**: Hit/miss counters available via `cache.stats()` for monitoring effectiveness
   - **Auto-eviction**: TTL-based expiry + max size limit prevent unbounded memory growth
   ```

3. **Environment Variables section** — add:
   ```bash
   # Caching
   CACHE_TTL_SECONDS=300    # TTL for cached PUBLISHED version data
   CACHE_MAX_SIZE=100       # Max cached versions in memory
   ```

4. **Project Structure section** — add:
   ```
   │   └── core/
   │       ├── cache.py          # In-memory TTL cache + cached data models
   ```

5. **Architecture > Key Architectural Choices** — add:
   ```markdown
   **In-memory caching for PUBLISHED versions**: PUBLISHED EntityVersion data (fields, values, rules)
   is cached in-process as frozen dataclasses, decoupled from SQLAlchemy sessions. Only immutable
   PUBLISHED versions are cached. The cache auto-invalidates on version archival and provides
   hit/miss counters for observability.
   ```

**`.env.example`** — add:
```bash
# ------------------------------------------------------------------------------
# Caching
# ------------------------------------------------------------------------------

# TTL for cached PUBLISHED EntityVersion data (seconds)
CACHE_TTL_SECONDS=300

# Max number of cached EntityVersions in memory
CACHE_MAX_SIZE=100
```

**`docs/ADR_REHYDRATION.md`** — in the "Trade-offs > Why that's acceptable" section, add a note that PUBLISHED version data is now cached in-memory, further reducing the cost of per-read re-hydration.

### Test updates

#### Impact on existing tests

The dataclass swap changes the internal representation but **not** the public API surface. All existing engine tests assert against `CalculationResponse` (Pydantic model), not against the raw ORM objects returned by `_load_version_data`. The waterfall methods (`_process_field`, `_generate_sku`, `_build_type_map`, etc.) access only scalar attributes (`.id`, `.data_type`, `.is_required`, `.conditions`, etc.) that exist identically on both the ORM models and the frozen dataclasses.

**Pre-implementation verification**: before writing any code, run a grep to confirm no existing test directly imports or asserts against `Field`, `Value`, or `Rule` ORM instances *from the engine output*. Test fixtures create ORM instances to populate the DB (that's fine — they're inputs to the engine, not outputs from the cache). The cache only affects what `_load_version_data` returns internally.

If the attribute audit (step 4) finds ORM-only access paths in engine code, fix those first — the existing tests will catch any regression.

#### New test file: `tests/engine/test_cache.py`

Two categories: unit tests for `TTLCache` and integration tests for cache-in-engine behavior.

**TTLCache unit tests** (~8 tests):

| Test | What it verifies |
|------|-----------------|
| `test_set_and_get` | Basic store and retrieve |
| `test_get_missing_key_returns_none` | Cache miss returns `None` |
| `test_ttl_expiry` | Entry expires after TTL (use `ttl_seconds=0` or mock `time.monotonic`) |
| `test_max_size_eviction` | When full, oldest entry is evicted on new insert |
| `test_invalidate` | Explicit invalidation removes entry |
| `test_clear` | `clear()` empties cache and resets counters |
| `test_update_existing_key` | Setting existing key updates value and resets TTL |
| `test_stats_hit_miss_counters` | `stats()` returns correct hit/miss counts |

**Engine integration tests** (~6 tests):

| Test | What it verifies |
|------|-----------------|
| `test_published_version_data_is_cached` | Two `calculate_state` calls for PUBLISHED version; verify `_cache.stats()` shows 1 miss + 1 hit |
| `test_draft_version_data_is_not_cached` | `calculate_state` for DRAFT version; `_cache.stats()` shows 0 hits |
| `test_cache_invalidation_on_publish` | Publish a new version; verify old version's cache entry is gone |
| `test_cached_data_matches_fresh_data` | Result from cached call is identical to result from uncached call |
| `test_cached_data_is_session_independent` | Cached data is accessible after the original DB session is closed (proves no detached-instance issues) |
| `test_cache_cleared_between_tests` | Meta-test: verify the fixture clears the cache properly |

#### `conftest.py` update

Add to the **root** `tests/conftest.py` (not a nested conftest) so the fixture applies to all test categories — API tests that call `calculate_state` indirectly also need a clean cache:

```python
@pytest.fixture(autouse=True)
def clear_engine_cache():
    """Prevent cross-test cache pollution."""
    yield
    from app.dependencies.services import get_rule_engine_service
    get_rule_engine_service()._cache.clear()
```

#### Update `docs/TESTING.md`

- Add `test_cache.py` to Engine Tests directory listing
- Update test statistics table (approximate totals: +14 tests)
- Document cache test categories (unit vs integration) in the Engine Tests section
- Add `clear_engine_cache` to the "Core Fixtures" section with explanation of why it's autouse and global

### Definition of done

- [ ] `TTLCache` with `stats()` method works and is unit-tested
- [ ] Cached data uses frozen dataclasses, not ORM instances
- [ ] `_load_version_data` receives `version_status` from caller (no extra query)
- [ ] Calling `calculate_state` twice for the same PUBLISHED version produces 1 DB load + 1 cache hit (verified via `stats()`)
- [ ] Calling `calculate_state` for a DRAFT version produces 0 cache entries
- [ ] Publishing a new version invalidates the old version's cache
- [ ] No `DetachedInstanceError` when accessing cached data after session close
- [ ] Full existing test suite passes unchanged (except `conftest.py` fixture addition) — confirms dataclass swap has no visible side effects
- [ ] README (Scope Boundaries, Features, Env Vars, Project Structure, Architectural Choices), `.env.example`, `ADR_REHYDRATION.md`, `TESTING.md` all updated

---

## 3. Structured Logging + Correlation ID

**Goal**: JSON-formatted logs with a `request_id` that traces every log line back to a specific HTTP request. Unified output format across application and uvicorn access logs.

### Architecture

```
Request arrives
  → middleware generates UUID request_id, stores it in contextvars
  → all logger calls automatically include request_id (via filter)
  → uvicorn access logs also use the JSON formatter
  → response includes X-Request-ID header
```

### Design decisions

- **Use `python-json-logger`** (battle-tested library) instead of a custom `JSONFormatter`. Handles edge cases (nested exceptions, binary data, encoding) that a hand-rolled formatter will miss. Add `python-json-logger` to `requirements.txt`.
- **Always attach a `RequestIDFilter`** to the handler, regardless of JSON or plain format. This ensures `request_id` is available as a `LogRecord` attribute in both modes — no `KeyError` risk in the plain-text fallback.
- **Configure uvicorn logging** via a log config dict passed to `uvicorn.run()` or set in `main.py`, so that uvicorn access logs also go through the same JSON formatter. Without this, stdout would have mixed JSON + plaintext lines, breaking any log aggregator.

### New files

**`app/core/logging.py`** (~50 lines) — logging configuration module

```python
import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

# Context variable for request correlation
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIDFilter(logging.Filter):
    """Injects request_id from contextvars into every LogRecord."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()  # type: ignore[attr-defined]
        return True


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Configure root logger. Call once at app startup."""
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIDFilter())

    if json_output:
        handler.setFormatter(JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s (%(request_id)s) %(message)s")
        )

    root.addHandler(handler)


def get_uvicorn_log_config(json_output: bool = True) -> dict:
    """
    Returns a log config dict for uvicorn that routes access/error logs
    through the same formatter as the application.
    Pass this to uvicorn.run(log_config=...) or set in main.py.
    """
    if not json_output:
        return {}  # Use uvicorn defaults for dev

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.json.JsonFormatter",
                "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            }
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
                "filters": [],
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
    }
```

**`app/middleware/request_id.py`** (~30 lines) — ASGI middleware

```python
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Use client-provided ID if present, else generate
        rid = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            request_id_ctx.reset(token)
```

Note on `BaseHTTPMiddleware`: it buffers the response body, which is a problem for streaming endpoints. This project has no streaming endpoints, so it's fine. If streaming is added later, rewrite as a pure ASGI middleware.

### Changes to existing files

**`requirements.txt`** — add:
```
python-json-logger>=3.0.0
```

**`app/core/config.py`** — add one setting:
```python
LOG_JSON: bool = True    # NEW — disable for human-readable logs in development
```

**`app/main.py`** — replace `logging.basicConfig(...)` and add middleware:
```python
from app.core.logging import setup_logging
from app.middleware.request_id import RequestIDMiddleware

# In lifespan (startup), replacing the existing logging.basicConfig call:
setup_logging(level=settings.LOG_LEVEL, json_output=settings.LOG_JSON)

# After app = FastAPI(...):
app.add_middleware(RequestIDMiddleware)
```

**`Dockerfile`** / **`docker-compose.yml`** — if uvicorn is launched via CLI (e.g., `uvicorn app.main:app`), the `log_config` dict can't be passed directly. Two options:
1. Launch uvicorn programmatically via `uvicorn.run()` in a `__main__.py` entry point, passing `log_config=get_uvicorn_log_config()`
2. Or set `--log-config` to a JSON/YAML file generated from `get_uvicorn_log_config()`

Check how the project currently launches uvicorn and choose accordingly.

### Steps

1. `pip install python-json-logger` and add to `requirements.txt`
2. Create `app/core/logging.py` with `RequestIDFilter`, `setup_logging()`, `get_uvicorn_log_config()`
3. Create `app/middleware/` package (with `__init__.py`) and `request_id.py`
4. Add `LOG_JSON: bool = True` to `app/core/config.py`
5. Update `app/main.py`: replace `logging.basicConfig` with `setup_logging()`, add `RequestIDMiddleware`
6. Configure uvicorn log output (see Dockerfile/docker-compose note above)
7. Existing `logger = logging.getLogger(__name__)` calls across the codebase need **zero changes** — the JSON formatter is applied at the root logger level, and `request_id` is injected via `RequestIDFilter`
8. Run test suite
9. Verify manually (see definition of done)

### Documentation updates

**`README.md`**:

1. **Features section** — add after `### Performance` (added by point 2):
   ```markdown
   ### Observability
   - **Structured JSON logging**: All log output (application + uvicorn) in machine-parseable JSON
   - **Request correlation**: Every request gets a unique `X-Request-ID` header, propagated through all log entries
   - **Configurable format**: JSON (production) or human-readable (development) via `LOG_JSON` setting
   ```

2. **Environment Variables section** — add:
   ```bash
   # Logging
   LOG_LEVEL=INFO
   LOG_JSON=true            # Set to false for human-readable logs in development
   ```

3. **Project Structure section** — add new entries:
   ```
   │   ├── middleware/
   │   │   └── request_id.py     # Request correlation ID middleware
   │   └── core/
   │       ├── logging.py        # Structured logging setup
   ```

4. **Tech Stack table** — add:
   ```
   | Observability | python-json-logger + correlation IDs |
   ```

**`.env.example`** — add under the Logging section:
```bash
# JSON structured logging (set to false for human-readable output in development)
LOG_JSON=true
```

**`docs/SECURITY_FEATURES.md`** — add a brief section about request tracing (`X-Request-ID` is security-relevant for incident investigation and audit trail correlation).

### Test updates

#### Impact on existing tests

**No existing tests use `caplog`, `capfd`, or `capsys`** — confirmed by grep. No existing tests will break from the format change.

However, `setup_logging()` is called during app lifespan startup, which runs when `TestClient` instantiates the app. To avoid JSON log noise during tests and potential interference with pytest's internal log capture:
- Set `LOG_JSON=false` in the test environment (via a `.env.test` file or in `conftest.py` by monkeypatching `settings.LOG_JSON = False`)
- Or call `setup_logging(json_output=False)` in the root `conftest.py` before tests run

Either way, the `RequestIDMiddleware` still functions — it stores/reads the context var and sets the response header regardless of log format. The middleware tests below verify this behavior directly.

#### New test file: `tests/api/test_request_id.py` (~6 tests)

| Test | What it verifies |
|------|-----------------|
| `test_response_includes_request_id_header` | Any endpoint response contains `X-Request-ID` header |
| `test_request_id_is_valid_uuid` | Auto-generated `X-Request-ID` is a valid UUID4 |
| `test_client_provided_request_id_is_echoed` | Sending `X-Request-ID: custom-123` gets the same value back |
| `test_different_requests_get_different_ids` | Two sequential requests produce distinct IDs |
| `test_error_response_includes_request_id` | A 4xx/5xx response still has the header |
| `test_request_id_filter_injects_attribute` | `RequestIDFilter` sets `record.request_id` from `request_id_ctx` |

#### Update `docs/TESTING.md`

- Add `test_request_id.py` to API Tests directory listing
- Update test statistics table (approximate totals: +6 tests)
- Brief description of middleware/logging test coverage
- If `LOG_JSON` is configured for test environment in `conftest.py`, document it in the "Core Fixtures" section

### Definition of done

- [ ] `python-json-logger` in `requirements.txt` and installed
- [ ] `curl -s -D- http://localhost:8000/entities` shows `X-Request-ID` in response headers
- [ ] stdout shows valid JSON log lines with `timestamp`, `levelname`, `name`, `message`, `request_id` fields
- [ ] The `request_id` in the log matches the `X-Request-ID` in the response
- [ ] uvicorn access logs (e.g., `"GET /entities HTTP/1.1" 200`) are also JSON-formatted
- [ ] With `LOG_JSON=false`, logs are human-readable with `(request_id)` and no `KeyError`
- [ ] Test environment configured for `LOG_JSON=false` (no JSON noise during test runs, no interference with pytest log capture)
- [ ] All new tests pass, full existing suite passes
- [ ] README (Features, Env Vars, Project Structure, Tech Stack), `.env.example`, `docs/SECURITY_FEATURES.md`, `docs/TESTING.md` all updated

---

## Execution order recommendation

1. **Dependencies refactor** (point 1) — prerequisito de facto: stabilizza la struttura dei moduli su cui gli altri due punti si appoggiano (punto 2 importa da `dependencies/services.py`, punto 3 crea `app/middleware/`). Rischio zero, rollback banale, diff di pura riorganizzazione.

2. **Caching** (point 2) — è il punto che porta il valore dimostrabile più alto: risponde direttamente alla critica ricevuta ("manca un caching layer"). È anche il più rischioso (dataclasses, audit degli attribute access, interazione con `@lru_cache`), quindi va affrontato quando il contesto è fresco. Gli errori nel caching sono silenziosi — meglio dedicargli la massima attenzione.

3. **Structured logging** (point 3) — il più isolato. Non ha dipendenze funzionali dagli altri due. Aggiunge un package (`middleware/`), un file (`core/logging.py`), una dipendenza esterna, e un setting. Nessuna interazione con caching o dependencies. Implementarlo per ultimo offre un test end-to-end naturale: i log di cache hit/miss del punto 2 usciranno già in formato JSON.

Each should be a separate commit. No Alembic migrations needed (no DB schema changes).
