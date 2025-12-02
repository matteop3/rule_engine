from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models.domain import Entity, EntityVersion, VersionStatus
from app.schemas import VersionCreate, VersionRead, VersionUpdate
from datetime import datetime, timezone

router = APIRouter(
    prefix="/versions",
    tags=["Versions"]
)

@router.post("/", response_model=VersionRead, status_code=status.HTTP_201_CREATED)
def create_version_draft(version_in: VersionCreate, db: Session = Depends(get_db)):
    """
    Creates a new Version (DRAFT) for an Entity.
    Auto-calculates the version number (incremental).
    """
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
def publish_version(version_id: int, db: Session = Depends(get_db)):
    """
    Promotes a DRAFT to PUBLISHED.
    Archives any previously PUBLISHED version (single published policy).
    """
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