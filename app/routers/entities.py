import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, get_current_user, get_entity_or_404, require_admin_or_author
from app.models.domain import Entity, EntityVersion, User
from app.schemas import EntityCreate, EntityRead, EntityUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entities", tags=["Entities"])


@router.post("/", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
def create_entity(
    entity: EntityCreate, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_author)
):
    """Create an Entity. ADMIN/AUTHOR only; rejects duplicate names with 400."""

    # Check if entity with same name already exists
    existing_entity = db.query(Entity).filter(Entity.name == entity.name).first()
    if existing_entity:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entity with this name already exists.")

    # Create and save entity
    with db_transaction(db, f"create_entity '{entity.name}'"):
        db_entity = Entity(**entity.model_dump())
        db_entity.created_by_id = current_user.id
        # updated_by_id intentionally NULL: record not yet modified

        db.add(db_entity)
        db.flush()

        logger.info(f"Entity {db_entity.id} created successfully: name='{entity.name}'")

    db.refresh(db_entity)
    return db_entity


@router.get("/", response_model=list[EntityRead])
def list_entities(
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List entities (any authenticated user)."""

    limit = min(limit, 100)

    entities = db.query(Entity).offset(skip).limit(limit).all()

    logger.info(f"Returning {len(entities)} entities")

    return entities


@router.get("/{entity_id}", response_model=EntityRead)
def read_entity(entity: Entity = Depends(get_entity_or_404), current_user: User = Depends(get_current_user)):
    """Get an Entity by id (any authenticated user)."""
    logger.debug(f"Reading entity {entity.id} by user {current_user.id}")
    return entity


@router.patch("/{entity_id}", response_model=EntityRead)
def update_entity(
    entity_update: EntityUpdate,
    entity: Entity = Depends(get_entity_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Update an Entity (ADMIN/AUTHOR only); rejects duplicate names with 400."""

    # Check name uniqueness if name is being changed
    if entity_update.name is not None and entity_update.name != entity.name:
        existing = db.query(Entity).filter(Entity.name == entity_update.name).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entity with this name already exists.")

    # Extract only provided fields
    update_data = entity_update.model_dump(exclude_unset=True)

    if not update_data:
        return entity

    # Update fields
    with db_transaction(db, f"update_entity {entity.id}"):
        for key, value in update_data.items():
            setattr(entity, key, value)

        entity.updated_by_id = current_user.id

        logger.info(f"Entity {entity.id} updated successfully")

    db.refresh(entity)
    return entity


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity(
    entity: Entity = Depends(get_entity_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Delete an Entity. ADMIN/AUTHOR only; blocked with 409 if any `EntityVersion` still exists."""

    # Guardrail: check for dependencies
    versions_count = db.query(EntityVersion).filter(EntityVersion.entity_id == entity.id).count()

    if versions_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Entity because it has {versions_count} associated Versions. "
            "Please delete them first.",
        )

    # Delete entity
    with db_transaction(db, f"delete_entity {entity.id}"):
        entity_name = entity.name
        db.delete(entity)

        logger.info(f"Entity {entity.id} ('{entity_name}') deleted successfully")

    return None
