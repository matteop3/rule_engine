# Test Suite Documentation

This document describes the structure and organization of the project's test suite.

## Directory Structure

```
tests/
├── conftest.py                  # Core fixtures: db_session, client
├── __init__.py
│
├── fixtures/                    # Centralized test fixtures
│   ├── __init__.py
│   ├── auth.py                  # User and authentication fixtures
│   ├── configurations_lifecycle.py  # Configuration lifecycle fixtures (DRAFT/FINALIZED, clone, upgrade)
│   ├── entities.py              # Entity, Version, Field, Value, Rule fixtures
│   └── engine.py                # Complex scenario fixtures (insurance, dropdown, operator, stress)
│
├── api/                                    # API endpoint tests (FastAPI routes)
│   ├── __init__.py
│   ├── test_auth.py                        # Authentication endpoints (login, token)
│   ├── test_auth_refresh.py               # Token refresh and rate limiting
│   ├── test_request_id.py                  # Request correlation ID middleware + logging filter
│   ├── test_configurations_calculate.py   # Configuration calculate/engine integration
│   ├── test_configurations_clone.py       # Configuration clone operation tests
│   ├── test_configurations_crud.py        # Configuration CRUD operations
│   ├── test_configurations_generated_sku.py  # SKU caching on configuration records
│   ├── test_configurations_finalize.py    # Configuration finalize operation tests
│   ├── test_configurations_lifecycle_rbac.py  # RBAC for lifecycle operations (USER/AUTHOR/ADMIN)
│   ├── test_configurations_rbac.py        # Configuration role-based access control
│   ├── test_configurations_state_transitions.py  # State transition matrix tests (DRAFT/FINALIZED)
│   ├── test_configurations_status.py      # Core status behavior tests (DRAFT/FINALIZED)
│   ├── test_configurations_upgrade.py     # Configuration upgrade operation tests
│   ├── test_configurations_validation.py  # Configuration input validation
│   ├── test_entities.py                    # Entity CRUD operations
│   ├── test_fields.py                      # Field CRUD operations
│   ├── test_rules_crud.py                  # Rule CRUD operations
│   ├── test_rules_edge_cases.py            # Rule edge cases and special scenarios
│   ├── test_rules_types.py                 # Rule type-specific tests
│   ├── test_bom_items.py                   # BOM item CRUD operations, validations, RBAC
│   ├── test_bom_item_rules.py              # BOM item rule CRUD operations, validations, RBAC
│   ├── test_engine_bom.py                  # BOM engine integration (calculate, persist bom_total_price)
│   ├── test_users.py                       # User CRUD operations
│   ├── test_values.py                      # Value CRUD operations
│   └── test_versions.py                    # Version lifecycle (publish, archive, clone)
│
├── engine/                      # Rule engine business logic tests
│   ├── __init__.py
│   ├── test_api.py              # Engine calculation endpoint
│   ├── test_bom_aggregation.py   # BOM line aggregation (grouping, quantity summing)
│   ├── test_bom_evaluation.py   # BOM inclusion/exclusion, OR/AND logic, type filtering
│   ├── test_bom_quantity.py     # BOM quantity resolution (static, field ref, fallback)
│   ├── test_bom_tree.py         # BOM tree pruning, nesting, sequence ordering
│   ├── test_cache.py            # TTLCache unit tests + engine caching integration tests
│   ├── test_calculation.py      # CALCULATION rule type (forced values, waterfall interactions, SKU, completeness)
│   ├── test_dropdowns.py        # Cascading dropdown logic
│   ├── test_logic.py            # Core engine logic (validation, mandatory, visibility, availability)
│   ├── test_operators.py        # Operator tests (EQUALS, GREATER_THAN, IN, etc.)
│   ├── test_sku_generation.py   # Smart SKU generation (modifiers, visibility, free-value fields)
│   └── test_stress.py           # Engine stress tests (domino effects, dependencies)
│
├── integration/                                     # End-to-end integration tests
│   ├── __init__.py
│   ├── test_data_integrity_clone_remapping.py   # Clone ID remapping logic
│   ├── test_data_integrity_consistency.py       # General data consistency checks
│   ├── test_data_integrity_field_dependencies.py # Field-rule dependency validation
│   ├── test_data_integrity_orphan_prevention.py # Orphan record prevention
│   ├── test_data_integrity_unique_constraints.py # Unique constraint enforcement
│   ├── test_data_integrity_value_dependencies.py # Value-rule dependency validation
│   ├── test_bom_workflow.py                      # End-to-end BOM lifecycle and configuration integration
│   ├── test_clone_bom.py                        # BOM data integrity during version clone
│   ├── test_integration_cascade.py              # Cascade delete/update operations
│   ├── test_integration_complex_rules.py        # Complex rule interaction scenarios
│   ├── test_integration_cross_router.py         # Cross-router data consistency
│   ├── test_integration_entity_lifecycle.py     # Complete entity lifecycle workflows
│   └── test_integration_rbac.py                 # End-to-end RBAC scenarios
│
├── performance/                 # Performance and benchmark tests
│   ├── __init__.py
│   └── test_performance.py      # Pytest-benchmark performance tests
│
└── stress/                      # Concurrency and stress tests
    ├── __init__.py
    ├── test_concurrency.py      # Concurrent operations and race conditions
    └── test_versioning_stress.py # Version cloning and complex scenarios

```

## Naming Conventions

### Files
- All test files start with `test_` prefix (pytest requirement)
- Avoid redundant prefixes/suffixes (e.g., `api/test_auth.py` not `api/test_auth_api.py`)
- Use descriptive names that clearly indicate what is being tested

### Test Functions and Classes
- API tests use classes to group related operations:
  ```python
  class TestCreateEntity:
      def test_success(...)
      def test_validation_error(...)
      def test_authorization(...)
  ```
- Engine tests use descriptive function names:
  ```python
  def test_operator_equals_string(...)
  def test_dropdown_cascade_logic(...)
  ```

## Fixture Organization

### Core Fixtures (conftest.py)
- `db_session`: Clean in-memory database for each test
- `client`: FastAPI TestClient with database override
- `clear_engine_cache` (autouse): Clears the RuleEngineService in-memory cache after each test to prevent cross-test pollution. Global and autouse because API tests that call `calculate_state` indirectly also need a clean cache.
- **Logging configuration**: `setup_logging(json_output=False)` is called at module level in the root `conftest.py` to use plain-text logs during tests, avoiding JSON noise in pytest output and preventing interference with pytest's log capture.

### Auth Fixtures (fixtures/auth.py)
- `admin_user`, `admin_headers`: Admin role user and auth headers
- `author_user`, `author_headers`: Author role user and auth headers
- `regular_user`, `user_headers`: Regular user and auth headers
- `inactive_user`: Inactive user for access denial tests

### Entity Fixtures (fixtures/entities.py)
- **Entities:** `test_entity`, `second_entity`
- **Versions:** `draft_version`, `published_version`, `archived_version`, `version_with_data`
- **Fields:** `draft_field`, `free_field`, `field_with_values`, `field_as_rule_target`, `published_field`, `archived_field`
- **Values:** `draft_value`, `value_in_rule_target`, `value_in_rule_condition`
- **Rules:** `draft_rule`, `published_rule`, `archived_rule`, `rule_with_value_target`
- **BOM Items:** `draft_bom_item`

### Engine Fixtures (fixtures/engine.py)
- `setup_insurance_scenario`: Complex auto insurance scenario with all rule types
- `setup_dropdown_scenario`: Cascading dropdown (Region → City)
- `setup_operator_scenario`: Generic scenario for operator testing
- `setup_stress_scenario`: Complex interdependent fields for stress testing
- `setup_sku_scenario`: SKU generation with multiple fields and `sku_modifier` values
- `setup_sku_visibility_scenario`: SKU with visibility rules (hidden fields excluded)
- `setup_sku_hidden_default_scenario`: SKU with `is_hidden=True` fields
- `setup_sku_availability_scenario`: SKU integrated with availability rules
- `setup_calculation_scenario`: CALCULATION rule type scenario with waterfall interactions (visibility, editability, availability, mandatory, validation)

