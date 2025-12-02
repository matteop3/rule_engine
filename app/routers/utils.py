from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.domain import EntityVersion, VersionStatus

def check_version_editable(version_id: int, db: Session):
    """
    Dependency helper.
    Checks if the Entity version exists and is in DRAFT status.
    If it's PUBLISHED or ARCHIVED, raises an HTTP 409 Conflict.
    """
    version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Entity version {version_id} not found."
        )
    
    if version.status != VersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Version {version_id} is in status '{version.status.value}'. "
                "Only 'DRAFT' versions can be modified. "
                "Please create a new version to make changes."
            )
        )
    return version