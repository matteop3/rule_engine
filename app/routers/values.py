from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Value, Field, Rule
from app.schemas import ValueCreate, ValueRead,  ValueUpdate

router = APIRouter(
    prefix="/values",
    tags=["Values"]
)

@router.post("/", response_model=ValueRead, status_code=status.HTTP_201_CREATED)
def create_value(value_data: ValueCreate, db: Session = Depends(get_db)):
    """Create a new Value related to a Field."""
    # Check integrity: does parent Field exist?
    field = db.query(Field).filter(Field.id == value_data.field_id).first()
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Field with id {value_data.field_id} not found"
        )

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
    new_value = Value(**value_data.model_dump()) # Convert Pydantic schema into a dictionary
    
    db.add(new_value)
    db.commit()
    db.refresh(new_value)
    
    return new_value


@router.get("/", response_model=List[ValueRead])
def read_values(
    field_id: Optional[int] = None, 
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db)
):
    """Retrieve the values of a Field"""
    query = db.query(Value)
    
    if field_id:
        query = query.filter(Value.field_id == field_id)
        
    return query.offset(skip).limit(limit).all()


@router.put("/{value_id}", response_model=ValueRead)
def update_value(value_id: int, value_in: ValueUpdate, db: Session = Depends(get_db)):
    """ Updates an existing Value. """
    db_value = db.query(Value).filter(Value.id == value_id).first()
    if not db_value:
        raise HTTPException(status_code=404, detail="Value not found")

    # If changing the field_id, validate the new parent field
    if value_in.field_id is not None and value_in.field_id != db_value.field_id:
        new_field = db.query(Field).filter(Field.id == value_in.field_id).first()
        if not new_field:
            raise HTTPException(status_code=404, detail="New Field not found")
        
        # Check integrity: cannot move value to a Free Field
        if new_field.is_free_value:
            raise HTTPException(
                status_code=400, 
                detail="Cannot assign Value to a Field with a free value."
            )

    # Apply updates (update only received fields, I 
    # prefer a non-strict PUT that acts also as a PATCH)
    update_data = value_in.model_dump(exclude_unset=True)

    # Update all fields
    for key, value in update_data.items():
        setattr(db_value, key, value)

    # Save
    db.commit()
    db.refresh(db_value)
    return db_value


@router.delete("/{value_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_value(value_id: int, db: Session = Depends(get_db)):
    """
    Delete a Value.
    Strict policy: 
    1. Cannot delete if it is the explicit target of a Rule.
    2. Cannot delete if it is used as a condition criteria in any Rule (deep scan).
    """
    db_value = db.query(Value).filter(Value.id == value_id).first()
    if not db_value:
        raise HTTPException(status_code=404, detail="Value not found")

    parent_field = db_value.field 
    if not parent_field:
        raise HTTPException(status_code=500, detail="Corrupted Data: Value has no parent Field")

    # Check for Rules targeting this value explicitly (target)
    rules_targeting_value = db.query(Rule).filter(Rule.target_value_id == value_id).count()
    if rules_targeting_value > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Value because it is the explicit target of {rules_targeting_value} Rules."
        )

    # Deep scan: check usage in JSON conditions (implicit ssage)
    # Fetch all rules belonging to the same Entity to scan their criteria.
    entity_rules = db.query(Rule).filter(Rule.entity_id == parent_field.entity_id).all()
    
    value_str_to_check = str(db_value.value) # Normalize to string for comparison

    for rule in entity_rules:
        criteria_list = rule.conditions.get("criteria", [])
        
        for criterion in criteria_list:
            # Check context: does this criterion refer to the same Field ID?
            crit_field_id = criterion.get("field_id")
            
            if crit_field_id == db_value.field_id:
                # Check content: does the value string match?
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