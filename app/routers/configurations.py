import logging
import uuid
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    get_current_user,
    fetch_version_by_id,
    get_rule_engine_service,
    db_transaction
)
from app.models.domain import Configuration, Field, User, UserRole, EntityVersion, VersionStatus, ConfigurationStatus
from app.schemas.configuration import (
    ConfigurationCreate,
    ConfigurationRead,
    ConfigurationUpdate,
    ConfigurationCloneResponse,
    ConfigurationStatusEnum
)
from app.schemas.engine import CalculationRequest, CalculationResponse, FieldInputState
from app.services.rule_engine import RuleEngineService


# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(
    prefix="/configurations",
    tags=["Configurations"]
)


# ============================================================
# VALIDATION HELPERS
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

    Raises:
        HTTPException(400): Invalid input data
    """
    if not data:
        return

    input_field_ids = [item['field_id'] for item in data]

    # Check for duplicates
    if len(input_field_ids) != len(set(input_field_ids)):
        logger.warning(f"Duplicate field_ids detected in configuration data for version {version_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate field_ids found in data. Each field can appear only once."
        )

    # Validate field existence
    valid_fields_count = db.query(Field).filter(
        Field.entity_version_id == version_id,
        Field.id.in_(input_field_ids)
    ).count()

    if valid_fields_count != len(input_field_ids):
        logger.warning(
            f"Invalid field_ids in configuration data: "
            f"expected {len(input_field_ids)}, found {valid_fields_count} valid fields"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more field_ids in the data do not belong to the specified Entity Version."
        )

    logger.debug(f"Input data validation passed for version {version_id}: {len(input_field_ids)} fields")


def check_user_can_access_configuration(config: Configuration, user: User) -> None:
    """
    Enforces ownership or admin privilege.

    Raises:
        HTTPException(403): If user lacks permission
    """
    if config.user_id != user.id and user.role != UserRole.ADMIN:
        logger.warning(
            f"Access denied: User {user.id} ({user.role_display}) attempted to access "
            f"configuration {config.id} owned by {config.user_id}"
        )
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
        logger.warning(f"Configuration not found: {config_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuration not found."
        )

    check_user_can_access_configuration(config, user)
    logger.debug(f"Configuration {config_id} retrieved by user {user.id}")

    return config


def validate_user_can_save_version(user: User, version: EntityVersion) -> None:
    """
    Enforces that regular users can only save PUBLISHED versions.

    Raises:
        HTTPException(400): If regular user tries to save non-PUBLISHED version
    """
    if user.role == UserRole.USER and version.status != VersionStatus.PUBLISHED.value:
        logger.warning(
            f"User {user.id} (role: USER) attempted to save configuration "
            f"for non-PUBLISHED version {version.id} (status: {version.status})"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Regular users can only save configurations for PUBLISHED versions."
        )


def validate_version_not_orphaned(version: Optional[EntityVersion], version_id: int) -> EntityVersion:
    """
    Validates that a version reference is not orphaned.

    Args:
        version: The EntityVersion object (nullable)
        version_id: The expected version ID (for logging)

    Returns:
        EntityVersion: The validated version

    Raises:
        HTTPException(500): If version is orphaned
    """
    if not version:
        logger.error(f"Orphaned configuration detected: version {version_id} not found")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Orphaned configuration: linked version not found."
        )
    return version


# ============================================================
# CALCULATION HELPERS
# ============================================================

def convert_to_field_input_states(data: List[Dict[str, Any]]) -> List[FieldInputState]:
    """
    Converts raw dict data to FieldInputState Pydantic objects.

    Args:
        data: List of dicts with field_id and value keys

    Returns:
        List[FieldInputState]: Validated field input objects
    """
    return [FieldInputState(**item) for item in data]


def calculate_configuration_state(
    db: Session,
    engine_service: RuleEngineService,
    version: EntityVersion,
    data: List[Dict[str, Any]]
) -> CalculationResponse:
    """
    Calculates the configuration state using the rule engine.

    Args:
        db: Database session
        engine_service: Rule engine instance
        version: The entity version to calculate against
        data: List of field inputs (dicts with field_id and value)

    Returns:
        CalculationResponse: Full calculated state including is_complete flag

    Raises:
        HTTPException(400): If calculation fails due to invalid data or rules
    """
    try:
        current_state_objects = convert_to_field_input_states(data)

        calc_request = CalculationRequest(
            entity_id=version.entity_id,
            entity_version_id=version.id,
            current_state=current_state_objects
        )

        logger.debug(
            f"Calculating state for version {version.id} with {len(data)} field inputs"
        )

        calc_result: CalculationResponse = engine_service.calculate_state(db, calc_request)

        logger.info(
            f"State calculation completed for version {version.id}: "
            f"is_complete={calc_result.is_complete}"
        )

        return calc_result

    except ValueError as e:
        logger.error(f"Configuration calculation failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Configuration calculation failed: {str(e)}"
        )


# ============================================================
# STATUS GUARDS
# ============================================================

def require_draft_status(config: Configuration, operation: str) -> None:
    """
    Guard clause that ensures configuration is in DRAFT status.

    Raises:
        HTTPException(409): If configuration is FINALIZED
    """
    if config.status == ConfigurationStatus.FINALIZED or config.status == ConfigurationStatus.FINALIZED.value:
        logger.warning(
            f"Operation '{operation}' blocked: configuration {config.id} is FINALIZED"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot {operation} a FINALIZED configuration. "
                "Use POST /configurations/{id}/clone to create a modifiable copy."
            )
        )


def require_complete_status(config: Configuration) -> None:
    """
    Guard clause that ensures configuration is complete before finalization.

    Raises:
        HTTPException(400): If configuration is not complete
    """
    if not config.is_complete:
        logger.warning(
            f"Finalization blocked: configuration {config.id} is not complete"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Cannot finalize an incomplete configuration. "
                "Ensure all required fields are filled before finalizing."
            )
        )


def check_soft_delete_permission(config: Configuration, user: User) -> None:
    """
    Validates that user can soft-delete a configuration.

    - DRAFT configurations: Owner or ADMIN can delete
    - FINALIZED configurations: Only ADMIN can soft-delete

    Raises:
        HTTPException(403): If user lacks permission for the operation
    """
    is_finalized = (
        config.status == ConfigurationStatus.FINALIZED or
        config.status == ConfigurationStatus.FINALIZED.value
    )

    if is_finalized and user.role != UserRole.ADMIN:
        logger.warning(
            f"Soft delete denied: user {user.id} ({user.role_display}) "
            f"attempted to delete FINALIZED configuration {config.id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only administrators can delete FINALIZED configurations. "
                "Use POST /configurations/{id}/clone to create a modifiable copy."
            )
        )


def get_latest_published_version(db: Session, entity_id: int) -> EntityVersion:
    """
    Retrieves the latest PUBLISHED version for an entity.

    Args:
        db: Database session
        entity_id: The entity to find the version for

    Returns:
        EntityVersion: The PUBLISHED version

    Raises:
        HTTPException(404): If no PUBLISHED version exists
    """
    version = db.query(EntityVersion).filter(
        EntityVersion.entity_id == entity_id,
        EntityVersion.status == VersionStatus.PUBLISHED.value
    ).first()

    if not version:
        logger.warning(f"No PUBLISHED version found for entity {entity_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No PUBLISHED version available for this entity."
        )

    return version


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
    current_user: User = Depends(get_current_user),
    engine_service: RuleEngineService = Depends(get_rule_engine_service)
):
    """
    Creates a new user configuration (snapshot of inputs).

    - Calculates and stores the is_complete flag
    - Accepts any Entity Version (Draft, Published, Archived) for ADMINs/AUTHORs
    - Regular USERs can only save PUBLISHED versions
    - Owner automatically assigned from JWT token

    Returns:
        ConfigurationRead: The created configuration
    """
    logger.info(
        f"Creating configuration for version {config_in.entity_version_id} "
        f"by user {current_user.id} (role: {current_user.role_display})"
    )

    # Validation phase
    version = fetch_version_by_id(db, config_in.entity_version_id)
    validate_user_can_save_version(current_user, version)

    data_list: List[Dict[str, Any]] = config_in.model_dump()['data']
    validate_input_data_integrity(db, config_in.entity_version_id, data_list)

    # Calculation phase
    calc_result: CalculationResponse = calculate_configuration_state(
        db=db,
        engine_service=engine_service,
        version=version,
        data=data_list
    )

    # Transaction phase
    with db_transaction(db, f"create_configuration for version {version.id}"):
        new_config = Configuration(
            entity_version_id=config_in.entity_version_id,
            user_id=current_user.id,
            name=config_in.name,
            is_complete=calc_result.is_complete,
            data=data_list,
            created_by_id=current_user.id
            # updated_by_id intentionally NULL: record not yet modified
        )

        db.add(new_config)
        db.flush()  # Get ID before commit

        logger.info(
            f"Configuration {new_config.id} created successfully: "
            f"name='{config_in.name}', is_complete={calc_result.is_complete}"
        )

    db.refresh(new_config)
    return new_config


@router.get("/", response_model=List[ConfigurationRead])
def list_configurations(
    entity_version_id: Optional[int] = None,
    user_id: Optional[str] = None,
    # Aliased to "status" in the API; named config_status internally to avoid conflict with fastapi.status
    config_status: Optional[str] = Query(None, alias="status"),
    include_deleted: bool = False,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Lists configurations with role-based access control.

    - ADMIN: Can view all configurations, optionally filtered by user_id
    - AUTHOR/USER: Can only view their own configurations

    Query Parameters:
        entity_version_id: Filter by specific version
        user_id: Filter by user (ADMIN only)
        status: Filter by status (DRAFT or FINALIZED)
        include_deleted: Include soft-deleted records (ADMIN only, default False)
        skip: Pagination offset
        limit: Maximum results (max 100)

    Returns:
        List[ConfigurationRead]: Filtered configurations, newest first
    """
    logger.info(
        f"Listing configurations: user={current_user.id}, role={current_user.role_display}, "
        f"version_id={entity_version_id}, filter_user_id={user_id}, status={config_status}"
    )

    query = db.query(Configuration)

    # Soft delete filter (ADMIN can override)
    if include_deleted and current_user.role != UserRole.ADMIN:
        logger.warning(
            f"Non-admin user {current_user.id} attempted to include deleted configurations"
        )
        include_deleted = False

    if not include_deleted:
        query = query.filter(Configuration.is_deleted == False)

    # Apply role-based filtering
    if current_user.role == UserRole.ADMIN:
        if user_id:
            query = query.filter(Configuration.user_id == user_id)
            logger.debug(f"Admin filtering by user_id: {user_id}")
    else:
        if user_id is not None and user_id != current_user.id:
            logger.warning(
                f"Non-admin user {current_user.id} attempted to list configurations "
                f"for other user {user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot list configurations belonging to other users."
            )
        # Force filter to current user
        query = query.filter(Configuration.user_id == current_user.id)

    # Optional version filter
    if entity_version_id:
        query = query.filter(Configuration.entity_version_id == entity_version_id)
        logger.debug(f"Filtering by version_id: {entity_version_id}")

    # Optional status filter
    if config_status:
        if config_status.upper() in [s.value for s in ConfigurationStatus]:
            query = query.filter(Configuration.status == config_status.upper())
            logger.debug(f"Filtering by status: {config_status.upper()}")
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {[s.value for s in ConfigurationStatus]}"
            )

    # Execute with pagination
    original_limit = limit
    limit = min(limit, 100)

    if original_limit > 100:
        logger.warning(f"Limit capped from {original_limit} to 100")

    results = query.order_by(
        Configuration.updated_at.desc()
    ).offset(skip).limit(limit).all()

    logger.info(f"Returning {len(results)} configurations")

    return results


