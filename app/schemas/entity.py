from typing import Optional
from pydantic import Field
from .base_schema import BaseSchema, AuditSchemaMixin


class EntityBase(BaseSchema):
    """Base properties shared by Entity schemas."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class EntityCreate(EntityBase):
    """Schema for creating an Entity (POST)."""
    pass


class EntityRead(EntityBase, AuditSchemaMixin):
    """Schema for reading Entity data (GET responses)."""
    id: int


class EntityUpdate(BaseSchema):
    """Schema for updating an Entity (PUT with partial update behavior). All fields optional."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None