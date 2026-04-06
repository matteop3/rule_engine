"""Data retrieval helpers — pure 'find or fail' functions."""

from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.domain import BOMItem, BOMItemRule, Entity, EntityVersion, Field, Rule, User, Value


def fetch_user_by_id(db: Session, user_id: str) -> User:
    """
    Helper: Get a User by its ID.
    Raises:
        HTTPException(404): If not found
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User {user_id} not found.")
    return user


def fetch_entity_by_id(db: Session, entity_id: int) -> Entity:
    """
    Helper: Get an Entity by its ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If not found
    """
    if entity_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid entity ID")

    entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity {entity_id} not found.")
    return entity


def fetch_field_by_id(db: Session, field_id: int) -> Field:
    """
    Helper: Get a Field by its ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If not found
    """
    if field_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid field ID")

    field = db.query(Field).filter(Field.id == field_id).first()
    if not field:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Field {field_id} not found.")
    return field


def fetch_rule_by_id(db: Session, rule_id: int) -> Rule:
    """
    Helper: Get a Rule by its ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If not found
    """
    if rule_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid rule ID")

    rule = db.query(Rule).filter(Rule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Rule {rule_id} not found.")
    return rule


def fetch_value_by_id(db: Session, value_id: int) -> Value:
    """
    Helper: Get a Value by its ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If not found
    """
    if value_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid value ID")

    value = db.query(Value).filter(Value.id == value_id).first()
    if not value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Value {value_id} not found.")
    return value


def fetch_version_by_id(db: Session, version_id: int) -> EntityVersion:
    """
    Fetch a Version object by its ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If not found
    """
    if version_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ID")

    version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()

    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entity Version {version_id} not found.")
    return version


# ============================================================
# HTTP DEPENDENCIES (Path parameter extraction)
# ============================================================


def get_version_or_404(
    version_id: Annotated[int, Path(description="Entity Version ID", gt=0)], db: Session = Depends(get_db)
) -> EntityVersion:
    """
    Dependency: Retrieves an EntityVersion by ID.
    Raises:
        HTTPException(404): If version doesn't exist
    """
    return fetch_version_by_id(db, version_id)


def get_user_or_404(user_id: Annotated[str, Path(description="User ID")], db: Session = Depends(get_db)) -> User:
    """
    Dependency: Fetch user from Path ID.
    Raises:
        HTTPException(404): If User doesn't exist or isn't active.
    """
    return fetch_user_by_id(db, user_id)


def get_entity_or_404(
    entity_id: Annotated[int, Path(description="Entity ID", gt=0)], db: Session = Depends(get_db)
) -> Entity:
    """
    Dependency: Retrieves an Entity by ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If entity doesn't exist
    """
    return fetch_entity_by_id(db, entity_id)


def get_field_or_404(
    field_id: Annotated[int, Path(description="Field ID", gt=0)], db: Session = Depends(get_db)
) -> Field:
    """
    Dependency: Retrieves a Field by ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If field doesn't exist
    """
    return fetch_field_by_id(db, field_id)


def get_rule_or_404(rule_id: Annotated[int, Path(description="Rule ID", gt=0)], db: Session = Depends(get_db)) -> Rule:
    """
    Dependency: Retrieves a Rule by ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If rule doesn't exist
    """
    return fetch_rule_by_id(db, rule_id)


def get_value_or_404(
    value_id: Annotated[int, Path(description="Value ID", gt=0)], db: Session = Depends(get_db)
) -> Value:
    """
    Dependency: Retrieves a Value by ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If value doesn't exist
    """
    return fetch_value_by_id(db, value_id)


# ============================================================
# BOM FETCHERS
# ============================================================


def fetch_bom_item_by_id(db: Session, bom_item_id: int) -> BOMItem:
    """
    Helper: Get a BOMItem by its ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If not found
    """
    if bom_item_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid BOM item ID")

    bom_item = db.query(BOMItem).filter(BOMItem.id == bom_item_id).first()
    if not bom_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"BOM item {bom_item_id} not found.")
    return bom_item


def fetch_bom_item_rule_by_id(db: Session, bom_item_rule_id: int) -> BOMItemRule:
    """
    Helper: Get a BOMItemRule by its ID.
    Raises:
        HTTPException(400): Invalid ID
        HTTPException(404): If not found
    """
    if bom_item_rule_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid BOM item rule ID")

    bom_item_rule = db.query(BOMItemRule).filter(BOMItemRule.id == bom_item_rule_id).first()
    if not bom_item_rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"BOM item rule {bom_item_rule_id} not found."
        )
    return bom_item_rule


def get_bom_item_or_404(
    bom_item_id: Annotated[int, Path(description="BOM Item ID", gt=0)], db: Session = Depends(get_db)
) -> BOMItem:
    """
    Dependency: Retrieves a BOMItem by ID.
    Raises:
        HTTPException(404): If BOM item doesn't exist
    """
    return fetch_bom_item_by_id(db, bom_item_id)


def get_bom_item_rule_or_404(
    bom_item_rule_id: Annotated[int, Path(description="BOM Item Rule ID", gt=0)], db: Session = Depends(get_db)
) -> BOMItemRule:
    """
    Dependency: Retrieves a BOMItemRule by ID.
    Raises:
        HTTPException(404): If BOM item rule doesn't exist
    """
    return fetch_bom_item_rule_by_id(db, bom_item_rule_id)
