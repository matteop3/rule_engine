"""
Engine-level tests for price resolution from price lists.

Covers COMMERCIAL pricing, TECHNICAL items (no pricing), missing parts,
temporal validity, warnings, partial totals, and error cases.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import (
    BOMItem,
    BOMType,
    Entity,
    EntityVersion,
    PriceList,
    PriceListItem,
    VersionStatus,
)
from app.schemas.engine import CalculationRequest
from app.services.rule_engine import RuleEngineService
from tests.fixtures.price_lists import create_price_list_with_items


@pytest.fixture(scope="function")
def bom_entity(db_session: Session):
    """Published entity with TECHNICAL + COMMERCIAL BOM items."""
    entity = Entity(name="Price Resolution Entity", description="engine tests")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.commit()

    tech_item = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="TECH-001",
        quantity=Decimal("1"),
        sequence=1,
    )
    comm_a = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="COMM-A",
        quantity=Decimal("2"),
        sequence=2,
    )
    comm_b = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="COMM-B",
        quantity=Decimal("3"),
        sequence=3,
    )
    db_session.add_all([tech_item, comm_a, comm_b])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "tech_id": tech_item.id,
        "comm_a_id": comm_a.id,
        "comm_b_id": comm_b.id,
    }


class TestBasicPriceResolution:
    """Prices resolved from the price list for COMMERCIAL items."""

    def test_prices_resolved_correctly(self, db_session, bom_entity):
        pl = create_price_list_with_items(
            db_session,
            {"COMM-A": Decimal("10.00"), "COMM-B": Decimal("5.00")},
            name="Basic PL",
        )

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                price_list_id=pl.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        by_part = {i.part_number: i for i in response.bom.commercial}
        assert by_part["COMM-A"].unit_price == Decimal("10.00")
        assert by_part["COMM-A"].line_total == Decimal("20.00")
        assert by_part["COMM-B"].unit_price == Decimal("5.00")
        assert by_part["COMM-B"].line_total == Decimal("15.00")
        assert response.bom.commercial_total == Decimal("35.00")
        assert response.bom.warnings == []

    def test_technical_items_have_no_pricing(self, db_session, bom_entity):
        pl = create_price_list_with_items(db_session, {"COMM-A": Decimal("10.00"), "COMM-B": Decimal("5.00")})

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                price_list_id=pl.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        tech = response.bom.technical[0]
        assert tech.unit_price is None
        assert tech.line_total is None
        assert response.bom.warnings == []


class TestMissingPrices:
    """Graceful handling: missing prices produce warnings, line_total=null."""

    def test_part_missing_from_price_list(self, db_session, bom_entity):
        pl = create_price_list_with_items(db_session, {"COMM-A": Decimal("10.00")}, name="Partial PL")

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                price_list_id=pl.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        by_part = {i.part_number: i for i in response.bom.commercial}
        assert by_part["COMM-A"].line_total == Decimal("20.00")
        assert by_part["COMM-B"].unit_price is None
        assert by_part["COMM-B"].line_total is None
        assert response.bom.commercial_total == Decimal("20.00")
        assert any("COMM-B" in w and "not found" in w for w in response.bom.warnings)

    def test_expired_price_generates_warning(self, db_session, bom_entity):
        """Part exists but its validity does not cover price_date."""
        pl = PriceList(
            name="Expired PL",
            valid_from=dt.date(2024, 1, 1),
            valid_to=dt.date(2030, 12, 31),
        )
        db_session.add(pl)
        db_session.flush()
        db_session.add(
            PriceListItem(
                price_list_id=pl.id,
                part_number="COMM-A",
                unit_price=Decimal("10.00"),
                valid_from=dt.date(2024, 1, 1),
                valid_to=dt.date(2024, 12, 31),
            )
        )
        db_session.add(
            PriceListItem(
                price_list_id=pl.id,
                part_number="COMM-B",
                unit_price=Decimal("5.00"),
                valid_from=dt.date(2025, 1, 1),
                valid_to=dt.date(2030, 12, 31),
            )
        )
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                price_list_id=pl.id,
                price_date=dt.date(2026, 6, 1),
                current_state=[],
            ),
        )

        assert response.bom is not None
        by_part = {i.part_number: i for i in response.bom.commercial}
        assert by_part["COMM-A"].line_total is None
        assert by_part["COMM-B"].line_total == Decimal("15.00")
        assert any("COMM-A" in w and "no valid price" in w for w in response.bom.warnings)

    def test_all_prices_missing(self, db_session, bom_entity):
        """Empty price list → line_totals null, commercial_total None, warnings for every part."""
        pl = PriceList(
            name="Empty PL",
            valid_from=dt.date(2020, 1, 1),
            valid_to=dt.date(9999, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                price_list_id=pl.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        for item in response.bom.commercial:
            assert item.unit_price is None
            assert item.line_total is None
        assert response.bom.commercial_total is None
        assert len(response.bom.warnings) == 2


class TestNoPriceList:
    """When price_list_id not provided, BOM has no pricing and no warnings."""

    def test_no_price_list_no_pricing_no_warnings(self, db_session, bom_entity):
        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                current_state=[],
            ),
        )

        assert response.bom is not None
        for item in response.bom.commercial:
            assert item.unit_price is None
            assert item.line_total is None
        assert response.bom.commercial_total is None
        assert response.bom.warnings == []


class TestPriceListErrors:
    """Error cases for the price_list_id parameter."""

    def test_invalid_price_list_id_raises(self, db_session, bom_entity):
        service = RuleEngineService()
        with pytest.raises(ValueError, match="not found"):
            service.calculate_state(
                db_session,
                CalculationRequest(
                    entity_id=bom_entity["entity_id"],
                    price_list_id=999999,
                    current_state=[],
                ),
            )

    def test_price_list_not_valid_at_date(self, db_session, bom_entity):
        pl = PriceList(
            name="Narrow PL",
            valid_from=dt.date(2025, 1, 1),
            valid_to=dt.date(2025, 12, 31),
        )
        db_session.add(pl)
        db_session.commit()

        service = RuleEngineService()
        with pytest.raises(ValueError, match="not valid"):
            service.calculate_state(
                db_session,
                CalculationRequest(
                    entity_id=bom_entity["entity_id"],
                    price_list_id=pl.id,
                    price_date=dt.date(2026, 6, 1),
                    current_state=[],
                ),
            )


class TestTemporalPricing:
    """Temporal versioning: different prices at different dates."""

    def test_different_prices_at_different_dates(self, db_session, bom_entity):
        pl = PriceList(
            name="Temporal PL",
            valid_from=dt.date(2024, 1, 1),
            valid_to=dt.date(2030, 12, 31),
        )
        db_session.add(pl)
        db_session.flush()

        # COMM-A: 10.00 in 2025, 12.00 in 2026
        db_session.add_all(
            [
                PriceListItem(
                    price_list_id=pl.id,
                    part_number="COMM-A",
                    unit_price=Decimal("10.00"),
                    valid_from=dt.date(2025, 1, 1),
                    valid_to=dt.date(2025, 12, 31),
                ),
                PriceListItem(
                    price_list_id=pl.id,
                    part_number="COMM-A",
                    unit_price=Decimal("12.00"),
                    valid_from=dt.date(2026, 1, 1),
                    valid_to=dt.date(2026, 12, 31),
                ),
                PriceListItem(
                    price_list_id=pl.id,
                    part_number="COMM-B",
                    unit_price=Decimal("5.00"),
                    valid_from=dt.date(2024, 1, 1),
                    valid_to=dt.date(2030, 12, 31),
                ),
            ]
        )
        db_session.commit()

        service = RuleEngineService()

        response_2025 = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                price_list_id=pl.id,
                price_date=dt.date(2025, 6, 1),
                current_state=[],
            ),
        )
        a_2025 = next(i for i in response_2025.bom.commercial if i.part_number == "COMM-A")
        assert a_2025.unit_price == Decimal("10.00")

        response_2026 = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                price_list_id=pl.id,
                price_date=dt.date(2026, 6, 1),
                current_state=[],
            ),
        )
        a_2026 = next(i for i in response_2026.bom.commercial if i.part_number == "COMM-A")
        assert a_2026.unit_price == Decimal("12.00")

    def test_price_date_defaults_to_today(self, db_session, bom_entity):
        today = dt.date.today()
        pl = PriceList(
            name="Today PL",
            valid_from=today - dt.timedelta(days=30),
            valid_to=today + dt.timedelta(days=30),
        )
        db_session.add(pl)
        db_session.flush()
        db_session.add_all(
            [
                PriceListItem(
                    price_list_id=pl.id,
                    part_number="COMM-A",
                    unit_price=Decimal("10.00"),
                    valid_from=today - dt.timedelta(days=30),
                    valid_to=today + dt.timedelta(days=30),
                ),
                PriceListItem(
                    price_list_id=pl.id,
                    part_number="COMM-B",
                    unit_price=Decimal("5.00"),
                    valid_from=today - dt.timedelta(days=30),
                    valid_to=today + dt.timedelta(days=30),
                ),
            ]
        )
        db_session.commit()

        service = RuleEngineService()
        response = service.calculate_state(
            db_session,
            CalculationRequest(
                entity_id=bom_entity["entity_id"],
                price_list_id=pl.id,
                current_state=[],
            ),
        )

        assert response.bom is not None
        assert response.bom.commercial_total == Decimal("35.00")
        assert response.bom.warnings == []
