from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.models.domain import Entity, EntityVersion, VersionStatus, User, UserRole
from app.schemas import VersionCreate, VersionRead, VersionUpdate, VersionClone
from datetime import datetime, timezone
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

    # Check Entity
    entity = db.query(Entity).filter(Entity.id == version_in.entity_id).first()
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found.")

    # Check if there is already a DRAFT (single draft policy)
    existing_draft = db.query(EntityVersion).filter(
        EntityVersion.entity_id == version_in.entity_id,
        EntityVersion.status == VersionStatus.DRAFT
    ).first()
    
    if existing_draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A DRAFT version ({existing_draft.version_number}) already exists. Please publish or delete it first."
        )

    # Calculate next version number
    # Get max version number for this entity
    last_ver = db.query(EntityVersion).filter(
        EntityVersion.entity_id == version_in.entity_id
    ).order_by(EntityVersion.version_number.desc()).first()
    
    next_num = last_ver.version_number + 1 if last_ver else 1

    # Create Version
    new_version = EntityVersion(
        entity_id=version_in.entity_id,
        version_number=next_num,
        status=VersionStatus.DRAFT,
        changelog=version_in.changelog
    )
    
    db.add(new_version)
    db.commit()
    db.refresh(new_version)

    return new_version

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

    version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
    if not version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")
    
    if version.status != VersionStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only DRAFT versions can be published.")

    # Archive currently published version (if any)
    current_published = db.query(EntityVersion).filter(
        EntityVersion.entity_id == version.entity_id,
        EntityVersion.status == VersionStatus.PUBLISHED
    ).first()
    
    if current_published:
        current_published.status = VersionStatus.ARCHIVED
    
    # Publish the new Version
    version.status = VersionStatus.PUBLISHED
    version.published_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(version)

    return version


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

    # Fetch source Version first (to know which Entity we are talking about)
    source_version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
    if not source_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source version not found.")

    # Check if a DRAFT already exists for this Entity
    # Allow one DRAFT at a time to avoid confusion
    existing_draft = db.query(EntityVersion).filter(
        EntityVersion.entity_id == source_version.entity_id,
        EntityVersion.status == VersionStatus.DRAFT
    ).first()
    
    if existing_draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A DRAFT version ({existing_draft.version_number}) already exists for Entity {source_version.entity_id}. Please publish or delete it first."
        )

    # Perform clone via Service
    service = VersioningService()
    try:
        clean_changelog = clone_in.changelog
        if clean_changelog and clean_changelog.strip() == "string": # Hack: blank Swagger default
            clean_changelog = None

        new_version = service.clone_version(
            db=db, 
            source_version_id=version_id, 
            new_changelog=clean_changelog
        )
        
        db.commit()
        db.refresh(new_version)
        
        return new_version

    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Cloning failed: {str(e)}")
    

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