### Configuration Lifecycle Fixtures (fixtures/configurations_lifecycle.py)
- **Users:** `lifecycle_admin`, `lifecycle_author`, `lifecycle_user`, `second_lifecycle_user` with corresponding headers
- **Entity & Versions:** `lifecycle_entity`, `multi_version_entity` (ARCHIVED/PUBLISHED/DRAFT versions), `published_version_for_lifecycle`
- **Configurations by Status:**
  - `draft_configuration`, `finalized_configuration`: Basic status-specific configs
  - `soft_deleted_configuration`: FINALIZED with is_deleted=True
  - `configuration_with_empty_data`, `configuration_null_name`: Edge case configs
- **Configurations by Owner:**
  - `admin_owned_draft_configuration`, `admin_owned_finalized_configuration`
  - `author_owned_draft_configuration`
  - `second_user_draft_configuration`, `second_user_finalized_configuration`
- **Upgrade Testing:** `configuration_on_archived_version`, `configuration_on_published_multi_version`

## Running Tests

### Run all tests
```bash
pytest tests/
```

### Run specific categories
```bash
pytest tests/api/              # API tests only
pytest tests/engine/           # Engine tests only
pytest tests/integration/      # Integration tests only
pytest tests/performance/      # Performance benchmarks
pytest tests/stress/           # Stress and concurrency tests
```

### Run specific test file
```bash
pytest tests/api/test_auth.py -v
```

### Run configuration lifecycle tests
```bash
pytest tests/api/test_configurations_status.py -v          # Status behavior
pytest tests/api/test_configurations_clone.py -v           # Clone operation
pytest tests/api/test_configurations_upgrade.py -v         # Upgrade operation
pytest tests/api/test_configurations_finalize.py -v        # Finalize operation
pytest tests/api/test_configurations_lifecycle_rbac.py -v  # RBAC for lifecycle
pytest tests/api/test_configurations_state_transitions.py -v  # State matrix
```

### Run specific test
```bash
pytest tests/api/test_auth.py::TestLoginEndpoint::test_success -v
```

## Test Statistics

| Category      | Files | Approx. Tests | Purpose                          |
|---------------|-------|---------------|----------------------------------|
| API           | 25    | ~362          | Endpoint CRUD, lifecycle, middleware, BOM |
| Engine        | 12    | ~124          | Business logic, rules, SKU, cache, BOM |
| Integration   | 14    | ~26           | End-to-end workflows, BOM clone, BOM lifecycle |
| Performance   | 1     | ~15           | Benchmarks and throughput        |
| Stress        | 2     | ~15           | Concurrency and edge cases       |
| **Total**     | **53**| **~540**      |                                  |

## Test Coverage

The test suite provides comprehensive coverage across all application layers:

### API Endpoints (~260 tests)
- **Authentication**: Login, token refresh, rate limiting, session management
- **Configurations**: Full CRUD, rule engine integration, validation, RBAC
- **Configuration Lifecycle** (~155 tests): Status management, clone, upgrade, finalize operations
- **Entities & Versions**: Lifecycle management, publishing, archiving, cloning
- **Fields & Values**: CRUD operations, data type validation, constraints, `sku_modifier` attribute
- **Rules**: CRUD, type-specific logic (including CALCULATION `set_value` validation), edge cases, complex scenarios
- **BOM Items**: CRUD, DRAFT-only enforcement, RBAC, pricing/type validation, hierarchy, COMMERCIAL-is-root, price consistency
- **BOM Item Rules**: CRUD, DRAFT-only enforcement, RBAC, ownership validation, conditions field_id validation
- **BOM Engine Integration**: Stateless and stateful BOM calculation, `bom_total_price` persistence across create/update/upgrade/clone
- **Users**: User management, role assignment, access control
- **Middleware**: Request correlation ID generation, propagation, and logging filter injection

#### DRAFT-only Policy Coverage
The test suite comprehensively validates that Fields, Values, and Rules can only be modified in DRAFT versions:

| Operation | DRAFT | PUBLISHED | ARCHIVED |
|-----------|-------|-----------|----------|
| Field CREATE | ✅ | ✅ 409 | ✅ 409 |
| Field UPDATE | ✅ | ✅ 409 | ✅ 409 |
| Field DELETE | ✅ | ✅ 409 | ✅ 409 |
| Rule CREATE | ✅ | ✅ 409 | ✅ 409 |
| Rule UPDATE | ✅ | ✅ 409 | ✅ 409 |
| Rule DELETE | ✅ | ✅ 409 | ✅ 409 |
| Value CREATE | ✅ | ✅ 409 | ✅ 409 |
| Value UPDATE | ✅ | ✅ 409 | ✅ 409 |
| Value DELETE | ✅ | ✅ 409 | ✅ 409 |
| BOM Item CREATE | ✅ | ✅ 409 | ✅ 409 |
| BOM Item UPDATE | ✅ | ✅ 409 | ✅ 409 |
| BOM Item DELETE | ✅ | ✅ 409 | ✅ 409 |
| BOM Item Rule CREATE | ✅ | ✅ 409 | ✅ 409 |
| BOM Item Rule UPDATE | ✅ | ✅ 409 | ✅ 409 |
| BOM Item Rule DELETE | ✅ | ✅ 409 | ✅ 409 |

All tests validate both the HTTP status code (409 Conflict) and the error message containing "draft".

#### Value SKU Modifier Tests (`test_values.py::TestValueSKUModifier`)
- **Create**: Value with `sku_modifier`, value without `sku_modifier` (optional field)
- **Update**: Update `sku_modifier`, update with other fields, clear `sku_modifier` (set to null)
- **Read**: Single value and list include `sku_modifier` in response
- **DRAFT-only**: Cannot update `sku_modifier` on PUBLISHED version (HTTP 409)
- **Edge cases**: Special characters, max length, move value preserves modifier

### Configuration Lifecycle Tests (~155 tests)

The configuration lifecycle management feature is thoroughly tested across multiple dimensions:

#### Status Management (`test_configurations_status.py`)
- **Create**: Default DRAFT status, is_deleted=False, cannot override status on create
- **List**: Exclude deleted by default, include_deleted for ADMIN, status filters (DRAFT/FINALIZED)
- **Read**: Status and is_deleted fields in response, visibility rules for deleted configs
- **Update**: DRAFT allowed, FINALIZED blocked (HTTP 409), guard clauses
- **Delete**: Hard delete for DRAFT, soft delete for FINALIZED (ADMIN only), forbidden for USER on FINALIZED

#### Generated SKU Caching (`test_configurations_generated_sku.py`)
- **Create**: SKU is calculated and cached from rule engine result, null when no sku_base configured
- **Update**: SKU is recalculated when data changes
- **Clone**: SKU is copied from source configuration
- **Upgrade**: SKU is recalculated against new version's sku_base
- **List**: SKU appears in list response

#### Clone Operation (`test_configurations_clone.py`)
- **Basic Functionality**: Creates new UUID, always results in DRAFT status, copies data and version reference
- **Data Preservation**: Input data, entity_version_id, is_complete flag, name with "(Copy)" suffix
- **Access Control**: Owner and ADMIN can clone, USER/AUTHOR cannot clone others' configs
- **Edge Cases**: Empty data, null name, deleted configs, multiple clones uniqueness

#### Upgrade Operation (`test_configurations_upgrade.py`)
- **Basic Functionality**: Updates entity_version_id to latest PUBLISHED, preserves input data
- **Status Constraints**: DRAFT allowed, FINALIZED blocked (HTTP 409 with clone suggestion)
- **Version Resolution**: Finds PUBLISHED, ignores DRAFT/ARCHIVED, handles missing PUBLISHED (404)
- **Access Control**: Owner and ADMIN can upgrade, USER cannot upgrade others' configs
- **Edge Cases**: Incompatible fields between versions (may set `is_complete=False`), audit field updates, idempotency

#### Finalize Operation (`test_configurations_finalize.py`)
- **Basic Functionality**: Changes status to FINALIZED, preserves all data, version, and is_complete
- **Completeness Requirement**: Only configurations with `is_complete=True` can be finalized (HTTP 400 if incomplete)
- **Idempotency/Constraints**: Cannot finalize twice (HTTP 409), audit field updates
- **Access Control**: Owner and ADMIN can finalize, USER/AUTHOR cannot finalize others' configs
- **Post-Finalize Behavior**: Update blocked, upgrade blocked, clone allowed, delete blocked for USER

#### Lifecycle RBAC (`test_configurations_lifecycle_rbac.py`)
- **USER Role**: Full access to own DRAFT, read-only on own FINALIZED, can clone FINALIZED, cannot delete FINALIZED
- **AUTHOR Role**: Same restrictions as USER for configurations (elevated privileges are for rules)
- **ADMIN Role**: Access all configs, soft-delete FINALIZED, cannot modify FINALIZED data, can clone any
- **Cross-Role Interactions**: Multi-user workflows, ownership isolation, visibility after soft-delete

#### State Transition Matrix (`test_configurations_state_transitions.py`)
- **DRAFT → DRAFT**: UPDATE allowed, UPGRADE allowed
- **DRAFT → FINALIZED**: FINALIZE operation (requires `is_complete=True`, HTTP 400 if incomplete)
- **DRAFT → Deleted**: Hard delete (record removed)
- **FINALIZED → FINALIZED**: UPDATE/UPGRADE/FINALIZE all blocked (HTTP 409)
- **FINALIZED → Soft Deleted**: ADMIN only, USER denied (HTTP 403)
- **Any → DRAFT**: CLONE always creates new DRAFT

### Rule Engine (~62 tests)
- **Core Logic**: Field validation, mandatory checks, visibility rules, availability logic
- **Caching**: TTLCache unit tests (set/get, TTL expiry, eviction, invalidation, stats) + engine integration tests (PUBLISHED cached, DRAFT not cached, invalidation on publish, session independence)
- **CALCULATION Rules**: Forced values, waterfall interactions, multiple rules, running context, SKU, completeness
- **Operators**: All comparison operators (EQUALS, NOT_EQUALS, GREATER_THAN, GREATER_THAN_OR_EQUAL, LESS_THAN, LESS_THAN_OR_EQUAL, IN)
- **Dropdown Logic**: Cascading dropdowns, dynamic value filtering
- **SKU Generation**: Smart SKU generation with modifiers (see below)
- **BOM Evaluation**: Inclusion/exclusion logic, OR/AND conditions, type filtering, line totals, commercial total
- **BOM Quantities**: Static quantity, field reference, null fallback, zero/negative exclusion, decimal support
- **BOM Tree**: Parent-child cascade pruning, three-level nesting, sibling independence, sequence ordering
- **BOM Aggregation**: Part-number grouping, quantity summing, type-aware keys, parent-aware keys
- **Stress Tests**: Domino effects, complex dependencies, performance under load

#### CALCULATION Rule Tests (`test_calculation.py`)
The CALCULATION rule type is comprehensively tested:

| Category | Tests | Description |
|----------|-------|-------------|
| Basic Behavior | 4 | Fires/doesn't fire, free-value vs non-free field output |
| Waterfall Interactions | 6 | Hidden field skip, EDITABILITY/AVAILABILITY skip, MANDATORY kept, VALIDATION safety net |
| Multiple Rules | 1 | First passing CALCULATION wins |
| Invalid set_value | 2 | Non-free field with unmatched set_value blanked to None, None propagated to downstream context |
| Running Context | 1 | Calculated values propagate to downstream conditions |
| SKU Integration | 1 | Calculated values feed into SKU generation |
| Completeness | 2 | Calculated fields satisfy required-field checks |

#### SKU Generation Tests (`test_sku_generation.py`)
The SKU generation feature is comprehensively tested across multiple scenarios:

| Category | Tests | Description |
|----------|-------|-------------|
| Basic Functionality | 3 | Base SKU generation, custom delimiter, empty delimiter handling |
| SKU Base Handling | 2 | Null/empty `sku_base` returns `None` |
| Modifier Handling | 2 | Values without modifiers skipped, only base SKU when no modifiers |
| Visibility Handling | 2 | Hidden fields (by rule or default) excluded from SKU |
| **Free-Value Fields** | **5** | `sku_modifier_when_filled` support for free-value fields |
| Field Ordering | 1 | SKU respects `step`/`sequence` ordering |
| No Value Selected | 1 | Unselected fields excluded from SKU |
| Max Length | 1 | SKU truncated at 100 characters |
| Availability Rules | 2 | Integration with availability rules |
| Edge Cases | 4 | Special characters, empty config, combined field types |

