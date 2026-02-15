from pydantic import Field

from .base_schema import AuditSchemaMixin, BaseSchema


class EntityBase(BaseSchema):
    """Base properties shared by Entity schemas."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None


class EntityCreate(EntityBase):
    """Schema for creating an Entity (POST)."""

    pass


class EntityRead(EntityBase, AuditSchemaMixin):
    """Schema for reading Entity data (GET responses)."""

    id: int


class EntityUpdate(BaseSchema):
    """Schema for partially updating an Entity (PATCH). All fields optional."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
