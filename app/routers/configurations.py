from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models.domain import Configuration, User, UserRole, EntityVersion, VersionStatus
from app.schemas.configuration import ConfigurationCreate, ConfigurationRead, ConfigurationUpdate
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldInputState
from app.services.rule_engine import RuleEngineService

router = APIRouter(
    prefix="/configurations",
    tags=["Configurations"]
)


# Internal helper for security

def get_configuration_or_404(
    db: Session, 
    config_id: str, 
    user: User
) -> Configuration:
    """
    Retrieve a configuration and check permissions.
    - If not exists, throw 404.
    - If exists but not yours (and you're not an admin), throw 403.
    """
    config = db.query(Configuration).filter(Configuration.id == config_id).first()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Configuration not found."
        )
    
    # Check permissions (RBAC + ownership)
    # If not yours and you're not an admin, throw 403
    if config.user_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this configuration."
        )
        
    return config


# CRUD

@router.post("/", response_model=ConfigurationRead, status_code=status.HTTP_201_CREATED)
def create_configuration(
    config_in: ConfigurationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Saves a user configuration (a snapshot of inputs).
    Accepts any Entity Version (Draft, Published, Archived).
    Owner automatically assigned from token.
    """
    # Check if Version exists
    version = db.query(EntityVersion).filter(EntityVersion.id == config_in.entity_version_id).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity Version not found.")

    if current_user.role == UserRole.USER and version.status != VersionStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Regular Users can only save Configurations for PUBLISHED versions."
        )

    # Create Configuration
    # UUID is generated automatically by the Model default
    new_config = Configuration(
        entity_version_id=config_in.entity_version_id,
        user_id=current_user.id, 
        name=config_in.name,
        data=config_in.model_dump()['data'], # Extract list of dicts from Pydantic models
        created_by_id=current_user.id,
        updated_by_id=current_user.id
    )
    
    db.add(new_config)
    db.commit()
    db.refresh(new_config)

    return new_config


@router.get("/", response_model=List[ConfigurationRead])
def list_configurations(
    entity_version_id: Optional[int] = None,
    user_id: Optional[str] = None,
    skip: int = 0, 
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Configurations list.
    ADMIN: can see everything.
    AUTHOR AND USER: can see only theirs.
    """
    query = db.query(Configuration)

    # Security filter (multi-tenancy)
    if current_user.role == UserRole.ADMIN:
        # Admins can see everything and optionally filter by specific User
        if user_id:
            query = query.filter(Configuration.user_id == user_id)
    else:
        # Non-admin Users cannot query other Users Configurations
        if user_id is not None and user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot list configurations belonging to other users."
            )
        # Force filter to current User
        query = query.filter(Configuration.user_id == current_user.id)

    # Optionally filter by Version
    if entity_version_id:
        query = query.filter(Configuration.entity_version_id == entity_version_id)

    # Order by newest first
    return query.order_by(Configuration.updated_at.desc()).offset(skip).limit(limit).all()


@router.get("/{config_id}", response_model=ConfigurationRead)
def read_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Retrieve the raw saved data (metadata + inputs).
    Protection: only owner or ADMIN.
    """
    return get_configuration_or_404(db, config_id, current_user)


@router.patch("/{config_id}", response_model=ConfigurationRead)
def update_configuration(
    config_id: str,
    config_update: ConfigurationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ 
    Update configuration name or data inputs. 
    Cannot change the linked Version ID (integrity).
    """
    config = get_configuration_or_404(db, config_id, current_user)

    update_data = config_update.model_dump(exclude_unset=True)

    # Pydantic has already validated data

    for key, value in update_data.items():
        setattr(config, key, value)

    db.commit()
    db.refresh(config)

    return config


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Delete a saved configuration. """
    config = get_configuration_or_404(db, config_id, current_user)
    
    db.delete(config)
    db.commit()

    return None


# Re-hydration endpoint

@router.get("/{config_id}/calculate", response_model=CalculationResponse)
def load_and_calculate_configuration(
    config_id: str, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Sandbox:
    1) Loads the saved inputs from DB.
    2) Invokes the Rule Engine using the linked Version.
    3) Returns the full calculated state.
    """
    # Fetch Config
    config = get_configuration_or_404(db, config_id, current_user)

    # Fetch linked Version to get Entity ID
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
        current_state=current_state_objects # Type here is correct: List[FieldInputState]
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