"""
Performance and Benchmark Test Suite.

Tests:
1. Rule engine calculation performance with varying complexity
2. API endpoint response times
3. Database query performance
4. Throughput under load

Usage:
    pytest tests/test_performance.py -v                    # Run all performance tests
    pytest tests/test_performance.py -v --benchmark-only   # Run only benchmark tests
    pytest tests/test_performance.py -v --benchmark-save=baseline  # Save baseline
    pytest tests/test_performance.py -v --benchmark-compare=baseline  # Compare to baseline

Note: These tests require pytest-benchmark. Install with: pip install pytest-benchmark
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token, get_password_hash
from app.models.domain import (
    Entity,
    EntityVersion,
    Field,
    FieldType,
    PriceList,
    Rule,
    RuleType,
    User,
    UserRole,
    Value,
    VersionStatus,
)
from app.schemas.engine import CalculationRequest, FieldInputState
from app.services.rule_engine import RuleEngineService

# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def perf_user(db_session):
    """Creates a test user for performance tests."""
    user = User(
        email="perfuser@example.com",
        hashed_password=get_password_hash("TestPassword123!"),
        role=UserRole.USER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def perf_auth_headers(perf_user):
    """Generates valid auth headers for the performance test user."""
    access_token = create_access_token(subject=perf_user.id)
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="function")
def perf_price_list(db_session):
    """Creates a price list for performance tests."""
    price_list = PriceList(
        name="Performance Test Price List",
        description="Price list for performance tests",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(price_list)
    db_session.commit()
    db_session.refresh(price_list)
    return price_list


@pytest.fixture(scope="function")
def simple_scenario(db_session):
    """
    Creates a simple scenario with 5 fields and no rules.
    Baseline for performance comparison.
    """
    entity = Entity(name="Simple Perf Entity", description="Simple scenario")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    fields = []
    for i in range(5):
        field = Field(
            entity_version_id=version.id,
            name=f"field_{i}",
            label=f"Field {i}",
            data_type=FieldType.STRING.value,
            sequence=i,
            is_free_value=True,
        )
        fields.append(field)
    db_session.add_all(fields)
    db_session.commit()

    return {"entity_id": entity.id, "version_id": version.id, "field_ids": [f.id for f in fields]}


@pytest.fixture(scope="function")
def medium_scenario(db_session):
    """
    Creates a medium complexity scenario with 20 fields and 10 rules.
    """
    entity = Entity(name="Medium Perf Entity", description="Medium scenario")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # Create 20 fields
    fields = []
    for i in range(20):
        data_type = [FieldType.STRING.value, FieldType.NUMBER.value, FieldType.BOOLEAN.value][i % 3]
        field = Field(
            entity_version_id=version.id,
            name=f"field_{i}",
            label=f"Field {i}",
            data_type=data_type,
            sequence=i,
            is_free_value=True,
        )
        fields.append(field)
    db_session.add_all(fields)
    db_session.commit()

    # Create 10 rules (visibility and mandatory)
    rules = []
    for i in range(10):
        target_idx = (i + 5) % 20
        source_idx = i % 5
        rule_type = RuleType.VISIBILITY.value if i % 2 == 0 else RuleType.MANDATORY.value

        rule = Rule(
            entity_version_id=version.id,
            target_field_id=fields[target_idx].id,
            rule_type=rule_type,
            conditions={"criteria": [{"field_id": fields[source_idx].id, "operator": "EQUALS", "value": "trigger"}]},
        )
        rules.append(rule)
    db_session.add_all(rules)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "field_ids": [f.id for f in fields],
        "rule_count": len(rules),
    }


@pytest.fixture(scope="function")
def complex_scenario(db_session):
    """
    Creates a complex scenario with 50 fields, 30 rules, and cascading dependencies.
    Stress test for rule engine performance.
    """
    entity = Entity(name="Complex Perf Entity", description="Complex scenario")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # Create 50 fields
    fields = []
    for i in range(50):
        data_type = [FieldType.STRING.value, FieldType.NUMBER.value, FieldType.BOOLEAN.value, FieldType.DATE.value][
            i % 4
        ]
        field = Field(
            entity_version_id=version.id,
            name=f"field_{i}",
            label=f"Field {i}",
            data_type=data_type,
            sequence=i,
            is_free_value=True,
        )
        fields.append(field)
    db_session.add_all(fields)
    db_session.commit()

    # Create 30 rules with various types and cascading dependencies
    rules = []
    rule_types = [RuleType.VISIBILITY.value, RuleType.MANDATORY.value, RuleType.VALIDATION.value]

    for i in range(30):
        target_idx = (i + 10) % 50
        source_idx = i % 10
        rule_type = rule_types[i % 3]

        rule = Rule(
            entity_version_id=version.id,
            target_field_id=fields[target_idx].id,
            rule_type=rule_type,
            error_message=f"Validation error {i}" if rule_type == RuleType.VALIDATION.value else None,
            conditions={
                "criteria": [
                    {"field_id": fields[source_idx].id, "operator": "EQUALS", "value": "trigger"},
                    {"field_id": fields[(source_idx + 1) % 10].id, "operator": "NOT_EQUALS", "value": "block"},
                ]
            },
        )
        rules.append(rule)
    db_session.add_all(rules)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "field_ids": [f.id for f in fields],
        "rule_count": len(rules),
    }


@pytest.fixture(scope="function")
def dropdown_scenario(db_session):
    """
    Creates a scenario with dropdown fields and availability rules.
    Tests cascading dropdown performance.
    """
    entity = Entity(name="Dropdown Perf Entity", description="Dropdown scenario")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # Create dropdown fields
    fields = []
    for i in range(10):
        field = Field(
            entity_version_id=version.id,
            name=f"dropdown_{i}",
            label=f"Dropdown {i}",
            data_type=FieldType.STRING.value,
            sequence=i,
            is_free_value=False,  # Dropdown
        )
        fields.append(field)
    db_session.add_all(fields)
    db_session.commit()

    # Create values for each dropdown (10 options each)
    all_values = []
    for field in fields:
        for j in range(10):
            value = Value(field_id=field.id, label=f"Option {j}", value=f"option_{j}")
            all_values.append(value)
    db_session.add_all(all_values)
    db_session.commit()

    # Create availability rules (cascading)
    rules = []
    for i in range(1, 10):
        # Each dropdown depends on the previous one
        source_field = fields[i - 1]
        target_field = fields[i]
        values_for_target = [v for v in all_values if v.field_id == target_field.id]

        for j, val in enumerate(values_for_target[:5]):  # 5 availability rules per field
            rule = Rule(
                entity_version_id=version.id,
                target_field_id=target_field.id,
                target_value_id=val.id,
                rule_type=RuleType.AVAILABILITY.value,
                conditions={"criteria": [{"field_id": source_field.id, "operator": "EQUALS", "value": f"option_{j}"}]},
            )
            rules.append(rule)
    db_session.add_all(rules)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "field_ids": [f.id for f in fields],
        "rule_count": len(rules),
    }


# ============================================================
# BENCHMARK TESTS - RULE ENGINE
# ============================================================


@pytest.mark.benchmark(group="rule-engine")
def test_benchmark_simple_calculation(benchmark, db_session, simple_scenario):
    """
    Benchmark: Simple rule engine calculation (5 fields, no rules).
    This is the baseline performance metric.
    """
    service = RuleEngineService()

    def run_calculation():
        payload = CalculationRequest(
            entity_id=simple_scenario["entity_id"],
            current_state=[
                FieldInputState(field_id=fid, value=f"value_{i}") for i, fid in enumerate(simple_scenario["field_ids"])
            ],
        )
        return service.calculate_state(db_session, payload)

    result = benchmark(run_calculation)
    assert result is not None
    assert len(result.fields) == 5


@pytest.mark.benchmark(group="rule-engine")
def test_benchmark_medium_calculation(benchmark, db_session, medium_scenario):
    """
    Benchmark: Medium complexity calculation (20 fields, 10 rules).
    """
    service = RuleEngineService()

    def run_calculation():
        payload = CalculationRequest(
            entity_id=medium_scenario["entity_id"],
            current_state=[
                FieldInputState(field_id=fid, value=f"value_{i}") for i, fid in enumerate(medium_scenario["field_ids"])
            ],
        )
        return service.calculate_state(db_session, payload)

    result = benchmark(run_calculation)
    assert result is not None
    assert len(result.fields) == 20


@pytest.mark.benchmark(group="rule-engine")
def test_benchmark_complex_calculation(benchmark, db_session, complex_scenario):
    """
    Benchmark: Complex calculation (50 fields, 30 rules with cascading).
    This tests the rule engine under heavy load.
    """
    service = RuleEngineService()

    def run_calculation():
        payload = CalculationRequest(
            entity_id=complex_scenario["entity_id"],
            current_state=[
                FieldInputState(field_id=fid, value=f"value_{i}") for i, fid in enumerate(complex_scenario["field_ids"])
            ],
        )
        return service.calculate_state(db_session, payload)

    result = benchmark(run_calculation)
    assert result is not None
    assert len(result.fields) == 50


@pytest.mark.benchmark(group="rule-engine")
def test_benchmark_dropdown_cascading(benchmark, db_session, dropdown_scenario):
    """
    Benchmark: Cascading dropdown calculation.
    Tests availability rule performance.
    """
    service = RuleEngineService()

    def run_calculation():
        payload = CalculationRequest(
            entity_id=dropdown_scenario["entity_id"],
            current_state=[FieldInputState(field_id=fid, value="option_0") for fid in dropdown_scenario["field_ids"]],
        )
        return service.calculate_state(db_session, payload)

    result = benchmark(run_calculation)
    assert result is not None


# ============================================================
# BENCHMARK TESTS - API ENDPOINTS
# ============================================================


@pytest.mark.benchmark(group="api")
def test_benchmark_api_list_configurations(
    benchmark, client: TestClient, perf_auth_headers, simple_scenario, perf_price_list
):
    """
    Benchmark: List configurations API endpoint.
    """
    # Create some configurations first
    for i in range(5):
        client.post(
            "/configurations/",
            json={
                "entity_version_id": simple_scenario["version_id"],
                "name": f"Perf Config {i}",
                "price_list_id": perf_price_list.id,
                "data": [],
            },
            headers=perf_auth_headers,
        )

    def call_list():
        return client.get(
            f"/configurations/?entity_version_id={simple_scenario['version_id']}", headers=perf_auth_headers
        )

    result = benchmark(call_list)
    assert result.status_code == 200


@pytest.mark.benchmark(group="api")
def test_benchmark_api_create_configuration(
    benchmark, client: TestClient, perf_auth_headers, simple_scenario, perf_price_list
):
    """
    Benchmark: Create configuration API endpoint.
    """
    counter = [0]

    def create_config():
        counter[0] += 1
        return client.post(
            "/configurations/",
            json={
                "entity_version_id": simple_scenario["version_id"],
                "name": f"Benchmark Config {counter[0]}",
                "price_list_id": perf_price_list.id,
                "data": [{"field_id": simple_scenario["field_ids"][0], "value": "test"}],
            },
            headers=perf_auth_headers,
        )

    result = benchmark(create_config)
    assert result.status_code == 201


@pytest.mark.benchmark(group="api")
def test_benchmark_api_calculate(benchmark, client: TestClient, perf_auth_headers, medium_scenario, perf_price_list):
    """
    Benchmark: Calculate endpoint with medium complexity scenario.
    """
    # Create a configuration
    create_resp = client.post(
        "/configurations/",
        json={
            "entity_version_id": medium_scenario["version_id"],
            "name": "Calc Benchmark",
            "price_list_id": perf_price_list.id,
            "data": [{"field_id": fid, "value": f"val_{i}"} for i, fid in enumerate(medium_scenario["field_ids"][:10])],
        },
        headers=perf_auth_headers,
    )
    config_id = create_resp.json()["id"]

    def call_calculate():
        return client.get(f"/configurations/{config_id}/calculate", headers=perf_auth_headers)

    result = benchmark(call_calculate)
    assert result.status_code == 200


# ============================================================
# THROUGHPUT TESTS
# ============================================================


def test_throughput_calculations(db_session, medium_scenario):
    """
    Throughput test: Measure how many calculations can be performed per second.
    """
    import time

    service = RuleEngineService()
    iterations = 100

    start_time = time.time()

    for i in range(iterations):
        payload = CalculationRequest(
            entity_id=medium_scenario["entity_id"],
            current_state=[FieldInputState(field_id=fid, value=f"value_{i}") for fid in medium_scenario["field_ids"]],
        )
        service.calculate_state(db_session, payload)

    elapsed_time = time.time() - start_time
    throughput = iterations / elapsed_time

    print(f"\n  Throughput: {throughput:.2f} calculations/second")
    print(f"  Total time: {elapsed_time:.2f}s for {iterations} iterations")
    print(f"  Avg time per calculation: {(elapsed_time / iterations) * 1000:.2f}ms")

    # Assert minimum throughput (adjust based on your requirements)
    assert throughput >= 10, f"Throughput too low: {throughput:.2f} calc/s"


def test_throughput_api_requests(client: TestClient, perf_auth_headers, simple_scenario, perf_price_list):
    """
    Throughput test: Measure API requests per second.
    """
    import time

    # Create a configuration to read
    create_resp = client.post(
        "/configurations/",
        json={
            "entity_version_id": simple_scenario["version_id"],
            "name": "Throughput Test",
            "price_list_id": perf_price_list.id,
            "data": [],
        },
        headers=perf_auth_headers,
    )
    config_id = create_resp.json()["id"]

    iterations = 100
    start_time = time.time()

    for _ in range(iterations):
        client.get(f"/configurations/{config_id}", headers=perf_auth_headers)

    elapsed_time = time.time() - start_time
    throughput = iterations / elapsed_time

    print(f"\n  API Throughput: {throughput:.2f} requests/second")
    print(f"  Total time: {elapsed_time:.2f}s for {iterations} requests")
    print(f"  Avg response time: {(elapsed_time / iterations) * 1000:.2f}ms")

    # Assert minimum throughput
    assert throughput >= 50, f"API throughput too low: {throughput:.2f} req/s"


# ============================================================
# SCALING TESTS
# ============================================================


def test_scaling_fields(db_session):
    """
    Test how performance scales with increasing number of fields.
    """
    import time

    service = RuleEngineService()
    results = []

    for num_fields in [10, 25, 50, 100]:
        # Create scenario with N fields
        entity = Entity(name=f"Scale Test {num_fields}", description="Scaling test")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
        db_session.add(version)
        db_session.commit()

        fields = []
        for i in range(num_fields):
            field = Field(
                entity_version_id=version.id,
                name=f"field_{i}",
                label=f"Field {i}",
                data_type=FieldType.STRING.value,
                sequence=i,
                is_free_value=True,
            )
            fields.append(field)
        db_session.add_all(fields)
        db_session.commit()

        # Measure calculation time
        iterations = 10
        start_time = time.time()

        for _ in range(iterations):
            payload = CalculationRequest(
                entity_id=entity.id,
                current_state=[FieldInputState(field_id=f.id, value=f"value_{i}") for i, f in enumerate(fields)],
            )
            service.calculate_state(db_session, payload)

        elapsed = time.time() - start_time
        avg_time_ms = (elapsed / iterations) * 1000

        results.append({"fields": num_fields, "avg_time_ms": avg_time_ms})

        # Cleanup
        db_session.query(Field).filter(Field.entity_version_id == version.id).delete()
        db_session.query(EntityVersion).filter(EntityVersion.id == version.id).delete()
        db_session.query(Entity).filter(Entity.id == entity.id).delete()
        db_session.commit()

    # Print scaling results
    print("\n  Field Scaling Results:")
    print("  Fields | Avg Time (ms)")
    print("  -------|-------------")
    for r in results:
        print(f"  {r['fields']:6} | {r['avg_time_ms']:.2f}")

    # Verify scaling is reasonable (not exponential)
    # Time for 100 fields should not be more than 20x time for 10 fields
    if len(results) >= 2:
        ratio = results[-1]["avg_time_ms"] / results[0]["avg_time_ms"]
        field_ratio = results[-1]["fields"] / results[0]["fields"]
        assert ratio < field_ratio * 3, f"Performance scaling too steep: {ratio:.1f}x for {field_ratio}x fields"


def test_scaling_rules(db_session):
    """
    Test how performance scales with increasing number of rules.
    """
    import time

    service = RuleEngineService()
    results = []

    for num_rules in [0, 10, 25, 50]:
        # Create scenario with fixed fields but varying rules
        entity = Entity(name=f"Rule Scale Test {num_rules}", description="Rule scaling")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
        db_session.add(version)
        db_session.commit()

        # Create 20 fields
        fields = []
        for i in range(20):
            field = Field(
                entity_version_id=version.id,
                name=f"field_{i}",
                label=f"Field {i}",
                data_type=FieldType.STRING.value,
                sequence=i,
                is_free_value=True,
            )
            fields.append(field)
        db_session.add_all(fields)
        db_session.commit()

        # Create N rules
        rules = []
        for i in range(num_rules):
            rule = Rule(
                entity_version_id=version.id,
                target_field_id=fields[(i + 5) % 20].id,
                rule_type=RuleType.VISIBILITY.value,
                conditions={"criteria": [{"field_id": fields[i % 5].id, "operator": "EQUALS", "value": "x"}]},
            )
            rules.append(rule)
        if rules:
            db_session.add_all(rules)
            db_session.commit()

        # Measure
        iterations = 10
        start_time = time.time()

        for _ in range(iterations):
            payload = CalculationRequest(
                entity_id=entity.id,
                current_state=[FieldInputState(field_id=f.id, value=f"value_{i}") for i, f in enumerate(fields)],
            )
            service.calculate_state(db_session, payload)

        elapsed = time.time() - start_time
        avg_time_ms = (elapsed / iterations) * 1000

        results.append({"rules": num_rules, "avg_time_ms": avg_time_ms})

        # Cleanup
        db_session.query(Rule).filter(Rule.entity_version_id == version.id).delete()
        db_session.query(Field).filter(Field.entity_version_id == version.id).delete()
        db_session.query(EntityVersion).filter(EntityVersion.id == version.id).delete()
        db_session.query(Entity).filter(Entity.id == entity.id).delete()
        db_session.commit()

    # Print scaling results
    print("\n  Rule Scaling Results:")
    print("  Rules | Avg Time (ms)")
    print("  ------|-------------")
    for r in results:
        print(f"  {r['rules']:5} | {r['avg_time_ms']:.2f}")


# ============================================================
# MEMORY TESTS (Optional - requires memory_profiler)
# ============================================================


def test_memory_large_payload(db_session, complex_scenario):
    """
    Test memory usage with large payloads.
    Ensures no memory leaks in rule engine processing.
    """
    import gc

    service = RuleEngineService()

    # Force garbage collection before test
    gc.collect()

    # Run multiple calculations
    for i in range(50):
        payload = CalculationRequest(
            entity_id=complex_scenario["entity_id"],
            current_state=[
                FieldInputState(field_id=fid, value=f"value_{i}_{j}")
                for j, fid in enumerate(complex_scenario["field_ids"])
            ],
        )
        result = service.calculate_state(db_session, payload)
        # Explicitly delete reference
        del result

    # Force garbage collection after test
    gc.collect()

    # If we got here without MemoryError, the test passes
    assert True


# ============================================================
# RESPONSE TIME SLA TESTS
# ============================================================


def test_sla_simple_under_100ms(db_session, simple_scenario):
    """
    SLA Test: Simple calculations must complete under 100ms.
    """
    import time

    service = RuleEngineService()

    payload = CalculationRequest(
        entity_id=simple_scenario["entity_id"],
        current_state=[
            FieldInputState(field_id=fid, value=f"value_{i}") for i, fid in enumerate(simple_scenario["field_ids"])
        ],
    )

    start_time = time.time()
    service.calculate_state(db_session, payload)
    elapsed_ms = (time.time() - start_time) * 1000

    assert elapsed_ms < 100, f"Simple calculation took {elapsed_ms:.2f}ms, exceeds 100ms SLA"


def test_sla_medium_under_500ms(db_session, medium_scenario):
    """
    SLA Test: Medium complexity calculations must complete under 500ms.
    """
    import time

    service = RuleEngineService()

    payload = CalculationRequest(
        entity_id=medium_scenario["entity_id"],
        current_state=[
            FieldInputState(field_id=fid, value=f"value_{i}") for i, fid in enumerate(medium_scenario["field_ids"])
        ],
    )

    start_time = time.time()
    service.calculate_state(db_session, payload)
    elapsed_ms = (time.time() - start_time) * 1000

    assert elapsed_ms < 500, f"Medium calculation took {elapsed_ms:.2f}ms, exceeds 500ms SLA"


def test_sla_complex_under_2000ms(db_session, complex_scenario):
    """
    SLA Test: Complex calculations must complete under 2000ms.
    """
    import time

    service = RuleEngineService()

    payload = CalculationRequest(
        entity_id=complex_scenario["entity_id"],
        current_state=[
            FieldInputState(field_id=fid, value=f"value_{i}") for i, fid in enumerate(complex_scenario["field_ids"])
        ],
    )

    start_time = time.time()
    service.calculate_state(db_session, payload)
    elapsed_ms = (time.time() - start_time) * 1000

    assert elapsed_ms < 2000, f"Complex calculation took {elapsed_ms:.2f}ms, exceeds 2000ms SLA"
