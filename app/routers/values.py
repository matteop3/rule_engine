from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Value, Field
from app.schemas import ValueCreate, ValueRead

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