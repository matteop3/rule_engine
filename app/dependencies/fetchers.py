"""Data retrieval helpers — pure 'find or fail' functions."""

from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.database import Base, get_db
from app.models.domain import BOMItem, BOMItemRule, Entity, EntityVersion, Field, Rule, User, Value


def _fetch_or_404[T: Base](db: Session, model: type[T], ident: int | str, label: str) -> T:
    """Return the row of `model` matching `ident`, or raise 404; 400 on a non-positive int id."""
    if isinstance(ident, int) and ident <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {label} ID.")
    row = db.query(model).filter(model.id == ident).first()  # type: ignore[attr-defined]
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} {ident} not found.")
    return row


def fetch_user_by_id(db: Session, user_id: str) -> User:
    return _fetch_or_404(db, User, user_id, "User")


def fetch_entity_by_id(db: Session, entity_id: int) -> Entity:
    return _fetch_or_404(db, Entity, entity_id, "Entity")


def fetch_field_by_id(db: Session, field_id: int) -> Field:
    return _fetch_or_404(db, Field, field_id, "Field")


def fetch_rule_by_id(db: Session, rule_id: int) -> Rule:
    return _fetch_or_404(db, Rule, rule_id, "Rule")


def fetch_value_by_id(db: Session, value_id: int) -> Value:
    return _fetch_or_404(db, Value, value_id, "Value")


def fetch_version_by_id(db: Session, version_id: int) -> EntityVersion:
    return _fetch_or_404(db, EntityVersion, version_id, "Entity Version")


def fetch_bom_item_by_id(db: Session, bom_item_id: int) -> BOMItem:
    return _fetch_or_404(db, BOMItem, bom_item_id, "BOM item")


def fetch_bom_item_rule_by_id(db: Session, bom_item_rule_id: int) -> BOMItemRule:
    return _fetch_or_404(db, BOMItemRule, bom_item_rule_id, "BOM item rule")


def get_user_or_404(user_id: Annotated[str, Path(description="User ID")], db: Session = Depends(get_db)) -> User:
    return fetch_user_by_id(db, user_id)


def get_entity_or_404(
    entity_id: Annotated[int, Path(description="Entity ID", gt=0)], db: Session = Depends(get_db)
) -> Entity:
    return fetch_entity_by_id(db, entity_id)


def get_field_or_404(
    field_id: Annotated[int, Path(description="Field ID", gt=0)], db: Session = Depends(get_db)
) -> Field:
    return fetch_field_by_id(db, field_id)


def get_rule_or_404(rule_id: Annotated[int, Path(description="Rule ID", gt=0)], db: Session = Depends(get_db)) -> Rule:
    return fetch_rule_by_id(db, rule_id)


def get_value_or_404(
    value_id: Annotated[int, Path(description="Value ID", gt=0)], db: Session = Depends(get_db)
) -> Value:
    return fetch_value_by_id(db, value_id)


def get_version_or_404(
    version_id: Annotated[int, Path(description="Entity Version ID", gt=0)], db: Session = Depends(get_db)
) -> EntityVersion:
    return fetch_version_by_id(db, version_id)


def get_bom_item_or_404(
    bom_item_id: Annotated[int, Path(description="BOM Item ID", gt=0)], db: Session = Depends(get_db)
) -> BOMItem:
    return fetch_bom_item_by_id(db, bom_item_id)


def get_bom_item_rule_or_404(
    bom_item_rule_id: Annotated[int, Path(description="BOM Item Rule ID", gt=0)], db: Session = Depends(get_db)
) -> BOMItemRule:
    return fetch_bom_item_rule_by_id(db, bom_item_rule_id)
