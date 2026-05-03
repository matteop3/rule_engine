import datetime as dt
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    _is_finalized,
    db_transaction,
    fetch_version_by_id,
    get_current_user,
    get_rule_engine_service,
    require_complete_status,
    require_draft_status,
)
from app.models.domain import (
    Configuration,
    ConfigurationCustomItem,
    ConfigurationStatus,
    EntityVersion,
    Field,
    PriceList,
    User,
    UserRole,
    VersionStatus,
)
from app.schemas.configuration import (
    ConfigurationCloneResponse,
    ConfigurationCreate,
    ConfigurationRead,
    ConfigurationStatusEnum,
    ConfigurationUpdate,
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

router = APIRouter(prefix="/configurations", tags=["Configurations"])


# ============================================================
# VALIDATION HELPERS
# ============================================================


def validate_input_data_integrity(db: Session, version_id: int, data: list[dict[str, Any]]) -> None:
    """Reject `data` if it has duplicate `field_id`s or any `field_id` not in `version_id`."""
    if not data:
        return

    input_field_ids = [item["field_id"] for item in data]

    # Check for duplicates
    if len(input_field_ids) != len(set(input_field_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate field_ids found in data. Each field can appear only once.",
        )

    # Validate field existence
    valid_fields_count = (
        db.query(Field).filter(Field.entity_version_id == version_id, Field.id.in_(input_field_ids)).count()
    )

    if valid_fields_count != len(input_field_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more field_ids in the data do not belong to the specified Entity Version.",
        )

    logger.debug(f"Input data validation passed for version {version_id}: {len(input_field_ids)} fields")


def require_user_can_access_configuration(config: Configuration, user: User) -> None:
    """Raise 403 unless `user` owns `config` or is ADMIN."""
    if config.user_id != user.id and user.role != UserRole.ADMIN:
        logger.warning(
            f"Access denied: User {user.id} ({user.role_display}) attempted to access "
            f"configuration {config.id} owned by {config.user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to access this configuration."
        )


def get_configuration_or_404(db: Session, config_id: str, user: User) -> Configuration:
    """Fetch a configuration and enforce ownership/ADMIN access (404 if missing, 403 if not allowed)."""
    config = db.query(Configuration).filter(Configuration.id == config_id).first()

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found.")

    require_user_can_access_configuration(config, user)
    logger.debug(f"Configuration {config_id} retrieved by user {user.id}")

    return config


def validate_user_can_save_version(user: User, version: EntityVersion) -> None:
    """Raise 400 if `user` is a regular USER and `version` is not PUBLISHED."""
    if user.role == UserRole.USER and version.status != VersionStatus.PUBLISHED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Regular users can only save configurations for PUBLISHED versions.",
        )


def validate_price_list_exists(db: Session, price_list_id: int) -> PriceList:
    """Return the `PriceList` or raise 422 if it does not exist."""
    price_list = db.query(PriceList).filter(PriceList.id == price_list_id).first()
    if not price_list:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Price list {price_list_id} not found.",
        )
    return price_list


def validate_version_not_orphaned(version: EntityVersion | None, version_id: int) -> EntityVersion:
    """Return `version` or raise 500 if `None` (configuration points at a missing `EntityVersion`)."""
    if not version:
        logger.error(f"Orphaned configuration detected: version {version_id} not found")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Orphaned configuration: linked version not found.",
        )
    return version


# ============================================================
# CALCULATION HELPERS
# ============================================================


def convert_to_field_input_states(data: list[dict[str, Any]]) -> list[FieldInputState]:
    """Convert raw `[{"field_id": ..., "value": ...}, ...]` dicts to `FieldInputState` instances."""
    return [FieldInputState(**item) for item in data]


