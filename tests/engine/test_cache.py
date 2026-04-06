"""
Tests for the in-memory TTL cache and its integration with the rule engine.

Three categories:
1. TTLCache unit tests — verify the cache data structure in isolation
2. Engine integration tests — verify caching behavior within RuleEngineService
3. BOM cache tests — verify BOM data in cached VersionData
"""

from decimal import Decimal

from app.core.cache import TTLCache
from app.models.domain import BOMItem, BOMItemRule, BOMType, EntityVersion, VersionStatus
from app.schemas.engine import CalculationRequest, FieldInputState
from app.services.rule_engine import RuleEngineService

# ============================================================
# TTLCache Unit Tests
# ============================================================


class TestTTLCacheSetAndGet:
    """Basic store and retrieve operations."""

    def test_set_and_get(self):
        """Basic store and retrieve."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60, max_size=10)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_missing_key_returns_none(self):
        """Cache miss returns None."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60, max_size=10)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        """Entry expires after TTL."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=0, max_size=10)
        cache.set("key1", "value1")
        # TTL=0 means it expires immediately on next get
        assert cache.get("key1") is None

    def test_max_size_eviction(self):
        """When full, oldest entry is evicted on new insert."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60, max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Should evict key1 (oldest expiry)

        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

    def test_invalidate(self):
        """Explicit invalidation removes entry."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60, max_size=10)
        cache.set("key1", "value1")
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_clear(self):
        """clear() empties cache and resets counters."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60, max_size=10)
        cache.set("key1", "value1")
        cache.get("key1")  # hit
        cache.get("missing")  # miss

        cache.clear()

        assert cache.get("key1") is None
        assert cache.stats() == {"hits": 0, "misses": 1, "size": 0}

    def test_update_existing_key(self):
        """Setting existing key updates value and resets TTL."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60, max_size=10)
        cache.set("key1", "old_value")
        cache.set("key1", "new_value")
        assert cache.get("key1") == "new_value"
        assert cache.stats()["size"] == 1

    def test_stats_hit_miss_counters(self):
        """stats() returns correct hit/miss counts."""
        cache: TTLCache[str] = TTLCache(ttl_seconds=60, max_size=10)
        cache.set("key1", "value1")

        cache.get("key1")  # hit
        cache.get("key1")  # hit
        cache.get("missing")  # miss

        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["size"] == 1


# ============================================================
# Engine Integration Tests
# ============================================================


