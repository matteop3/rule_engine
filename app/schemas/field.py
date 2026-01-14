from typing import Optional
from pydantic import Field
from .base_schema import BaseSchema
from app.models.domain import FieldType


class FieldBase(BaseSchema):
    """Base properties shared by create and read operations."""
    name: str = Field(..., max_length=100)
    label: Optional[str] = None
    data_type: FieldType = FieldType.STRING
    is_required: bool = False
    is_readonly: bool = False
    is_hidden: bool = False
    is_free_value: bool = False
    default_value: Optional[str] = None
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
    name: Optional[str] = Field(None, max_length=100)
    label: Optional[str] = None
    data_type: Optional[FieldType] = None
    is_required: Optional[bool] = None
    is_readonly: Optional[bool] = None
    is_hidden: Optional[bool] = None
    is_free_value: Optional[bool] = None
    default_value: Optional[str] = None
    step: Optional[int] = None
    sequence: Optional[int] = None
    entity_version_id: Optional[int] = None


class FieldRead(FieldBase):
    """Schema for reading Field data (GET responses)."""
    id: int
    entity_version_id: int