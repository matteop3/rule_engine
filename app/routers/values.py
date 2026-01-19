import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    require_admin_or_author,
    fetch_version_by_id,
    fetch_field_by_id,
    validate_version_is_draft,
    validate_value_not_used_in_rules,
    get_value_or_404,
    get_editable_value,
    db_transaction
)
from app.models.domain import Value, Field, User
from app.schemas import ValueCreate, ValueRead, ValueUpdate


# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(
    prefix="/values",
    tags=["Values"]
)


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/", response_model=List[ValueRead])
def list_values(
    field_id: Optional[int] = None,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Retrieve Values for a specific Field.

    Access Control:
        - Only ADMIN and AUTHOR can view values

    Query Parameters:
        field_id: Filter by field (optional)
        skip: Pagination offset
        limit: Maximum results (max 100)

    Returns:
        List[ValueRead]: List of values
    """
    logger.info(
        f"Listing values by user {current_user.id}: "
        f"field={field_id}, skip={skip}, limit={limit}"
    )

    # Cap limit to prevent abuse
    original_limit = limit
    limit = min(limit, 100)

    if original_limit > 100:
        logger.warning(f"Limit capped from {original_limit} to 100")

    query = db.query(Value)

    if field_id:
        query = query.filter(Value.field_id == field_id)

    values = query.offset(skip).limit(limit).all()

    logger.info(f"Returning {len(values)} values")

    return values


@router.get("/{value_id}", response_model=ValueRead)
def read_value(
    value: Value = Depends(get_value_or_404),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Retrieve a single Value.

    Access Control:
        - Only ADMIN and AUTHOR can view value details

    Returns:
        ValueRead: The requested value
    """
    logger.debug(f"Reading value {value.id} by user {current_user.id}")
    return value


@router.post("/", response_model=ValueRead, status_code=status.HTTP_201_CREATED)
def create_value(
    value_data: ValueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Create a new Value related to a Field.

    Restrictions:
        - The version must be DRAFT
        - Parent Field must exist
        - Cannot create values for free-value Fields

    Access Control:
        - Only ADMIN and AUTHOR can create values

    Returns:
        ValueRead: The created value
    """
    logger.info(
        f"Creating value for field {value_data.field_id} "
        f"by user {current_user.id} (role: {current_user.role_display})"
    )

    # Check integrity: does parent Field exist?
    field = fetch_field_by_id(db, value_data.field_id)

    # Security check: is the version editable?
    version = fetch_version_by_id(db, field.entity_version_id)
    validate_version_is_draft(version)

    # Prevent creation of Value for free-value Fields
    if field.is_free_value:
        logger.warning(
            f"Value creation failed: field {field.id} ('{field.name}') is free-value"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Field '{field.name}' (ID {field.id}) is configured as 'Free Value'. "
                "You cannot define pre-set values for it."
            )
        )

    # Value creation
    with db_transaction(db, f"create_value for field {field.id}"):
        new_value = Value(**value_data.model_dump())
        db.add(new_value)
        db.flush()

        logger.info(
            f"Value {new_value.id} created successfully: "
            f"value='{value_data.value}', field={field.id}"
        )

    db.refresh(new_value)
    return new_value


@router.patch("/{value_id}", response_model=ValueRead)
def update_value(
    value_update: ValueUpdate,
    value: Value = Depends(get_editable_value),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Updates an existing Value.

    Restrictions:
        - The version must be DRAFT
        - Cannot move value to a different version (must belong to same version)
        - Cannot move value to a free-value Field

    Access Control:
        - Only ADMIN and AUTHOR can update values

    Returns:
        ValueRead: The updated value
    """
    logger.info(
        f"Updating value {value.id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    parent_field = value.field
    if not parent_field:
        logger.error(f"Value {value.id} has no parent field")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Corrupted Data: Value has no parent Field."
        )

    # If changing the Field_id, validate the new parent Field
    if value_update.field_id is not None and value_update.field_id != value.field_id:
        logger.debug(f"Validating field change from {value.field_id} to {value_update.field_id}")

        new_field = fetch_field_by_id(db, value_update.field_id)

        # Check integrity: cannot move value to a Free Field
        if new_field.is_free_value:
            logger.warning(
                f"Update value {value.id} failed: cannot move to free-value field {new_field.id}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot assign Value to a Field with free value."
            )

        # If new_field does not belong to the same version -> Error
        if new_field.entity_version_id != parent_field.entity_version_id:
            logger.warning(
                f"Update value {value.id} failed: version mismatch "
                f"({parent_field.entity_version_id} vs {new_field.entity_version_id})"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Consistency error: You cannot move a Value to a Field belonging to a different Version. "
                    f"Current Version ID: {parent_field.entity_version_id}, "
                    f"Target Field Version ID: {new_field.entity_version_id}."
                )
            )

    # Apply updates
    update_data = value_update.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning(f"Empty update request for value {value.id}")
        return value

    # Update fields
    with db_transaction(db, f"update_value {value.id}"):
        for key, val in update_data.items():
            setattr(value, key, val)

        logger.info(f"Value {value.id} updated successfully")

    db.refresh(value)
    return value


@router.delete("/{value_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_value(
    value: Value = Depends(get_editable_value),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Delete a Value.

    Strict Policy:
        - Cannot delete if it is the explicit target of a Rule
        - Cannot delete if it is used as a condition criteria in any Rule (deep scan)
        - The version must be DRAFT

    Access Control:
        - Only ADMIN and AUTHOR can delete values

    Returns:
        204 No Content on success
    """
    logger.info(
        f"Deleting value {value.id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    # Validate value is not used in any rules (explicit or implicit)
    validate_value_not_used_in_rules(db, value)

    # Delete value
    with db_transaction(db, f"delete_value {value.id}"):
        value_text = value.value
        db.delete(value)

        logger.info(f"Value {value.id} ('{value_text}') deleted successfully")

    return None
