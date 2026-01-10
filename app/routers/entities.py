import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    require_admin_or_author,
    get_entity_or_404,
    db_transaction
)
from app.models.domain import Entity, EntityVersion, User
from app.schemas import EntityCreate, EntityRead, EntityUpdate


# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(
    prefix="/entities",
    tags=["Entities"]
)


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
def create_entity(
    entity: EntityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Create a new Entity into database.

    Access Control:
        - Only ADMIN and AUTHOR can create entities

    Returns:
        EntityRead: The created entity
    """
    logger.info(
        f"Creating entity '{entity.name}' by user {current_user.id} "
        f"(role: {current_user.role.value})"
    )

    # Check if entity with same name already exists
    existing_entity = db.query(Entity).filter(Entity.name == entity.name).first()
    if existing_entity:
        logger.warning(f"Entity creation failed: name '{entity.name}' already exists")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Entity with this name already exists."
        )

    # Create and save entity
    with db_transaction(db, f"create_entity '{entity.name}'"):
        db_entity = Entity(**entity.model_dump())
        db_entity.created_by_id = current_user.id
        db_entity.updated_by_id = current_user.id

        db.add(db_entity)
        db.flush()

        logger.info(
            f"Entity {db_entity.id} created successfully: name='{entity.name}'"
        )

    db.refresh(db_entity)
    return db_entity


@router.get("/", response_model=List[EntityRead])
def list_entities(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve Entity list.

    Access Control:
        - Any authenticated user can list entities

    Query Parameters:
        skip: Pagination offset
        limit: Maximum results (max 100)

    Returns:
        List[EntityRead]: List of entities
    """
    logger.info(
        f"Listing entities by user {current_user.id}: skip={skip}, limit={limit}"
    )

    # Cap limit to prevent abuse
    original_limit = limit
    limit = min(limit, 100)

    if original_limit > 100:
        logger.warning(f"Limit capped from {original_limit} to 100")

    entities = db.query(Entity).offset(skip).limit(limit).all()

    logger.info(f"Returning {len(entities)} entities")

    return entities


@router.get("/{entity_id}", response_model=EntityRead)
def read_entity(
    entity: Entity = Depends(get_entity_or_404),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve a single Entity by ID.

    Access Control:
        - Any authenticated user can read entities

    Returns:
        EntityRead: The requested entity
    """
    logger.debug(f"Reading entity {entity.id} by user {current_user.id}")
    return entity


@router.put("/{entity_id}", response_model=EntityRead)
def update_entity(
    entity_update: EntityUpdate,
    entity: Entity = Depends(get_entity_or_404),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Update an existing Entity.

    Access Control:
        - Only ADMIN and AUTHOR can update entities

    Returns:
        EntityRead: The updated entity
    """
    logger.info(
        f"Updating entity {entity.id} by user {current_user.id} "
        f"(role: {current_user.role.value})"
    )

    # Check name uniqueness if name is being changed
    if entity_update.name is not None and entity_update.name != entity.name:
        existing = db.query(Entity).filter(Entity.name == entity_update.name).first()
        if existing:
            logger.warning(
                f"Update entity {entity.id} failed: name '{entity_update.name}' already in use"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Entity with this name already exists."
            )

    # Extract only provided fields
    update_data = entity_update.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning(f"Empty update request for entity {entity.id}")
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
    current_user: User = Depends(require_admin_or_author)
):
    """
    Delete an Entity.

    Strict Policy:
        - Cannot delete if it contains Versions (Draft, Published or Archived)
        - Must delete all versions first

    Access Control:
        - Only ADMIN and AUTHOR can delete entities

    Returns:
        204 No Content on success
    """
    logger.info(
        f"Deleting entity {entity.id} by user {current_user.id} "
        f"(role: {current_user.role.value})"
    )

    # Guardrail: check for dependencies
    versions_count = db.query(EntityVersion).filter(
        EntityVersion.entity_id == entity.id
    ).count()

    if versions_count > 0:
        logger.warning(
            f"Delete entity {entity.id} failed: has {versions_count} associated versions"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Entity because it has {versions_count} associated Versions. "
                   "Please delete them first."
        )

    # Delete entity
    with db_transaction(db, f"delete_entity {entity.id}"):
        entity_name = entity.name
        db.delete(entity)

        logger.info(f"Entity {entity.id} ('{entity_name}') deleted successfully")

    return None
