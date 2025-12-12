from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.domain import Configuration, EntityVersion
from app.schemas import ConfigurationCreate, ConfigurationRead, ConfigurationUpdate
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldInputState
from app.services.rule_engine import RuleEngineService

router = APIRouter(
    prefix="/configurations",
    tags=["Configurations"]
)

# CRUD

@router.post("/", response_model=ConfigurationRead, status_code=status.HTTP_201_CREATED)
def save_configuration(config_in: ConfigurationCreate, db: Session = Depends(get_db)):
    """
    Saves a user configuration (a snapshot of inputs).
    Accepts any Entity Version (Draft, Published, Archived).
    """
    # Check if Version exists
    version = db.query(EntityVersion).filter(EntityVersion.id == config_in.entity_version_id).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity Version not found.")

    # Create Configuration
    # UUID is generated automatically by the Model default
    new_config = Configuration(
        entity_version_id=config_in.entity_version_id,
        name=config_in.name,
        data=config_in.model_dump()['data'] # Extract list of dicts from Pydantic models
    )
    
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    
    return new_config


@router.get("/{config_id}", response_model=ConfigurationRead)
def read_configuration(config_id: str, db: Session = Depends(get_db)):
    """ Retrieve the raw saved data (metadata + inputs). """
    config = db.query(Configuration).filter(Configuration.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found.")
    
    return config


@router.get("/", response_model=List[ConfigurationRead])
def list_configurations(
    entity_version_id: Optional[int] = None,
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db)
):
    """ List saved configurations, optionally filtered by Version. """
    query = db.query(Configuration)
    
    if entity_version_id:
        query = query.filter(Configuration.entity_version_id == entity_version_id)
    
    # Order by newest first
    return query.order_by(Configuration.updated_at.desc()).offset(skip).limit(limit).all()


@router.patch("/{config_id}", response_model=ConfigurationRead)
def update_configuration(config_id: str, config_update: ConfigurationUpdate, db: Session = Depends(get_db)):
    """ 
    Update configuration name or data inputs. 
    Cannot change the linked Version ID (integrity).
    """
    config = db.query(Configuration).filter(Configuration.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found.")

    update_data = config_update.model_dump(exclude_unset=True)

    # Pydantic has already validated data

    for key, value in update_data.items():
        setattr(config, key, value)

    db.commit()
    db.refresh(config)

    return config


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_configuration(config_id: str, db: Session = Depends(get_db)):
    """ Delete a saved configuration. """
    config = db.query(Configuration).filter(Configuration.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found.")

    db.delete(config)
    db.commit()

    return None


# Re-hydration endpoint

@router.get("/{config_id}/calculate", response_model=CalculationResponse)
def load_and_calculate_configuration(config_id: str, db: Session = Depends(get_db)):
    """
    Sandbox:
    1. Loads the saved inputs from DB.
    2. Invokes the Rule Engine using the linked Version.
    3. Returns the full calculated state (Fields, Options, Visibility).
    """
    # Fetch Config
    config = db.query(Configuration).filter(Configuration.id == config_id).first()
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found.")

    # Fetch Linked Version to get Entity ID
    version = config.entity_version
    if not version:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Orphaned Configuration: Version not found.")

    # Build engine request (re-hydration)

    # Explicit conversion of dictionaries to FieldInputState objects
    # config.data is a dict list
    # FieldInputState(**item) unpacks dict and create the object
    current_state_objects = [FieldInputState(**item) for item in config.data]

    engine_payload = CalculationRequest(
        entity_id=version.entity_id,
        entity_version_id=version.id, 
        current_state=current_state_objects # Type is now correct: List[FieldInputState]
    )

    # Run engine
    service = RuleEngineService()
    try:
        result = service.calculate_state(db, engine_payload)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Calculation Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))