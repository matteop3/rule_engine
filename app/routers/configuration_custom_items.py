"""CRUD for configuration-scoped, commercial-only `ConfigurationCustomItem` rows."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, get_current_user, require_draft_status
from app.models.domain import Configuration, ConfigurationCustomItem, User
from app.routers.configurations import get_configuration_or_404
from app.schemas.configuration_custom_item import (
    ConfigurationCustomItemCreate,
    ConfigurationCustomItemRead,
    ConfigurationCustomItemUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/configurations/{config_id}/custom-items", tags=["Configuration Custom Items"])


def _get_custom_item_or_404(db: Session, configuration: Configuration, custom_item_id: int) -> ConfigurationCustomItem:
    """Fetch a ConfigurationCustomItem scoped to its configuration or raise 404."""
    item = (
        db.query(ConfigurationCustomItem)
        .filter(
            ConfigurationCustomItem.id == custom_item_id,
            ConfigurationCustomItem.configuration_id == configuration.id,
        )
        .first()
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Custom item {custom_item_id} not found on configuration {configuration.id}.",
        )
    return item


def _generate_custom_key() -> str:
    """Generate a stable, never-reused custom key in the form ``CUSTOM-<uuid8>``."""
    return f"CUSTOM-{uuid.uuid4().hex[:8]}"


@router.get("/", response_model=list[ConfigurationCustomItemRead])
def list_custom_items(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List custom items, ordered by `sequence`. Owner/ADMIN only."""

    configuration = get_configuration_or_404(db, config_id, current_user)

    items = (
        db.query(ConfigurationCustomItem)
        .filter(ConfigurationCustomItem.configuration_id == configuration.id)
        .order_by(ConfigurationCustomItem.sequence, ConfigurationCustomItem.id)
        .all()
    )

    logger.info(f"Returning {len(items)} custom items for configuration {config_id}")
    return items


@router.post("/", response_model=ConfigurationCustomItemRead, status_code=status.HTTP_201_CREATED)
def create_custom_item(
    config_id: str,
    payload: ConfigurationCustomItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a custom item on a DRAFT configuration (owner/ADMIN).

    Server generates `custom_key` as `CUSTOM-<uuid8>`; any client-supplied
    value is ignored. FINALIZED configurations return 409.
    """

    configuration = get_configuration_or_404(db, config_id, current_user)
    require_draft_status(configuration, "add custom items to")

    with db_transaction(db, f"create_custom_item on configuration {config_id}"):
        item = ConfigurationCustomItem(
            configuration_id=configuration.id,
            custom_key=_generate_custom_key(),
            description=payload.description,
            quantity=payload.quantity,
            unit_price=payload.unit_price,
            unit_of_measure=payload.unit_of_measure,
            sequence=payload.sequence,
            created_by_id=current_user.id,
        )
        db.add(item)
        db.flush()

        logger.info(f"Custom item {item.id} ('{item.custom_key}') created on configuration {config_id}")

    db.refresh(item)
    return item


@router.patch("/{custom_item_id}", response_model=ConfigurationCustomItemRead)
def update_custom_item(
    config_id: str,
    custom_item_id: int,
    payload: ConfigurationCustomItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a custom item on a DRAFT configuration (owner/ADMIN); `custom_key` is immutable."""

    configuration = get_configuration_or_404(db, config_id, current_user)
    require_draft_status(configuration, "update custom items on")

    item = _get_custom_item_or_404(db, configuration, custom_item_id)

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        return item

    with db_transaction(db, f"update_custom_item {custom_item_id} on configuration {config_id}"):
        for key, value in update_data.items():
            setattr(item, key, value)
        item.updated_by_id = current_user.id

        logger.info(f"Custom item {custom_item_id} updated successfully")

    db.refresh(item)
    return item


@router.delete("/{custom_item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_item(
    config_id: str,
    custom_item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a custom item from a DRAFT configuration (owner/ADMIN)."""

    configuration = get_configuration_or_404(db, config_id, current_user)
    require_draft_status(configuration, "delete custom items from")

    item = _get_custom_item_or_404(db, configuration, custom_item_id)

    with db_transaction(db, f"delete_custom_item {custom_item_id} on configuration {config_id}"):
        custom_key = item.custom_key
        db.delete(item)

        logger.info(f"Custom item {custom_item_id} ('{custom_key}') deleted")

    return None
