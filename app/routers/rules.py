import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    require_admin_or_author,
    fetch_version_by_id,
    validate_version_is_draft,
    validate_field_belongs_to_version,
    validate_value_belongs_to_field,
    get_rule_or_404,
    get_editable_rule,
    db_transaction
)
from app.models.domain import Rule, Field, Value, User
from app.schemas import RuleCreate, RuleRead, RuleUpdate


# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(
    prefix="/rules",
    tags=["Rules"]
)


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/", response_model=List[RuleRead])
def list_rules(
    entity_version_id: Optional[int] = None,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Retrieve a list of Rules.

    Access Control:
        - Only ADMIN and AUTHOR can view rules

    Query Parameters:
        entity_version_id: Filter by version (optional but recommended)
        skip: Pagination offset
        limit: Maximum results (max 100)

    Returns:
        List[RuleRead]: List of rules
    """
    logger.info(
        f"Listing rules by user {current_user.id}: "
        f"version={entity_version_id}, skip={skip}, limit={limit}"
    )

    # Cap limit to prevent abuse
    original_limit = limit
    limit = min(limit, 100)

    if original_limit > 100:
        logger.warning(f"Limit capped from {original_limit} to 100")

    query = db.query(Rule)
    if entity_version_id:
        query = query.filter(Rule.entity_version_id == entity_version_id)

    rules = query.offset(skip).limit(limit).all()

    logger.info(f"Returning {len(rules)} rules")

    return rules


@router.get("/{rule_id}", response_model=RuleRead)
def read_rule(
    rule: Rule = Depends(get_rule_or_404),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Retrieve a single Rule.

    Access Control:
        - Only ADMIN and AUTHOR can view rule details

    Returns:
        RuleRead: The requested rule
    """
    logger.debug(f"Reading rule {rule.id} by user {current_user.id}")
    return rule


@router.post("/", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(
    rule_data: RuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Creates a new Rule in a DRAFT version.

    Restrictions:
        - The version must be DRAFT
        - Target Field must belong to the specified Version
        - Target Value (if specified) must belong to the Target Field

    Access Control:
        - Only ADMIN and AUTHOR can create rules

    Returns:
        RuleRead: The created rule
    """
    logger.info(
        f"Creating rule for version {rule_data.entity_version_id} "
        f"by user {current_user.id} (role: {current_user.role_display})"
    )

    # Security check: is the version editable?
    version = fetch_version_by_id(db, rule_data.entity_version_id)
    validate_version_is_draft(version)

    # Validate target Field belongs to the Version
    validate_field_belongs_to_version(db, rule_data.target_field_id, rule_data.entity_version_id)

    # Check target Value existence and ownership (if specified)
    if rule_data.target_value_id is not None:
        validate_value_belongs_to_field(db, rule_data.target_value_id, rule_data.target_field_id)

    # Create the Rule
    with db_transaction(db, f"create_rule for version {version.id}"):
        new_rule = Rule(**rule_data.model_dump())
        db.add(new_rule)
        db.flush()

        logger.info(
            f"Rule {new_rule.id} created successfully: "
            f"target_field={rule_data.target_field_id}, target_value={rule_data.target_value_id}"
        )

    db.refresh(new_rule)
    return new_rule


@router.patch("/{rule_id}", response_model=RuleRead)
def update_rule(
    rule_update: RuleUpdate,
    rule: Rule = Depends(get_editable_rule),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Updates an existing Rule.

    Restrictions:
        - The version must be DRAFT
        - Cannot change entity_version_id (rules belong strictly to their creation version)
        - New target Field must belong to the same Version
        - New target Value must belong to the new target Field

    Access Control:
        - Only ADMIN and AUTHOR can update rules

    Returns:
        RuleRead: The updated rule
    """
    logger.info(
        f"Updating rule {rule.id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    # The Version must be immutable
    final_version_id = rule.entity_version_id

    # Determine final state of IDs (mix of new input and existing DB data)
    final_target_field_id = rule_update.target_field_id if rule_update.target_field_id is not None else rule.target_field_id
    final_target_value_id = rule_update.target_value_id if rule_update.target_value_id is not None else rule.target_value_id

    # Validate target Field consistency (if being changed)
    if rule_update.target_field_id is not None and rule_update.target_field_id != rule.target_field_id:
        logger.debug(f"Validating new target field {final_target_field_id}")
        validate_field_belongs_to_version(db, final_target_field_id, final_version_id)

    # Validate target Value consistency (if Field or Value is being changed)
    if rule_update.target_field_id or rule_update.target_value_id:
        # Check only if a target Value is set (Rule-level vs Value-level)
        if final_target_value_id is not None:
            logger.debug(f"Validating target value {final_target_value_id} belongs to field {final_target_field_id}")
            validate_value_belongs_to_field(db, final_target_value_id, final_target_field_id)

    # Apply updates
    update_data = rule_update.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning(f"Empty update request for rule {rule.id}")
        return rule

    # Update fields
    with db_transaction(db, f"update_rule {rule.id}"):
        for key, value in update_data.items():
            setattr(rule, key, value)

        logger.info(f"Rule {rule.id} updated successfully")

    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule: Rule = Depends(get_editable_rule),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Delete a Rule.

    Restrictions:
        - The version must be DRAFT

    Access Control:
        - Only ADMIN and AUTHOR can delete rules

    Returns:
        204 No Content on success
    """
    logger.info(
        f"Deleting rule {rule.id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    # Delete rule
    with db_transaction(db, f"delete_rule {rule.id}"):
        db.delete(rule)

        logger.info(f"Rule {rule.id} deleted successfully")

    return None
