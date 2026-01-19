import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    require_admin_or_author,
    fetch_version_by_id,
    validate_version_is_draft,
    get_field_or_404,
    get_editable_field,
    db_transaction
)
from app.models.domain import EntityVersion, Field, Value, Rule, User
from app.schemas import FieldCreate, FieldRead, FieldUpdate


# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(
    prefix="/fields",
    tags=["Fields"]
)


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/", response_model=List[FieldRead])
def list_fields(
    entity_version_id: int,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Retrieve Fields for a specific Version.

    Access Control:
        - Only ADMIN and AUTHOR can view fields

    Query Parameters:
        entity_version_id: The version to retrieve fields for (required)
        skip: Pagination offset
        limit: Maximum results (max 100)

    Returns:
        List[FieldRead]: Fields ordered by step and sequence
    """
    logger.info(
        f"Listing fields for version {entity_version_id} by user {current_user.id}: "
        f"skip={skip}, limit={limit}"
    )

    # Cap limit to prevent abuse
    original_limit = limit
    limit = min(limit, 100)

    if original_limit > 100:
        logger.warning(f"Limit capped from {original_limit} to 100")

    fields = db.query(Field)\
        .filter(Field.entity_version_id == entity_version_id)\
        .order_by(Field.step, Field.sequence)\
        .offset(skip).limit(limit).all()

    logger.info(f"Returning {len(fields)} fields for version {entity_version_id}")

    return fields


@router.get("/{field_id}", response_model=FieldRead)
def read_field(
    field: Field = Depends(get_field_or_404),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Retrieve a single Field.

    Access Control:
        - Only ADMIN and AUTHOR can view field details

    Returns:
        FieldRead: The requested field
    """
    logger.debug(f"Reading field {field.id} by user {current_user.id}")
    return field


@router.post("/", response_model=FieldRead, status_code=status.HTTP_201_CREATED)
def create_field(
    field_data: FieldCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Creates a new Field attached to a specific Entity Version.

    Restrictions:
        - The version must be DRAFT
        - default_value on Field is allowed ONLY for free-text fields

    Access Control:
        - Only ADMIN and AUTHOR can create fields

    Returns:
        FieldRead: The created field
    """
    logger.info(
        f"Creating field '{field_data.name}' for version {field_data.entity_version_id} "
        f"by user {current_user.id} (role: {current_user.role_display})"
    )

    # Security check: is the version editable?
    version = fetch_version_by_id(db, field_data.entity_version_id)
    validate_version_is_draft(version)

    # Ensure data consistency: default_value on Field model is allowed ONLY for free-text fields
    if not field_data.is_free_value and field_data.default_value is not None:
        logger.warning(
            f"Field creation failed: attempted to set default_value on non-free field "
            f"'{field_data.name}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You cannot set 'default_value' on the Field object if 'is_free_value' is False. "
                "For non-free fields, please set 'is_default=True' on the specific Value object instead."
            )
        )

    # Create Field
    with db_transaction(db, f"create_field '{field_data.name}' for version {version.id}"):
        new_field = Field(**field_data.model_dump())
        db.add(new_field)
        db.flush()

        logger.info(
            f"Field {new_field.id} created successfully: name='{field_data.name}', "
            f"is_free_value={field_data.is_free_value}"
        )

    db.refresh(new_field)
    return new_field


@router.patch("/{field_id}", response_model=FieldRead)
def update_field(
    field_update: FieldUpdate,
    field: Field = Depends(get_editable_field),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Update a Field.

    Restrictions:
        - The version must be DRAFT
        - Cannot change is_free_value from False to True if field has Values
        - Cannot set default_value when switching to non-free field

    Access Control:
        - Only ADMIN and AUTHOR can update fields

    Returns:
        FieldRead: The updated field
    """
    logger.info(
        f"Updating field {field.id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    # State transition analysis
    old_is_free = field.is_free_value
    new_is_free = field_update.is_free_value

    # SCENARIO A: from Field with a data source to a free Field
    if not old_is_free and new_is_free:
        # Check integrity: are there any related values?
        existing_values_count = db.query(Value).filter(Value.field_id == field.id).count()

        if existing_values_count > 0:
            logger.warning(
                f"Update field {field.id} failed: cannot change to free value "
                f"with {existing_values_count} associated values"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot change 'is_free_value' to True because this field has associated Values. "
                    "Please delete all Values (and related Rules) associated with this field first."
                )
            )

    # SCENARIO B: from free Field to a Field with a data source
    # Ensure the DB is cleaned of any old default_value
    force_default_reset = False
    if old_is_free and not new_is_free:
        # Non-free fields do not use Field.default_value
        if field_update.default_value is not None:
            logger.warning(
                f"Update field {field.id} failed: attempted to set default_value "
                f"when switching to non-free field"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set 'default_value' when switching to a non-free field. "
                       "Use Value.is_default instead."
            )
        # Flag to force cleanup later
        force_default_reset = True

    # Apply updates
    update_data = field_update.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning(f"Empty update request for field {field.id}")
        return field

    # If switching from free to non-free, explicitly overwrite DB default_value to None
    if force_default_reset:
        update_data['default_value'] = None

    # Update all fields
    with db_transaction(db, f"update_field {field.id}"):
        for key, value in update_data.items():
            setattr(field, key, value)

        logger.info(f"Field {field.id} updated successfully")

    db.refresh(field)
    return field


@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(
    field: Field = Depends(get_editable_field),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Delete a Field.

    Strict Policy:
        - Cannot delete if it has Values
        - Cannot delete if it is the target of a Rule
        - Cannot delete if it is used as a condition inside any Rule of the same Entity
        - The version must be DRAFT

    Access Control:
        - Only ADMIN and AUTHOR can delete fields

    Returns:
        204 No Content on success
    """
    logger.info(
        f"Deleting field {field.id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    # Guardrail: check for Values
    values_count = db.query(Value).filter(Value.field_id == field.id).count()
    if values_count > 0:
        logger.warning(
            f"Delete field {field.id} failed: has {values_count} associated values"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Field because it has {values_count} associated Values."
        )

    # Guardrail: check for Rules targeting this field
    rules_targeting_field = db.query(Rule).filter(Rule.target_field_id == field.id).count()
    if rules_targeting_field > 0:
        logger.warning(
            f"Delete field {field.id} failed: is target of {rules_targeting_field} rules"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Field because it is the target of {rules_targeting_field} Rules."
        )

    # Deep scan: check usage in JSON conditions (implicit relation)
    # Retrieve all Entity Rules
    entity_rules = db.query(Rule).filter(
        Rule.entity_version_id == field.entity_version_id
    ).all()

    for rule in entity_rules:
        # Expected structure: {"criteria": [{"field_id": 1, ...}, ...]}
        criteria_list = rule.conditions.get("criteria", [])

        for criterion in criteria_list:
            # If the Field ID is found inside the Rule criterion...
            if criterion.get("field_id") == field.id:
                logger.warning(
                    f"Delete field {field.id} failed: used in rule {rule.id} conditions"
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot delete Field because it is used as a condition criteria "
                        f"in Rule ID {rule.id} (Target Field ID: {rule.target_field_id}). "
                        "Please update or delete that rule first."
                    )
                )

    # Delete field
    with db_transaction(db, f"delete_field {field.id}"):
        field_name = field.name
        db.delete(field)

        logger.info(f"Field {field.id} ('{field_name}') deleted successfully")

    return None
