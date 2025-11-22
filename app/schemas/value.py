from typing import Optional
from pydantic import Field
from .base_schema import BaseSchema

class ValueBase(BaseSchema):
    value: str = Field(..., max_length=255)
    label: Optional[str] = Field(None, max_length=255)
    is_default: bool = False

class ValueCreate(ValueBase):
    field_id: int

class ValueRead(ValueBase):
    id: int
    field_id: int