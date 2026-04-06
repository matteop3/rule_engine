"""
Entity, Version, Field, Value, and Rule fixtures for tests.
Provides common building blocks for domain model tests.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.domain import (
    BOMItem,
    BOMType,
    Entity,
    EntityVersion,
    Field,
    FieldType,
    Rule,
    RuleType,
    Value,
    VersionStatus,
)

# ============================================================
# ENTITY FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def test_entity(db_session, admin_user):
    """Creates a basic Entity for version tests."""
    entity = Entity(
        name="Test Entity", description="Entity for testing", created_by_id=admin_user.id, updated_by_id=admin_user.id
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture(scope="function")
def second_entity(db_session, admin_user):
    """Creates a second Entity for multi-entity tests."""
    entity = Entity(
        name="Second Entity",
        description="Another entity for testing",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id,
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


# ============================================================
# VERSION FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def draft_version(db_session, test_entity, admin_user):
    """Creates a DRAFT version for the test entity."""
    version = EntityVersion(
        entity_id=test_entity.id,
        version_number=1,
        status=VersionStatus.DRAFT,
        changelog="Initial draft",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id,
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


@pytest.fixture(scope="function")
def published_version(db_session, test_entity, admin_user):
    """Creates a PUBLISHED version for the test entity."""
    version = EntityVersion(
        entity_id=test_entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        changelog="Published version",
        published_at=datetime.now(UTC),
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id,
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


@pytest.fixture(scope="function")
def archived_version(db_session, test_entity, admin_user):
    """Creates an ARCHIVED version for the test entity."""
    version = EntityVersion(
        entity_id=test_entity.id,
        version_number=1,
        status=VersionStatus.ARCHIVED,
        changelog="Archived version",
        published_at=datetime.now(UTC),
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id,
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


@pytest.fixture(scope="function")
def version_with_data(db_session, test_entity, admin_user):
    """
    Creates a PUBLISHED version with Fields, Values, and Rules.
    Used for testing deep clone functionality.
    """
    version = EntityVersion(
        entity_id=test_entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        changelog="Version with data for clone tests",
        published_at=datetime.now(UTC),
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id,
    )
    db_session.add(version)
    db_session.flush()

    # Create Fields
    field_type = Field(
        entity_version_id=version.id,
        name="vehicle_type",
        label="Vehicle Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        sequence=1,
    )
    field_value = Field(
        entity_version_id=version.id,
        name="vehicle_value",
        label="Vehicle Value",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        sequence=2,
    )
    field_optional = Field(
        entity_version_id=version.id,
        name="has_alarm",
        label="Has Alarm",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        sequence=3,
    )
    db_session.add_all([field_type, field_value, field_optional])
    db_session.flush()

    # Create Values for field_type
    value_car = Value(field_id=field_type.id, value="CAR", label="Car", is_default=True)
    value_moto = Value(field_id=field_type.id, value="MOTO", label="Motorcycle", is_default=False)
    value_truck = Value(field_id=field_type.id, value="TRUCK", label="Truck", is_default=False)
    db_session.add_all([value_car, value_moto, value_truck])
    db_session.flush()

    # Create Rules
    rule_mandatory = Rule(
        entity_version_id=version.id,
        target_field_id=field_optional.id,
        rule_type=RuleType.MANDATORY.value,
        description="Alarm mandatory if value > 50000",
        conditions={"criteria": [{"field_id": field_value.id, "operator": "GREATER_THAN", "value": 50000}]},
    )
    rule_visibility = Rule(
        entity_version_id=version.id,
        target_field_id=field_optional.id,
        rule_type=RuleType.VISIBILITY.value,
        description="Hide alarm for motorcycles",
        conditions={"criteria": [{"field_id": field_type.id, "operator": "NOT_EQUALS", "value": "MOTO"}]},
    )
    db_session.add_all([rule_mandatory, rule_visibility])
    db_session.commit()

    db_session.refresh(version)

    return {
        "version": version,
        "fields": {"type": field_type, "value": field_value, "optional": field_optional},
        "values": {"car": value_car, "moto": value_moto, "truck": value_truck},
        "rules": {"mandatory": rule_mandatory, "visibility": rule_visibility},
    }


# ============================================================
# FIELD FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def draft_field(db_session, draft_version):
    """Creates a basic field in a DRAFT version."""
    field = Field(
        entity_version_id=draft_version.id,
        name="test_field",
        label="Test Field",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1,
    )
    db_session.add(field)
    db_session.commit()
    db_session.refresh(field)
    return field


@pytest.fixture(scope="function")
def free_field(db_session, draft_version):
    """Creates a free-value field in a DRAFT version."""
    field = Field(
        entity_version_id=draft_version.id,
        name="free_text_field",
        label="Free Text Field",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=False,
        default_value="default",
        step=1,
        sequence=2,
    )
    db_session.add(field)
    db_session.commit()
    db_session.refresh(field)
    return field


@pytest.fixture(scope="function")
def field_with_values(db_session, draft_version):
    """Creates a non-free field with associated values."""
    field = Field(
        entity_version_id=draft_version.id,
        name="field_with_options",
        label="Field With Options",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1,
    )
    db_session.add(field)
    db_session.flush()

    values = [
        Value(field_id=field.id, value="OPTION_A", label="Option A", is_default=True),
        Value(field_id=field.id, value="OPTION_B", label="Option B", is_default=False),
        Value(field_id=field.id, value="OPTION_C", label="Option C", is_default=False),
    ]
    db_session.add_all(values)
    db_session.commit()
    db_session.refresh(field)

    return {"field": field, "values": values}


@pytest.fixture(scope="function")
def field_as_rule_target(db_session, draft_version):
    """Creates a field that is the target of a rule."""
    target_field = Field(
        entity_version_id=draft_version.id,
        name="target_field",
        label="Target Field",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=1,
    )
    condition_field = Field(
        entity_version_id=draft_version.id,
        name="condition_field",
        label="Condition Field",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2,
    )
    db_session.add_all([target_field, condition_field])
    db_session.flush()

    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.MANDATORY.value,
        description="Target field mandatory if condition > 100",
        conditions={"criteria": [{"field_id": condition_field.id, "operator": "GREATER_THAN", "value": 100}]},
    )
    db_session.add(rule)
    db_session.commit()

    return {"target_field": target_field, "condition_field": condition_field, "rule": rule}


@pytest.fixture(scope="function")
def published_field(db_session, published_version):
    """Creates a field in a PUBLISHED version (immutable)."""
    field = Field(
        entity_version_id=published_version.id,
        name="published_field",
        label="Published Field",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1,
    )
    db_session.add(field)
    db_session.commit()
    db_session.refresh(field)
    return field


@pytest.fixture(scope="function")
def archived_field(db_session, archived_version):
    """Creates a field in an ARCHIVED version (immutable)."""
    field = Field(
        entity_version_id=archived_version.id,
        name="archived_field",
        label="Archived Field",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1,
    )
    db_session.add(field)
    db_session.commit()
    db_session.refresh(field)
    return field


# ============================================================
# VALUE FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def draft_value(db_session, draft_field):
    """Creates a value attached to a field in DRAFT version."""
    value = Value(field_id=draft_field.id, value="TEST_VALUE", label="Test Value", is_default=False)
    db_session.add(value)
    db_session.commit()
    db_session.refresh(value)
    return value


@pytest.fixture(scope="function")
def value_in_rule_target(db_session, draft_version):
    """Creates a value that is the explicit target of a rule."""
    field = Field(
        entity_version_id=draft_version.id,
        name="field_for_value_rule",
        label="Field For Value Rule",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1,
    )
    db_session.add(field)
    db_session.flush()

    value = Value(field_id=field.id, value="TARGETED", label="Targeted Value", is_default=False)
    other_value = Value(field_id=field.id, value="OTHER", label="Other Value", is_default=True)
    db_session.add_all([value, other_value])
    db_session.flush()

    # Condition field
    cond_field = Field(
        entity_version_id=draft_version.id,
        name="condition_for_value",
        label="Condition For Value",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=2,
    )
    db_session.add(cond_field)
    db_session.flush()

    cond_value = Value(field_id=cond_field.id, value="TRIGGER", label="Trigger", is_default=True)
    db_session.add(cond_value)
    db_session.flush()

    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=field.id,
        target_value_id=value.id,
        rule_type=RuleType.AVAILABILITY.value,
        description="Value available only if trigger",
        conditions={
            "criteria": [
                {"field_id": cond_field.id, "value_id": cond_value.id, "operator": "EQUALS", "value": "TRIGGER"}
            ]
        },
    )
    db_session.add(rule)
    db_session.commit()

    return {
        "field": field,
        "value": value,
        "other_value": other_value,
        "condition_field": cond_field,
        "condition_value": cond_value,
        "rule": rule,
    }


@pytest.fixture(scope="function")
def value_in_rule_condition(db_session, draft_version):
    """Creates a value that is used in a rule's condition criteria."""
    # Field with value used as condition
    condition_field = Field(
        entity_version_id=draft_version.id,
        name="condition_source_field",
        label="Condition Source",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1,
    )
    db_session.add(condition_field)
    db_session.flush()

    condition_value = Value(
        field_id=condition_field.id, value="CONDITION_VAL", label="Condition Value", is_default=True
    )
    db_session.add(condition_value)
    db_session.flush()

    # Target field
    target_field = Field(
        entity_version_id=draft_version.id,
        name="affected_field",
        label="Affected Field",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=2,
    )
    db_session.add(target_field)
    db_session.flush()

    # Rule that uses condition_value in its criteria
    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.VISIBILITY.value,
        description="Show if condition value selected",
        conditions={
            "criteria": [
                {
                    "field_id": condition_field.id,
                    "value_id": condition_value.id,
                    "operator": "EQUALS",
                    "value": "CONDITION_VAL",
                }
            ]
        },
    )
    db_session.add(rule)
    db_session.commit()

    return {
        "condition_field": condition_field,
        "condition_value": condition_value,
        "target_field": target_field,
        "rule": rule,
    }


