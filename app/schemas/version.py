from datetime import datetime

from app.models.domain import VersionStatus

from .base_schema import AuditSchemaMixin, BaseSchema


class VersionBase(BaseSchema):
    """Base properties shared by create and read operations."""

    changelog: str | None = None
    status: VersionStatus = VersionStatus.DRAFT
    # SKU generation fields
    sku_base: str | None = None
    sku_delimiter: str = "-"


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
    published_at: datetime | None = None


class VersionUpdate(BaseSchema):
    """Schema for updating version metadata (PATCH)."""

    changelog: str | None = None
    sku_base: str | None = None
    sku_delimiter: str | None = None


class VersionClone(BaseSchema):
    """
    Schema for clone operation.
    The entity_id is derived from the source Version.
    """

    changelog: str | None = None
