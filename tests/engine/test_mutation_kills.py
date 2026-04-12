"""
Tests targeting surviving mutants identified by mutation testing (mutmut).

Each test kills one or more specific mutants in app/services/rule_engine.py.
Organized by method/area. See docs/MUTMUT_REPORT.md for the full analysis.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import (
    BOMItem,
    BOMItemRule,
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
from app.schemas.engine import CalculationRequest, FieldInputState
from app.services.rule_engine import RuleEngineService
from tests.fixtures.price_lists import create_price_list_with_items

# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture(scope="function")
def setup_normalize_scenario(db_session: Session):
    """
    Scenario for testing _normalize_user_input edge cases.

    Fields:
    - str_field (STRING, free value)
    - list_field (STRING, dropdown with values)
    - target (STRING, free value, required)
    """
    entity = Entity(name="Normalize Test", description="Input normalization")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    f_str = Field(
        entity_version_id=version.id,
        name="str_field",
        label="String Field",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=0,
    )
    f_list = Field(
        entity_version_id=version.id,
        name="list_field",
        label="List Field",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=1,
        sequence=1,
    )
    f_target = Field(
        entity_version_id=version.id,
        name="target",
        label="Target",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        step=1,
        sequence=2,
    )
    db_session.add_all([f_str, f_list, f_target])
    db_session.commit()

    # Values for list_field
    v_a = Value(field_id=f_list.id, value="A", label="Option A")
    v_b = Value(field_id=f_list.id, value="B", label="Option B")
    db_session.add_all([v_a, v_b])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "str": f_str.id,
            "list": f_list.id,
            "target": f_target.id,
        },
    }


@pytest.fixture(scope="function")
def setup_auto_select_scenario(db_session: Session):
    """
    Scenario for testing _auto_select_value edge cases.

    Fields:
    - selector (STRING, dropdown, required): multiple values with one default
    """
    entity = Entity(name="AutoSelect Test", description="Auto-selection logic")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    f_single = Field(
        entity_version_id=version.id,
        name="single_option",
        label="Single Option",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=0,
    )
    f_multi = Field(
        entity_version_id=version.id,
        name="multi_option",
        label="Multi Option",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1,
    )
    db_session.add_all([f_single, f_multi])
    db_session.commit()

    # Single value for single_option field
    v_only = Value(field_id=f_single.id, value="ONLY", label="Only Option")
    # Multiple values for multi_option field (one is default)
    v_x = Value(field_id=f_multi.id, value="X", label="X")
    v_y = Value(field_id=f_multi.id, value="Y", label="Y", is_default=True)
    v_z = Value(field_id=f_multi.id, value="Z", label="Z")
    db_session.add_all([v_only, v_x, v_y, v_z])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "fields": {
            "single": f_single.id,
            "multi": f_multi.id,
        },
    }


@pytest.fixture(scope="function")
def setup_comparison_scenario(db_session: Session):
    """
    Scenario for testing _compare_numbers and _compare_dates edge cases.

    Fields:
    - num_field (NUMBER, free value)
    - date_field (DATE, free value)
    - target (STRING, free value): visibility controlled by rules
    """
    entity = Entity(name="Comparison Test", description="Comparison edge cases")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    f_num = Field(
        entity_version_id=version.id,
        name="num_field",
        label="Number",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        step=1,
        sequence=0,
    )
    f_date = Field(
        entity_version_id=version.id,
        name="date_field",
        label="Date",
        data_type=FieldType.DATE.value,
        is_free_value=True,
        step=1,
        sequence=1,
    )
    f_target = Field(
        entity_version_id=version.id,
        name="target",
        label="Target",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        step=1,
        sequence=2,
    )
    db_session.add_all([f_num, f_date, f_target])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "num": f_num.id,
            "date": f_date.id,
            "target": f_target.id,
        },
    }


@pytest.fixture(scope="function")
def setup_completeness_scenario(db_session: Session):
    """
    Scenario for testing _check_completeness with hidden fields.

    Fields:
    - trigger (STRING, free value): controls visibility of required_field
    - required_field (STRING, free value, required): hidden when trigger == "HIDE"
    """
    entity = Entity(name="Completeness Test", description="Completeness checks")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    f_trigger = Field(
        entity_version_id=version.id,
        name="trigger",
        label="Trigger",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        step=1,
        sequence=0,
    )
    f_required = Field(
        entity_version_id=version.id,
        name="required_field",
        label="Required Field",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=True,
        step=2,
        sequence=0,
    )
    db_session.add_all([f_trigger, f_required])
    db_session.commit()

    # Visibility rule: required_field visible only when trigger != "HIDE"
    rule = Rule(
        entity_version_id=version.id,
        target_field_id=f_required.id,
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": f_trigger.id, "operator": "NOT_EQUALS", "value": "HIDE"}]},
    )
    db_session.add(rule)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "fields": {
            "trigger": f_trigger.id,
            "required": f_required.id,
        },
    }


# ============================================================
# _normalize_user_input TESTS
# Kills: mutmut_5 (empty string → None vs "")
#        mutmut_6/7 (empty list normalization)
#        mutmut_8 (empty list → None vs "")
# ============================================================


class TestNormalizeUserInput:
    """Tests for empty string and empty list normalization."""

    def test_empty_string_normalized_to_none(self, db_session, setup_normalize_scenario):
        """Empty string input is treated as None (field shows 'Required field.' error)."""
        data = setup_normalize_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["str"], value="")],
            ),
        )

        str_field = next(f for f in response.fields if f.field_id == data["fields"]["str"])
        # Empty string normalizes to None → required field shows error
        assert str_field.current_value is None
        assert str_field.error_message == "Required field."

    def test_whitespace_only_string_normalized_to_none(self, db_session, setup_normalize_scenario):
        """Whitespace-only string input is treated as None."""
        data = setup_normalize_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["str"], value="   ")],
            ),
        )

        str_field = next(f for f in response.fields if f.field_id == data["fields"]["str"])
        assert str_field.current_value is None


# ============================================================
# _auto_select_value TESTS
# Kills: mutmut_1 (== 1 → != 1), mutmut_2 (== 1 → == 2)
# ============================================================


class TestAutoSelectValue:
    """Tests for auto-selection logic when required field has no user input."""

    def test_single_option_auto_selected(self, db_session, setup_auto_select_scenario):
        """Required field with exactly one available option auto-selects it."""
        data = setup_auto_select_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[],
            ),
        )

        single_field = next(f for f in response.fields if f.field_id == data["fields"]["single"])
        assert single_field.current_value == "ONLY"

    def test_multiple_options_selects_default_not_first(self, db_session, setup_auto_select_scenario):
        """Required field with multiple options selects the default, not first available."""
        data = setup_auto_select_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[],
            ),
        )

        multi_field = next(f for f in response.fields if f.field_id == data["fields"]["multi"])
        # Should pick "Y" (is_default=True), not "X" (first in list)
        assert multi_field.current_value == "Y"


# ============================================================
# _compare_numbers TESTS
# Kills: mutmut_2 (None expected → True instead of False)
#        mutmut_7 (inverted isinstance check for list)
# ============================================================


class TestCompareNumbers:
    """Tests for number comparison edge cases."""

    def test_number_comparison_with_none_expected_returns_false(self, db_session, setup_comparison_scenario):
        """Rule with expected=None in number comparison does not fire."""
        data = setup_comparison_scenario
        service = RuleEngineService()

        # Visibility rule: target visible if num_field EQUALS None
        rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["target"],
            rule_type=RuleType.VISIBILITY.value,
            conditions={"criteria": [{"field_id": data["fields"]["num"], "operator": "EQUALS", "value": None}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["num"], value=42)],
            ),
        )

        target = next(f for f in response.fields if f.field_id == data["fields"]["target"])
        # Rule should NOT fire (None expected returns False), so target is hidden
        assert target.is_hidden is True

    def test_number_in_list_comparison(self, db_session, setup_comparison_scenario):
        """IN operator with a list of numbers works correctly."""
        data = setup_comparison_scenario
        service = RuleEngineService()

        # Visibility rule: target visible if num_field IN [10, 20, 30]
        rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["target"],
            rule_type=RuleType.VISIBILITY.value,
            conditions={"criteria": [{"field_id": data["fields"]["num"], "operator": "IN", "value": [10, 20, 30]}]},
        )
        db_session.add(rule)
        db_session.commit()

        # num_field = 20 → target visible
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["num"], value=20)],
            ),
        )
        target = next(f for f in response.fields if f.field_id == data["fields"]["target"])
        assert target.is_hidden is False

        # num_field = 99 → target hidden
        service_fresh = RuleEngineService()
        response2 = service_fresh.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["num"], value=99)],
            ),
        )
        target2 = next(f for f in response2.fields if f.field_id == data["fields"]["target"])
        assert target2.is_hidden is True


# ============================================================
# _compare_dates TESTS
# Kills: mutmut_2 (None expected → True)
#        mutmut_3,4 (parse_date with None)
#        mutmut_6 (parse_date(None) for actual)
#        mutmut_8 (parse_date(None) for expected)
#        mutmut_13-17 (argument mutations to _apply_operator)
# ============================================================


class TestCompareDates:
    """Tests for date comparison edge cases."""

    def test_date_equals_comparison_with_string_dates(self, db_session, setup_comparison_scenario):
        """Date comparison works with ISO format string dates."""
        data = setup_comparison_scenario
        service = RuleEngineService()

        rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["target"],
            rule_type=RuleType.VISIBILITY.value,
            conditions={
                "criteria": [{"field_id": data["fields"]["date"], "operator": "EQUALS", "value": "2025-06-15"}]
            },
        )
        db_session.add(rule)
        db_session.commit()

        # Matching date → target visible
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["date"], value="2025-06-15")],
            ),
        )
        target = next(f for f in response.fields if f.field_id == data["fields"]["target"])
        assert target.is_hidden is False

        # Non-matching date → target hidden
        service_fresh = RuleEngineService()
        response2 = service_fresh.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["date"], value="2025-07-01")],
            ),
        )
        target2 = next(f for f in response2.fields if f.field_id == data["fields"]["target"])
        assert target2.is_hidden is True

    def test_date_greater_than_comparison(self, db_session, setup_comparison_scenario):
        """GREATER_THAN works correctly for date fields."""
        data = setup_comparison_scenario
        service = RuleEngineService()

        rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["target"],
            rule_type=RuleType.VISIBILITY.value,
            conditions={
                "criteria": [{"field_id": data["fields"]["date"], "operator": "GREATER_THAN", "value": "2025-01-01"}]
            },
        )
        db_session.add(rule)
        db_session.commit()

        # date > "2025-01-01" → target visible
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["date"], value="2025-06-15")],
            ),
        )
        target = next(f for f in response.fields if f.field_id == data["fields"]["target"])
        assert target.is_hidden is False

        # date < "2025-01-01" → target hidden
        service_fresh = RuleEngineService()
        response2 = service_fresh.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["date"], value="2024-12-01")],
            ),
        )
        target2 = next(f for f in response2.fields if f.field_id == data["fields"]["target"])
        assert target2.is_hidden is True

    def test_date_comparison_with_none_expected_returns_false(self, db_session, setup_comparison_scenario):
        """Rule with expected=None in date comparison does not fire."""
        data = setup_comparison_scenario
        service = RuleEngineService()

        rule = Rule(
            entity_version_id=data["version_id"],
            target_field_id=data["fields"]["target"],
            rule_type=RuleType.VISIBILITY.value,
            conditions={"criteria": [{"field_id": data["fields"]["date"], "operator": "EQUALS", "value": None}]},
        )
        db_session.add(rule)
        db_session.commit()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["date"], value="2025-06-15")],
            ),
        )

        target = next(f for f in response.fields if f.field_id == data["fields"]["target"])
        assert target.is_hidden is True


# ============================================================
# _generate_sku TESTS
# Kills: mutmut_9 (continue → break), mutmut_16 (continue → break for free value)
#        mutmut_19/21 (default=[] → None), mutmut_28 (> → >=)
# ============================================================


class TestSKUMutationKills:
    """Tests for SKU generation edge cases found by mutation testing."""

    def test_sku_processes_all_fields_not_just_first(self, db_session):
        """SKU generation iterates through ALL fields (continue, not break)."""
        entity = Entity(name="SKU Multi Field", description="Multiple fields for SKU")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base="BASE",
            sku_delimiter="-",
        )
        db_session.add(version)
        db_session.commit()

        f1 = Field(
            entity_version_id=version.id,
            name="f1",
            label="Field 1",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=0,
        )
        f2 = Field(
            entity_version_id=version.id,
            name="f2",
            label="Field 2",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=1,
        )
        f3 = Field(
            entity_version_id=version.id,
            name="f3",
            label="Field 3",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=2,
        )
        db_session.add_all([f1, f2, f3])
        db_session.commit()

        v1 = Value(field_id=f1.id, value="A", label="A", sku_modifier="A1")
        v2 = Value(field_id=f2.id, value="B", label="B", sku_modifier="B1")
        v3 = Value(field_id=f3.id, value="C", label="C", sku_modifier="C1")
        db_session.add_all([v1, v2, v3])
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[
                    FieldInputState(field_id=f1.id, value="A"),
                    FieldInputState(field_id=f2.id, value="B"),
                    FieldInputState(field_id=f3.id, value="C"),
                ],
            ),
        )

        # All three modifiers should be present
        assert response.generated_sku == "BASE-A1-B1-C1"

    def test_sku_free_value_followed_by_regular_fields(self, db_session):
        """Free-value field with modifier doesn't stop SKU processing of subsequent fields."""
        entity = Entity(name="SKU Free+Regular", description="Free value then regular")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base="BASE",
            sku_delimiter="-",
        )
        db_session.add(version)
        db_session.commit()

        f_free = Field(
            entity_version_id=version.id,
            name="free_field",
            label="Free Field",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            sku_modifier_when_filled="CUSTOM",
            step=1,
            sequence=0,
        )
        f_regular = Field(
            entity_version_id=version.id,
            name="regular_field",
            label="Regular Field",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=1,
        )
        db_session.add_all([f_free, f_regular])
        db_session.commit()

        v_reg = Value(field_id=f_regular.id, value="OPT", label="Option", sku_modifier="OPT")
        db_session.add(v_reg)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[
                    FieldInputState(field_id=f_free.id, value="anything"),
                    FieldInputState(field_id=f_regular.id, value="OPT"),
                ],
            ),
        )

        # Both modifiers: free value modifier + regular value modifier
        assert response.generated_sku == "BASE-CUSTOM-OPT"

    def test_sku_at_exact_max_length_not_truncated(self, db_session):
        """SKU at exactly _MAX_SKU_LENGTH (100) is NOT truncated."""
        entity = Entity(name="SKU Max Length", description="Exact max length")
        db_session.add(entity)
        db_session.commit()

        # sku_base is VARCHAR(50), so use base + modifiers to reach 100 chars
        sku_base = "A" * 50
        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base=sku_base,
            sku_delimiter="-",
        )
        db_session.add(version)
        db_session.commit()

        # Modifier to push total to exactly 100 chars: 50 (base) + 1 (delimiter) + 49 (modifier) = 100
        f1 = Field(
            entity_version_id=version.id,
            name="f1",
            label="F1",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=0,
        )
        db_session.add(f1)
        db_session.commit()

        v1 = Value(field_id=f1.id, value="X", label="X", sku_modifier="B" * 49)
        db_session.add(v1)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[FieldInputState(field_id=f1.id, value="X")],
            ),
        )

        # Exactly 100 chars → no truncation
        expected = sku_base + "-" + "B" * 49
        assert len(expected) == 100
        assert response.generated_sku == expected


