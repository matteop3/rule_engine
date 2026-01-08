from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import Value, Field, Rule, User, UserRole
from app.schemas import ValueCreate, ValueRead, ValueUpdate
from .utils import check_version_editable

router = APIRouter(
    prefix="/values",
    tags=["Values"]
)

@router.post("/", response_model=ValueRead, status_code=status.HTTP_201_CREATED)
def create_value(
    value_data: ValueCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Create a new Value related to a Field. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    # Check integrity: does parent Field exist?
    field = db.query(Field).filter(Field.id == value_data.field_id).first()
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Field with id {value_data.field_id} not found."
        )

    # Security check: is the Version containing this Field editable?
    check_version_editable(field.entity_version_id, db)

    # Prevent the creation of the Value if I am associating it with a free-value Field
    if field.is_free_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Field '{field.name}' (ID {field.id}) is configured as 'Free Value'. "
                "You cannot define pre-set values for it."
            )
        )

    # Value creation
    new_value = Value(**value_data.model_dump()) 
    
    db.add(new_value)
    db.commit()
    db.refresh(new_value)
    
    return new_value


@router.get("/", response_model=List[ValueRead])
def read_values(
    field_id: Optional[int] = None, 
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Retrieve the values of a Field. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    query = db.query(Value)
    
    if field_id:
        query = query.filter(Value.field_id == field_id)
        
    return query.offset(skip).limit(limit).all()


@router.get("/{value_id}", response_model=ValueRead)
def read_value(
    value_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Retrieve a single Value. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    value = db.query(Value).filter(Value.id == value_id).first()
    if not value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Value not found.")
    return value


@router.put("/{value_id}", response_model=ValueRead)
def update_value(
    value_id: int, 
    value_in: ValueUpdate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Updates an existing Value. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    db_value = db.query(Value).filter(Value.id == value_id).first()
    if not db_value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Value not found.")

    # To check security, we need the parent field to access the entity_version_id
    parent_field = db_value.field
    if not parent_field:
        # Should not happen if DB integrity is preserved
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Corrupted Data: Value has no parent Field."
        )

    # Security check
    check_version_editable(parent_field.entity_version_id, db)

    # If changing the Field_id, validate the new parent Field
    if value_in.field_id is not None and value_in.field_id != db_value.field_id:
        new_field = db.query(Field).filter(Field.id == value_in.field_id).first()
        if not new_field:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="New Field not found."
            )
        
        # Check integrity: cannot move value to a Free Field
        if new_field.is_free_value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Cannot assign Value to a Field with a free value."
            )

        # If new_field does not belongs to the same version -> Error
        if new_field.entity_version_id != parent_field.entity_version_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Consistency error: You cannot move a Value to a Field belonging to a different Version. "
                    f"Current Version ID: {parent_field.entity_version_id}, "
                    f"Target Field Version ID: {new_field.entity_version_id}."
                )
            )

    # Apply updates
    update_data = value_in.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(db_value, key, value)

    # Save
    db.commit()
    db.refresh(db_value)

    return db_value


@router.delete("/{value_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_value(
    value_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Delete a Value.
    Strict policy: 
    1. Cannot delete if it is the explicit target of a Rule.
    2. Cannot delete if it is used as a condition criteria in any Rule (deep scan).
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    db_value = db.query(Value).filter(Value.id == value_id).first()
    if not db_value:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Value not found."
        )

    parent_field = db_value.field 
    if not parent_field:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Corrupted Data: Value has no parent Field."
        )

    # Security check
    check_version_editable(parent_field.entity_version_id, db)

    # Check for Rules targeting this value explicitly (target)
    rules_targeting_value = db.query(Rule).filter(Rule.target_value_id == value_id).count()
    if rules_targeting_value > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Value because it is the explicit target of {rules_targeting_value} Rules."
        )

    # Deep scan: check usage in JSON conditions (implicit usage)
    entity_rules = db.query(Rule).filter(
        Rule.entity_version_id == parent_field.entity_version_id
    ).all()
    
    value_str_to_check = str(db_value.value) 

    for rule in entity_rules:
        criteria_list = rule.conditions.get("criteria", [])
        
        for criterion in criteria_list:
            crit_field_id = criterion.get("field_id")
            
            if crit_field_id == db_value.field_id:
                crit_value = str(criterion.get("value", ""))
                
                if crit_value == value_str_to_check:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Cannot delete Value '{db_value.value}' because it is used as a condition criteria "
                            f"in Rule ID {rule.id}. Please update or delete that rule first."
                        )
                    )

    # If all checks pass
    db.delete(db_value)
    db.commit()

    return None