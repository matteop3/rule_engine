from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Field, Entity, Value
from app.schemas import FieldCreate, FieldRead, FieldUpdate

router = APIRouter(
    prefix="/fields",
    tags=["Fields"]
)

@router.post("/", response_model=FieldRead, status_code=status.HTTP_201_CREATED)
def create_field(field_data: FieldCreate, db: Session = Depends(get_db)):
    """Create a new Field linked to an existing Entity."""
    # Integrity check: does the parent Entity exist?
    entity = db.query(Entity).filter(Entity.id == field_data.entity_id).first()
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Entity with id {field_data.entity_id} not found"
        )
    
    # Ensure data consistency: default_value on Field model is allowed ONLY for free-text fields.
    if not field_data.is_free_value and field_data.default_value is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You cannot set 'default_value' on the Field object if 'is_free_value' is False. "
                "For non-free fields, please set 'is_default=True' on the specific Value object instead."
            )
        )

    # Field creation
    new_field = Field(**field_data.model_dump()) # Convert Pydantic schema into a dictionary
    
    db.add(new_field)
    db.commit()
    db.refresh(new_field)
    
    return new_field

@router.get("/", response_model=List[FieldRead])
def read_fields(
    entity_id: Optional[int] = None, 
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db)
):
    """
    Retrieve fields (optionally related to an Entity).
    """
    query = db.query(Field)
    
    if entity_id:
        query = query.filter(Field.entity_id == entity_id)
        
    return query.offset(skip).limit(limit).all()

@router.put("/{field_id}", response_model=FieldRead)
def update_field(field_id: int, field_update: FieldUpdate, db: Session = Depends(get_db)):
    # Read Field from DB
    db_field = db.query(Field).filter(Field.id == field_id).first()
    if not db_field:
        raise HTTPException(status_code=404, detail="Field not found")

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
        
        # Do not clear the default_value here, otherwise 
        # if the user has passed one it will be blanked.

    # SCENARIO B: from free Field to a Field with a data source
    if old_is_free and not new_is_free:
        # Non-free fields do not use Field.default_value
        if field_update.default_value is not None:
             raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot set 'default_value' when switching to a non-free field. Use Value.is_default instead."
            )

    # Apply updates (update only received fields, I 
    # prefer a non-strict PUT that acts also as a PATCH)
    update_data = field_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(db_field, key, value)

    db.commit()
    db.refresh(db_field)
    return db_field