# ============================================================
# _resolve_bom_quantity TESTS
# Kills: mutmut_2/3 (field_state lookup), mutmut_5 (is not None → is None)
#        mutmut_13 (<= 0 → <= 1)
# ============================================================


class TestResolveBOMQuantityMutations:
    """Tests for BOM quantity resolution edge cases found by mutation testing."""

    def test_quantity_from_field_value_one_is_included(self, db_session):
        """BOM item with quantity_from_field value of 1 is included (not excluded)."""
        entity = Entity(name="BOM Qty One", description="Quantity = 1")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        f_qty = Field(
            entity_version_id=version.id,
            name="qty",
            label="Quantity",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        db_session.add(f_qty)
        db_session.commit()

        bom = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="QTY-ONE",
            quantity=Decimal("5"),
            quantity_from_field_id=f_qty.id,
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        pl = create_price_list_with_items(db_session, {"QTY-ONE": Decimal("10.00")}, name="Qty One PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                price_list_id=pl.id,
                current_state=[FieldInputState(field_id=f_qty.id, value=1)],
            ),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.quantity == Decimal("1")
        assert item.line_total == Decimal("10.00")

    def test_quantity_from_visible_field_uses_field_value(self, db_session):
        """BOM uses field value when the referenced field is visible (not hidden)."""
        entity = Entity(name="BOM Visible Qty", description="Visible field quantity")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        f_trigger = Field(
            entity_version_id=version.id,
            name="trigger",
            label="Trigger",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        f_qty = Field(
            entity_version_id=version.id,
            name="qty",
            label="Quantity",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            step=2,
            sequence=0,
        )
        db_session.add_all([f_trigger, f_qty])
        db_session.commit()

        # Visibility rule: qty visible when trigger != "HIDE"
        rule = Rule(
            entity_version_id=version.id,
            target_field_id=f_qty.id,
            rule_type=RuleType.VISIBILITY.value,
            conditions={"criteria": [{"field_id": f_trigger.id, "operator": "NOT_EQUALS", "value": "HIDE"}]},
        )
        db_session.add(rule)
        db_session.commit()

        bom = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="VIS-QTY",
            quantity=Decimal("5"),
            quantity_from_field_id=f_qty.id,
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()

        # Field visible + value provided → uses field value
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[
                    FieldInputState(field_id=f_trigger.id, value="SHOW"),
                    FieldInputState(field_id=f_qty.id, value=7),
                ],
            ),
        )

        assert response.bom is not None
        item = next(i for i in response.bom.commercial if i.bom_item_id == bom.id)
        assert item.quantity == Decimal("7")

        # Field hidden → falls back to static quantity
        service2 = RuleEngineService()
        response2 = service2.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[
                    FieldInputState(field_id=f_trigger.id, value="HIDE"),
                    FieldInputState(field_id=f_qty.id, value=7),
                ],
            ),
        )

        assert response2.bom is not None
        item2 = next(i for i in response2.bom.commercial if i.bom_item_id == bom.id)
        assert item2.quantity == Decimal("5")


