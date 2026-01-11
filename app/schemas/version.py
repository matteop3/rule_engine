from typing import Optional
from datetime import datetime
from .base_schema import BaseSchema, AuditSchemaMixin
from app.models.domain import VersionStatus


class VersionBase(BaseSchema):
    """Base properties shared by create and read operations."""
    changelog: Optional[str] = None
    status: VersionStatus = VersionStatus.DRAFT


class VersionCreate(VersionBase):
    """
    Schema for creating a new Version (POST).

    Note: version_number is auto-calculated by the backend.
    For cloning, use the dedicated /clone endpoint with VersionClone schema.
    """
    entity_id: int


class VersionRead(VersionBase, AuditSchemaMixin):
    """Schema for reading Version data (GET responses)."""
    id: int
    entity_id: int
    version_number: int
    published_at: Optional[datetime] = None


class VersionUpdate(BaseSchema):
    """Schema for updating version metadata (PATCH). Only changelog is editable."""
    changelog: Optional[str] = None


class VersionClone(BaseSchema):
    """
    Schema for clone operation.
    The entity_id is derived from the source Version.
    """
    changelog: Optional[str] = None