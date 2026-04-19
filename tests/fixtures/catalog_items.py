"""
Catalog item fixtures for tests.
Provides factory helpers for creating catalog entries used in tests.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.domain import CatalogItem, CatalogItemStatus


def create_catalog_item(
    db: Session,
    part_number: str,
    **overrides: Any,
) -> CatalogItem:
    """
    Create a CatalogItem with sensible defaults.

    Defaults:
        description  = part_number
        unit_of_measure = "PC"
        status       = CatalogItemStatus.ACTIVE

    Any field can be overridden via keyword arguments.
    """
    attrs: dict[str, Any] = {
        "part_number": part_number,
        "description": part_number,
        "unit_of_measure": "PC",
        "status": CatalogItemStatus.ACTIVE,
    }
    attrs.update(overrides)

    item = CatalogItem(**attrs)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def ensure_catalog_entry(
    db: Session,
    part_number: str,
    **overrides: Any,
) -> CatalogItem:
    """
    Idempotent catalog entry provisioning.

    If a catalog item with the given `part_number` already exists, return it
    unchanged. Otherwise create a fresh one with sensible defaults (see
    `create_catalog_item`). This is the helper used by BOM and price list
    fixtures to guarantee a catalog row is present before referencing it.
    """
    existing = db.query(CatalogItem).filter(CatalogItem.part_number == part_number).first()
    if existing:
        return existing
    return create_catalog_item(db, part_number, **overrides)
