import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    db_transaction,
    fetch_bom_item_by_id,
    fetch_version_by_id,
    get_bom_item_rule_or_404,
    get_editable_bom_item_rule,
    require_admin_or_author,
    validate_field_belongs_to_version,
    validate_version_is_draft,
)
from app.models.domain import BOMItemRule, User
from app.schemas.bom_item_rule import BOMItemRuleCreate, BOMItemRuleRead, BOMItemRuleUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bom-item-rules", tags=["BOM Item Rules"])


def _validate_bom_item_belongs_to_version(db: Session, bom_item_id: int, entity_version_id: int) -> None:
    """Validates that a BOM item belongs to the specified version."""
    bom_item = fetch_bom_item_by_id(db, bom_item_id)
    if bom_item.entity_version_id != entity_version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"BOM item {bom_item_id} does not belong to version {entity_version_id}.",
        )


def _validate_conditions_field_ids(db: Session, conditions: dict, entity_version_id: int) -> None:
    """Validates that all field_id values in conditions.criteria belong to the version."""
    criteria = conditions.get("criteria", [])
    for criterion in criteria:
        field_id = criterion.get("field_id")
        if field_id is not None:
            validate_field_belongs_to_version(db, field_id, entity_version_id)


@router.get("/", response_model=list[BOMItemRuleRead])
def list_bom_item_rules(
    bom_item_id: int | None = None,
    entity_version_id: int | None = None,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """List BOM item rules; requires at least one of `bom_item_id` or `entity_version_id`. ADMIN/AUTHOR only."""
    logger.info(
        f"Listing BOM item rules by user {current_user.id}: "
        f"bom_item_id={bom_item_id}, entity_version_id={entity_version_id}"
    )

    if bom_item_id is None and entity_version_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one filter parameter (bom_item_id or entity_version_id) is required.",
        )

    query = db.query(BOMItemRule)

    if bom_item_id is not None:
        query = query.filter(BOMItemRule.bom_item_id == bom_item_id)

    if entity_version_id is not None:
        query = query.filter(BOMItemRule.entity_version_id == entity_version_id)

    rules = query.offset(skip).limit(limit).all()

    logger.info(f"Returning {len(rules)} BOM item rules")
    return rules


@router.get("/{bom_item_rule_id}", response_model=BOMItemRuleRead)
def read_bom_item_rule(
    bom_item_rule: BOMItemRule = Depends(get_bom_item_rule_or_404),
    current_user: User = Depends(require_admin_or_author),
):
    """Get a BOM item rule by id. ADMIN/AUTHOR only."""
    logger.debug(f"Reading BOM item rule {bom_item_rule.id} by user {current_user.id}")
    return bom_item_rule


@router.post("/", response_model=BOMItemRuleRead, status_code=status.HTTP_201_CREATED)
def create_bom_item_rule(
    rule_data: BOMItemRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Create a BOM item rule on a DRAFT version. ADMIN/AUTHOR only.

    Validates that `bom_item_id` and every `criteria[].field_id` belong to the
    target version.
    """
    logger.info(
        f"Creating BOM item rule for bom_item {rule_data.bom_item_id} "
        f"in version {rule_data.entity_version_id} by user {current_user.id}"
    )

    version = fetch_version_by_id(db, rule_data.entity_version_id)
    validate_version_is_draft(version)

    _validate_bom_item_belongs_to_version(db, rule_data.bom_item_id, rule_data.entity_version_id)
    _validate_conditions_field_ids(db, rule_data.conditions.model_dump(), rule_data.entity_version_id)

    with db_transaction(db, f"create_bom_item_rule for bom_item {rule_data.bom_item_id}"):
        new_rule = BOMItemRule(
            bom_item_id=rule_data.bom_item_id,
            entity_version_id=rule_data.entity_version_id,
            conditions=rule_data.conditions.model_dump(),
            description=rule_data.description,
        )
        db.add(new_rule)
        db.flush()

        logger.info(f"BOM item rule {new_rule.id} created successfully")

    db.refresh(new_rule)
    return new_rule


@router.patch("/{bom_item_rule_id}", response_model=BOMItemRuleRead)
def update_bom_item_rule(
    rule_update: BOMItemRuleUpdate,
    bom_item_rule: BOMItemRule = Depends(get_editable_bom_item_rule),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Update a BOM item rule on a DRAFT version; revalidates `criteria[].field_id`. ADMIN/AUTHOR only."""

    update_data = rule_update.model_dump(exclude_unset=True)

    if not update_data:
        return bom_item_rule

    if "conditions" in update_data:
        _validate_conditions_field_ids(db, update_data["conditions"], bom_item_rule.entity_version_id)

    with db_transaction(db, f"update_bom_item_rule {bom_item_rule.id}"):
        for key, value in update_data.items():
            setattr(bom_item_rule, key, value)

        logger.info(f"BOM item rule {bom_item_rule.id} updated successfully")

    db.refresh(bom_item_rule)
    return bom_item_rule


@router.delete("/{bom_item_rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bom_item_rule(
    bom_item_rule: BOMItemRule = Depends(get_editable_bom_item_rule),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Delete a BOM item rule on a DRAFT version. ADMIN/AUTHOR only."""

    with db_transaction(db, f"delete_bom_item_rule {bom_item_rule.id}"):
        db.delete(bom_item_rule)

        logger.info(f"BOM item rule {bom_item_rule.id} deleted successfully")

    return None
