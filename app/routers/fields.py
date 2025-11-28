from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Field, Entity
from app.schemas import FieldCreate, FieldRead

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