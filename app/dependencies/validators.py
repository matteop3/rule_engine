"""Business rule validation helpers."""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.fetchers import (
    fetch_version_by_id,
    get_bom_item_or_404,
    get_bom_item_rule_or_404,
    get_field_or_404,
    get_rule_or_404,
    get_value_or_404,
    get_version_or_404,
)
from app.models.domain import (
    BOMItem,
    BOMItemRule,
    CatalogItem,
    CatalogItemStatus,
    EngineeringTemplateItem,
    EntityVersion,
    Field,
    PriceListItem,
    Rule,
    Value,
    VersionStatus,
)


def validate_version_is_draft(version: EntityVersion) -> None:
    """
    Helper: Validates a version is DRAFT.
    Raises:
        HTTPException(409): If not DRAFT
    """
    if version.status != VersionStatus.DRAFT.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Version {version.id} is {version.status}. "
                "Only DRAFT versions can be modified. "
                "Clone this version to make changes."
            ),
        )


def validate_field_belongs_to_version(db: Session, field_id: int, version_id: int) -> Field:
    """
    Helper: Validates that a Field belongs to a specific Version.
    Raises:
        HTTPException(400): If field doesn't belong to version
    Returns:
        Field: The validated field
    """
    field = db.query(Field).filter(Field.id == field_id, Field.entity_version_id == version_id).first()

    if not field:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Field {field_id} not found in Version {version_id}."
        )
    return field


def validate_value_belongs_to_field(db: Session, value_id: int, field_id: int) -> Value:
    """
    Helper: Validates that a Value belongs to a specific Field.
    Raises:
        HTTPException(400): If value doesn't belong to field
    Returns:
        Value: The validated value
    """
    value = db.query(Value).filter(Value.id == value_id, Value.field_id == field_id).first()

    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Value {value_id} not found or does not belong to Field {field_id}.",
        )
    return value


def validate_value_not_used_in_rules(db: Session, value: Value) -> None:
    """
    Helper: Validates that a Value is not used in any Rules.
    Checks both explicit target_value_id and implicit usage in conditions JSON.

    Raises:
        HTTPException(409): If value is used in rules
    """
    # Check explicit usage (target_value_id)
    rules_targeting_value = db.query(Rule).filter(Rule.target_value_id == value.id).count()
    if rules_targeting_value > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Value because it is the explicit target of {rules_targeting_value} Rules.",
        )

    # Check CALCULATION rules: set_value references this Value's string
    from app.models.domain import RuleType

    calc_rules_count = (
        db.query(Rule)
        .filter(
            Rule.target_field_id == value.field_id,
            Rule.rule_type == RuleType.CALCULATION,
            Rule.set_value == value.value,
        )
        .count()
    )
    if calc_rules_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete Value '{value.value}' because it is referenced by "
                f"{calc_rules_count} CALCULATION rule(s) via 'set_value'. "
                f"Update or delete those rules first."
            ),
        )

    # Deep scan: check usage in JSON conditions (implicit usage)
    parent_field = value.field
    if not parent_field:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Corrupted Data: Value has no parent Field."
        )

    entity_rules = db.query(Rule).filter(Rule.entity_version_id == parent_field.entity_version_id).all()

    value_str_to_check = str(value.value)

    for rule in entity_rules:
        criteria_list = rule.conditions.get("criteria", [])

        for criterion in criteria_list:
            crit_field_id = criterion.get("field_id")

            if crit_field_id == value.field_id:
                crit_value = str(criterion.get("value", ""))

                if crit_value == value_str_to_check:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Cannot delete Value '{value.value}' because it is used as a condition criteria "
                            f"in Rule ID {rule.id}. Please update or delete that rule first."
                        ),
                    )


# ============================================================
# CATALOG REFERENCE VALIDATORS
# ============================================================


def validate_catalog_reference(db: Session, part_number: str, *, on_create: bool) -> CatalogItem:
    """
    Validates a `part_number` references an ACTIVE CatalogItem.

    Rules (see PART_CATALOG_ANALYSIS_AND_PLAN §4.3):
        - Unknown part_number -> HTTP 409
        - OBSOLETE catalog entry on create -> HTTP 409
        - OBSOLETE catalog entry on update -> HTTP 409

    Raises:
        HTTPException(409): If catalog entry is missing or OBSOLETE.
    Returns:
        CatalogItem: The validated catalog item.
    """
    catalog_item = db.query(CatalogItem).filter(CatalogItem.part_number == part_number).first()
    if catalog_item is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Catalog item '{part_number}' does not exist",
        )
    if catalog_item.status == CatalogItemStatus.OBSOLETE.value:
        if on_create:
            detail = f"Catalog item '{part_number}' is OBSOLETE and cannot be referenced by new items"
        else:
            detail = f"Catalog item '{part_number}' is OBSOLETE and cannot be referenced"
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    return catalog_item


