"""In-memory TTL cache and cached data models for PUBLISHED version data."""

import threading
import time
from dataclasses import dataclass
from decimal import Decimal

# ============================================================
# CACHED DATA MODELS (frozen dataclasses, session-independent)
# ============================================================


@dataclass(frozen=True)
class CachedField:
    """Immutable snapshot of a Field for cache storage."""

    id: int
    entity_version_id: int
    name: str
    label: str | None
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
    label: str | None
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
class CachedBOMItem:
    """Immutable snapshot of a BOMItem for cache storage."""

    id: int
    entity_version_id: int
    parent_bom_item_id: int | None
    bom_type: str
    part_number: str
    quantity: Decimal
    quantity_from_field_id: int | None
    sequence: int


@dataclass(frozen=True)
class CachedBOMItemRule:
    """Immutable snapshot of a BOMItemRule for cache storage."""

    id: int
    bom_item_id: int
    entity_version_id: int
    conditions: dict
    description: str | None


@dataclass(frozen=True)
class VersionData:
    """All data needed to evaluate rules for a version."""

    fields: list[CachedField]
    values: list[CachedValue]
    rules: list[CachedRule]
    bom_items: list[CachedBOMItem]
    bom_item_rules: list[CachedBOMItemRule]


# ============================================================
# TTL CACHE
# ============================================================


class TTLCache[T]:
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