# ============================================================
# RULE FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def draft_rule(db_session, draft_version):
    """Creates a basic rule in a DRAFT version."""
    target_field = Field(
        entity_version_id=draft_version.id,
        name="rule_target",
        label="Rule Target",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=1,
    )
    source_field = Field(
        entity_version_id=draft_version.id,
        name="rule_source",
        label="Rule Source",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2,
    )
    db_session.add_all([target_field, source_field])
    db_session.flush()

    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.MANDATORY.value,
        description="Basic test rule",
        conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    return {"rule": rule, "target_field": target_field, "source_field": source_field}


@pytest.fixture(scope="function")
def published_rule(db_session, published_version):
    """Creates a rule in a PUBLISHED version (immutable)."""
    target_field = Field(
        entity_version_id=published_version.id,
        name="pub_rule_target",
        label="Published Rule Target",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=1,
    )
    source_field = Field(
        entity_version_id=published_version.id,
        name="pub_rule_source",
        label="Published Rule Source",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2,
    )
    db_session.add_all([target_field, source_field])
    db_session.flush()

    rule = Rule(
        entity_version_id=published_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.VISIBILITY.value,
        description="Published rule",
        conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    return {"rule": rule, "target_field": target_field, "source_field": source_field}


@pytest.fixture(scope="function")
def rule_with_value_target(db_session, draft_version):
    """Creates a rule that targets a specific value (AVAILABILITY rule)."""
    field = Field(
        entity_version_id=draft_version.id,
        name="availability_field",
        label="Availability Field",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1,
    )
    source_field = Field(
        entity_version_id=draft_version.id,
        name="availability_source",
        label="Availability Source",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2,
    )
    db_session.add_all([field, source_field])
    db_session.flush()

    value1 = Value(field_id=field.id, value="VAL1", label="Value 1", is_default=True)
    value2 = Value(field_id=field.id, value="VAL2", label="Value 2", is_default=False)
    db_session.add_all([value1, value2])
    db_session.flush()

    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=field.id,
        target_value_id=value2.id,
        rule_type=RuleType.AVAILABILITY.value,
        description="Value 2 availability rule",
        conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
    )
    db_session.add(rule)
    db_session.commit()

    return {"field": field, "source_field": source_field, "value1": value1, "value2": value2, "rule": rule}


@pytest.fixture(scope="function")
def archived_rule(db_session, archived_version):
    """Creates a rule in an ARCHIVED version (immutable)."""
    target_field = Field(
        entity_version_id=archived_version.id,
        name="arch_rule_target",
        label="Archived Rule Target",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=1,
    )
    source_field = Field(
        entity_version_id=archived_version.id,
        name="arch_rule_source",
        label="Archived Rule Source",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2,
    )
    db_session.add_all([target_field, source_field])
    db_session.flush()

    rule = Rule(
        entity_version_id=archived_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.VISIBILITY.value,
        description="Archived rule",
        conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    return {"rule": rule, "target_field": target_field, "source_field": source_field}


# ============================================================
# BOM ITEM FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def draft_bom_item(db_session, draft_version):
    """Creates a TECHNICAL BOM item in a DRAFT version."""
    item = BOMItem(
        entity_version_id=draft_version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="TEST-BOM-001",
        description="Test BOM item",
        quantity=Decimal("1"),
        sequence=0,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item
