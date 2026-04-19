import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, get_current_user, require_admin_or_author, validate_catalog_not_referenced
from app.models.domain import CatalogItem, CatalogItemStatus, User
from app.schemas.catalog_item import CatalogItemCreate, CatalogItemRead, CatalogItemUpdate

# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)

# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(prefix="/catalog-items", tags=["Catalog Items"])

# ============================================================
# HELPERS
# ============================================================


def _get_catalog_item_or_404(item_id: int, db: Session = Depends(get_db)) -> CatalogItem:
    """Fetch a CatalogItem by surrogate id or raise 404."""
    item = db.query(CatalogItem).filter(CatalogItem.id == item_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Catalog item {item_id} not found.",
        )
    return item


# ============================================================
# ENDPOINTS
# ============================================================


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
    """
    List catalog items, optionally filtered by `status`.

    Ordered by `part_number` ASC.

    Access Control:
        - Any authenticated user can list catalog items
    """
    logger.info(f"Listing catalog items (status={status_filter}) by user {current_user.id}")

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
    """
    Create a new catalog item.

    Validation:
        - `part_number` must be unique (HTTP 409 on duplicate)

    Access Control:
        - Only ADMIN and AUTHOR can create catalog items
    """
    logger.info(f"Creating catalog item '{payload.part_number}' by user {current_user.id}")

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
    """
    Retrieve a single catalog item by its surrogate id.

    Access Control:
        - Any authenticated user can read catalog items
    """
    logger.debug(f"Reading catalog item {item.id} by user {current_user.id}")
    return item


@router.get("/by-part-number/{part_number}", response_model=CatalogItemRead)
def read_catalog_item_by_part_number(
    part_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve a single catalog item by its business key (`part_number`).

    Access Control:
        - Any authenticated user can read catalog items
    """
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
    """
    Update a catalog item.

    The `part_number` field is the immutable business key and cannot be
    modified; any payload containing `part_number` is rejected with
    HTTP 422 at the schema layer. To retire a part, set `status` to
    OBSOLETE and create a new entry with the desired number.

    Access Control:
        - Only ADMIN and AUTHOR can update catalog items
    """
    logger.info(f"Updating catalog item {item.id} by user {current_user.id}")

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning(f"Empty update request for catalog item {item.id}")
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
    """
    Delete a catalog item.

    Access Control:
        - Only ADMIN and AUTHOR can delete catalog items
    """
    logger.info(f"Deleting catalog item {item.id} by user {current_user.id}")

    validate_catalog_not_referenced(db, item)

    with db_transaction(db, f"delete_catalog_item {item.id}"):
        part_number = item.part_number
        db.delete(item)

        logger.info(f"Catalog item {item.id} ('{part_number}') deleted successfully")

    return None