@router.get("/{config_id}", response_model=ConfigurationRead)
def read_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieves a single configuration by ID.

    Access Control:
        - Only owner or ADMIN can access

    Returns:
        ConfigurationRead: The requested configuration
    """
    logger.info(f"Reading configuration {config_id} by user {current_user.id}")
    return get_configuration_or_404(db, config_id, current_user)


@router.patch("/{config_id}", response_model=ConfigurationRead)
def update_configuration(
    config_id: str,
    config_update: ConfigurationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    engine_service: RuleEngineService = Depends(get_rule_engine_service)
):
    """
    Updates a configuration's name or data inputs.

    - Recalculates is_complete if data changes
    - Cannot change the linked entity_version_id (data integrity)

    Access Control:
        - Only owner or ADMIN can update
        - Only DRAFT configurations can be updated

    Status Constraint:
        - Returns HTTP 409 Conflict if configuration is FINALIZED

    Returns:
        ConfigurationRead: The updated configuration
    """
    logger.info(f"Updating configuration {config_id} by user {current_user.id}")

    config = get_configuration_or_404(db, config_id, current_user)

    # Guard clause: block updates on FINALIZED configurations
    require_draft_status(config, "update")

    # Extract only provided fields
    update_data: Dict[str, Any] = config_update.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning(f"Empty update request for configuration {config_id}")
        return config

    # Data update logic
    if "data" in update_data:
        logger.debug(f"Recalculating state for configuration {config_id} due to data update")

        validate_input_data_integrity(db, config.entity_version_id, update_data["data"])

        version = validate_version_not_orphaned(
            config.entity_version,
            config.entity_version_id
        )

        calc_result: CalculationResponse = calculate_configuration_state(
            db=db,
            engine_service=engine_service,
            version=version,
            data=update_data["data"]
        )

        update_data["is_complete"] = calc_result.is_complete
        logger.info(f"Recalculated is_complete: {calc_result.is_complete}")

    # Transaction phase
    with db_transaction(db, f"update_configuration {config_id}"):
        for key, value in update_data.items():
            setattr(config, key, value)

        config.updated_by_id = current_user.id

        logger.info(f"Configuration {config_id} updated successfully")

    db.refresh(config)
    return config


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Deletes a saved configuration.

    Deletion Strategy by Status:
        - DRAFT: Hard delete (physical removal from database)
        - FINALIZED: Soft delete (is_deleted=True) to preserve audit trail

    Access Control:
        - DRAFT: Owner or ADMIN can delete
        - FINALIZED: Only ADMIN can soft-delete

    Returns:
        204 No Content on success
    """
    logger.info(f"Deleting configuration {config_id} by user {current_user.id}")

    config = get_configuration_or_404(db, config_id, current_user)

    is_finalized = (
        config.status == ConfigurationStatus.FINALIZED or
        config.status == ConfigurationStatus.FINALIZED.value
    )

    if is_finalized:
        # FINALIZED: Soft delete only, ADMIN only
        check_soft_delete_permission(config, current_user)

        with db_transaction(db, f"soft_delete_configuration {config_id}"):
            config.is_deleted = True
            config.updated_by_id = current_user.id
            logger.info(
                f"Configuration {config_id} soft-deleted by ADMIN {current_user.id}"
            )
    else:
        # DRAFT: Hard delete allowed for owner or ADMIN
        with db_transaction(db, f"delete_configuration {config_id}"):
            db.delete(config)
            logger.info(f"Configuration {config_id} hard-deleted successfully")

    return None


# ============================================================
# CALCULATION ENDPOINT (Re-hydration)
# ============================================================

@router.get("/{config_id}/calculate", response_model=CalculationResponse)
def load_and_calculate_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    logger.info(f"Loading and calculating configuration {config_id} by user {current_user.id}")

    config = get_configuration_or_404(db, config_id, current_user)

    version = validate_version_not_orphaned(
        config.entity_version,
        config.entity_version_id
    )

    try:
        current_state_objects = convert_to_field_input_states(config.data)

        engine_payload = CalculationRequest(
            entity_id=version.entity_id,
            entity_version_id=version.id,
            current_state=current_state_objects
        )

        result = engine_service.calculate_state(db, engine_payload)

        logger.info(
            f"Configuration {config_id} recalculated: is_complete={result.is_complete}"
        )

        return result

    except ValueError as e:
        logger.error(
            f"Calculation error for configuration {config_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Calculation error: {str(e)}"
        )

    except Exception as e:
        logger.critical(
            f"Unexpected error during calculation for configuration {config_id}: {str(e)}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during calculation: {str(e)}"
        )


# ============================================================
# LIFECYCLE MANAGEMENT ENDPOINTS
# ============================================================

@router.post("/{config_id}/clone", response_model=ConfigurationCloneResponse, status_code=status.HTTP_201_CREATED)
def clone_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Creates an exact copy of an existing configuration.

    Non-Destructive Operation:
        - The source configuration remains unchanged
        - A new configuration is created with a fresh UUID
        - The clone always starts in DRAFT status (regardless of source status)

    Cloned Data:
        - input data (payload JSON)
        - entity_version_id reference
        - name (with " (Copy)" suffix)

    Use Cases:
        - Reopen work on a FINALIZED configuration without altering the original
        - Create variations of an existing configuration
        - Duplicate a configuration for another purpose

    Access Control:
        - Only owner or ADMIN can clone

    Returns:
        ConfigurationCloneResponse: The newly created configuration with source_id
    """
    logger.info(f"Cloning configuration {config_id} by user {current_user.id}")

    source = get_configuration_or_404(db, config_id, current_user)

    # Prepare cloned data with name truncation to respect 100 char limit
    new_name = None
    if source.name:
        suffix = " (Copy)"
        max_base_length = 100 - len(suffix)  # 93 characters for base name
        base_name = source.name[:max_base_length] if len(source.name) > max_base_length else source.name
        new_name = f"{base_name}{suffix}"

    with db_transaction(db, f"clone_configuration {config_id}"):
        cloned_config = Configuration(
            id=str(uuid.uuid4()),
            entity_version_id=source.entity_version_id,
            user_id=current_user.id,
            name=new_name,
            status=ConfigurationStatus.DRAFT,  # Always DRAFT
            is_complete=source.is_complete,
            is_deleted=False,
            data=source.data.copy() if source.data else [],
            created_by_id=current_user.id
            # updated_by_id intentionally NULL: record not yet modified
        )

        db.add(cloned_config)
        db.flush()

        logger.info(
            f"Configuration {config_id} cloned to {cloned_config.id} "
            f"(source status: {source.status}, clone status: DRAFT)"
        )

    db.refresh(cloned_config)

    # Build response with source_id
    response = ConfigurationCloneResponse(
        id=cloned_config.id,
        entity_version_id=cloned_config.entity_version_id,
        name=cloned_config.name,
        status=ConfigurationStatusEnum(cloned_config.status),
        is_complete=cloned_config.is_complete,
        is_deleted=cloned_config.is_deleted,
        data=convert_to_field_input_states(cloned_config.data),
        created_at=cloned_config.created_at,
        updated_at=cloned_config.updated_at,
        created_by_id=cloned_config.created_by_id,
        updated_by_id=cloned_config.updated_by_id,
        source_id=config_id
    )

    return response


@router.post("/{config_id}/upgrade", response_model=ConfigurationRead)
def upgrade_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    engine_service: RuleEngineService = Depends(get_rule_engine_service)
):
    """
    Upgrades a configuration to the latest PUBLISHED version.

    Destructive In-Place Operation:
        - Updates entity_version_id to the latest PUBLISHED version
        - Preserves the existing input data (user selections)
        - Recalculates is_complete with the new version's rules

    Status Constraint:
        - Only DRAFT configurations can be upgraded
        - Returns HTTP 409 Conflict if configuration is FINALIZED

    Use Cases:
        - Update a saved draft to use newer product rules
        - Migrate configurations when new versions are published

    Access Control:
        - Only owner or ADMIN can upgrade

    Returns:
        ConfigurationRead: The updated configuration

    Raises:
        404: If no PUBLISHED version exists for the entity
        409: If configuration is FINALIZED
    """
    logger.info(f"Upgrading configuration {config_id} by user {current_user.id}")

    config = get_configuration_or_404(db, config_id, current_user)

    # Guard clause: only DRAFT can be upgraded
    require_draft_status(config, "upgrade")

    # Get current version to find entity_id
    current_version = validate_version_not_orphaned(
        config.entity_version,
        config.entity_version_id
    )

    # Find latest PUBLISHED version
    latest_version = get_latest_published_version(db, current_version.entity_id)

    if latest_version.id == config.entity_version_id:
        logger.info(
            f"Configuration {config_id} already on latest version {latest_version.id}"
        )
        return config

    # Recalculate state with new version
    logger.debug(
        f"Upgrading configuration {config_id} from version "
        f"{config.entity_version_id} to {latest_version.id}"
    )

    calc_result = calculate_configuration_state(
        db=db,
        engine_service=engine_service,
        version=latest_version,
        data=config.data
    )

    with db_transaction(db, f"upgrade_configuration {config_id}"):
        config.entity_version_id = latest_version.id
        config.is_complete = calc_result.is_complete
        config.updated_by_id = current_user.id

        logger.info(
            f"Configuration {config_id} upgraded to version {latest_version.id}, "
            f"is_complete={calc_result.is_complete}"
        )

    db.refresh(config)
    return config


@router.post("/{config_id}/finalize", response_model=ConfigurationRead)
def finalize_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Finalizes a configuration, making it immutable.

    Unidirectional State Transition:
        - Transitions status from DRAFT to FINALIZED
        - Once finalized, the configuration becomes read-only
        - Cannot be undone (use clone to create a new editable copy)

    Completeness Requirement:
        - Only configurations with is_complete=True can be finalized
        - Ensures all required fields are filled before locking

    Immutability Guarantees:
        - Input data cannot be modified
        - Version reference cannot be changed
        - Record cannot be hard-deleted (only soft-deleted by ADMIN)

    Use Cases:
        - Lock a quote before sending to customer
        - Freeze an order configuration before submission
        - Create an audit-compliant snapshot

    Access Control:
        - Only owner or ADMIN can finalize

    Returns:
        ConfigurationRead: The finalized configuration

    Raises:
        400: If configuration is not complete (is_complete=False)
        409: If configuration is already FINALIZED
    """
    logger.info(f"Finalizing configuration {config_id} by user {current_user.id}")

    config = get_configuration_or_404(db, config_id, current_user)

    # Check if already finalized
    is_finalized = (
        config.status == ConfigurationStatus.FINALIZED or
        config.status == ConfigurationStatus.FINALIZED.value
    )

    if is_finalized:
        logger.warning(f"Configuration {config_id} is already FINALIZED")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configuration is already FINALIZED."
        )

    # Guard clause: only complete configurations can be finalized
    require_complete_status(config)

    with db_transaction(db, f"finalize_configuration {config_id}"):
        config.status = ConfigurationStatus.FINALIZED
        config.updated_by_id = current_user.id

        logger.info(
            f"Configuration {config_id} finalized by user {current_user.id}"
        )

    db.refresh(config)
    return config