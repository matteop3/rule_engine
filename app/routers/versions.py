from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_db
from app.dependencies import get_current_user, require_role, get_version_or_404, validate_version_is_draft
from app.models.domain import EntityVersion, VersionStatus, User, UserRole
from app.schemas import VersionCreate, VersionRead, VersionUpdate, VersionClone
from app.services.versioning import VersioningService

router = APIRouter(
    prefix="/versions",
    tags=["Versions"]
)


# ============================================================
# DEPENDENCIES
# ============================================================

def get_versioning_service() -> VersioningService:
    """
    Dependency for Versioning Service.
    Centralizes service instantiation.
    """
    return VersioningService()


# ============================================================
# HELPERS
# ============================================================

def handle_service_error(e: ValueError) -> HTTPException:
    """
    Converts service ValueError to appropriate HTTP exception.
    
    Business logic errors from VersioningService are mapped to:
    - 404 for "not found"
    - 409 for "already exists"
    - 400 for other validation errors
    """
    msg: str = str(e)
    
    if "not found" in msg.lower():
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=msg
        )
    
    if "already exists" in msg.lower():
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
    entity_id: int,  # Required: listing versions without entity context makes no sense
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
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
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    
    # Cap limit to prevent abuse
    limit = min(limit, 100)
    
    versions = db.query(EntityVersion).filter(
        EntityVersion.entity_id == entity_id
    ).order_by(
        EntityVersion.version_number.desc()
    ).offset(skip).limit(limit).all()
    
    return versions


@router.get("/{version_id}", response_model=VersionRead)
def read_version(
    version_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
):
    """
    Retrieves a single version by ID.
    
    Access Control:
        - Only ADMIN and AUTHOR can view version details
    
    Returns:
        VersionRead: The requested version
    """
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    
    return get_version_or_404(version_id)


@router.post("/", response_model=VersionRead, status_code=status.HTTP_201_CREATED)
def create_version_draft(
    version_in: VersionCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth
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
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    
    try:
        new_version = versioning_service.create_draft_version(
            db=db, 
            entity_id=version_in.entity_id,
            user_id=current_user.id,
            changelog=version_in.changelog
        )
        
        db.commit()
        db.refresh(new_version)
        
        return new_version
    
    except ValueError as e:
        db.rollback()
        raise handle_service_error(e)
    
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.post("/{version_id}/publish", response_model=VersionRead)
def publish_version(
    version_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth
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
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    
    try:
        version = versioning_service.publish_version(
            db=db, 
            version_id=version_id, 
            user_id=current_user.id
        )
        
        db.commit()
        db.refresh(version)
        
        return version
    
    except ValueError as e:
        db.rollback()
        raise handle_service_error(e)
    
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.post("/{version_id}/clone", response_model=VersionRead, status_code=status.HTTP_201_CREATED)
def clone_version(
    version_id: int, 
    clone_in: VersionClone, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth
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
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    
    try:
        # Clean Swagger default value hack
        clean_changelog: Optional[str] = clone_in.changelog
        if clean_changelog and clean_changelog.strip() == "string":
            clean_changelog = None
        
        new_version = versioning_service.clone_version(
            db=db, 
            source_version_id=version_id, 
            user_id=current_user.id, 
            new_changelog=clean_changelog
        )
        
        db.commit()
        db.refresh(new_version)
        
        return new_version
    
    except ValueError as e:
        db.rollback()
        raise handle_service_error(e)
    
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during cloning: {str(e)}"
        )


@router.patch("/{version_id}", response_model=VersionRead)
def update_version_metadata(
    version_id: int, 
    version_update: VersionUpdate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
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
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    
    version = get_version_or_404(version_id)
    
    # Enforce DRAFT-only modification policy
    validate_version_is_draft(version)
    
    try:
        # Update allowed fields
        if version_update.changelog is not None:
            version.changelog = version_update.changelog
        
        version.updated_by_id = current_user.id
        
        db.commit()
        db.refresh(version)
        
        return version
    
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.delete("/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(
    version_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)  # Auth
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
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    
    version = get_version_or_404(version_id)
    
    # Enforce DRAFT-only deletion policy
    if version.status != VersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete {version.status.value} version. Only DRAFT versions can be deleted to preserve history."
        )
    
    try:
        # Cascade delete handled by SQLAlchemy relationships
        # (Fields, Values, Rules, Configurations)
        db.delete(version)
        db.commit()
        
        return None
    
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )