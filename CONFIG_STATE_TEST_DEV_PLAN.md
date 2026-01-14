# Configuration Status Test Development Plan

## Overview

This document outlines the comprehensive test strategy for the Configuration lifecycle management feature, including status transitions (DRAFT/FINALIZED), clone, upgrade, finalize operations, and RBAC enforcement.

---

## Test File Structure

```
tests/
├── api/
│   ├── test_configurations_status.py          # Core status behavior tests
│   ├── test_configurations_clone.py           # Clone operation tests
│   ├── test_configurations_upgrade.py         # Upgrade operation tests
│   ├── test_configurations_finalize.py        # Finalize operation tests
│   └── test_configurations_lifecycle_rbac.py  # RBAC for lifecycle operations
└── fixtures/
    └── configurations_lifecycle.py            # Shared fixtures for lifecycle tests
```

---

## Test Categories

### 1. Model Layer Tests

#### 1.1 ConfigurationStatus Enum Tests
**File:** `tests/models/test_configuration_status_enum.py`

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_status_enum_values` | Verify enum has exactly DRAFT and FINALIZED | Enum values match specification |
| `test_status_enum_string_representation` | Check string serialization | "DRAFT" and "FINALIZED" strings |
| `test_status_default_value` | New Configuration gets DRAFT | `config.status == DRAFT` |

#### 1.2 Configuration Model Tests
**File:** `tests/models/test_configuration_model.py`

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_configuration_status_field_exists` | Verify status column in model | Column present with correct type |
| `test_configuration_is_deleted_field_exists` | Verify is_deleted column | Column present, default False |
| `test_configuration_status_index_exists` | Verify ix_config_status index | Index created on status column |
| `test_configuration_deleted_index_exists` | Verify ix_config_deleted index | Index created on is_deleted column |
| `test_configuration_repr_includes_status` | Check __repr__ output | Status included in representation |

---

### 2. Schema Layer Tests

#### 2.1 ConfigurationRead Schema Tests
**File:** `tests/schemas/test_configuration_schemas.py`

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_configuration_read_includes_status` | Status field in response schema | Field present with enum type |
| `test_configuration_read_includes_is_deleted` | is_deleted field in response | Field present, default False |
| `test_configuration_create_no_status_field` | Create schema excludes status | Status not settable on create |
| `test_configuration_update_no_status_field` | Update schema excludes status | Status not settable on update |
| `test_clone_response_includes_source_id` | Clone response has source_id | source_id field present |

---

### 3. API Endpoint Tests

#### 3.1 Create Configuration (POST /configurations/)
**File:** `tests/api/test_configurations_status.py`

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_create_configuration_default_status_draft` | New config has DRAFT status | `response.status == "DRAFT"` |
| `test_create_configuration_is_deleted_false` | New config not deleted | `response.is_deleted == False` |
| `test_create_configuration_cannot_set_status` | Cannot override status on create | Status ignored, defaults to DRAFT |
| `test_create_configuration_cannot_set_is_deleted` | Cannot set is_deleted on create | Field ignored |

#### 3.2 List Configurations (GET /configurations/)
**File:** `tests/api/test_configurations_status.py`

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_list_excludes_deleted_by_default` | Soft-deleted configs hidden | Deleted configs not in results |
| `test_list_include_deleted_admin_only` | ADMIN can see deleted | include_deleted=true works for ADMIN |
| `test_list_include_deleted_denied_for_user` | USER cannot see deleted | Parameter ignored for non-ADMIN |
| `test_list_filter_by_status_draft` | Filter status=DRAFT works | Only DRAFT configs returned |
| `test_list_filter_by_status_finalized` | Filter status=FINALIZED works | Only FINALIZED configs returned |
| `test_list_filter_invalid_status` | Invalid status value | HTTP 400 Bad Request |
| `test_list_combines_status_and_deleted_filters` | Multiple filters work together | Correct intersection |

#### 3.3 Read Configuration (GET /configurations/{id})
**File:** `tests/api/test_configurations_status.py`

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_read_returns_status_field` | Response includes status | Status field in JSON response |
| `test_read_returns_is_deleted_field` | Response includes is_deleted | Field in JSON response |
| `test_read_deleted_config_404_for_user` | Deleted config hidden from USER | HTTP 404 (or 403) |
| `test_read_deleted_config_visible_to_admin` | ADMIN can read deleted config | HTTP 200 with config data |