# ============================================================
# _build_bom_output TESTS
# Kills: mutmut_3/32 (continue → break), mutmut_28 (children=[])
#        mutmut_38 (and → or in parent check)
# ============================================================


class TestBuildBOMOutputMutations:
    """Tests for BOM output construction edge cases."""

    def test_multiple_bom_items_all_present(self, db_session):
        """All included BOM items appear in output (loop continues, doesn't break)."""
        entity = Entity(name="BOM Multi Items", description="Multiple items")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        items = []
        for i in range(5):
            bom = BOMItem(
                entity_version_id=version.id,
                bom_type=BOMType.COMMERCIAL.value,
                part_number=f"ITEM-{i:03d}",
                quantity=Decimal("1"),
                sequence=i,
            )
            items.append(bom)
        db_session.add_all(items)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        assert len(response.bom.commercial) == 5
        part_numbers = {i.part_number for i in response.bom.commercial}
        for i in range(5):
            assert f"ITEM-{i:03d}" in part_numbers

    def test_technical_parent_child_tree_structure(self, db_session):
        """TECHNICAL items with parent_bom_item_id form correct parent-child tree."""
        entity = Entity(name="BOM Tree Structure", description="Parent-child")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        parent = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="PARENT",
            quantity=Decimal("1"),
            sequence=1,
        )
        db_session.add(parent)
        db_session.commit()

        child = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="CHILD",
            parent_bom_item_id=parent.id,
            quantity=Decimal("2"),
            sequence=2,
        )
        db_session.add(child)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        assert len(response.bom.technical) == 1
        parent_item = response.bom.technical[0]
        assert parent_item.part_number == "PARENT"
        assert len(parent_item.children) == 1
        assert parent_item.children[0].part_number == "CHILD"


