from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import Rule, Field, Value, User, UserRole
from app.schemas import RuleCreate, RuleRead, RuleUpdate
from app.dependencies import fetch_version_by_id, get_editable_version

router = APIRouter(
    prefix="/rules",
    tags=["Rules"]
)

@router.post("/", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(
    rule_data: RuleCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Creates a new Rule in a DRAFT version.
    Includes validation to ensure target Field and Value belong to 
    the specified Entity Version.
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    # Security check: is the version editable?
    version = fetch_version_by_id(db, rule_data.entity_version_id)
    get_editable_version(version)
    
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Retrieve a list of rules. 
    Can filter by entity_version_id (recommended).
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    query = db.query(Rule)
    if entity_version_id:
        query = query.filter(Rule.entity_version_id == entity_version_id)
        
    return query.offset(skip).limit(limit).all()


@router.get("/{rule_id}", response_model=RuleRead)
def read_rule(
    rule_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Retrieve a single Rule. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")
    
    return rule


@router.patch("/{rule_id}", response_model=RuleRead)
def update_rule(
    rule_id: int, 
    rule_in: RuleUpdate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Updates an existing Rule.
    Includes validation to ensure target Field and Value belong to the correct Version.
    Note: Changing 'entity_version_id' is forbidden. Rules belongs strictly to their creation version.
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")

    # Security check: is the version editable?
    version = fetch_version_by_id(db, db_rule.entity_version_id)
    get_editable_version(version)

    # The Version must be immutable
    final_version_id = db_rule.entity_version_id

    # Determine final state of IDs (mix of new input and existing DB data)
    final_target_field_id = rule_in.target_field_id if rule_in.target_field_id is not None else db_rule.target_field_id
    final_target_value_id = rule_in.target_value_id if rule_in.target_value_id is not None else db_rule.target_value_id
    
    # Validate target Field consistency
    # If the user is changing the Field, we must verify it belongs to the same Rule's Version.
    should_validate_field = (
        rule_in.target_field_id is not None and 
        rule_in.target_field_id != db_rule.target_field_id
    )

    if should_validate_field:
        field_check = db.query(Field).filter(
            Field.id == final_target_field_id,
            Field.entity_version_id == final_version_id
        ).first()
        
        if not field_check:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"New Target Field (ID {final_target_field_id}) does not belong to the Entity Version of this Rule (ID {final_version_id})."
            )
    
    # Validate target Value consistency
    # If the user is changing the Field or the Value, we must verify the relationship Value -> Field
    if rule_in.target_field_id or rule_in.target_value_id:
        # Check only if a target Value is set (Rule-level vs Value-level)
        if final_target_value_id is not None:
            value_check = db.query(Value).filter(
                Value.id == final_target_value_id,
                Value.field_id == final_target_field_id
            ).first()
            
            if not value_check:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail=f"Target Value (ID {final_target_value_id}) does not belong to the Target Field (ID {final_target_field_id})."
                )

    # Apply updates
    update_data = rule_in.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(db_rule, key, value)

    db.commit()
    db.refresh(db_rule)

    return db_rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Delete a Rule. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    db_rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found.")

    # Security check: is the version editable?
    version = fetch_version_by_id(db, db_rule.entity_version_id)
    get_editable_version(version)

    db.delete(db_rule)
    db.commit()
    
    return None