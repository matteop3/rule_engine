"""
Engine tests for ConfigurationCustomItem integration.

The CUSTOM step runs after BOM/PRICING and appends configuration-scoped
lines to the commercial output with ``is_custom=True``. Custom items
contribute to ``commercial_total`` but never produce warnings and never
affect ``is_complete``.
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import (
    BOMItem,
    BOMType,
    Configuration,
    ConfigurationCustomItem,
    ConfigurationStatus,
    Entity,
    EntityVersion,
    User,
    UserRole,
    VersionStatus,
)
from app.schemas.engine import CalculationRequest
from app.services.rule_engine import RuleEngineService
from tests.fixtures.catalog_items import ensure_catalog_entry
from tests.fixtures.price_lists import create_price_list_with_items


@pytest.fixture(scope="function")
def custom_items_scenario(db_session: Session):
    """
    Entity + PUBLISHED version with one TECHNICAL and two COMMERCIAL BOM
    items, and a persisted Configuration with three custom items attached.
    """
    ensure_catalog_entry(db_session, "TECH-X", description="Tech Item X", category="T", unit_of_measure="EA")
    ensure_catalog_entry(db_session, "COMM-A", description="Commercial A", category="C", unit_of_measure="PC")
    ensure_catalog_entry(db_session, "COMM-B", description="Commercial B", category="C", unit_of_measure="PC")

    owner = User(email="custom_owner@example.com", hashed_password="x", role=UserRole.ADMIN, is_active=True)
    db_session.add(owner)
    db_session.flush()

    entity = Entity(name="Custom Items Product", description="engine tests")
    db_session.add(entity)
    db_session.flush()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.flush()

    db_session.add_all(
        [
            BOMItem(
                entity_version_id=version.id,
                bom_type=BOMType.TECHNICAL.value,
                part_number="TECH-X",
                quantity=Decimal("1"),
                sequence=1,
            ),
            BOMItem(
                entity_version_id=version.id,
                bom_type=BOMType.COMMERCIAL.value,
                part_number="COMM-A",
                quantity=Decimal("2"),
                sequence=2,
            ),
            BOMItem(
                entity_version_id=version.id,
                bom_type=BOMType.COMMERCIAL.value,
                part_number="COMM-B",
                quantity=Decimal("3"),
                sequence=3,
            ),
        ]
    )

    price_list = create_price_list_with_items(
        db_session,
        {"COMM-A": Decimal("10.00"), "COMM-B": Decimal("5.00")},
        name="Custom Items PL",
    )

    configuration = Configuration(
        entity_version_id=version.id,
        user_id=owner.id,
        name="Custom Items Config",
        status=ConfigurationStatus.DRAFT,
        is_complete=True,
        price_list_id=price_list.id,
        data=[],
        created_by_id=owner.id,
    )
    db_session.add(configuration)
    db_session.flush()

    db_session.add_all(
        [
            ConfigurationCustomItem(
                configuration_id=configuration.id,
                custom_key="CUSTOM-aaaaaaaa",
                description="Special bracket",
                quantity=Decimal("2"),
                unit_price=Decimal("12.50"),
                unit_of_measure="PC",
                sequence=5,
                created_by_id=owner.id,
            ),
            ConfigurationCustomItem(
                configuration_id=configuration.id,
                custom_key="CUSTOM-bbbbbbbb",
                description="Onsite calibration",
                quantity=Decimal("1"),
                unit_price=Decimal("300.00"),
                unit_of_measure=None,
                sequence=0,
                created_by_id=owner.id,
            ),
            ConfigurationCustomItem(
                configuration_id=configuration.id,
                custom_key="CUSTOM-cccccccc",
                description="Free gift line",
                quantity=Decimal("1"),
                unit_price=Decimal("0"),
                unit_of_measure=None,
                sequence=10,
                created_by_id=owner.id,
            ),
        ]
    )
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "price_list_id": price_list.id,
        "configuration_id": configuration.id,
    }


def _calculate_for_configuration(db: Session, scenario: dict):
    service = RuleEngineService()
    request = CalculationRequest(
        entity_id=scenario["entity_id"],
        entity_version_id=scenario["version_id"],
        current_state=[],
        price_list_id=scenario["price_list_id"],
        configuration_id=scenario["configuration_id"],
    )
    return service.calculate_state(db, request)


def _calculate_stateless(db: Session, scenario: dict):
    service = RuleEngineService()
    request = CalculationRequest(
        entity_id=scenario["entity_id"],
        entity_version_id=scenario["version_id"],
        current_state=[],
        price_list_id=scenario["price_list_id"],
    )
    return service.calculate_state(db, request)


class TestCustomItemsAppearInOutput:
    """Custom items show up in the commercial list after catalog lines."""

    def test_custom_items_appended_after_catalog_lines(self, db_session, custom_items_scenario):
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        commercial = response.bom.commercial
        assert [line.part_number for line in commercial] == [
            "COMM-A",
            "COMM-B",
            "CUSTOM-bbbbbbbb",
            "CUSTOM-aaaaaaaa",
            "CUSTOM-cccccccc",
        ]

    def test_custom_lines_carry_is_custom_flag(self, db_session, custom_items_scenario):
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        by_part = {line.part_number: line for line in response.bom.commercial}
        assert by_part["COMM-A"].is_custom is False
        assert by_part["COMM-B"].is_custom is False
        for key in ("CUSTOM-aaaaaaaa", "CUSTOM-bbbbbbbb", "CUSTOM-cccccccc"):
            assert by_part[key].is_custom is True

    def test_custom_lines_have_no_bom_item_id(self, db_session, custom_items_scenario):
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        for line in response.bom.commercial:
            if line.is_custom:
                assert line.bom_item_id is None
            else:
                assert line.bom_item_id is not None

    def test_custom_lines_carry_row_metadata(self, db_session, custom_items_scenario):
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        by_part = {line.part_number: line for line in response.bom.commercial}
        bracket = by_part["CUSTOM-aaaaaaaa"]
        assert bracket.description == "Special bracket"
        assert bracket.unit_of_measure == "PC"
        assert bracket.category is None
        assert bracket.quantity == Decimal("2")
        assert bracket.unit_price == Decimal("12.50")
        assert bracket.line_total == Decimal("25.00")

        calibration = by_part["CUSTOM-bbbbbbbb"]
        assert calibration.description == "Onsite calibration"
        assert calibration.unit_of_measure is None
        assert calibration.quantity == Decimal("1")
        assert calibration.unit_price == Decimal("300.00")
        assert calibration.line_total == Decimal("300.00")

    def test_custom_lines_are_commercial_only(self, db_session, custom_items_scenario):
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        for line in response.bom.technical:
            assert line.is_custom is False
            assert not line.part_number.startswith("CUSTOM-")


class TestCommercialTotalIncludesCustom:
    """``commercial_total`` sums catalog lines and custom lines."""

    def test_total_sums_catalog_and_custom(self, db_session, custom_items_scenario):
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        # Catalog: COMM-A (2 × 10.00) + COMM-B (3 × 5.00) = 20 + 15 = 35
        # Custom:  bracket (2 × 12.50) + calibration (1 × 300) + gift (1 × 0) = 25 + 300 + 0 = 325
        # Total:   360
        assert response.bom is not None
        assert response.bom.commercial_total == Decimal("360.00")

    def test_total_is_custom_only_when_no_catalog_prices(self, db_session, custom_items_scenario):
        """Drop the price list coverage: catalog lines contribute None, custom lines still add to the total."""
        # Remove the price list so no catalog prices resolve
        scenario = custom_items_scenario
        service = RuleEngineService()
        request = CalculationRequest(
            entity_id=scenario["entity_id"],
            entity_version_id=scenario["version_id"],
            current_state=[],
            configuration_id=scenario["configuration_id"],
        )
        response = service.calculate_state(db_session, request)

        assert response.bom is not None
        # No price_list_id → no pricing pass → no catalog contributions to the total.
        # Custom lines still contribute 25 + 300 + 0 = 325.
        assert response.bom.commercial_total == Decimal("325.00")


class TestCustomItemsDoNotProduceWarnings:
    """Custom items are always complete by construction."""

    def test_custom_items_do_not_emit_warnings(self, db_session, custom_items_scenario):
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        for warning in response.bom.warnings:
            assert "CUSTOM-" not in warning

    def test_no_warnings_added_when_catalog_prices_missing(self, db_session, custom_items_scenario):
        """
        Catalog item without a price generates a warning; custom items
        sitting next to it must not add extra warnings of their own.
        """
        from app.models.domain import PriceListItem

        # Delete COMM-B from the price list so it becomes unpriced
        db_session.query(PriceListItem).filter(PriceListItem.part_number == "COMM-B").delete()
        db_session.commit()

        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        warnings_about_customs = [w for w in response.bom.warnings if "CUSTOM-" in w]
        assert warnings_about_customs == []
        # Exactly one warning — the one about COMM-B — regardless of custom items present
        assert len(response.bom.warnings) == 1
        assert "COMM-B" in response.bom.warnings[0]


class TestCustomItemsDoNotAffectCompleteness:
    """``is_complete`` ignores custom items entirely."""

    def test_is_complete_unchanged_when_custom_items_added(self, db_session, custom_items_scenario):
        """Remove all custom items → is_complete stays the same as with them."""
        with_customs = _calculate_for_configuration(db_session, custom_items_scenario)

        db_session.query(ConfigurationCustomItem).filter(
            ConfigurationCustomItem.configuration_id == custom_items_scenario["configuration_id"]
        ).delete()
        db_session.commit()

        without_customs = _calculate_for_configuration(db_session, custom_items_scenario)

        assert with_customs.is_complete == without_customs.is_complete


class TestZeroPricedCustomItem:
    """A zero-priced custom item is included and produces line_total = 0."""

    def test_zero_priced_line_is_present_with_zero_total(self, db_session, custom_items_scenario):
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        by_part = {line.part_number: line for line in response.bom.commercial}
        gift = by_part["CUSTOM-cccccccc"]
        assert gift.unit_price == Decimal("0")
        assert gift.line_total == Decimal("0")
        assert gift.is_custom is True


class TestStatelessEngineSkipsCustomItems:
    """The stateless endpoint never emits custom lines (no configuration_id)."""

    def test_stateless_calculate_has_no_custom_lines(self, db_session, custom_items_scenario):
        response = _calculate_stateless(db_session, custom_items_scenario)

        assert response.bom is not None
        for line in response.bom.commercial:
            assert line.is_custom is False
            assert not line.part_number.startswith("CUSTOM-")


class TestCustomItemsMutationKill:
    """
    Mutation kill: swapping the sign or ignoring unit_price/quantity on
    custom lines must be detectable, and the commercial_total must always
    include them when present.
    """

    def test_commercial_total_strictly_exceeds_catalog_only(self, db_session, custom_items_scenario):
        """A mutation that skips adding custom totals would leave the sum at 35, not 360."""
        with_customs = _calculate_for_configuration(db_session, custom_items_scenario)
        stateless = _calculate_stateless(db_session, custom_items_scenario)

        assert with_customs.bom is not None
        assert stateless.bom is not None
        assert with_customs.bom.commercial_total is not None
        assert stateless.bom.commercial_total is not None
        assert with_customs.bom.commercial_total > stateless.bom.commercial_total
        assert with_customs.bom.commercial_total - stateless.bom.commercial_total == Decimal("325.00")

    def test_line_total_equals_quantity_times_unit_price(self, db_session, custom_items_scenario):
        """A mutation that swapped quantity and unit_price would break this product identity."""
        response = _calculate_for_configuration(db_session, custom_items_scenario)

        assert response.bom is not None
        for line in response.bom.commercial:
            if line.is_custom:
                assert line.unit_price is not None
                assert line.line_total == line.quantity * line.unit_price
