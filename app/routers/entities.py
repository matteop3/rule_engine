from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import Entity, EntityVersion, User, UserRole
from app.schemas import EntityCreate, EntityRead, EntityUpdate

# Router definition 
# prefix="/entities" all routes will begin with /entities
router = APIRouter(
    prefix="/entities",
    tags=["Entities"]
)

@router.post("/", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
def create_entity(
    entity: EntityCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Create a new Entity into database. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    # Preventive check to see if an entity with the same name already exists
    existing_entity = db.query(Entity).filter(Entity.name == entity.name).first()
    if existing_entity:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entity with this name already exists.")

    # Create DB instance
    # Using **unpacking handles 'description' and other optional fields automatically
    db_entity = Entity(**entity.model_dump())

    # Audit update
    db_entity.created_by_id = current_user.id
    db_entity.updated_by_id = current_user.id
    
    # Save
    db.add(db_entity)
    db.commit()
    db.refresh(db_entity) # Reload the object from the DB to get the generated ID
    
    return db_entity


@router.get("/", response_model=List[EntityRead])
def read_entities(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Retrieve Entity list. """
    entities = db.query(Entity).offset(skip).limit(limit).all()
    
    return entities


@router.get("/{entity_id}", response_model=EntityRead)
def read_entity(
    entity_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Retrieve a single Entity by ID. """
    db_entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not db_entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found.")
    
    return db_entity


@router.put("/{entity_id}", response_model=EntityRead)
def update_entity(
    entity_id: int, 
    entity_in: EntityUpdate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Update an existing Entity. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    # Read Entity from DB
    db_entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not db_entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found.")
    
    # Check name uniqueness if name is being changed
    if entity_in.name is not None and entity_in.name != db_entity.name:
        existing = db.query(Entity).filter(Entity.name == entity_in.name).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entity with this name already exists.")
    
    # Update fields
    # exclude_unset=True ensures we don't overwrite existing data with None unless explicitly sent
    update_data = entity_in.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(db_entity, key, value)

    # Audit update
    db_entity.updated_by_id = current_user.id
    
    # Save
    db.commit()
    db.refresh(db_entity)

    return db_entity


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity(
    entity_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Delete an Entity.
    Strict policy: cannot delete if it contains Versions (Draft, Published or Archived).
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    db_entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not db_entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found.")

    # Guardrail: check for dependencies
    versions_count = db.query(EntityVersion).filter(EntityVersion.entity_id == entity_id).count()
    
    if versions_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Entity because it has {versions_count} associated Versions. Please delete them first."
        )

    # Save
    db.delete(db_entity)
    db.commit()

    return None