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
    default_value: Optional[str] = None # Only if is_free_value
    step: int = 0
    sequence: int = 0

class FieldCreate(FieldBase):
    """ Schema to create a Field (POST). """
    entity_id: int

class FieldRead(FieldBase):
    """ Schema to read a Field (GET). """
    id: int
    entity_id: int
    # Datasource not included here

class FieldUpdate(FieldCreate):
    """ Schema to update a Field (PUT). """
    # In a PUT, I expect the client to send all fields, 
    # so inheriting from FieldBase is correct.
    pass