import datetime as dt
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, require_admin_or_author, validate_catalog_reference
from app.models.domain import PriceList, PriceListItem, User
from app.schemas.price_list_item import PriceListItemCreate, PriceListItemRead, PriceListItemUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/price-list-items", tags=["Price List Items"])


def _get_price_list_or_404(db: Session, price_list_id: int) -> PriceList:
    """Fetch a PriceList by ID or raise 404."""
    price_list = db.query(PriceList).filter(PriceList.id == price_list_id).first()
    if not price_list:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Price list {price_list_id} not found.",
        )
    return price_list


def _get_item_or_404(item_id: int, db: Session = Depends(get_db)) -> PriceListItem:
    """Fetch a PriceListItem by ID or raise 404."""
    item = db.query(PriceListItem).filter(PriceListItem.id == item_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Price list item {item_id} not found.",
        )
    return item


def _validate_bounding_box(
    item_valid_from: dt.date,
    item_valid_to: dt.date,
    price_list: PriceList,
) -> None:
    """Validate item dates fall within the parent price list's bounding box."""
    violations = []
    if item_valid_from < price_list.valid_from:
        violations.append(f"valid_from ({item_valid_from}) is before price list valid_from ({price_list.valid_from})")
    if item_valid_to > price_list.valid_to:
        violations.append(f"valid_to ({item_valid_to}) is after price list valid_to ({price_list.valid_to})")
    if violations:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Item dates outside price list bounding box: {'; '.join(violations)}.",
        )


def _validate_no_overlap(
    db: Session,
    price_list_id: int,
    part_number: str,
    valid_from: dt.date,
    valid_to: dt.date,
    exclude_id: int | None = None,
) -> None:
    """Validate no overlapping date ranges for the same (price_list_id, part_number)."""
    query = db.query(PriceListItem).filter(
        PriceListItem.price_list_id == price_list_id,
        PriceListItem.part_number == part_number,
        PriceListItem.valid_from < valid_to,
        PriceListItem.valid_to > valid_from,
    )
    if exclude_id is not None:
        query = query.filter(PriceListItem.id != exclude_id)

    conflict = query.first()
    if conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Date range {valid_from}..{valid_to} overlaps with existing item "
                f"'{conflict.part_number}' ({conflict.valid_from}..{conflict.valid_to})."
            ),
        )


def _validate_unit_price(unit_price: Decimal) -> None:
    """Validate unit_price is positive."""
    if unit_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unit_price must be greater than 0.",
        )


@router.get("/", response_model=list[PriceListItemRead])
def list_price_list_items(
    price_list_id: int = Query(..., description="Filter by price list ID"),
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """List items of a price list, ordered by `(part_number, valid_from)`. ADMIN/AUTHOR only."""

    # Verify price list exists
    _get_price_list_or_404(db, price_list_id)

    items = (
        db.query(PriceListItem)
        .filter(PriceListItem.price_list_id == price_list_id)
        .order_by(PriceListItem.part_number, PriceListItem.valid_from)
        .offset(skip)
        .limit(limit)
        .all()
    )

    logger.info(f"Returning {len(items)} price list items for price_list_id={price_list_id}")
    return items


@router.get("/{item_id}", response_model=PriceListItemRead)
def read_price_list_item(
    item: PriceListItem = Depends(_get_item_or_404),
    current_user: User = Depends(require_admin_or_author),
):
    """Get a price list item by id. ADMIN/AUTHOR only."""
    logger.debug(f"Reading price list item {item.id} by user {current_user.id}")
    return item


@router.post("/", response_model=PriceListItemRead, status_code=status.HTTP_201_CREATED)
def create_price_list_item(
    payload: PriceListItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Create a price list item (ADMIN/AUTHOR).

    Dates default to the parent price list's bounding box; rejects overlaps
    on `(price_list_id, part_number)` with 409 and out-of-box dates with 400.
    """
    logger.info(
        f"Creating price list item '{payload.part_number}' "
        f"for price_list_id={payload.price_list_id} by user {current_user.id}"
    )

    price_list = _get_price_list_or_404(db, payload.price_list_id)

    validate_catalog_reference(db, payload.part_number, on_create=True)
    _validate_unit_price(payload.unit_price)

    # Default dates from parent price list
    effective_valid_from = payload.valid_from if payload.valid_from is not None else price_list.valid_from
    effective_valid_to = payload.valid_to if payload.valid_to is not None else price_list.valid_to

    if effective_valid_from >= effective_valid_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="valid_from must be strictly less than valid_to.",
        )

    _validate_bounding_box(effective_valid_from, effective_valid_to, price_list)
    _validate_no_overlap(db, payload.price_list_id, payload.part_number, effective_valid_from, effective_valid_to)

    with db_transaction(db, f"create_price_list_item '{payload.part_number}' for price_list {price_list.id}"):
        item_data = payload.model_dump()
        item_data["valid_from"] = effective_valid_from
        item_data["valid_to"] = effective_valid_to
        new_item = PriceListItem(**item_data)
        db.add(new_item)
        db.flush()

        logger.info(f"Price list item {new_item.id} created successfully: part_number='{payload.part_number}'")

    db.refresh(new_item)
    return new_item


@router.patch("/{item_id}", response_model=PriceListItemRead)
def update_price_list_item(
    payload: PriceListItemUpdate,
    item: PriceListItem = Depends(_get_item_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Update a price list item (ADMIN/AUTHOR); revalidates bounding box and overlaps."""

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        return item

    if "part_number" in update_data and update_data["part_number"] != item.part_number:
        validate_catalog_reference(db, update_data["part_number"], on_create=False)

    if "unit_price" in update_data:
        _validate_unit_price(update_data["unit_price"])

    # Compute effective values for validation
    effective_valid_from = update_data.get("valid_from", item.valid_from)
    effective_valid_to = update_data.get("valid_to", item.valid_to)
    effective_part_number = update_data.get("part_number", item.part_number)

    if effective_valid_from >= effective_valid_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="valid_from must be strictly less than valid_to.",
        )

    # Validate bounding box and overlap if dates or part_number changed
    if "valid_from" in update_data or "valid_to" in update_data or "part_number" in update_data:
        price_list = _get_price_list_or_404(db, item.price_list_id)
        _validate_bounding_box(effective_valid_from, effective_valid_to, price_list)
        _validate_no_overlap(
            db, item.price_list_id, effective_part_number, effective_valid_from, effective_valid_to, exclude_id=item.id
        )

    with db_transaction(db, f"update_price_list_item {item.id}"):
        for key, value in update_data.items():
            setattr(item, key, value)

        logger.info(f"Price list item {item.id} updated successfully")

    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_price_list_item(
    item: PriceListItem = Depends(_get_item_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Delete a price list item. ADMIN/AUTHOR only."""

    with db_transaction(db, f"delete_price_list_item {item.id}"):
        part_number = item.part_number
        db.delete(item)

        logger.info(f"Price list item {item.id} ('{part_number}') deleted successfully")

    return None
