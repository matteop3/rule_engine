from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Rule, Field, Value
from app.schemas import RuleCreate, RuleRead, RuleUpdate
from .utils import check_version_editable

router = APIRouter(
    prefix="/rules",
    tags=["Rules"]
)

@router.post("/", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(rule_data: RuleCreate, db: Session = Depends(get_db)):
    """
    Creates a new Rule in a DRAFT version.
    Includes validation to ensure target Field and Value belong to 
    the specified Entity Version.
    """

    # Security check: ensure the version is in DRAFT status
    check_version_editable(rule_data.entity_version_id, db)
    
    # Validate target Field belongs to the Version
    target_field = db.query(Field).filter(
        Field.id == rule_data.target_field_id,
        Field.entity_version_id == rule_data.entity_version_id
    ).first()
    
    if not target_field:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Target Field not found in this Version."
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
                detail=f"Target Value {rule_data.target_value_id} not found or does not belong to Field."
            )

    # Create the Rule
    new_rule = Rule(**rule_data.model_dump()) 
    
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    
    return new_rule


@router.get("/", response_model=List[RuleRead])
def read_rules(
    entity_version_id: Optional[int] = None, 
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db)
):
    """
    Retrieve a list of rules. 
    Can filter by entity_version_id (recommended).
    """
    query = db.query(Rule)
    if entity_version_id:
        query = query.filter(Rule.entity_version_id == entity_version_id)
        
    return query.offset(skip).limit(limit).all()


@router.get("/{rule_id}", response_model=RuleRead)
def read_rule(rule_id: int, db: Session = Depends(get_db)):
    """ Retrieve a single Rule. """
    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")
    return rule


@router.put("/{rule_id}", response_model=RuleRead)
def update_rule(rule_id: int, rule_in: RuleUpdate, db: Session = Depends(get_db)):
    """
    Updates an existing Rule.
    Includes validation to ensure target Field and Value belong to the correct Version.
    """
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")

    # Security check: Ensure the Version containing this Rule is editable
    check_version_editable(db_rule.entity_version_id, db)

    # Determine final state of IDs (mix of new input and existing DB data)
    final_version_id = rule_in.entity_version_id if rule_in.entity_version_id is not None else db_rule.entity_version_id
    final_target_field_id = rule_in.target_field_id if rule_in.target_field_id is not None else db_rule.target_field_id
    final_target_value_id = rule_in.target_value_id if rule_in.target_value_id is not None else db_rule.target_value_id

    # Validate consistency (target Field belongs to the Version)
    # If the user is changing the Version or the Field, we must verify the relationship
    if rule_in.entity_version_id or rule_in.target_field_id:
        field_check = db.query(Field).filter(
            Field.id == final_target_field_id,
            Field.entity_version_id == final_version_id
        ).first()
        if not field_check:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Target Field does not belong to the specified Entity Version."
            )

    # Validate consistency (target Value belongs to target Field)
    # If the user is changing the Field or the Value, we must verify the relationship
    if rule_in.target_field_id or rule_in.target_value_id:
        # Note: if target_value_id is None (Rule-level), we skip this check
        if final_target_value_id is not None:
            value_check = db.query(Value).filter(
                Value.id == final_target_value_id,
                Value.field_id == final_target_field_id
            ).first()
            if not value_check:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail="Target Value does not belong to the Target Field."
                )

    # Apply updates
    update_data = rule_in.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(db_rule, key, value)

    db.commit()
    db.refresh(db_rule)
    return db_rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    """ Delete a Rule. """
    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")

    # Security check: ensure the version is editable before deleting
    check_version_editable(db_rule.entity_version_id, db)

    db.delete(db_rule)
    db.commit()
    return None