#### 3.4 Update Configuration (PATCH /configurations/{id})
**File:** `tests/api/test_configurations_status.py`

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_update_draft_allowed` | DRAFT config can be updated | HTTP 200, changes applied |
| `test_update_finalized_blocked` | FINALIZED config cannot update | HTTP 409 Conflict |
| `test_update_finalized_error_message` | Error suggests clone | Message mentions clone operation |
| `test_update_draft_name_only` | Update name works on DRAFT | Name changed, data unchanged |
| `test_update_draft_data_only` | Update data works on DRAFT | Data changed, recalculated |
| `test_update_cannot_change_status_via_patch` | Status not modifiable via PATCH | Status unchanged |
| `test_update_deleted_config_fails` | Cannot update deleted config | HTTP 404 or 409 |

#### 3.5 Delete Configuration (DELETE /configurations/{id})
**File:** `tests/api/test_configurations_status.py`

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_delete_draft_hard_delete_owner` | Owner can hard-delete DRAFT | HTTP 204, config removed |
| `test_delete_draft_hard_delete_admin` | ADMIN can hard-delete DRAFT | HTTP 204, config removed |
| `test_delete_finalized_soft_delete_admin` | ADMIN soft-deletes FINALIZED | HTTP 204, is_deleted=True |
| `test_delete_finalized_denied_for_user` | USER cannot delete FINALIZED | HTTP 403 Forbidden |
| `test_delete_finalized_denied_for_author` | AUTHOR cannot delete FINALIZED | HTTP 403 Forbidden |
| `test_delete_finalized_error_message` | Error suggests clone | Message mentions alternative |
| `test_soft_deleted_config_hidden_in_list` | Soft-deleted not in default list | Config excluded |
| `test_soft_deleted_preserves_data` | Soft delete keeps all data | Data integrity verified |

---

### 4. Clone Operation Tests

**File:** `tests/api/test_configurations_clone.py`

#### 4.1 Basic Clone Functionality

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_clone_draft_creates_new_config` | Clone DRAFT config | New UUID, HTTP 201 |
| `test_clone_finalized_creates_new_config` | Clone FINALIZED config | New UUID, HTTP 201 |
| `test_clone_result_always_draft` | Clone is always DRAFT | `clone.status == "DRAFT"` |
| `test_clone_copies_input_data` | Data preserved in clone | Identical data array |
| `test_clone_copies_version_reference` | entity_version_id preserved | Same version ID |
| `test_clone_copies_name_with_suffix` | Name gets " (Copy)" suffix | `"Original (Copy)"` |
| `test_clone_null_name_stays_null` | Null name cloned as null | `clone.name == None` |
| `test_clone_copies_is_complete` | is_complete preserved | Same value as source |
| `test_clone_source_unchanged` | Source not modified | Original intact |
| `test_clone_returns_source_id` | Response has source_id | source_id matches original |

#### 4.2 Clone Access Control

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_clone_owner_can_clone_own` | Owner can clone own config | HTTP 201 |
| `test_clone_admin_can_clone_any` | ADMIN can clone any config | HTTP 201 |
| `test_clone_user_cannot_clone_others` | USER cannot clone other's config | HTTP 403 |
| `test_clone_author_cannot_clone_others` | AUTHOR cannot clone other's config | HTTP 403 |
| `test_clone_deleted_config_fails` | Cannot clone deleted config | HTTP 404 |

