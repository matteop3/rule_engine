"""
Engine tests for catalog-driven BOMLineItem metadata.

The rule engine sources `description`, `category`, and `unit_of_measure` for
each BOMLineItem from the CatalogItem joined on `part_number`. These tests
verify the wiring end-to-end (DRAFT recalculation, OBSOLETE tolerance,
mutation, and snapshot independence).
"""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.domain import (
    BOMItem,
    BOMType,
    CatalogItem,
    CatalogItemStatus,
    Entity,
    EntityVersion,
    VersionStatus,
)
from app.schemas.engine import CalculationRequest, CalculationResponse
from app.services.rule_engine import RuleEngineService
from tests.fixtures.catalog_items import ensure_catalog_entry
from tests.fixtures.price_lists import create_price_list_with_items


@pytest.fixture(scope="function")
def setup_catalog_bom_scenario(db_session: Session):
    """
    Minimal entity with one TECHNICAL and one COMMERCIAL BOM item, both
    referencing curated catalog entries with distinct descriptions,
    categories, and units of measure.
    """
    # Pre-seed the catalog with rich metadata (overrides the conftest auto-seed defaults)
    ensure_catalog_entry(
        db_session,
        "FRM-001",
        description="Steel Frame Assembly",
        category="STRUCTURE",
        unit_of_measure="EA",
    )
    ensure_catalog_entry(
        db_session,
        "BOLT-M8",
        description="M8 Stainless Bolt",
        category="HARDWARE",
        unit_of_measure="PC",
    )

    entity = Entity(name="Catalog Metadata Product", description="Catalog wiring tests")
    db_session.add(entity)
    db_session.flush()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
    )
    db_session.add(version)
    db_session.flush()

    bom_frame = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.TECHNICAL.value,
        part_number="FRM-001",
        quantity=Decimal("1"),
        sequence=1,
    )
    bom_bolt = BOMItem(
        entity_version_id=version.id,
        bom_type=BOMType.COMMERCIAL.value,
        part_number="BOLT-M8",
        quantity=Decimal("4"),
        sequence=2,
    )
    db_session.add_all([bom_frame, bom_bolt])
    db_session.commit()

    price_list = create_price_list_with_items(
        db_session,
        {"BOLT-M8": Decimal("0.50")},
    )

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "price_list_id": price_list.id,
        "bom_frame_id": bom_frame.id,
        "bom_bolt_id": bom_bolt.id,
    }


def _calculate(db_session: Session, scenario: dict) -> CalculationResponse:
    service = RuleEngineService()
    return service.calculate_state(
        db_session,
        CalculationRequest(
            entity_id=scenario["entity_id"],
            entity_version_id=scenario["version_id"],
            current_state=[],
            price_list_id=scenario["price_list_id"],
        ),
    )


def _by_part(items, part_number):
    for item in items:
        if item.part_number == part_number:
            return item
    raise AssertionError(f"BOMLineItem '{part_number}' not present in output")


class TestBOMLineMetadataFromCatalog:
    """Each BOMLineItem in the response carries metadata from the catalog row."""

    def test_technical_line_metadata_sourced_from_catalog(self, db_session, setup_catalog_bom_scenario):
        response = _calculate(db_session, setup_catalog_bom_scenario)

        assert response.bom is not None
        frame = _by_part(response.bom.technical, "FRM-001")
        assert frame.description == "Steel Frame Assembly"
        assert frame.category == "STRUCTURE"
        assert frame.unit_of_measure == "EA"

    def test_commercial_line_metadata_sourced_from_catalog(self, db_session, setup_catalog_bom_scenario):
        response = _calculate(db_session, setup_catalog_bom_scenario)

        assert response.bom is not None
        bolt = _by_part(response.bom.commercial, "BOLT-M8")
        assert bolt.description == "M8 Stainless Bolt"
        assert bolt.category == "HARDWARE"
        assert bolt.unit_of_measure == "PC"
        # Pricing still resolves correctly alongside metadata
        assert bolt.unit_price == Decimal("0.50")
        assert bolt.line_total == Decimal("2.00")


