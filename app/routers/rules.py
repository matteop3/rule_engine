from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Rule, Entity, Field, Value
from app.schemas import RuleCreate, RuleRead

router = APIRouter(
    prefix="/rules",
    tags=["Rules"]
)

@router.post("/", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(rule_data: RuleCreate, db: Session = Depends(get_db)):
    """
    Creates a new Rule defining availability logic for a specific target Value.
    Includes validation to ensure the target Field and Value belong to the specified Entity.
    """
    
    # Check Entity existence
    entity = db.query(Entity).filter(Entity.id == rule_data.entity_id).first()
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Entity with id {rule_data.entity_id} not found"
        )

    # Check Target Field existence and ownership
    # The target field must belong to the entity declared in the rule
    target_field = db.query(Field).filter(
        Field.id == rule_data.target_field_id,
        Field.entity_id == rule_data.entity_id
    ).first()
    
    if not target_field:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Target Field {rule_data.target_field_id} not found or does not belong to Entity {rule_data.entity_id}"
        )

    # Check target Value existence and ownership
    # The target Value must belong to the target Field
    target_value = db.query(Value).filter(
        Value.id == rule_data.target_value_id,
        Value.field_id == rule_data.target_field_id
    ).first()

    if not target_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Target Value {rule_data.target_value_id} not found or does not belong to Field {rule_data.target_field_id}"
        )

    # Create the Rule
    new_rule = Rule(**rule_data.model_dump()) # Convert Pydantic schema into a dictionary
    
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    
    return new_rule

@router.get("/", response_model=List[RuleRead])
def read_rules(
    entity_id: Optional[int] = None, 
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db)
):
    """Retrieve a list of rules. Eventually by filtering by entity_id."""
    query = db.query(Rule)
    
    if entity_id:
        query = query.filter(Rule.entity_id == entity_id)
        
    return query.offset(skip).limit(limit).all()