#### 4.3 Clone Edge Cases

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_clone_with_empty_data` | Clone config with empty data | Works, empty array cloned |
| `test_clone_with_large_data` | Clone config with many fields | All fields preserved |
| `test_clone_assigns_current_user_as_owner` | Clone owned by cloning user | `clone.user_id == current_user` |
| `test_clone_sets_new_audit_timestamps` | Fresh created_at/updated_at | Timestamps are current |
| `test_clone_nonexistent_config` | Clone non-existent ID | HTTP 404 |

---

### 5. Upgrade Operation Tests

**File:** `tests/api/test_configurations_upgrade.py`

#### 5.1 Basic Upgrade Functionality

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_upgrade_updates_version_id` | Version ID changes to latest | entity_version_id updated |
| `test_upgrade_preserves_input_data` | User data unchanged | Same data array |
| `test_upgrade_recalculates_is_complete` | is_complete recalculated | New rules applied |
| `test_upgrade_already_on_latest` | No change if already latest | HTTP 200, unchanged |
| `test_upgrade_returns_updated_config` | Response has new version | Full config in response |

#### 5.2 Upgrade Status Constraints

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_upgrade_draft_allowed` | DRAFT can be upgraded | HTTP 200 |
| `test_upgrade_finalized_blocked` | FINALIZED cannot upgrade | HTTP 409 Conflict |
| `test_upgrade_finalized_error_message` | Error suggests clone | Message mentions clone |
| `test_upgrade_deleted_config_fails` | Cannot upgrade deleted | HTTP 404 |

#### 5.3 Upgrade Version Resolution

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_upgrade_finds_published_version` | Finds PUBLISHED version | Correct version used |
| `test_upgrade_no_published_version` | No PUBLISHED exists | HTTP 404 |
| `test_upgrade_ignores_draft_versions` | DRAFT versions skipped | Only PUBLISHED considered |
| `test_upgrade_ignores_archived_versions` | ARCHIVED versions skipped | Only PUBLISHED considered |
| `test_upgrade_from_archived_to_published` | Config on ARCHIVED version | Upgrades to PUBLISHED |

#### 5.4 Upgrade Access Control

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_upgrade_owner_can_upgrade_own` | Owner can upgrade | HTTP 200 |
| `test_upgrade_admin_can_upgrade_any` | ADMIN can upgrade any | HTTP 200 |
| `test_upgrade_user_cannot_upgrade_others` | USER cannot upgrade other's | HTTP 403 |

#### 5.5 Upgrade Edge Cases

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_upgrade_with_incompatible_fields` | Fields removed in new version | Graceful handling |
| `test_upgrade_with_new_required_fields` | New required fields | is_complete may change |
| `test_upgrade_updates_audit_fields` | updated_by_id set | Current user recorded |

---

### 6. Finalize Operation Tests

**File:** `tests/api/test_configurations_finalize.py`

#### 6.1 Basic Finalize Functionality

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_finalize_changes_status` | Status becomes FINALIZED | `status == "FINALIZED"` |
| `test_finalize_returns_updated_config` | Response has new status | Full config returned |
| `test_finalize_preserves_all_data` | Data unchanged | All fields intact |
| `test_finalize_preserves_version` | Version reference unchanged | Same entity_version_id |

#### 6.2 Finalize Idempotency and Constraints

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_finalize_already_finalized` | Cannot finalize twice | HTTP 409 Conflict |
| `test_finalize_deleted_config_fails` | Cannot finalize deleted | HTTP 404 |
| `test_finalize_updates_audit_fields` | updated_by_id set | Current user recorded |