# ============================================================
# _sum_line_totals TESTS
# Kills: mutmut_4/5 (has_any = None/True), mutmut_11 (no recursion)
#        mutmut_14/15 (+=child → =child / -=child)
#        mutmut_16/17 (has_any after child = None/False)
# ============================================================


class TestSumLineTotalsMutations:
    """Tests for recursive line total summing."""

    def test_commercial_total_sums_all_items(self, db_session):
        """commercial_total correctly sums line_total across all COMMERCIAL items."""
        entity = Entity(name="BOM Sum Test", description="Total summing")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        bom1 = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="SUM-001",
            quantity=Decimal("2"),
            sequence=1,
        )
        bom2 = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="SUM-002",
            quantity=Decimal("3"),
            sequence=2,
        )
        bom3 = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="SUM-003",
            quantity=Decimal("1"),
            sequence=3,
        )
        db_session.add_all([bom1, bom2, bom3])
        db_session.commit()

        pl = create_price_list_with_items(
            db_session,
            {
                "SUM-001": Decimal("10.00"),
                "SUM-002": Decimal("20.00"),
                "SUM-003": Decimal("50.00"),
            },
            name="Sum Totals PL",
        )

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                price_list_id=pl.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        # 2*10 + 3*20 + 1*50 = 20 + 60 + 50 = 130
        assert response.bom.commercial_total == Decimal("130.00")

    def test_no_pricing_items_returns_none_total(self, db_session):
        """commercial_total is None when no items have pricing."""
        entity = Entity(name="BOM No Price", description="No pricing")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        bom = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="NO-PRICE",
            quantity=Decimal("1"),
            sequence=1,
        )
        db_session.add(bom)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        # Only TECHNICAL items with no pricing → commercial_total is None
        assert response.bom.commercial_total is None


