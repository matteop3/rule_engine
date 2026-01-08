from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_db
from app.dependencies import get_current_user
from app.models.domain import Configuration, Field, User, UserRole, EntityVersion, VersionStatus
from app.schemas.configuration import ConfigurationCreate, ConfigurationRead, ConfigurationUpdate
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldInputState
from app.services.rule_engine import RuleEngineService


router = APIRouter(
    prefix="/configurations",
    tags=["Configurations"]
)


# ============================================================
# DEPENDENCIES
# ============================================================

def get_rule_engine_service() -> RuleEngineService:
    """
    Dependency for Rule Engine Service.
    Can be replaced with a singleton or factory pattern if needed.
    """
    return RuleEngineService()


# ============================================================
# SECURITY HELPERS
# ============================================================

def validate_input_data_integrity(
    db: Session, 
    version_id: int, 
    data: List[Dict[str, Any]]
) -> None:
    """
    Validates that:
    1. All field_ids exist in the target version
    2. No duplicate field_ids in the input
    """
    # Extract field IDs
    input_field_ids = [item['field_id'] for item in data]
    
    # Check for duplicates (convert to set that has not duplicates)
    if len(input_field_ids) != len(set(input_field_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate field_ids found in data. Each field can appear only once."
        )
    
    # Check existence (existing code)
    if not input_field_ids:
        return
    
    valid_fields_count = db.query(Field).filter(
        Field.entity_version_id == version_id,
        Field.id.in_(input_field_ids)
    ).count()
    
    if valid_fields_count != len(input_field_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more field_ids in the data do not belong to the specified Entity Version."
        )

def check_user_can_access_configuration(config: Configuration, user: User) -> None:
    """
    Enforces ownership or admin privilege.
    Raises HTTPException(403) if user lacks permission.
    """
    if config.user_id != user.id and user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this configuration."
        )


def get_configuration_or_404(
    db: Session, 
    config_id: str, 
    user: User
) -> Configuration:
    """
    Retrieves a configuration and enforces access control.
    
    Raises:
        HTTPException(404): If configuration doesn't exist
        HTTPException(403): If user lacks permission
    """
    config = db.query(Configuration).filter(
        Configuration.id == config_id
    ).first()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Configuration not found."
        )
    
    check_user_can_access_configuration(config, user)
    
    return config


def validate_version_exists(db: Session, version_id: int) -> EntityVersion:
    """
    Validates that an EntityVersion exists.
    
    Raises:
        HTTPException(404): If version doesn't exist
    """
    version = db.query(EntityVersion).filter(
        EntityVersion.id == version_id
    ).first()
    
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Entity Version not found."
        )
    
    return version


def validate_user_can_save_version(user: User, version: EntityVersion) -> None:
    """
    Enforces that regular users can only save PUBLISHED versions.
    
    Raises:
        HTTPException(400): If regular user tries to save non-PUBLISHED version
    """
    if user.role == UserRole.USER and version.status != VersionStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Regular users can only save configurations for PUBLISHED versions."
        )


# ============================================================
# CRUD ENDPOINTS
# ============================================================

@router.post(
    "/", 
    response_model=ConfigurationRead, 
    status_code=status.HTTP_201_CREATED
)
def create_configuration(
    config_in: ConfigurationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
):
    """
    Creates a new user configuration (snapshot of inputs).
    
    - Accepts any Entity Version (Draft, Published, Archived) for ADMINs/AUTHORs
    - Regular USERs can only save PUBLISHED versions
    - Owner automatically assigned from JWT token
    
    Returns:
        ConfigurationRead: The created configuration
    """
    
    # Validation
    version = validate_version_exists(db, config_in.entity_version_id)
    validate_user_can_save_version(current_user, version)

    # Extract and validate data structure
    data_list: List[Dict[str, Any]] = config_in.model_dump()['data']
    validate_input_data_integrity(db, config_in.entity_version_id, data_list)
    
    try:
        # Create configuration
        new_config = Configuration(
            entity_version_id=config_in.entity_version_id,
            user_id=current_user.id,
            name=config_in.name,
            data=data_list,
            created_by_id=current_user.id,
            updated_by_id=current_user.id
        )
        
        db.add(new_config)
        db.commit()
        db.refresh(new_config)
        
        return new_config
    
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while creating the configuration."
        )