def validate_catalog_not_referenced(db: Session, catalog_item: CatalogItem) -> None:
    """
    Blocks catalog deletion when any live row references the part: BOMItem,
    PriceListItem, or EngineeringTemplateItem (as parent or as child).

    Raises:
        HTTPException(409): With message listing reference counts per source.
    """
    bom_count = db.query(BOMItem).filter(BOMItem.part_number == catalog_item.part_number).count()
    pli_count = db.query(PriceListItem).filter(PriceListItem.part_number == catalog_item.part_number).count()
    template_count = (
        db.query(EngineeringTemplateItem)
        .filter(
            (EngineeringTemplateItem.parent_part_number == catalog_item.part_number)
            | (EngineeringTemplateItem.child_part_number == catalog_item.part_number)
        )
        .count()
    )
    if bom_count > 0 or pli_count > 0 or template_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Catalog item '{catalog_item.part_number}' cannot be deleted: "
                f"referenced by {bom_count} BOM item(s), "
                f"{pli_count} price list item(s), "
                f"and {template_count} engineering template item(s)"
            ),
        )


# ============================================================
# EDITABLE DEPENDENCIES (HTTP context — compose fetcher + validation)
# ============================================================


def get_editable_version(version: EntityVersion = Depends(get_version_or_404)) -> EntityVersion:
    """
    Dependency: Retrieves a DRAFT EntityVersion.

    It reuses 'get_version_or_404' to fetch the object,
    then applies the status validation.
    """
    validate_version_is_draft(version)
    return version


def get_editable_field(field: Field = Depends(get_field_or_404), db: Session = Depends(get_db)) -> Field:
    """
    Dependency: Retrieves a Field and validates its version is DRAFT.

    Raises:
        HTTPException(404): If field doesn't exist
        HTTPException(409): If version is not DRAFT
    """
    version = fetch_version_by_id(db, field.entity_version_id)
    validate_version_is_draft(version)
    return field


def get_editable_rule(rule: Rule = Depends(get_rule_or_404), db: Session = Depends(get_db)) -> Rule:
    """
    Dependency: Retrieves a Rule and validates its version is DRAFT.

    Raises:
        HTTPException(404): If rule doesn't exist
        HTTPException(409): If version is not DRAFT
    """
    version = fetch_version_by_id(db, rule.entity_version_id)
    validate_version_is_draft(version)
    return rule


def get_editable_value(value: Value = Depends(get_value_or_404), db: Session = Depends(get_db)) -> Value:
    """
    Dependency: Retrieves a Value and validates its version is DRAFT.

    Raises:
        HTTPException(404): If value doesn't exist
        HTTPException(409): If version is not DRAFT
    """
    parent_field = value.field
    if not parent_field:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Corrupted Data: Value has no parent Field."
        )

    version = fetch_version_by_id(db, parent_field.entity_version_id)
    validate_version_is_draft(version)
    return value


# ============================================================
# BOM EDITABLE DEPENDENCIES
# ============================================================


def get_editable_bom_item(bom_item: BOMItem = Depends(get_bom_item_or_404), db: Session = Depends(get_db)) -> BOMItem:
    """
    Dependency: Retrieves a BOMItem and validates its version is DRAFT.

    Raises:
        HTTPException(404): If BOM item doesn't exist
        HTTPException(409): If version is not DRAFT
    """
    version = fetch_version_by_id(db, bom_item.entity_version_id)
    validate_version_is_draft(version)
    return bom_item


def get_editable_bom_item_rule(
    bom_item_rule: BOMItemRule = Depends(get_bom_item_rule_or_404), db: Session = Depends(get_db)
) -> BOMItemRule:
    """
    Dependency: Retrieves a BOMItemRule and validates its version is DRAFT.

    Raises:
        HTTPException(404): If BOM item rule doesn't exist
        HTTPException(409): If version is not DRAFT
    """
    version = fetch_version_by_id(db, bom_item_rule.entity_version_id)
    validate_version_is_draft(version)
    return bom_item_rule