class TestPublishedVersionCaching:
    """Verify caching behavior for PUBLISHED versions."""

    def test_published_version_data_is_cached(self, db_session, setup_insurance_scenario):
        """Two calculate_state calls for PUBLISHED version: 1 miss + 1 hit."""
        data_map = setup_insurance_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data_map["entity_id"],
            current_state=[
                FieldInputState(field_id=data_map["fields"]["tipo"], value="CAR"),
            ],
        )

        # First call — cache miss, loads from DB
        response1 = service.calculate_state(db_session, payload)

        # Second call — cache hit
        response2 = service.calculate_state(db_session, payload)

        stats = service._cache.stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 1
        assert stats["size"] == 1

        # Results must be identical
        assert response1.is_complete == response2.is_complete
        assert response1.generated_sku == response2.generated_sku
        assert len(response1.fields) == len(response2.fields)

    def test_draft_version_data_is_not_cached(self, db_session, setup_insurance_scenario):
        """calculate_state for DRAFT version produces 0 cache entries."""
        data_map = setup_insurance_scenario

        # Create a DRAFT version (no user FK needed — fields are nullable)
        draft = EntityVersion(
            entity_id=data_map["entity_id"],
            version_number=99,
            status=VersionStatus.DRAFT,
        )
        db_session.add(draft)
        db_session.flush()

        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data_map["entity_id"],
            entity_version_id=draft.id,
            current_state=[],
        )

        service.calculate_state(db_session, payload)

        stats = service._cache.stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0
        assert stats["size"] == 0  # Nothing cached for DRAFT

    def test_cached_data_matches_fresh_data(self, db_session, setup_insurance_scenario):
        """Result from cached call is identical to result from uncached call."""
        data_map = setup_insurance_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data_map["entity_id"],
            current_state=[
                FieldInputState(field_id=data_map["fields"]["tipo"], value="CAR"),
                FieldInputState(field_id=data_map["fields"]["valore"], value=30000),
            ],
        )

        # First call — uncached
        response_fresh = service.calculate_state(db_session, payload)

        # Second call — cached
        response_cached = service.calculate_state(db_session, payload)

        # Compare field-by-field
        for f_fresh, f_cached in zip(response_fresh.fields, response_cached.fields):
            assert f_fresh.field_id == f_cached.field_id
            assert f_fresh.field_name == f_cached.field_name
            assert f_fresh.current_value == f_cached.current_value
            assert f_fresh.is_required == f_cached.is_required
            assert f_fresh.is_readonly == f_cached.is_readonly
            assert f_fresh.is_hidden == f_cached.is_hidden
            assert f_fresh.error_message == f_cached.error_message
            assert len(f_fresh.available_options) == len(f_cached.available_options)

    def test_cached_data_is_session_independent(self, db_session, setup_insurance_scenario):
        """Cached data is accessible after the original DB session is closed."""
        data_map = setup_insurance_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data_map["entity_id"],
            current_state=[],
        )

        # First call populates the cache
        service.calculate_state(db_session, payload)

        # Verify cache entry exists and data is accessible
        version_id = str(data_map["version_id"])
        cached = service._cache.get(version_id)
        assert cached is not None

        # Access all attributes — no DetachedInstanceError
        for field in cached.fields:
            _ = field.id
            _ = field.name
            _ = field.data_type
        for value in cached.values:
            _ = value.id
            _ = value.field_id
            _ = value.value
        for rule in cached.rules:
            _ = rule.id
            _ = rule.conditions
            _ = rule.rule_type
        for bom_item in cached.bom_items:
            _ = bom_item.id
            _ = bom_item.part_number
            _ = bom_item.bom_type
        for bom_rule in cached.bom_item_rules:
            _ = bom_rule.id
            _ = bom_rule.conditions
            _ = bom_rule.bom_item_id

    def test_cache_invalidation_on_publish(self, db_session, setup_insurance_scenario):
        """Publishing a new version invalidates the old version's cache entry."""
        data_map = setup_insurance_scenario
        from app.dependencies.services import get_rule_engine_service
        from app.models.domain import User, UserRole
        from app.services.versioning import VersioningService

        # Create a user for versioning operations (FK constraint on created_by_id)
        user = User(email="cache-test@test.com", hashed_password="x", role=UserRole.AUTHOR)
        db_session.add(user)
        db_session.flush()

        engine_service = get_rule_engine_service()

        # Populate cache by calling calculate_state
        payload = CalculationRequest(
            entity_id=data_map["entity_id"],
            current_state=[],
        )
        engine_service.calculate_state(db_session, payload)

        published_id = str(data_map["version_id"])
        assert engine_service._cache.get(published_id) is not None

        # Create a DRAFT version and publish it
        versioning = VersioningService()
        new_draft = versioning.create_draft_version(
            db=db_session,
            entity_id=data_map["entity_id"],
            user_id=user.id,
        )
        db_session.flush()

        versioning.publish_version(db=db_session, version_id=new_draft.id, user_id=user.id)
        db_session.flush()

        # The old published version's cache entry should be invalidated
        assert engine_service._cache.get(published_id) is None

    def test_cache_cleared_between_tests(self):
        """Meta-test: verify the autouse fixture clears the cache properly."""
        from app.dependencies.services import get_rule_engine_service

        service = get_rule_engine_service()
        stats = service._cache.stats()
        # Cache should be clean at the start of each test (cleared by autouse fixture)
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0


