from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Rule, Entity, Field, Value
from app.schemas import RuleCreate, RuleRead, RuleUpdate

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
    # The target Value must belong to the target Field (if specified)
    if rule_data.target_value_id is not None:
        target_value = db.query(Value).filter(
            Value.id == rule_data.target_value_id,
            Value.field_id == rule_data.target_field_id
        ).first()

        if not target_value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Target Value {rule_data.target_value_id} not found or does not belong to Field"
            )

    # Create the Rule
    new_rule = Rule(**rule_data.model_dump()) # Convert Pydantic schema into a dictionary
    
    # Save
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


@router.put("/{rule_id}", response_model=RuleRead)
def update_rule(rule_id: int, rule_in: RuleUpdate, db: Session = Depends(get_db)):
    """
    Updates an existing Rule.
    Includes validation to ensure target Field and Value belong to the Entity.
    """
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Determine final state of IDs (mix of new input and existing DB data)
    final_entity_id = rule_in.entity_id if rule_in.entity_id is not None else db_rule.entity_id
    final_target_field_id = rule_in.target_field_id if rule_in.target_field_id is not None else db_rule.target_field_id
    final_target_value_id = rule_in.target_value_id if rule_in.target_value_id is not None else db_rule.target_value_id

    # Check if Entity exists (if changed)
    if rule_in.entity_id is not None:
         entity = db.query(Entity).filter(Entity.id == final_entity_id).first()
         if not entity:
             raise HTTPException(status_code=404, detail="Entity not found")

    # Validate consistency (target Field belongs to Entity)
    if rule_in.entity_id or rule_in.target_field_id:
        field_check = db.query(Field).filter(
            Field.id == final_target_field_id,
            Field.entity_id == final_entity_id
        ).first()
        if not field_check:
            raise HTTPException(status_code=400, detail="Target Field does not belong to the specified Entity")

    # Validate consistency (target Value belongs to target Field)
    if rule_in.target_field_id or rule_in.target_value_id:
        value_check = db.query(Value).filter(
            Value.id == final_target_value_id,
            Value.field_id == final_target_field_id
        ).first()
        if not value_check:
            raise HTTPException(status_code=400, detail="Target Value does not belong to the target Field")

    # Apply updates (update only received fields, I 
    # prefer a non-strict PUT that acts also as a PATCH)
    update_data = rule_in.model_dump(exclude_unset=True)

    # Update all fields
    for key, value in update_data.items():
        setattr(db_rule, key, value)

    # Save
    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    """ Delete a Rule. """
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    db.delete(db_rule)
    db.commit()
    return None