#### 6.3 Finalize Access Control

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_finalize_owner_can_finalize` | Owner can finalize | HTTP 200 |
| `test_finalize_admin_can_finalize_any` | ADMIN can finalize any | HTTP 200 |
| `test_finalize_user_cannot_finalize_others` | USER cannot finalize other's | HTTP 403 |
| `test_finalize_author_cannot_finalize_others` | AUTHOR cannot finalize other's | HTTP 403 |

---

### 7. RBAC Matrix Tests

**File:** `tests/api/test_configurations_lifecycle_rbac.py`

#### 7.1 USER Role Tests

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_user_full_access_own_draft` | USER has full access to own DRAFT | CRUD + lifecycle works |
| `test_user_read_only_own_finalized` | USER can only read own FINALIZED | Updates blocked |
| `test_user_can_clone_own_finalized` | USER can clone own FINALIZED | HTTP 201 |
| `test_user_cannot_delete_finalized` | USER cannot delete FINALIZED | HTTP 403 |
| `test_user_cannot_upgrade_finalized` | USER cannot upgrade FINALIZED | HTTP 409 |
| `test_user_no_access_others_configs` | USER cannot access other's configs | HTTP 403 |

#### 7.2 AUTHOR Role Tests

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_author_same_restrictions_as_user` | AUTHOR has same config restrictions | Same behavior as USER |
| `test_author_full_access_own_draft` | AUTHOR full access own DRAFT | CRUD works |
| `test_author_cannot_delete_finalized` | AUTHOR cannot delete FINALIZED | HTTP 403 |

#### 7.3 ADMIN Role Tests

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_admin_can_access_all_configs` | ADMIN sees all configs | Full access |
| `test_admin_can_soft_delete_finalized` | ADMIN can soft-delete FINALIZED | is_deleted=True |
| `test_admin_cannot_modify_finalized_data` | ADMIN cannot alter FINALIZED inputs | HTTP 409 |
| `test_admin_can_clone_any_config` | ADMIN can clone anyone's config | HTTP 201 |
| `test_admin_can_view_deleted_configs` | ADMIN can include deleted in list | include_deleted works |

#### 7.4 Cross-Role Interaction Tests

| Test ID | Description | Expected Outcome |
|---------|-------------|------------------|
| `test_user_creates_admin_finalizes` | Multi-user workflow | Status transitions work |
| `test_author_creates_user_cannot_access` | Ownership isolation | USER cannot see AUTHOR's |
| `test_admin_soft_deletes_user_cannot_see` | Soft delete hides from USER | Visibility correct |

---

### 8. State Transition Matrix Tests

**File:** `tests/api/test_configurations_state_transitions.py`

| From State | To State | Operation | Expected |
|------------|----------|-----------|----------|
| DRAFT | DRAFT | UPDATE | Allowed |
| DRAFT | DRAFT | UPGRADE | Allowed |
| DRAFT | FINALIZED | FINALIZE | Allowed |
| DRAFT | (deleted) | DELETE | Hard delete |
| FINALIZED | FINALIZED | UPDATE | HTTP 409 |
| FINALIZED | FINALIZED | UPGRADE | HTTP 409 |
| FINALIZED | FINALIZED | FINALIZE | HTTP 409 |
| FINALIZED | (soft deleted) | DELETE (ADMIN) | Soft delete |
| FINALIZED | (denied) | DELETE (USER) | HTTP 403 |
| Any | DRAFT | CLONE | Always DRAFT |

---

### 9. Integration Tests

**File:** `tests/integration/test_configuration_lifecycle_flow.py`

#### 9.1 Complete Lifecycle Flow

| Test ID | Description |
|---------|-------------|
| `test_full_lifecycle_draft_to_finalized` | Create -> Update -> Finalize |
| `test_lifecycle_finalized_clone_modify` | Finalize -> Clone -> Update clone |
| `test_lifecycle_upgrade_then_finalize` | Create -> Upgrade -> Finalize |
| `test_lifecycle_multi_clone_chain` | Clone of clone of clone |
| `test_lifecycle_concurrent_modifications` | Concurrent access handling |

#### 9.2 Error Recovery Scenarios

| Test ID | Description |
|---------|-------------|
| `test_transaction_rollback_on_clone_failure` | Clone failure doesn't corrupt |
| `test_transaction_rollback_on_upgrade_failure` | Upgrade failure safe |
| `test_orphaned_version_handling` | Config with deleted version |

---

### 10. Performance Tests

