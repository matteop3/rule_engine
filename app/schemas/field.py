from typing import Optional
from pydantic import Field
from .base_schema import BaseSchema

class FieldBase(BaseSchema):
    name: str = Field(..., max_length=100)
    data_type: str = Field("string", max_length=50)
    is_required: bool = False
    is_readonly: bool = False
    is_hidden: bool = False
    is_free_value: bool = False
    step: int = 0
    sequence: int = 0

class FieldCreate(FieldBase):
    entity_id: int

class FieldRead(FieldBase):
    id: int
    entity_id: int
    # Datasource not included here