@router.get("/", response_model=List[ConfigurationRead])
def list_configurations(
    entity_version_id: Optional[int] = None,
    user_id: Optional[str] = None,
    skip: int = 0, 
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
):
    """
    Lists configurations with role-based access control.
    
    - ADMIN: Can view all configurations, optionally filtered by user_id
    - AUTHOR/USER: Can only view their own configurations
    
    Query Parameters:
        entity_version_id: Filter by specific version
        user_id: Filter by user (ADMIN only)
        skip: Pagination offset
        limit: Maximum results (max 100)
    
    Returns:
        List[ConfigurationRead]: Filtered configurations, newest first
    """
    
    query = db.query(Configuration)
    
    # Apply role-based filtering
    if current_user.role == UserRole.ADMIN:
        # Admins can optionally filter by specific user
        if user_id:
            query = query.filter(Configuration.user_id == user_id)
    else:
        # Non-admins can't query other users' configurations
        if user_id is not None and user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot list configurations belonging to other users."
            )
        # Force filter to current user
        query = query.filter(Configuration.user_id == current_user.id)
    
    # Optional version filter
    if entity_version_id:
        query = query.filter(Configuration.entity_version_id == entity_version_id)
    
    # Execute with pagination
    limit = min(limit, 100)

    return query.order_by(
        Configuration.updated_at.desc()
    ).offset(skip).limit(limit).all()


@router.get("/{config_id}", response_model=ConfigurationRead)
def read_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
):
    """
    Retrieves a single configuration by ID.
    
    Access Control:
        - Only owner or ADMIN can access
    
    Returns:
        ConfigurationRead: The requested configuration
    """
    return get_configuration_or_404(db, config_id, current_user)


@router.patch("/{config_id}", response_model=ConfigurationRead)
def update_configuration(
    config_id: str,
    config_update: ConfigurationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
):
    """
    Updates a configuration's name or data inputs.
    
    Note: Cannot change the linked entity_version_id (data integrity).
    
    Access Control:
        - Only owner or ADMIN can update
    
    Returns:
        ConfigurationRead: The updated configuration
    """
    
    config = get_configuration_or_404(db, config_id, current_user)

    # Extract only provided fields
    update_data: Dict[str, Any] = config_update.model_dump(exclude_unset=True)
    if "data" in update_data:
        validate_input_data_integrity(db, config.entity_version_id, update_data["data"])
    
    try:
        # Apply updates
        for key, value in update_data.items():
            setattr(config, key, value)
        
        # Update metadata
        config.updated_by_id = current_user.id
        
        db.commit()
        db.refresh(config)
        
        return config
    
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating the configuration."
        )


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
):
    """
    Deletes a saved configuration.
    
    Access Control:
        - Only owner or ADMIN can delete
    
    Returns:
        204 No Content on success
    """
    
    config = get_configuration_or_404(db, config_id, current_user)
    
    try:
        db.delete(config)
        db.commit()
        return None
    
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


# ============================================================
# CALCULATION ENDPOINT (Re-hydration)
# ============================================================

@router.get("/{config_id}/calculate", response_model=CalculationResponse)
def load_and_calculate_configuration(
    config_id: str, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user),  # Auth
    engine_service: RuleEngineService = Depends(get_rule_engine_service)
):
    """
    Loads a saved configuration and recalculates its state.
    
    Workflow:
        1. Retrieves saved inputs from database
        2. Invokes Rule Engine using the linked version
        3. Returns full calculated state
    
    Access Control:
        - Only owner or ADMIN can access
    
    Returns:
        CalculationResponse: Full field states with validation
    """
    
    # Fetch configuration
    config = get_configuration_or_404(db, config_id, current_user)
    
    # Validate linked version exists
    version = config.entity_version
    if not version:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Orphaned configuration: linked version not found."
        )
    
    try:
        # Reconstruct FieldInputState objects from saved data dictionaries
        # config.data is a dict list, FieldInputState(**item) unpacks dict and create the object
        current_state_objects: List[FieldInputState] = [
            FieldInputState(**item) for item in config.data
        ]
        
        # Build engine request
        engine_payload = CalculationRequest(
            entity_id=version.entity_id,
            entity_version_id=version.id, 
            current_state=current_state_objects
        )
        
        # Execute calculation
        result = engine_service.calculate_state(db, engine_payload)
        
        return result
    
    except ValueError as e:
        # Business logic errors (validation failures, rule errors)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Calculation error: {str(e)}"
        )
    
    except Exception as e:
        # Unexpected errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during calculation: {str(e)}"
        )