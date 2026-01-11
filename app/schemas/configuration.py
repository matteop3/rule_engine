from typing import List, Optional
from .base_schema import BaseSchema, AuditSchemaMixin
from .engine import FieldInputState


class ConfigurationBase(BaseSchema):
    """Base properties for Configuration schemas."""
    name: Optional[str] = None
    data: List[FieldInputState]


class ConfigurationCreate(ConfigurationBase):
    """Schema for creating a new Configuration (POST)."""
    entity_version_id: int


class ConfigurationRead(ConfigurationBase, AuditSchemaMixin):
    """Schema for reading Configuration data (GET responses)."""
    id: str  # UUID
    entity_version_id: int
    is_complete: bool


class ConfigurationUpdate(BaseSchema):
    """
    Schema for updating a Configuration (PATCH).
    Allows updating name or data, but not the version linkage.
    """
    name: Optional[str] = None
    data: Optional[List[FieldInputState]] = None