def calculate_configuration_state(
    db: Session,
    engine_service: RuleEngineService,
    version: EntityVersion,
    data: list[dict[str, Any]],
    price_list_id: int | None = None,
    price_date: dt.date | None = None,
    configuration_id: str | None = None,
) -> CalculationResponse:
    """Run the rule engine against `data`; raises 400 on `ValueError` from the engine.

    When `configuration_id` is provided, custom items are appended to the commercial BOM.
    """
    try:
        current_state_objects = convert_to_field_input_states(data)

        calc_request = CalculationRequest(
            entity_id=version.entity_id,
            entity_version_id=version.id,
            current_state=current_state_objects,
            price_list_id=price_list_id,
            price_date=price_date,
            configuration_id=configuration_id,
        )

        logger.debug(f"Calculating state for version {version.id} with {len(data)} field inputs")

        calc_result: CalculationResponse = engine_service.calculate_state(db, calc_request)

        logger.info(f"State calculation completed for version {version.id}: is_complete={calc_result.is_complete}")

        return calc_result

    except ValueError as e:
        logger.error(f"Configuration calculation failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Configuration calculation failed: {str(e)}"
        ) from None


# ============================================================
# STATUS GUARDS
# ============================================================


def require_soft_delete_permission(config: Configuration, user: User) -> None:
    """Raise 403 if a non-ADMIN tries to soft-delete a FINALIZED configuration."""
    if _is_finalized(config) and user.role != UserRole.ADMIN:
        logger.warning(
            f"Soft delete denied: user {user.id} ({user.role_display}) "
            f"attempted to delete FINALIZED configuration {config.id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only administrators can delete FINALIZED configurations. "
                "Use POST /configurations/{id}/clone to create a modifiable copy."
            ),
        )


def get_latest_published_version(db: Session, entity_id: int) -> EntityVersion:
    """Return the PUBLISHED version of `entity_id` or raise 404."""
    version = (
        db.query(EntityVersion)
        .filter(EntityVersion.entity_id == entity_id, EntityVersion.status == VersionStatus.PUBLISHED.value)
        .first()
    )

    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No PUBLISHED version available for this entity."
        )

    return version


# ============================================================
# CRUD ENDPOINTS
# ============================================================


