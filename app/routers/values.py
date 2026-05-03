import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    db_transaction,
    fetch_field_by_id,
    fetch_version_by_id,
    get_editable_value,
    get_value_or_404,
    require_admin_or_author,
    validate_value_not_used_in_rules,
    validate_version_is_draft,
)
from app.models.domain import Rule, RuleType, User, Value
from app.schemas import ValueCreate, ValueRead, ValueUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/values", tags=["Values"])


@router.get("/", response_model=list[ValueRead])
def list_values(
    field_id: int | None = None,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """List Values, optionally filtered by `field_id`. ADMIN/AUTHOR only."""

    limit = min(limit, 100)

    query = db.query(Value)

    if field_id:
        query = query.filter(Value.field_id == field_id)

    values = query.offset(skip).limit(limit).all()

    logger.info(f"Returning {len(values)} values")

    return values


@router.get("/{value_id}", response_model=ValueRead)
def read_value(value: Value = Depends(get_value_or_404), current_user: User = Depends(require_admin_or_author)):
    """Get a Value by id. ADMIN/AUTHOR only."""
    logger.debug(f"Reading value {value.id} by user {current_user.id}")
    return value


@router.post("/", response_model=ValueRead, status_code=status.HTTP_201_CREATED)
def create_value(
    value_data: ValueCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_author)
):
    """Create a Value on a DRAFT version's option-based Field. ADMIN/AUTHOR only.

    Rejects free-value parent Fields with 400.
    """
    logger.info(
        f"Creating value for field {value_data.field_id} by user {current_user.id} (role: {current_user.role_display})"
    )

    # Check integrity: does parent Field exist?
    field = fetch_field_by_id(db, value_data.field_id)

    # Security check: is the version editable?
    version = fetch_version_by_id(db, field.entity_version_id)
    validate_version_is_draft(version)

    # Prevent creation of Value for free-value Fields
    if field.is_free_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Field '{field.name}' (ID {field.id}) is configured as 'Free Value'. "
                "You cannot define pre-set values for it."
            ),
        )

    # Value creation
    with db_transaction(db, f"create_value for field {field.id}"):
        new_value = Value(**value_data.model_dump())
        db.add(new_value)
        db.flush()

        logger.info(f"Value {new_value.id} created successfully: value='{value_data.value}', field={field.id}")

    db.refresh(new_value)
    return new_value


@router.patch("/{value_id}", response_model=ValueRead)
def update_value(
    value_update: ValueUpdate,
    value: Value = Depends(get_editable_value),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Update a Value on a DRAFT version. ADMIN/AUTHOR only.

    Cannot move a Value to a different version, to a free-value Field, or
    rename its `value` string while a CALCULATION rule references it.
    """

    parent_field = value.field
    if not parent_field:
        logger.error(f"Value {value.id} has no parent field")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Corrupted Data: Value has no parent Field."
        )

    # If changing the Field_id, validate the new parent Field
    if value_update.field_id is not None and value_update.field_id != value.field_id:
        logger.debug(f"Validating field change from {value.field_id} to {value_update.field_id}")

        new_field = fetch_field_by_id(db, value_update.field_id)

        # Check integrity: cannot move value to a Free Field
        if new_field.is_free_value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign Value to a Field with free value."
            )

        # If new_field does not belong to the same version -> Error
        if new_field.entity_version_id != parent_field.entity_version_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Consistency error: You cannot move a Value to a Field belonging to a different Version. "
                    f"Current Version ID: {parent_field.entity_version_id}, "
                    f"Target Field Version ID: {new_field.entity_version_id}."
                ),
            )

    # Check CALCULATION rules if value string is being changed
    if value_update.value is not None and value_update.value != value.value:
        calc_rules_count = (
            db.query(Rule)
            .filter(
                Rule.target_field_id == value.field_id,
                Rule.rule_type == RuleType.CALCULATION,
                Rule.set_value == value.value,
            )
            .count()
        )
        if calc_rules_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot change value string '{value.value}' because it is referenced by "
                    f"{calc_rules_count} CALCULATION rule(s) via 'set_value'. "
                    f"Update or delete those rules first."
                ),
            )

    # Apply updates
    update_data = value_update.model_dump(exclude_unset=True)

    if not update_data:
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
    current_user: User = Depends(require_admin_or_author),
):
    """Delete a Value on a DRAFT version (blocked if referenced by any Rule). ADMIN/AUTHOR only."""

    # Validate value is not used in any rules (explicit or implicit)
    validate_value_not_used_in_rules(db, value)

    # Delete value
    with db_transaction(db, f"delete_value {value.id}"):
        value_text = value.value
        db.delete(value)

        logger.info(f"Value {value.id} ('{value_text}') deleted successfully")

    return None
