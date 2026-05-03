import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, get_current_user, require_admin_or_author, validate_catalog_not_referenced
from app.models.domain import BOMItem, CatalogItem, CatalogItemStatus, EngineeringTemplateItem, User
from app.schemas.catalog_item import (
    CatalogItemBOMReference,
    CatalogItemCreate,
    CatalogItemRead,
    CatalogItemUpdate,
    CatalogItemUsageResponse,
)
from app.schemas.engineering_template_item import EngineeringTemplateItemRead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/catalog-items", tags=["Catalog Items"])


def _get_catalog_item_or_404(item_id: int, db: Session = Depends(get_db)) -> CatalogItem:
    """Fetch a CatalogItem by surrogate id or raise 404."""
    item = db.query(CatalogItem).filter(CatalogItem.id == item_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Catalog item {item_id} not found.",
        )
    return item


@router.get("/", response_model=list[CatalogItemRead])
def list_catalog_items(
    status_filter: CatalogItemStatus | None = Query(
        default=None, alias="status", description="Filter by lifecycle status"
    ),
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List catalog items by `part_number` ASC, optionally filtered by `status` (any authenticated user)."""

    query = db.query(CatalogItem)
    if status_filter is not None:
        query = query.filter(CatalogItem.status == status_filter)

    items = query.order_by(CatalogItem.part_number).offset(skip).limit(limit).all()

    logger.info(f"Returning {len(items)} catalog items")
    return items


@router.post("/", response_model=CatalogItemRead, status_code=status.HTTP_201_CREATED)
def create_catalog_item(
    payload: CatalogItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Create a catalog item (ADMIN/AUTHOR); duplicate `part_number` returns 409."""

    existing = db.query(CatalogItem).filter(CatalogItem.part_number == payload.part_number).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Catalog item with part_number '{payload.part_number}' already exists.",
        )

    with db_transaction(db, f"create_catalog_item '{payload.part_number}'"):
        item = CatalogItem(**payload.model_dump())
        db.add(item)
        db.flush()

        logger.info(f"Catalog item {item.id} created successfully: part_number='{payload.part_number}'")

    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=CatalogItemRead)
def read_catalog_item(
    item: CatalogItem = Depends(_get_catalog_item_or_404),
    current_user: User = Depends(get_current_user),
):
    """Get a catalog item by surrogate id (any authenticated user)."""
    logger.debug(f"Reading catalog item {item.id} by user {current_user.id}")
    return item


@router.get("/{part_number}/usage", response_model=CatalogItemUsageResponse)
def read_catalog_item_usage(
    part_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Where-used graph: template rows (parent/child) and `BOMItem` references. ADMIN/AUTHOR only."""
    logger.debug(f"Reading usage for catalog item '{part_number}' by user {current_user.id}")

    catalog_item = db.query(CatalogItem).filter(CatalogItem.part_number == part_number).first()
    if catalog_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Catalog item with part_number '{part_number}' not found.",
        )

    templates_as_parent = (
        db.query(EngineeringTemplateItem)
        .filter(EngineeringTemplateItem.parent_part_number == part_number)
        .order_by(EngineeringTemplateItem.sequence, EngineeringTemplateItem.child_part_number)
        .all()
    )
    templates_as_child = (
        db.query(EngineeringTemplateItem)
        .filter(EngineeringTemplateItem.child_part_number == part_number)
        .order_by(EngineeringTemplateItem.parent_part_number, EngineeringTemplateItem.sequence)
        .all()
    )
    bom_item_rows = (
        db.query(BOMItem.id, BOMItem.entity_version_id)
        .filter(BOMItem.part_number == part_number)
        .order_by(BOMItem.entity_version_id, BOMItem.id)
        .all()
    )
    bom_items = [
        CatalogItemBOMReference(bom_item_id=bom_id, entity_version_id=version_id)
        for bom_id, version_id in bom_item_rows
    ]

    logger.info(
        f"Returning usage for '{part_number}': "
        f"templates_as_parent={len(templates_as_parent)} "
        f"templates_as_child={len(templates_as_child)} "
        f"bom_items={len(bom_items)}"
    )

    return CatalogItemUsageResponse(
        part_number=part_number,
        templates_as_parent=[EngineeringTemplateItemRead.model_validate(t) for t in templates_as_parent],
        templates_as_child=[EngineeringTemplateItemRead.model_validate(t) for t in templates_as_child],
        bom_items=bom_items,
    )


@router.get("/by-part-number/{part_number}", response_model=CatalogItemRead)
def read_catalog_item_by_part_number(
    part_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a catalog item by business key `part_number` (any authenticated user)."""
    logger.debug(f"Reading catalog item by part_number '{part_number}' by user {current_user.id}")
    item = db.query(CatalogItem).filter(CatalogItem.part_number == part_number).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Catalog item with part_number '{part_number}' not found.",
        )
    return item


@router.patch("/{item_id}", response_model=CatalogItemRead)
def update_catalog_item(
    payload: CatalogItemUpdate,
    item: CatalogItem = Depends(_get_catalog_item_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Update a catalog item (ADMIN/AUTHOR); `part_number` is immutable and rejected with 422."""

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        return item

    with db_transaction(db, f"update_catalog_item {item.id}"):
        for key, value in update_data.items():
            setattr(item, key, value)

        logger.info(f"Catalog item {item.id} updated successfully")

    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_catalog_item(
    item: CatalogItem = Depends(_get_catalog_item_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Delete a catalog item; blocked with 409 if any BOM, price-list, or template row references it."""

    validate_catalog_not_referenced(db, item)

    with db_transaction(db, f"delete_catalog_item {item.id}"):
        part_number = item.part_number
        db.delete(item)

        logger.info(f"Catalog item {item.id} ('{part_number}') deleted successfully")

    return None
