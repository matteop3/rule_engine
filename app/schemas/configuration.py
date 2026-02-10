from typing import List, Optional
from enum import Enum
from .base_schema import BaseSchema, AuditSchemaMixin
from .engine import FieldInputState


class ConfigurationStatusEnum(str, Enum):
    """
    Configuration lifecycle status for API schemas.

    - DRAFT: Work in progress, mutable configuration
    - FINALIZED: Immutable snapshot, read-only
    """
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class ConfigurationBase(BaseSchema):
    """Base properties for Configuration schemas."""
    name: Optional[str] = None
    data: List[FieldInputState]


class ConfigurationCreate(ConfigurationBase):
    """
    Schema for creating a new Configuration (POST).

    Note: status is automatically set to DRAFT on creation.
    """
    entity_version_id: int


class ConfigurationRead(ConfigurationBase, AuditSchemaMixin):
    """
    Schema for reading Configuration data (GET responses).

    Includes all configuration details including lifecycle status.
    """
    id: str  # UUID
    entity_version_id: int
    status: ConfigurationStatusEnum
    is_complete: bool
    generated_sku: Optional[str] = None
    is_deleted: bool = False


class ConfigurationUpdate(BaseSchema):
    """
    Schema for updating a Configuration (PATCH).

    Allows updating name or data, but not the version linkage or status.
    Status can only be changed via the /finalize endpoint.

    Note: Updates are only allowed on DRAFT configurations.
    FINALIZED configurations will return HTTP 409 Conflict.
    """
    name: Optional[str] = None
    data: Optional[List[FieldInputState]] = None


class ConfigurationCloneResponse(ConfigurationRead):
    """
    Response schema for clone operation.

    The cloned configuration always has status=DRAFT,
    regardless of the source configuration's status.
    """
    source_id: str  # UUID of the original configuration