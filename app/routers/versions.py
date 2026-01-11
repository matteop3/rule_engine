import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db
from app.dependencies import (
    validate_version_is_draft,
    fetch_version_by_id,
    require_admin_or_author,
    get_versioning_service,
    db_transaction
)
from app.models.domain import EntityVersion, VersionStatus, User
from app.schemas import VersionCreate, VersionRead, VersionUpdate, VersionClone
from app.services.versioning import VersioningService


# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)


# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(
    prefix="/versions",
    tags=["Versions"]
)


# ============================================================
# ERROR HANDLING HELPERS
# ============================================================

def handle_service_error(e: ValueError, context: str = "") -> HTTPException:
    """
    Converts service ValueError to appropriate HTTP exception.

    Business logic errors from VersioningService are mapped to:
    - 404 for "not found"
    - 409 for "already exists" or "conflict"
    - 400 for other validation errors

    Args:
        e: The ValueError from service layer
        context: Optional context for logging (e.g., "create_version")

    Returns:
        HTTPException: Appropriate HTTP exception
    """
    msg: str = str(e)

    if context:
        logger.error(f"Service error in {context}: {msg}")
    else:
        logger.error(f"Service error: {msg}")

    if "not found" in msg.lower():
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=msg
        )

    if "already exists" in msg.lower() or "conflict" in msg.lower():
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=msg
        )

    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=msg
    )


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/", response_model=List[VersionRead])
def read_versions(
    entity_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Retrieves version history for a specific Entity.

    Access Control:
        - Only ADMIN and AUTHOR can view versions

    Query Parameters:
        entity_id: The Entity to retrieve versions for (required)
        skip: Pagination offset
        limit: Maximum results (max 100)

    Returns:
        List[VersionRead]: Versions ordered by version_number descending (newest first)
    """
    logger.info(
        f"Listing versions for entity {entity_id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    # Cap limit to prevent abuse
    original_limit = limit
    limit = min(limit, 100)

    if original_limit > 100:
        logger.warning(f"Limit capped from {original_limit} to 100")

    versions = db.query(EntityVersion).filter(
        EntityVersion.entity_id == entity_id
    ).order_by(
        EntityVersion.version_number.desc()
    ).offset(skip).limit(limit).all()

    logger.info(f"Returning {len(versions)} versions for entity {entity_id}")

    return versions


@router.get("/{version_id}", response_model=VersionRead)
def read_version(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Retrieves a single version by ID.

    Access Control:
        - Only ADMIN and AUTHOR can view version details

    Returns:
        VersionRead: The requested version
    """
    logger.info(f"Reading version {version_id} by user {current_user.id}")

    version = fetch_version_by_id(db, version_id)

    logger.debug(
        f"Version {version_id} retrieved: entity_id={version.entity_id}, "
        f"status={version.status}, version_number={version.version_number}"
    )

    return version


@router.post("/", response_model=VersionRead, status_code=status.HTTP_201_CREATED)
def create_version_draft(
    version_in: VersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
    versioning_service: VersioningService = Depends(get_versioning_service)
):
    """
    Creates a new DRAFT version for an Entity.

    - Version number is auto-calculated (incremental)
    - Enforces Single Draft Policy (only one DRAFT per Entity)

    Access Control:
        - Only ADMIN and AUTHOR can create versions

    Returns:
        VersionRead: The created DRAFT version
    """
    logger.info(
        f"Creating DRAFT version for entity {version_in.entity_id} "
        f"by user {current_user.id} (role: {current_user.role_display})"
    )

    try:
        with db_transaction(db, f"create_draft_version for entity {version_in.entity_id}"):
            new_version = versioning_service.create_draft_version(
                db=db,
                entity_id=version_in.entity_id,
                user_id=current_user.id,
                changelog=version_in.changelog
            )

            db.flush()

            logger.info(
                f"DRAFT version {new_version.id} created successfully: "
                f"entity_id={version_in.entity_id}, version_number={new_version.version_number}"
            )

        db.refresh(new_version)
        return new_version

    except ValueError as e:
        raise handle_service_error(e, "create_version_draft")


@router.post("/{version_id}/publish", response_model=VersionRead)
def publish_version(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
    versioning_service: VersioningService = Depends(get_versioning_service)
):
    """
    Promotes a DRAFT version to PUBLISHED.

    - Archives any previously PUBLISHED version (Single Published Policy)
    - Only DRAFT versions can be published
    - Existing Configurations on this version become "production data"

    Access Control:
        - Only ADMIN and AUTHOR can publish versions

    Returns:
        VersionRead: The published version
    """
    logger.info(
        f"Publishing version {version_id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    try:
        with db_transaction(db, f"publish_version {version_id}"):
            version = versioning_service.publish_version(
                db=db,
                version_id=version_id,
                user_id=current_user.id
            )

            db.flush()

            logger.info(
                f"Version {version_id} published successfully: "
                f"entity_id={version.entity_id}, version_number={version.version_number}, "
                f"published_at={version.published_at}"
            )

        db.refresh(version)
        return version

    except ValueError as e:
        raise handle_service_error(e, "publish_version")


@router.post("/{version_id}/clone", response_model=VersionRead, status_code=status.HTTP_201_CREATED)
def clone_version(
    version_id: int,
    clone_in: VersionClone,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
    versioning_service: VersioningService = Depends(get_versioning_service)
):
    """
    Creates a new DRAFT version by deep-copying an existing version.

    - Source version can be in any status (DRAFT, PUBLISHED, ARCHIVED)
    - Copies all Fields, Values, and Rules with ID remapping
    - Enforces Single Draft Policy (target entity must not have a DRAFT)

    Access Control:
        - Only ADMIN and AUTHOR can clone versions

    Returns:
        VersionRead: The newly created DRAFT version
    """
    logger.info(
        f"Cloning version {version_id} by user {current_user.id} "
        f"(role: {current_user.role_display})"
    )

    try:
        # Clean Swagger default value hack
        # NOTE: should ideally be handled in Pydantic schema
        clean_changelog: Optional[str] = clone_in.changelog
        if clean_changelog and clean_changelog.strip() == "string":
            clean_changelog = None
            logger.debug("Removed Swagger default 'string' value from changelog")

        with db_transaction(db, f"clone_version {version_id}"):
            new_version = versioning_service.clone_version(
                db=db,
                source_version_id=version_id,
                user_id=current_user.id,
                new_changelog=clean_changelog
            )

            db.flush()

            logger.info(
                f"Version {version_id} cloned successfully to new version {new_version.id}: "
                f"entity_id={new_version.entity_id}, version_number={new_version.version_number}"
            )

        db.refresh(new_version)
        return new_version

    except ValueError as e:
        raise handle_service_error(e, "clone_version")


@router.patch("/{version_id}", response_model=VersionRead)
def update_version_metadata(
    version_id: int,
    version_update: VersionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Updates version metadata (changelog).

    Restrictions:
        - Only DRAFT versions can be modified
        - PUBLISHED/ARCHIVED versions are immutable (history protection)
        - Status changes must use dedicated endpoints (/publish)

    Access Control:
        - Only ADMIN and AUTHOR can update versions

    Returns:
        VersionRead: The updated version
    """
    logger.info(f"Updating metadata for version {version_id} by user {current_user.id}")

    version = fetch_version_by_id(db, version_id)

    # Enforce DRAFT-only modification policy
    validate_version_is_draft(version)

    # Check if there are actual changes
    if version_update.changelog is None:
        logger.warning(f"Empty update request for version {version_id}")
        return version

    try:
        with db_transaction(db, f"update_version_metadata {version_id}"):
            version.changelog = version_update.changelog
            version.updated_by_id = current_user.id

            logger.info(
                f"Version {version_id} metadata updated successfully: "
                f"changelog length={len(version_update.changelog) if version_update.changelog else 0}"
            )

        db.refresh(version)
        return version

    except SQLAlchemyError as e:
        logger.error(f"Database error updating version {version_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.delete("/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(
    version_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author)
):
    """
    Deletes a version.

    Strict Policy:
        - Only DRAFT versions can be deleted
        - PUBLISHED/ARCHIVED versions are protected (history preservation)
        - Cascade deletes all Fields, Values, Rules, and Configurations

    Note: Configurations on DRAFT versions are considered test data
          and will be automatically deleted.

    Access Control:
        - Only ADMIN and AUTHOR can delete versions

    Returns:
        204 No Content on success
    """
    logger.info(f"Deleting version {version_id} by user {current_user.id}")

    version = fetch_version_by_id(db, version_id)

    # Enforce DRAFT-only deletion policy
    validate_version_is_draft(version)

    try:
        with db_transaction(db, f"delete_version {version_id}"):
            entity_id = version.entity_id
            version_number = version.version_number

            # Cascade delete handled by SQLAlchemy relationships
            # (Fields, Values, Rules, Configurations)
            db.delete(version)

            logger.info(
                f"Version {version_id} deleted successfully: "
                f"entity_id={entity_id}, version_number={version_number}"
            )

        return None

    except SQLAlchemyError as e:
        logger.error(f"Database error deleting version {version_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )