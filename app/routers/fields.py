from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import EntityVersion, Field, Value, Rule, User, UserRole
from app.schemas import FieldCreate, FieldRead, FieldUpdate
from app.dependencies import fetch_version_by_id, get_editable_version

router = APIRouter(
    prefix="/fields",
    tags=["Fields"]
)


# ============================================================
# CRUD endpoints
# ============================================================

@router.get("/", response_model=List[FieldRead])
def read_fields(
    entity_version_id: int, # Required: fields always belong to a version context
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Retrieve Fields for a specific Version.
    Ordered by step and sequence.
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    fields = db.query(Field)\
        .filter(Field.entity_version_id == entity_version_id)\
        .order_by(Field.step, Field.sequence)\
        .offset(skip).limit(limit).all()
    
    return fields


@router.get("/{field_id}", response_model=FieldRead)
def read_field(
    field_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Retrieve a single Field. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    field = db.query(Field).filter(Field.id == field_id).first()
    if not field:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found.")
    
    return field


@router.post("/", response_model=FieldRead, status_code=status.HTTP_201_CREATED)
def create_field(
    field_data: FieldCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Creates a new Field attached to a specific Entity Version.
    Protected: The version must be DRAFT.
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    # Security check: is the version editable?
    version = fetch_version_by_id(db, field_data.entity_version_id)
    get_editable_version(version)

    # Ensure data consistency: default_value on Field model is allowed ONLY for free-text fields.
    if not field_data.is_free_value and field_data.default_value is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You cannot set 'default_value' on the Field object if 'is_free_value' is False. "
                "For non-free fields, please set 'is_default=True' on the specific Value object instead."
            )
        )

    # Create Field
    new_field = Field(**field_data.model_dump())
    
    # Save
    db.add(new_field)
    db.commit()
    db.refresh(new_field)
    
    return new_field

@router.put("/{field_id}", response_model=FieldRead)
def update_field(
    field_id: int, 
    field_update: FieldUpdate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    db_field = db.query(Field).filter(Field.id == field_id).first()
    if not db_field:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found.")

    # Security check: is the parent version editable?
    version = fetch_version_by_id(db, db_field.entity_version_id)
    get_editable_version(version)

    # State transition analysis
    old_is_free = db_field.is_free_value
    new_is_free = field_update.is_free_value

    # SCENARIO A: from Field with a data ource to a free Field
    if not old_is_free and new_is_free:
        # Check integrity: are there any related values?
        existing_values_count = db.query(Value).filter(Value.field_id == field_id).count()
        
        if existing_values_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot change 'is_free_value' to True because this field has associated Values. "
                    "Please delete all Values (and related Rules) associated with this field first."
                )
            )
        
        # Do not clear the default_value here, otherwise if the user has passed one it will be blanked.

    # SCENARIO B: from free Field to a Field with a data source
    # Ensure the DB is cleaned of any old default_value
    force_default_reset = False
    if old_is_free and not new_is_free:
        # Non-free fields do not use Field.default_value
        if field_update.default_value is not None:
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set 'default_value' when switching to a non-free field. Use Value.is_default instead."
            )
        # Flag to force cleanup later
        force_default_reset = True

    # Apply updates (update only received fields, I 
    # prefer a non-strict PUT that acts also as a PATCH)
    update_data = field_update.model_dump(exclude_unset=True)

    # If switching from a Field with a free value to a  Field with a 
    # data source, explicitly overwrite DB default_value to None
    if force_default_reset:
        update_data['default_value'] = None
    
    # Update all fields
    for key, value in update_data.items():
        setattr(db_field, key, value)

    # Save
    db.commit()
    db.refresh(db_field)

    return db_field

@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(
    field_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Delete a Field.
    Strict policy: 
    1. Cannot delete if it has Values.
    2. Cannot delete if it is the target of a Rule.
    3. Cannot delete if it is used as a condition inside any Rule of the same Entity.
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    db_field = db.query(Field).filter(Field.id == field_id).first()
    if not db_field:
        raise HTTPException(status_code=404, detail="Field not found.")

    # Security check: is the version editable?
    version = fetch_version_by_id(db, db_field.entity_version_id)
    get_editable_version(version)

    # Guardrail: check for Values
    values_count = db.query(Value).filter(Value.field_id == field_id).count()
    if values_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Field because it has {values_count} associated Values."
        )

    # Guardrail: check for Rules targeting this field
    rules_targeting_field = db.query(Rule).filter(Rule.target_field_id == field_id).count()
    if rules_targeting_field > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Field because it is the target of {rules_targeting_field} Rules."
        )
    
    # Deep scan: check usage in JSON conditions (implicit relation)
    # Retrive all Entity Rules
    entity_rules = db.query(Rule).filter(Rule.entity_version_id == db_field.entity_version_id).all()
    
    for rule in entity_rules:
        # Expected structure: {"criteria": [{"field_id": 1, ...}, ...]}
        criteria_list = rule.conditions.get("criteria", [])
        
        for criterion in criteria_list:
            # If the Field ID is found inside the Rule criterion...
            if criterion.get("field_id") == field_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot delete Field because it is used as a condition criteria "
                        f"in Rule ID {rule.id} (Target Field ID: {rule.target_field_id}). "
                        "Please update or delete that rule first."
                    )
                )

    db.delete(db_field)
    db.commit()

    return None