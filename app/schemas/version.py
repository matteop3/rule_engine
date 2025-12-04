from typing import Optional
from datetime import datetime
from pydantic import Field
from .base_schema import BaseSchema
from app.models.domain import VersionStatus # Importing Enum for validation

class VersionBase(BaseSchema):
    """ Base properties shared by create and read operations. """
    changelog: Optional[str] = None
    status: VersionStatus = VersionStatus.DRAFT

class VersionCreate(VersionBase):
    """ 
    Payload to create a new version. 
    Usually, version_number is calculated by the backend, 
    but we keep it flexible here or we can remove it if auto-incremented logic is strict.
    """
    entity_id: int
    # Note: When cloning, we might need a source_version_id, but that goes in the URL/Service logic.
    pass

class VersionRead(VersionBase):
    """ Output schema for API responses. """
    id: int
    entity_id: int
    version_number: int
    created_at: datetime
    published_at: Optional[datetime] = None

class VersionUpdate(BaseSchema):
    """ Schema for updating version metadata (e.g. changelog, status). """
    changelog: Optional[str] = None

class VersionClone(BaseSchema):
    """ 
    Specific schema for clone operation.
    The entity_id is derived from the source Version.
    """
    changelog: Optional[str] = None