class TestCatalogMutationOnDraft:
    """Mutating the catalog changes the next calculation output (DRAFT path)."""

    def test_description_change_reflected_in_next_calculation(self, db_session, setup_catalog_bom_scenario):
        scenario = setup_catalog_bom_scenario

        # Reuse a single service across both calls so the second hits the
        # PUBLISHED-version cache; catalog metadata must still re-resolve.
        service = RuleEngineService()
        request = CalculationRequest(
            entity_id=scenario["entity_id"],
            entity_version_id=scenario["version_id"],
            current_state=[],
            price_list_id=scenario["price_list_id"],
        )

        first = service.calculate_state(db_session, request)
        assert first.bom is not None
        assert _by_part(first.bom.commercial, "BOLT-M8").description == "M8 Stainless Bolt"

        bolt_catalog = db_session.query(CatalogItem).filter(CatalogItem.part_number == "BOLT-M8").one()
        bolt_catalog.description = "M8 Bolt — Updated"
        bolt_catalog.category = "FASTENER"
        db_session.commit()

        second = service.calculate_state(db_session, request)
        assert second.bom is not None
        bolt = _by_part(second.bom.commercial, "BOLT-M8")
        assert bolt.description == "M8 Bolt — Updated"
        assert bolt.category == "FASTENER"
        # Sanity: cached version data was reused (1 miss + 1 hit)
        stats = service._cache.stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 1

    def test_unit_of_measure_change_reflected_in_next_calculation(self, db_session, setup_catalog_bom_scenario):
        scenario = setup_catalog_bom_scenario

        frame_catalog = db_session.query(CatalogItem).filter(CatalogItem.part_number == "FRM-001").one()
        frame_catalog.unit_of_measure = "KG"
        db_session.commit()

        response = _calculate(db_session, scenario)
        assert response.bom is not None
        assert _by_part(response.bom.technical, "FRM-001").unit_of_measure == "KG"


class TestObsoleteCatalogTolerance:
    """OBSOLETE gates new references but does not break calculations on existing ones."""

    def test_obsoleting_referenced_catalog_does_not_break_calculation(self, db_session, setup_catalog_bom_scenario):
        scenario = setup_catalog_bom_scenario

        bolt_catalog = db_session.query(CatalogItem).filter(CatalogItem.part_number == "BOLT-M8").one()
        bolt_catalog.status = CatalogItemStatus.OBSOLETE
        db_session.commit()

        response = _calculate(db_session, scenario)

        assert response.bom is not None
        bolt = _by_part(response.bom.commercial, "BOLT-M8")
        # Metadata remains fully populated despite OBSOLETE status.
        assert bolt.description == "M8 Stainless Bolt"
        assert bolt.category == "HARDWARE"
        assert bolt.unit_of_measure == "PC"


class TestSnapshotIsolatedFromCatalogMutation:
    """Round-tripping the response through model_dump simulates the FINALIZED snapshot path."""

    def test_snapshot_description_unchanged_after_catalog_modified(self, db_session, setup_catalog_bom_scenario):
        scenario = setup_catalog_bom_scenario

        original = _calculate(db_session, scenario)
        snapshot = original.model_dump(mode="json")

        # Mutate the catalog after the snapshot is taken
        bolt_catalog = db_session.query(CatalogItem).filter(CatalogItem.part_number == "BOLT-M8").one()
        bolt_catalog.description = "Mutated After Finalize"
        bolt_catalog.category = "MUTATED"
        db_session.commit()

        restored = CalculationResponse(**snapshot)
        assert restored.bom is not None
        bolt = _by_part(restored.bom.commercial, "BOLT-M8")
        assert bolt.description == "M8 Stainless Bolt"
        assert bolt.category == "HARDWARE"

    def test_snapshot_intact_after_catalog_deleted(self, db_session, setup_catalog_bom_scenario):
        scenario = setup_catalog_bom_scenario

        original = _calculate(db_session, scenario)
        snapshot = original.model_dump(mode="json")

        # Clear all live references so the catalog row can be deleted, then drop it.
        db_session.query(BOMItem).filter(BOMItem.part_number == "FRM-001").delete()
        db_session.commit()
        frame_catalog = db_session.query(CatalogItem).filter(CatalogItem.part_number == "FRM-001").one()
        db_session.delete(frame_catalog)
        db_session.commit()
        assert db_session.query(CatalogItem).filter(CatalogItem.part_number == "FRM-001").first() is None

        restored = CalculationResponse(**snapshot)
        assert restored.bom is not None
        frame = _by_part(restored.bom.technical, "FRM-001")
        assert frame.description == "Steel Frame Assembly"
        assert frame.category == "STRUCTURE"
        assert frame.unit_of_measure == "EA"


class TestCatalogLookupMutationKill:
    """
    Mutation kill: the engine must never fall back to `part_number` (or `None`)
    for `description`. It must always source from the catalog row.
    """

    def test_description_does_not_fall_back_to_part_number(self, db_session, setup_catalog_bom_scenario):
        scenario = setup_catalog_bom_scenario
        response = _calculate(db_session, scenario)

        assert response.bom is not None
        for line in (*response.bom.technical, *response.bom.commercial):
            assert line.description is not None, f"BOMLineItem for '{line.part_number}' has no description"
            assert line.description != line.part_number, (
                f"BOMLineItem description for '{line.part_number}' fell back to the part_number; "
                "the engine must source description from the catalog row."
            )
