from typing import Optional
from pydantic import Field
from .base_schema import BaseSchema

class FieldBase(BaseSchema):
    """ Base properties shared by create and read operations. """
    name: str = Field(..., max_length=100)
    data_type: str = Field("string", max_length=50)
    is_required: bool = False
    is_readonly: bool = False
    is_hidden: bool = False
    is_free_value: bool = False    
    default_value: Optional[str] = None    
    step: int = 0
    sequence: int = 0

class FieldCreate(FieldBase):
    """ Payload to create a new version. """
    entity_version_id: int 

class FieldUpdate(FieldCreate):
    # I inherit entity_version_id, but technically moving a field 
    # between versions is rare. I keep it for consistency.
    pass

class FieldRead(FieldBase):
    """ Output schema for API responses. """
    id: int
    entity_version_id: int