**Free-Value Fields with SKU Modifiers:**
- `test_free_value_field_ignored`: Free-value fields without `sku_modifier_when_filled` are ignored
- `test_free_value_field_with_modifier_when_filled`: When free-value field has a value, `sku_modifier_when_filled` is added to SKU
- `test_free_value_field_with_modifier_when_empty`: When free-value field is empty, modifier is NOT included
- `test_free_value_field_modifier_combined_with_regular_values`: Free-value modifiers combine correctly with regular value modifiers
- `test_free_value_field_without_modifier_config_still_ignored`: Backward compatibility - free-value fields without config are still ignored

### Integration & E2E (~18 tests)
- **Data Integrity**: Referential integrity, orphan prevention, unique constraints
- **Cross-Module Workflows**: Entity lifecycle, cross-router consistency
- **Cascade Operations**: Delete/update propagation
- **RBAC End-to-End**: Complete authorization flows across modules
- **Complex Rule Interactions**: Multi-rule scenarios, interdependencies
- **BOM Clone Remapping**: BOM item/rule ID remapping during version clone (parent, quantity_from_field, conditions)
- **Configuration Lifecycle Flows**: Complete workflows (create → update → finalize → clone → modify), upgrade-then-finalize blocked when incompatible

### Performance & Stress (~30 tests)
- **Benchmarks**: Throughput measurements, response time analysis
- **Concurrency**: Race condition detection, parallel operation handling
- **Version Cloning**: Large-scale cloning stress tests

### Coverage Metrics
To generate a coverage report:
```bash
pytest --cov=app --cov-report=html --cov-report=term tests/
```

Coverage targets:
- **Overall**: >85% line coverage
- **Critical paths** (auth, engine, data integrity): >95% coverage
- **API endpoints**: 100% route coverage
- **Configuration lifecycle** (status guards, clone, upgrade, finalize): 100% coverage

## Test Organization Principles

The test suite follows these key principles:

- **Hierarchical structure by test category**: Tests are organized by type (API, engine, integration, performance, stress)
- **Centralized fixtures**: Shared fixtures in dedicated modules to avoid duplication
- **Consistent naming conventions**: All test files use `test_` prefix with descriptive names
- **Focused, single-responsibility files**: Each file tests one specific aspect (200-500 lines optimal)
- **Clear separation of concerns**: CRUD vs validation vs RBAC tests are in separate files

## Guidelines for New Tests

1. **Choose the right directory:**
   - Testing an API endpoint? → `api/`
   - Testing rule engine logic? → `engine/`
   - Testing cross-module workflows? → `integration/`
   - Testing performance? → `performance/`
   - Testing concurrency/edge cases? → `stress/`
   - Testing configuration lifecycle (status, clone, upgrade, finalize)? → `api/test_configurations_*.py`

2. **Use existing fixtures:**
   - Check `fixtures/` modules before creating new fixtures
   - Prefer composition of existing fixtures over creating new ones

3. **Follow naming conventions:**
   - File: `test_<feature>.py`
   - Class: `Test<Operation><Resource>`
   - Function: `test_<specific_case>`

4. **Write clear docstrings:**
   ```python
   def test_dropdown_cascade_logic(...):
       """
       GIVEN: Region=NORD with cascading city dropdown
       WHEN: User selects NORD region
       THEN: Only northern cities (Milano, Torino) are available
       """

   # For lifecycle tests, use descriptive single-line docstrings:
   def test_finalize_changes_status(...):
       """Finalize should change status to FINALIZED."""

   def test_clone_finalized_creates_draft(...):
       """Cloning FINALIZED config should create a new DRAFT configuration."""
   ```

5. **Keep tests atomic and independent:**
   - Each test should run in isolation
   - Use fixtures for setup, not test dependencies
   - Clean up is handled automatically by fixtures

## Maintenance

- Keep this documentation updated when adding new test categories
- Periodically review test coverage: `pytest --cov=app tests/`
- **File size guideline:** Aim for 200-500 lines per test file for optimal maintainability
- **When to split:** If a test file exceeds ~500 lines, consider splitting by:
  - Functionality (CRUD vs validation vs RBAC)
  - Test classes (one class per file for integration tests)
  - Scenarios (different end-to-end workflows)
- Remove obsolete tests when features are deprecated