# ============================================================
# _check_completeness TESTS
# Kills: mutmut_3 (not field.is_hidden → field.is_hidden)
# ============================================================


class TestCheckCompletenessMutations:
    """Tests for completeness check with hidden required fields."""

    def test_hidden_required_field_does_not_block_completeness(self, db_session, setup_completeness_scenario):
        """Hidden required field (no value) does NOT make is_complete=False."""
        data = setup_completeness_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["trigger"], value="HIDE")],
            ),
        )

        # required_field is hidden → should NOT block completeness
        assert response.is_complete is True

    def test_visible_required_field_without_value_blocks_completeness(self, db_session, setup_completeness_scenario):
        """Visible required field without value makes is_complete=False."""
        data = setup_completeness_scenario
        service = RuleEngineService()

        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=data["entity_id"],
                current_state=[FieldInputState(field_id=data["fields"]["trigger"], value="SHOW")],
            ),
        )

        # required_field is visible but no value → blocks completeness
        assert response.is_complete is False


# ============================================================
# _prune_bom_tree TESTS
# Kills: mutmut_12 (changed = True → changed = False)
# ============================================================


class TestPruneBOMTreeMutations:
    """Tests for multi-level tree pruning."""

    def test_deep_pruning_three_levels(self, db_session):
        """Excluding root prunes grandchildren (multi-pass pruning required)."""
        entity = Entity(name="BOM Deep Prune", description="Three-level prune")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add(version)
        db_session.commit()

        f_toggle = Field(
            entity_version_id=version.id,
            name="toggle",
            label="Toggle",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        db_session.add(f_toggle)
        db_session.commit()

        # Level 0: Root (conditional)
        root = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="ROOT",
            quantity=Decimal("1"),
            sequence=1,
        )
        db_session.add(root)
        db_session.commit()

        # Level 1: Child
        child = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="CHILD",
            parent_bom_item_id=root.id,
            quantity=Decimal("1"),
            sequence=2,
        )
        db_session.add(child)
        db_session.commit()

        # Level 2: Grandchild
        grandchild = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="GRANDCHILD",
            parent_bom_item_id=child.id,
            quantity=Decimal("1"),
            sequence=3,
        )
        db_session.add(grandchild)
        db_session.commit()

        # Another root (unconditional) to verify it remains
        other_root = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="OTHER",
            quantity=Decimal("1"),
            sequence=4,
        )
        db_session.add(other_root)
        db_session.commit()

        # Rule: ROOT included only if toggle == ON
        rule = BOMItemRule(
            bom_item_id=root.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_toggle.id, "operator": "EQUALS", "value": "ON"}]},
        )
        db_session.add(rule)
        db_session.commit()

        service = RuleEngineService()

        # toggle = OFF → root excluded → child and grandchild also excluded
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity.id,
                current_state=[FieldInputState(field_id=f_toggle.id, value="OFF")],
            ),
        )

        assert response.bom is not None

        def collect_ids(items):
            ids = set()
            for item in items:
                ids.add(item.bom_item_id)
                ids.update(collect_ids(item.children))
            return ids

        all_ids = collect_ids(response.bom.technical)
        assert root.id not in all_ids
        assert child.id not in all_ids
        assert grandchild.id not in all_ids
        # Other root still present
        assert other_root.id in all_ids