**File:** `tests/stress/test_configuration_lifecycle_stress.py`

| Test ID | Description | Threshold |
|---------|-------------|-----------|
| `test_clone_performance` | Clone 100 configs sequentially | < 10s |
| `test_finalize_bulk_performance` | Finalize 100 configs | < 5s |
| `test_list_with_status_filter_performance` | Filter 10k configs by status | < 500ms |
| `test_soft_delete_scan_performance` | List excluding soft-deleted | < 500ms |

---

## Test Fixtures

### Shared Fixtures (`tests/fixtures/configurations_lifecycle.py`)

```python
@pytest.fixture
def draft_configuration(db, user, published_version):
    """Creates a DRAFT configuration owned by user."""
    ...

@pytest.fixture
def finalized_configuration(db, user, published_version):
    """Creates a FINALIZED configuration owned by user."""
    ...

@pytest.fixture
def soft_deleted_configuration(db, admin, published_version):
    """Creates a soft-deleted FINALIZED configuration."""
    ...

@pytest.fixture
def configuration_with_data(db, user, published_version, sample_input_data):
    """Creates a DRAFT configuration with populated data."""
    ...

@pytest.fixture
def multi_version_entity(db, author):
    """Creates entity with DRAFT, PUBLISHED, and ARCHIVED versions."""
    ...
```

---

## Test Data Requirements

### Minimum Test Data Setup

1. **Users:**
   - 1 ADMIN user
   - 1 AUTHOR user
   - 2 USER users (for ownership tests)

2. **Entities & Versions:**
   - 1 Entity with multiple versions:
     - v1: ARCHIVED
     - v2: PUBLISHED (current)
     - v3: DRAFT (optional, for upgrade edge cases)

3. **Configurations:**
   - DRAFT configs (various owners)
   - FINALIZED configs (various owners)
   - Soft-deleted configs

4. **Field Data:**
   - Fields with different types
   - Required and optional fields
   - Fields with validation rules

---

## Execution Strategy

### Test Execution Order

1. **Unit Tests First:** Model and Schema tests
2. **API Tests:** Endpoint behavior tests
3. **RBAC Tests:** Permission matrix verification
4. **Integration Tests:** Full workflow tests
5. **Performance Tests:** Stress testing (optional in CI)

### CI/CD Integration

```yaml
# pytest configuration
pytest:
  markers:
    - lifecycle: Tests for configuration lifecycle
    - rbac: Role-based access control tests
    - slow: Performance/stress tests

  # Run fast tests by default
  default_args: "-m 'not slow'"

  # Full suite for release
  release_args: "-m 'lifecycle or rbac'"
```

---

## Coverage Requirements

| Component | Minimum Coverage |
|-----------|-----------------|
| `models/domain.py` (Configuration) | 95% |
| `schemas/configuration.py` | 100% |
| `routers/configurations.py` | 90% |
| Status guard functions | 100% |
| Lifecycle endpoints | 100% |

---

## Test Implementation Notes

### HTTP Status Code Reference

| Scenario | Expected Status |
|----------|----------------|
| Successful operation | 200 / 201 / 204 |
| Resource not found | 404 |
| Permission denied | 403 |
| Status conflict (FINALIZED) | 409 |
| Invalid input | 400 |
| Server error | 500 |

### Common Assertions

```python
# Status check
assert response.json()["status"] == "DRAFT"

# Conflict check
assert response.status_code == 409
assert "FINALIZED" in response.json()["detail"]
assert "clone" in response.json()["detail"].lower()

# Soft delete check
assert config.is_deleted == True
assert config in db.query(Configuration).filter(Configuration.is_deleted == True).all()
```

---

## Review Checklist

Before marking tests complete:

- [ ] All status transitions covered
- [ ] All RBAC combinations tested
- [ ] Error messages verified
- [ ] Edge cases handled
- [ ] Performance acceptable
- [ ] Database integrity maintained
- [ ] Audit fields correctly set
- [ ] Documentation updated
