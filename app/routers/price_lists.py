import datetime as dt
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, require_admin_or_author
from app.models.domain import Configuration, ConfigurationStatus, PriceList, PriceListItem, User
from app.schemas.price_list import PriceListCreate, PriceListRead, PriceListUpdate

# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)

# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(prefix="/price-lists", tags=["Price Lists"])

# ============================================================
# HELPERS
# ============================================================


def _get_price_list_or_404(price_list_id: int, db: Session = Depends(get_db)) -> PriceList:
    """Fetch a PriceList by ID or raise 404."""
    price_list = db.query(PriceList).filter(PriceList.id == price_list_id).first()
    if not price_list:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Price list {price_list_id} not found.",
        )
    return price_list


# ============================================================
# ENDPOINTS
# ============================================================


@router.get("/", response_model=list[PriceListRead])
def list_price_lists(
    valid_at: dt.date | None = Query(default=None, description="Filter by validity date (default: today)"),
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """
    List price lists, optionally filtered by validity at a given date.

    If `valid_at` is not provided, defaults to today.

    Access Control:
        - Only ADMIN and AUTHOR can view price lists
    """
    effective_date = valid_at if valid_at is not None else dt.date.today()

    logger.info(f"Listing price lists valid at {effective_date} by user {current_user.id}")

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
    """
    Create a new price list.

    Validation:
        - valid_from must be strictly less than valid_to (enforced by schema)
        - name must be unique (DB constraint)

    Access Control:
        - Only ADMIN and AUTHOR can create price lists
    """
    logger.info(f"Creating price list '{payload.name}' by user {current_user.id}")

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
    """
    Retrieve a single price list by ID.

    Access Control:
        - Only ADMIN and AUTHOR can view price list details
    """
    logger.debug(f"Reading price list {price_list.id} by user {current_user.id}")
    return price_list


@router.patch("/{price_list_id}", response_model=PriceListRead)
def update_price_list(
    payload: PriceListUpdate,
    price_list: PriceList = Depends(_get_price_list_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """
    Update a price list header.

    Validation:
        - valid_from must be strictly less than valid_to (considering current + new values)
        - If changing dates, all existing items must still fit within the new bounding box

    Access Control:
        - Only ADMIN and AUTHOR can update price lists
    """
    logger.info(f"Updating price list {price_list.id} by user {current_user.id}")

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning(f"Empty update request for price list {price_list.id}")
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
    """
    Delete a price list.

    Restrictions:
        - Cannot delete if referenced by any FINALIZED configuration (HTTP 409)
        - DRAFT configurations using this price list will have price_list_id set to NULL (FK SET NULL)

    Access Control:
        - Only ADMIN and AUTHOR can delete price lists
    """
    logger.info(f"Deleting price list {price_list.id} by user {current_user.id}")

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