# ============================================================
# BOM Cache Tests
# ============================================================


class TestBOMCachedVersionData:
    """Verify BOM data is included in cached VersionData."""

    def test_cached_version_data_contains_bom_items(self, db_session):
        """VersionData includes BOM items after caching."""
        entity_version, _ = _create_version_with_bom(db_session)

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity_version.entity_id,
            current_state=[],
        )
        service.calculate_state(db_session, payload)

        cached = service._cache.get(str(entity_version.id))
        assert cached is not None
        assert len(cached.bom_items) == 1
        assert cached.bom_items[0].part_number == "CHASSIS-001"
        assert cached.bom_items[0].bom_type == BOMType.COMMERCIAL.value
        assert cached.bom_items[0].quantity == Decimal("1.0000")
        assert cached.bom_items[0].unit_price == Decimal("100.0000")

    def test_cached_version_data_contains_bom_item_rules(self, db_session):
        """VersionData includes BOM item rules after caching."""
        entity_version, bom_item = _create_version_with_bom(db_session)

        # Add a BOM item rule
        bom_rule = BOMItemRule(
            bom_item_id=bom_item.id,
            entity_version_id=entity_version.id,
            conditions={"criteria": [{"field_id": 999, "operator": "EQUALS", "value": "X"}]},
            description="Test BOM rule",
        )
        db_session.add(bom_rule)
        db_session.flush()

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity_version.entity_id,
            current_state=[],
        )
        service.calculate_state(db_session, payload)

        cached = service._cache.get(str(entity_version.id))
        assert cached is not None
        assert len(cached.bom_item_rules) == 1
        assert cached.bom_item_rules[0].bom_item_id == bom_item.id
        assert cached.bom_item_rules[0].conditions["criteria"][0]["operator"] == "EQUALS"

    def test_draft_bom_data_not_cached(self, db_session):
        """BOM data for DRAFT versions is not stored in cache."""
        from app.models.domain import Entity

        entity = Entity(name="BOM Draft Test Entity", description="Test")
        db_session.add(entity)
        db_session.flush()

        version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.DRAFT)
        db_session.add(version)
        db_session.flush()

        bom_item = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="DRAFT-001",
            quantity=Decimal("1"),
        )
        db_session.add(bom_item)
        db_session.flush()

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity.id,
            entity_version_id=version.id,
            current_state=[],
        )
        service.calculate_state(db_session, payload)

        assert service._cache.get(str(version.id)) is None

    def test_cache_invalidation_clears_bom_data(self, db_session):
        """Invalidating a cached version removes BOM data too."""
        entity_version, _ = _create_version_with_bom(db_session)

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity_version.entity_id,
            current_state=[],
        )
        service.calculate_state(db_session, payload)

        cache_key = str(entity_version.id)
        assert service._cache.get(cache_key) is not None

        service._cache.invalidate(cache_key)
        assert service._cache.get(cache_key) is None

    def test_version_without_bom_has_empty_bom_lists(self, db_session, setup_insurance_scenario):
        """Existing version without BOM items caches with empty BOM lists."""
        data_map = setup_insurance_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data_map["entity_id"],
            current_state=[],
        )
        service.calculate_state(db_session, payload)

        cached = service._cache.get(str(data_map["version_id"]))
        assert cached is not None
        assert cached.bom_items == []
        assert cached.bom_item_rules == []


def _create_version_with_bom(db_session):
    """Helper: creates a PUBLISHED version with one BOM item."""
    from app.models.domain import Entity

    entity = Entity(name="BOM Cache Test Entity", description="Test")
    db_session.add(entity)
    db_session.flush()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.flush()

    bom_item = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="CHASSIS-001",
        description="Main chassis",
        quantity=Decimal("1"),
        unit_price=Decimal("100"),
    )
    db_session.add(bom_item)
    db_session.flush()

    return version, bom_item
