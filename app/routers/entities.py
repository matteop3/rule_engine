from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Entity, Field
from app.schemas import EntityCreate, EntityRead, EntityUpdate

# Router definition 
# prefix="/entities" all routes will begin with /entities
router = APIRouter(
    prefix="/entities",
    tags=["Entities"]
)

@router.post("/", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
def create_entity(entity: EntityCreate, db: Session = Depends(get_db)):
    """
    Create a new Entity into database.
    """
    # Preventive check to see if an entity with the same name already exists (optional but recommended)
    existing_entity = db.query(Entity).filter(Entity.name == entity.name).first()
    if existing_entity:
        raise HTTPException(status_code=400, detail="Entity with this name already exists")

    # Create DB instance
    db_entity = Entity(name=entity.name)
    
    # Save
    db.add(db_entity)
    db.commit()
    db.refresh(db_entity) # Reload the object from the DB to get the generated ID
    
    return db_entity


@router.get("/", response_model=List[EntityRead])
def read_entities(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Retrieve Entity list.
    """
    entities = db.query(Entity).offset(skip).limit(limit).all()
    return entities


@router.put("/{entity_id}", response_model=EntityRead)
def update_entity(entity_id: int, entity_in: EntityUpdate, db: Session = Depends(get_db)):
    """ Update an existing Entity. """
    # Read Entity from DB
    db_entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not db_entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    
    # Check name uniqueness if name is being changed
    if entity_in.name is not None and entity_in.name != db_entity.name:
        existing = db.query(Entity).filter(Entity.name == entity_in.name).first()
        if existing:
            raise HTTPException(status_code=400, detail="Entity with this name already exists")
    
    # Update all fields
    for key, value in entity_in.model_dump().items():
        setattr(db_entity, key, value)
    
    # Save
    db.commit()
    db.refresh(db_entity)
    return db_entity


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity(entity_id: int, db: Session = Depends(get_db)):
    """
    Delete an Entity.
    Strict policy: cannot delete if it contains Fields.
    """
    db_entity = db.query(Entity).filter(Entity.id == entity_id).first()
    if not db_entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Guardrail: check for dependencies
    fields_count = db.query(Field).filter(Field.entity_id == entity_id).count()
    if fields_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete Entity because it has {fields_count} associated Fields. Please delete them first."
        )

    db.delete(db_entity)
    db.commit()
    return None