# ============================================================
# _resolve_target_version TESTS
# Kills: mutmut_24 (missing entity_id filter)
#        mutmut_16/19 (ValueError message content)
# ============================================================


class TestResolveTargetVersionMutations:
    """Tests for version resolution edge cases."""

    def test_published_version_resolves_correct_entity(self, db_session):
        """Production mode resolves PUBLISHED version for the correct entity (not any entity)."""
        entity_a = Entity(name="Entity A", description="A")
        entity_b = Entity(name="Entity B", description="B")
        db_session.add_all([entity_a, entity_b])
        db_session.commit()

        # Entity A has PUBLISHED version
        ver_a = EntityVersion(
            entity_id=entity_a.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        # Entity B has PUBLISHED version with different fields
        ver_b = EntityVersion(
            entity_id=entity_b.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
        )
        db_session.add_all([ver_a, ver_b])
        db_session.commit()

        # Entity A has a field
        f_a = Field(
            entity_version_id=ver_a.id,
            name="field_a",
            label="Field A",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        # Entity B has a different field
        f_b = Field(
            entity_version_id=ver_b.id,
            name="field_b",
            label="Field B",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=0,
        )
        db_session.add_all([f_a, f_b])
        db_session.commit()

        service = RuleEngineService()

        # Calculate for Entity A → should get field_a, not field_b
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=entity_a.id,
                current_state=[],
            ),
        )

        field_names = {f.field_name for f in response.fields}
        assert "field_a" in field_names
        assert "field_b" not in field_names

    def test_version_not_found_error_message_contains_id(self, db_session):
        """ValueError message contains the version ID when version not found."""
        entity = Entity(name="Error Test", description="Error messages")
        db_session.add(entity)
        db_session.commit()

        service = RuleEngineService()

        with pytest.raises(ValueError, match="99999"):
            service.calculate_state(
                db_session,
                CalculationRequest(
                    entity_id=entity.id,
                    entity_version_id=99999,
                    current_state=[],
                ),
            )

    def test_version_wrong_entity_error_message(self, db_session):
        """ValueError message contains details when version belongs to different entity."""
        entity_a = Entity(name="Entity A", description="A")
        entity_b = Entity(name="Entity B", description="B")
        db_session.add_all([entity_a, entity_b])
        db_session.commit()

        ver_b = EntityVersion(
            entity_id=entity_b.id,
            version_number=1,
            status=VersionStatus.DRAFT,
        )
        db_session.add(ver_b)
        db_session.commit()

        service = RuleEngineService()

        with pytest.raises(ValueError, match=str(ver_b.id)):
            service.calculate_state(
                db_session,
                CalculationRequest(
                    entity_id=entity_a.id,
                    entity_version_id=ver_b.id,
                    current_state=[],
                ),
            )
