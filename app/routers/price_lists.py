import datetime as dt
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, require_admin_or_author
from app.models.domain import Configuration, ConfigurationStatus, PriceList, PriceListItem, User
from app.schemas.price_list import PriceListCreate, PriceListRead, PriceListUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/price-lists", tags=["Price Lists"])


def _get_price_list_or_404(price_list_id: int, db: Session = Depends(get_db)) -> PriceList:
    """Fetch a PriceList by ID or raise 404."""
    price_list = db.query(PriceList).filter(PriceList.id == price_list_id).first()
    if not price_list:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Price list {price_list_id} not found.",
        )
    return price_list


@router.get("/", response_model=list[PriceListRead])
def list_price_lists(
    valid_at: dt.date | None = Query(default=None, description="Filter by validity date (default: today)"),
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """List price lists valid at `valid_at` (default today). ADMIN/AUTHOR only."""
    effective_date = valid_at if valid_at is not None else dt.date.today()

    items = (
        db.query(PriceList)
        .filter(PriceList.valid_from <= effective_date, PriceList.valid_to >= effective_date)
        .order_by(PriceList.name)
        .offset(skip)
        .limit(limit)
        .all()
    )

    logger.info(f"Returning {len(items)} price lists")
    return items


@router.post("/", response_model=PriceListRead, status_code=status.HTTP_201_CREATED)
def create_price_list(
    payload: PriceListCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Create a price list (ADMIN/AUTHOR); duplicate `name` returns 409."""

    # Check unique name
    existing = db.query(PriceList).filter(PriceList.name == payload.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Price list with name '{payload.name}' already exists.",
        )

    with db_transaction(db, f"create_price_list '{payload.name}'"):
        price_list = PriceList(**payload.model_dump())
        db.add(price_list)
        db.flush()

        logger.info(f"Price list {price_list.id} created successfully: name='{payload.name}'")

    db.refresh(price_list)
    return price_list


@router.get("/{price_list_id}", response_model=PriceListRead)
def read_price_list(
    price_list: PriceList = Depends(_get_price_list_or_404),
    current_user: User = Depends(require_admin_or_author),
):
    """Get a price list by id. ADMIN/AUTHOR only."""
    logger.debug(f"Reading price list {price_list.id} by user {current_user.id}")
    return price_list


@router.patch("/{price_list_id}", response_model=PriceListRead)
def update_price_list(
    payload: PriceListUpdate,
    price_list: PriceList = Depends(_get_price_list_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Update a price list header (ADMIN/AUTHOR).

    `valid_from < valid_to` is enforced; narrowing the bounding box that
    excludes any existing item returns 409.
    """

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        return price_list

    # Check unique name if being changed
    if "name" in update_data and update_data["name"] != price_list.name:
        existing = db.query(PriceList).filter(PriceList.name == update_data["name"]).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Price list with name '{update_data['name']}' already exists.",
            )

    # Compute effective dates for cross-validation
    new_valid_from = update_data.get("valid_from", price_list.valid_from)
    new_valid_to = update_data.get("valid_to", price_list.valid_to)

    if new_valid_from >= new_valid_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="valid_from must be strictly less than valid_to.",
        )

    # If dates are changing, verify bounding box for existing items
    if "valid_from" in update_data or "valid_to" in update_data:
        violating_items = (
            db.query(PriceListItem)
            .filter(
                PriceListItem.price_list_id == price_list.id,
                (PriceListItem.valid_from < new_valid_from) | (PriceListItem.valid_to > new_valid_to),
            )
            .all()
        )
        if violating_items:
            details = [f"'{item.part_number}' ({item.valid_from}..{item.valid_to})" for item in violating_items[:5]]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot narrow date range to {new_valid_from}..{new_valid_to}. "
                    f"The following items fall outside the new range: {', '.join(details)}"
                    + (f" (and {len(violating_items) - 5} more)" if len(violating_items) > 5 else "")
                ),
            )

    with db_transaction(db, f"update_price_list {price_list.id}"):
        for key, value in update_data.items():
            setattr(price_list, key, value)

        logger.info(f"Price list {price_list.id} updated successfully")

    db.refresh(price_list)
    return price_list


@router.delete("/{price_list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_price_list(
    price_list: PriceList = Depends(_get_price_list_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Delete a price list (ADMIN/AUTHOR); blocked with 409 if any FINALIZED configuration references it."""

    finalized_count = (
        db.query(Configuration)
        .filter(
            Configuration.price_list_id == price_list.id,
            Configuration.status == ConfigurationStatus.FINALIZED,
        )
        .count()
    )
    if finalized_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete price list '{price_list.name}': "
                f"referenced by {finalized_count} FINALIZED configuration(s)."
            ),
        )

    with db_transaction(db, f"delete_price_list {price_list.id}"):
        name = price_list.name
        db.delete(price_list)

        logger.info(f"Price list {price_list.id} ('{name}') deleted successfully")

    return None
