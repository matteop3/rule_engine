from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import Entity, EntityVersion, VersionStatus, User, UserRole
from app.schemas import VersionCreate, VersionRead, VersionUpdate, VersionClone
from app.services.versioning import VersioningService

router = APIRouter(
    prefix="/versions",
    tags=["Versions"]
)

@router.get("/", response_model=List[VersionRead])
def read_versions(
    entity_id: int,  # Required filter: listing all versions of ALL entities makes no sense
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Retrieve version history for a specific Entity.
    Ordered by version_number descending (newest first).
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    versions = db.query(EntityVersion)\
        .filter(EntityVersion.entity_id == entity_id)\
        .order_by(EntityVersion.version_number.desc())\
        .offset(skip).limit(limit).all()
    
    return versions


@router.get("/{version_id}", response_model=VersionRead)
def read_version(
    version_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Retrieve a single Version details. """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    
    return version


@router.post("/", response_model=VersionRead, status_code=status.HTTP_201_CREATED)
def create_version_draft(
    version_in: VersionCreate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Creates a new Version (DRAFT) for an Entity.
    Auto-calculates the version number (incremental).
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    service = VersioningService()

    try:
        new_version = service.create_draft_version(
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
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=msg)
        if "already exists" in msg:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=msg)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg)

@router.post("/{version_id}/publish", response_model=VersionRead)
def publish_version(
    version_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Promotes a DRAFT to PUBLISHED.
    Archives any previously PUBLISHED version (single published policy).
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])
    
    service = VersioningService()

    try:
        version = service.publish_version(db, version_id, current_user.id)
        db.commit()
        db.refresh(version)

        return version

    except ValueError as e:
        db.rollback()
        msg = str(e)
        if "not found" in msg:
             raise HTTPException(status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=msg)


@router.post("/{version_id}/clone", response_model=VersionRead, status_code=status.HTTP_201_CREATED)
def clone_version(
    version_id: int, 
    clone_in: VersionClone, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """ Creates a new DRAFT version by cloning an existing source version (deep copy). """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    service = VersioningService()

    try:
        clean_changelog = clone_in.changelog
        if clean_changelog and clean_changelog.strip() == "string": # Hack: clean Swagger default
            clean_changelog = None

        new_version = service.clone_version(
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
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=msg)
        if "already exists" in msg:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=msg)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Cloning failed: {msg}")
    

@router.patch("/{version_id}", response_model=VersionRead)
def update_version_metadata(
    version_id: int, 
    version_update: VersionUpdate, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Update version metadata (e.g. fix a typo in the changelog).
    Allowed for DRAFT and even PUBLISHED/ARCHIVED (it's just a label).
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")

    # Update allowed fields only
    if version_update.changelog is not None:
        version.changelog = version_update.changelog
    
    # Do not allow changing the ‘status’ here; use the dedicated 
    # /publish or /archive routes to ensure transition logic.

    db.commit()
    db.refresh(version)

    return version


@router.delete("/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(
    version_id: int, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Auth required
):
    """
    Delete a Version.
    Strict policy: only 'DRAFT' versions can be deleted.
    Once published, a version is part of history and cannot be removed.
    """
    # Verify current user's role
    require_role(current_user, [UserRole.ADMIN, UserRole.AUTHOR])

    version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")

    # Guardrail: history protection
    if version.status != VersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete version with status '{version.status.value}'. Only DRAFT versions can be deleted to clean up workspace."
        )

    # Note: Fields, Values and Rules will be automatically 
    # deleted thanks to 'cascade="all, delete-orphan"' into models
    
    db.delete(version)
    db.commit()

    return None