@router.post("/", response_model=ConfigurationRead, status_code=status.HTTP_201_CREATED)
def create_configuration(
    config_in: ConfigurationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    engine_service: RuleEngineService = Depends(get_rule_engine_service),
):
    """Create a configuration; computes `is_complete` on creation.

    ADMIN/AUTHOR may save against any `EntityVersion`; USER only against PUBLISHED.
    """
    logger.info(
        f"Creating configuration for version {config_in.entity_version_id} "
        f"by user {current_user.id} (role: {current_user.role_display})"
    )

    # Validation phase
    version = fetch_version_by_id(db, config_in.entity_version_id)
    validate_user_can_save_version(current_user, version)
    validate_price_list_exists(db, config_in.price_list_id)

    data_list: list[dict[str, Any]] = config_in.model_dump()["data"]
    validate_input_data_integrity(db, config_in.entity_version_id, data_list)

    # Calculation phase
    calc_result: CalculationResponse = calculate_configuration_state(
        db=db,
        engine_service=engine_service,
        version=version,
        data=data_list,
        price_list_id=config_in.price_list_id,
        price_date=dt.date.today(),
    )

    # Transaction phase
    with db_transaction(db, f"create_configuration for version {version.id}"):
        new_config = Configuration(
            entity_version_id=config_in.entity_version_id,
            user_id=current_user.id,
            name=config_in.name,
            price_list_id=config_in.price_list_id,
            is_complete=calc_result.is_complete,
            generated_sku=calc_result.generated_sku,
            bom_total_price=calc_result.bom.commercial_total if calc_result.bom else None,
            data=data_list,
            created_by_id=current_user.id,
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


@router.get("/", response_model=list[ConfigurationRead])
def list_configurations(
    entity_version_id: int | None = None,
    user_id: str | None = None,
    price_list_id: int | None = None,
    # Aliased to "status" in the API; named config_status internally to avoid conflict with fastapi.status
    config_status: str | None = Query(None, alias="status"),
    include_deleted: bool = False,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List configurations newest first; ADMIN sees all (optional `user_id` filter), others only their own.

    `include_deleted` is silently ignored for non-ADMIN. `status` accepts DRAFT or FINALIZED.
    """
    logger.info(
        f"Listing configurations: user={current_user.id}, role={current_user.role_display}, "
        f"version_id={entity_version_id}, filter_user_id={user_id}, status={config_status}"
    )

    query = db.query(Configuration)

    # Soft delete filter (ADMIN can override)
    if include_deleted and current_user.role != UserRole.ADMIN:
        logger.warning(f"Non-admin user {current_user.id} attempted to include deleted configurations")
        include_deleted = False

    if not include_deleted:
        query = query.filter(Configuration.is_deleted.is_(False))

    # Apply role-based filtering
    if current_user.role == UserRole.ADMIN:
        if user_id:
            query = query.filter(Configuration.user_id == user_id)
            logger.debug(f"Admin filtering by user_id: {user_id}")
    else:
        if user_id is not None and user_id != current_user.id:
            logger.warning(
                f"Non-admin user {current_user.id} attempted to list configurations for other user {user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="You cannot list configurations belonging to other users."
            )
        # Force filter to current user
        query = query.filter(Configuration.user_id == current_user.id)

    # Optional version filter
    if entity_version_id:
        query = query.filter(Configuration.entity_version_id == entity_version_id)
        logger.debug(f"Filtering by version_id: {entity_version_id}")

    # Optional price list filter
    if price_list_id is not None:
        query = query.filter(Configuration.price_list_id == price_list_id)
        logger.debug(f"Filtering by price_list_id: {price_list_id}")

    # Optional status filter
    if config_status:
        if config_status.upper() in [s.value for s in ConfigurationStatus]:
            query = query.filter(Configuration.status == config_status.upper())
            logger.debug(f"Filtering by status: {config_status.upper()}")
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {[s.value for s in ConfigurationStatus]}",
            )

    limit = min(limit, 100)

    results = query.order_by(Configuration.updated_at.desc()).offset(skip).limit(limit).all()

    logger.info(f"Returning {len(results)} configurations")

    return results


@router.get("/{config_id}", response_model=ConfigurationRead)
def read_configuration(config_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a single configuration. Owner or ADMIN only."""
    return get_configuration_or_404(db, config_id, current_user)


@router.patch("/{config_id}", response_model=ConfigurationRead)
def update_configuration(
    config_id: str,
    config_update: ConfigurationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    engine_service: RuleEngineService = Depends(get_rule_engine_service),
):
    """Update a DRAFT configuration; recalculates `is_complete` when `data` or `price_list_id` change.

    `entity_version_id` is immutable here; FINALIZED configurations are rejected with 409.
    """

    config = get_configuration_or_404(db, config_id, current_user)

    # Guard clause: block updates on FINALIZED configurations
    require_draft_status(config, "update")

    # Extract only provided fields
    update_data: dict[str, Any] = config_update.model_dump(exclude_unset=True)

    if not update_data:
        return config

    # Validate price_list_id if provided
    if "price_list_id" in update_data and update_data["price_list_id"] is not None:
        validate_price_list_exists(db, update_data["price_list_id"])

    # Data update logic — recalculate if data or price_list_id changed
    if "data" in update_data or "price_list_id" in update_data:
        data_for_calc = update_data.get("data", config.data)
        effective_price_list_id = update_data.get("price_list_id", config.price_list_id)

        if "data" in update_data:
            validate_input_data_integrity(db, config.entity_version_id, data_for_calc)

        version = validate_version_not_orphaned(config.entity_version, config.entity_version_id)

        logger.debug(f"Recalculating state for configuration {config_id}")

        calc_result: CalculationResponse = calculate_configuration_state(
            db=db,
            engine_service=engine_service,
            version=version,
            data=data_for_calc,
            price_list_id=effective_price_list_id,
            price_date=dt.date.today(),
            configuration_id=config.id,
        )

        update_data["is_complete"] = calc_result.is_complete
        update_data["generated_sku"] = calc_result.generated_sku
        update_data["bom_total_price"] = calc_result.bom.commercial_total if calc_result.bom else None
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
def delete_configuration(config_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a configuration: hard-delete for DRAFT, soft-delete (`is_deleted=True`) for FINALIZED.

    DRAFT can be deleted by owner or ADMIN; FINALIZED only by ADMIN.
    """

    config = get_configuration_or_404(db, config_id, current_user)

    if _is_finalized(config):
        # FINALIZED: Soft delete only, ADMIN only
        require_soft_delete_permission(config, current_user)

        with db_transaction(db, f"soft_delete_configuration {config_id}"):
            config.is_deleted = True
            config.updated_by_id = current_user.id
            logger.info(f"Configuration {config_id} soft-deleted by ADMIN {current_user.id}")
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
    engine_service: RuleEngineService = Depends(get_rule_engine_service),
):
    """Recalculate a configuration; FINALIZED configs return their stored snapshot directly."""

    config = get_configuration_or_404(db, config_id, current_user)
    is_finalized = _is_finalized(config)

    # FINALIZED with snapshot: return stored snapshot directly (no recalculation)
    if is_finalized and config.snapshot is not None:
        logger.info(f"Returning snapshot for FINALIZED configuration {config_id}")
        return CalculationResponse(**config.snapshot)

    # DRAFT or FINALIZED without snapshot (backward compatibility): rehydrate
    if not config.price_list_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Configuration has no price list assigned.",
        )

    version = validate_version_not_orphaned(config.entity_version, config.entity_version_id)

    try:
        return calculate_configuration_state(
            db=db,
            engine_service=engine_service,
            version=version,
            data=config.data,
            price_list_id=config.price_list_id,
            price_date=config.price_date if is_finalized else dt.date.today(),
            configuration_id=config.id,
        )

    except HTTPException:
        # Pass through 400 raised by calculate_configuration_state on engine ValueError.
        raise

    except Exception as e:
        logger.critical(f"Unexpected error during calculation for configuration {config_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during calculation: {str(e)}",
        ) from None


# ============================================================
# LIFECYCLE MANAGEMENT ENDPOINTS
# ============================================================


@router.post("/{config_id}/clone", response_model=ConfigurationCloneResponse, status_code=status.HTTP_201_CREATED)
def clone_configuration(config_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Clone a configuration into a fresh DRAFT (with a `(Copy)` suffix on the name).

    Custom items are copied with fresh `custom_key` values so source and clone never share keys.
    """

    source = get_configuration_or_404(db, config_id, current_user)

    # Prepare cloned data with name truncation to respect 100 char limit
    new_name = None
    if source.name:
        suffix = " (Copy)"
        max_base_length = 100 - len(suffix)  # 93 characters for base name
        base_name = source.name[:max_base_length] if len(source.name) > max_base_length else source.name
        new_name = f"{base_name}{suffix}"

    source_custom_items = (
        db.query(ConfigurationCustomItem)
        .filter(ConfigurationCustomItem.configuration_id == source.id)
        .order_by(ConfigurationCustomItem.sequence, ConfigurationCustomItem.id)
        .all()
    )

    with db_transaction(db, f"clone_configuration {config_id}"):
        cloned_config = Configuration(
            id=str(uuid.uuid4()),
            entity_version_id=source.entity_version_id,
            user_id=current_user.id,
            name=new_name,
            status=ConfigurationStatus.DRAFT,  # Always DRAFT
            is_complete=source.is_complete,
            generated_sku=source.generated_sku,
            bom_total_price=source.bom_total_price,
            price_list_id=source.price_list_id,
            is_deleted=False,
            data=source.data.copy() if source.data else [],
            created_by_id=current_user.id,
            # updated_by_id intentionally NULL: record not yet modified
        )

        db.add(cloned_config)
        db.flush()

        # Copy custom items with fresh custom_key values so source and clone
        # never share keys (future promotions or histories may diverge).
        for src_item in source_custom_items:
            db.add(
                ConfigurationCustomItem(
                    configuration_id=cloned_config.id,
                    custom_key=f"CUSTOM-{uuid.uuid4().hex[:8]}",
                    description=src_item.description,
                    quantity=src_item.quantity,
                    unit_price=src_item.unit_price,
                    unit_of_measure=src_item.unit_of_measure,
                    sequence=src_item.sequence,
                    created_by_id=current_user.id,
                )
            )

        logger.info(
            f"Configuration {config_id} cloned to {cloned_config.id} "
            f"(source status: {source.status}, clone status: DRAFT, "
            f"custom_items copied: {len(source_custom_items)})"
        )

    db.refresh(cloned_config)

    # Build response with source_id
    response = ConfigurationCloneResponse(
        id=cloned_config.id,
        entity_version_id=cloned_config.entity_version_id,
        name=cloned_config.name,
        status=ConfigurationStatusEnum(cloned_config.status),
        is_complete=cloned_config.is_complete,
        generated_sku=cloned_config.generated_sku,
        bom_total_price=cloned_config.bom_total_price,
        price_list_id=cloned_config.price_list_id,
        is_deleted=cloned_config.is_deleted,
        data=convert_to_field_input_states(cloned_config.data),
        created_at=cloned_config.created_at,
        updated_at=cloned_config.updated_at,
        created_by_id=cloned_config.created_by_id,
        updated_by_id=cloned_config.updated_by_id,
        source_id=config_id,
    )

    return response


@router.post("/{config_id}/upgrade", response_model=ConfigurationRead)
def upgrade_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    engine_service: RuleEngineService = Depends(get_rule_engine_service),
):
    """Re-point a DRAFT configuration at the latest PUBLISHED version, recalculating `is_complete`.

    Inputs (`data`) are preserved; FINALIZED configurations are rejected with 409.
    """

    config = get_configuration_or_404(db, config_id, current_user)

    # Guard clause: only DRAFT can be upgraded
    require_draft_status(config, "upgrade")

    # Get current version to find entity_id
    current_version = validate_version_not_orphaned(config.entity_version, config.entity_version_id)

    # Find latest PUBLISHED version
    latest_version = get_latest_published_version(db, current_version.entity_id)

    if latest_version.id == config.entity_version_id:
        logger.info(f"Configuration {config_id} already on latest version {latest_version.id}")
        return config

    # Recalculate state with new version
    logger.debug(f"Upgrading configuration {config_id} from version {config.entity_version_id} to {latest_version.id}")

    calc_result = calculate_configuration_state(
        db=db,
        engine_service=engine_service,
        version=latest_version,
        data=config.data,
        price_list_id=config.price_list_id,
        price_date=dt.date.today(),
        configuration_id=config.id,
    )

    with db_transaction(db, f"upgrade_configuration {config_id}"):
        config.entity_version_id = latest_version.id
        config.is_complete = calc_result.is_complete
        config.generated_sku = calc_result.generated_sku
        config.bom_total_price = calc_result.bom.commercial_total if calc_result.bom else None
        config.updated_by_id = current_user.id

        logger.info(
            f"Configuration {config_id} upgraded to version {latest_version.id}, is_complete={calc_result.is_complete}"
        )

    db.refresh(config)
    return config


@router.post("/{config_id}/finalize", response_model=ConfigurationRead)
def finalize_configuration(
    config_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    engine_service: RuleEngineService = Depends(get_rule_engine_service),
):
    """Finalize a DRAFT configuration; recalculates with today's `price_date` and stores a snapshot.

    Requires `is_complete=True` (else 400); already-FINALIZED configurations return 409.
    Once finalized, the configuration is immutable (snapshot frozen, prices locked).
    """

    config = get_configuration_or_404(db, config_id, current_user)

    if _is_finalized(config):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Configuration is already FINALIZED.")

    # Guard clause: only complete configurations can be finalized
    require_complete_status(config)

    # Recalculate with today's price to lock current prices at finalization.
    version = validate_version_not_orphaned(config.entity_version, config.entity_version_id)
    today = dt.date.today()

    calc_result = calculate_configuration_state(
        db=db,
        engine_service=engine_service,
        version=version,
        data=config.data,
        price_list_id=config.price_list_id,
        price_date=today,
        configuration_id=config.id,
    )

    with db_transaction(db, f"finalize_configuration {config_id}"):
        config.status = ConfigurationStatus.FINALIZED
        config.price_date = today
        config.is_complete = calc_result.is_complete
        config.generated_sku = calc_result.generated_sku
        config.bom_total_price = calc_result.bom.commercial_total if calc_result.bom else None
        config.snapshot = calc_result.model_dump(mode="json")
        config.updated_by_id = current_user.id

        logger.info(f"Configuration {config_id} finalized by user {current_user.id}")

    db.refresh(config)
    return config
