import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    db_transaction,
    fetch_version_by_id,
    get_editable_rule,
    get_rule_or_404,
    require_admin_or_author,
    validate_field_belongs_to_version,
    validate_value_belongs_to_field,
    validate_version_is_draft,
)
from app.models.domain import Field, Rule, RuleType, User, Value
from app.schemas import RuleCreate, RuleRead, RuleUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rules", tags=["Rules"])


@router.get("/", response_model=list[RuleRead])
def list_rules(
    entity_version_id: int | None = None,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """List Rules, optionally filtered by `entity_version_id`. ADMIN/AUTHOR only."""

    limit = min(limit, 100)

    query = db.query(Rule)
    if entity_version_id:
        query = query.filter(Rule.entity_version_id == entity_version_id)

    rules = query.offset(skip).limit(limit).all()

    logger.info(f"Returning {len(rules)} rules")

    return rules


@router.get("/{rule_id}", response_model=RuleRead)
def read_rule(rule: Rule = Depends(get_rule_or_404), current_user: User = Depends(require_admin_or_author)):
    """Get a Rule by id. ADMIN/AUTHOR only."""
    logger.debug(f"Reading rule {rule.id} by user {current_user.id}")
    return rule


@router.post("/", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(
    rule_data: RuleCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_author)
):
    """Create a Rule on a DRAFT version. ADMIN/AUTHOR only.

    Validates that the target Field belongs to the version, the target Value
    (if any) belongs to the Field, and that CALCULATION `set_value` matches a
    defined `Value` for option-based fields.
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

    # Validate set_value against field's defined Values (CALCULATION on non-free fields)
    if rule_data.rule_type == RuleType.CALCULATION and rule_data.set_value is not None:
        target_field = db.query(Field).filter(Field.id == rule_data.target_field_id).first()
        if target_field and not target_field.is_free_value:
            valid_values = db.query(Value.value).filter(Value.field_id == target_field.id).all()
            valid_value_strings = [v[0] for v in valid_values]
            if rule_data.set_value not in valid_value_strings:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Consistency error: 'set_value' ('{rule_data.set_value}') is not among the "
                        f"defined Values for field '{target_field.name}' (ID {target_field.id}). "
                        f"Valid values: {valid_value_strings}."
                    ),
                )

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
    current_user: User = Depends(require_admin_or_author),
):
    """Update a Rule on a DRAFT version. ADMIN/AUTHOR only.

    `entity_version_id` is immutable; target Field/Value changes are
    re-validated; `error_message` is only valid for VALIDATION rules and
    `set_value` only for CALCULATION rules.
    """

    # The Version must be immutable
    final_version_id = rule.entity_version_id

    # Determine final state of IDs (mix of new input and existing DB data)
    final_target_field_id = (
        rule_update.target_field_id if rule_update.target_field_id is not None else rule.target_field_id
    )
    final_target_value_id = (
        rule_update.target_value_id if rule_update.target_value_id is not None else rule.target_value_id
    )

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

    # Validate error_message consistency
    # When error_message is provided, the final rule_type must be VALIDATION
    if rule_update.error_message is not None:
        final_rule_type = rule_update.rule_type if rule_update.rule_type is not None else rule.rule_type
        if final_rule_type != RuleType.VALIDATION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Consistency error: 'error_message' is only allowed for rule_type"
                    f" 'validation'. Got '{final_rule_type}'."
                ),
            )

    # Validate set_value consistency
    if rule_update.set_value is not None:
        final_rule_type = rule_update.rule_type if rule_update.rule_type is not None else rule.rule_type
        if final_rule_type != RuleType.CALCULATION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Consistency error: 'set_value' is only allowed for rule_type"
                    f" 'calculation'. Got '{final_rule_type}'."
                ),
            )

    # Validate set_value against field's defined Values (CALCULATION on non-free fields)
    final_rule_type = rule_update.rule_type if rule_update.rule_type is not None else rule.rule_type
    final_set_value = rule_update.set_value if rule_update.set_value is not None else rule.set_value
    if final_rule_type == RuleType.CALCULATION and final_set_value is not None:
        target_field = db.query(Field).filter(Field.id == final_target_field_id).first()
        if target_field and not target_field.is_free_value:
            valid_values = db.query(Value.value).filter(Value.field_id == target_field.id).all()
            valid_value_strings = [v[0] for v in valid_values]
            if final_set_value not in valid_value_strings:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Consistency error: 'set_value' ('{final_set_value}') is not among the "
                        f"defined Values for field '{target_field.name}' (ID {target_field.id}). "
                        f"Valid values: {valid_value_strings}."
                    ),
                )

    # Apply updates
    update_data = rule_update.model_dump(exclude_unset=True)

    if not update_data:
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
    current_user: User = Depends(require_admin_or_author),
):
    """Delete a Rule on a DRAFT version. ADMIN/AUTHOR only."""

    # Delete rule
    with db_transaction(db, f"delete_rule {rule.id}"):
        db.delete(rule)

        logger.info(f"Rule {rule.id} deleted successfully")

    return None
