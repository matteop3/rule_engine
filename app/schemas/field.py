from pydantic import Field

from app.models.domain import FieldType

from .base_schema import BaseSchema


class FieldBase(BaseSchema):
    """Base properties shared by create and read operations."""

    name: str = Field(..., max_length=100)
    label: str | None = None
    data_type: FieldType = FieldType.STRING
    is_required: bool = False
    is_readonly: bool = False
    is_hidden: bool = False
    is_free_value: bool = False
    default_value: str | None = None
    sku_modifier_when_filled: str | None = Field(
        None,
        max_length=20,
        description="SKU segment to append when this free-value field has a non-null value (e.g., 'CUSTOM')",
    )
    step: int = 0
    sequence: int = 0


class FieldCreate(FieldBase):
    """Schema for creating a new Field (POST)."""

    entity_version_id: int


class FieldUpdate(BaseSchema):
    """
    Schema for partially updating a Field (PATCH).

    Note: entity_version_id is included for consistency, but moving fields
    between versions is rare and should be done with caution.
    """

    name: str | None = Field(None, max_length=100)
    label: str | None = None
    data_type: FieldType | None = None
    is_required: bool | None = None
    is_readonly: bool | None = None
    is_hidden: bool | None = None
    is_free_value: bool | None = None
    default_value: str | None = None
    sku_modifier_when_filled: str | None = Field(None, max_length=20)
    step: int | None = None
    sequence: int | None = None
    entity_version_id: int | None = None


class FieldRead(FieldBase):
    """Schema for reading Field data (GET responses)."""

    id: int
    entity_version_id: int
