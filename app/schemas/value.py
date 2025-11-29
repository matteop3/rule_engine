from typing import Optional
from pydantic import Field, field_validator
from .base_schema import BaseSchema

class ValueBase(BaseSchema):
    value: str = Field(..., max_length=255)
    label: Optional[str] = Field(None, max_length=255)
    is_default: bool = False

class ValueCreate(ValueBase):
    """ Schema to create a Value (POST). """
    field_id: int

    # Validator to forbid empty or whitespace-only strings
    @field_validator('value')
    @classmethod
    def value_must_not_be_empty(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("The value cannot be empty or just whitespace")
        return v

class ValueRead(ValueBase):
    """ Schema to read a Value (GET). """
    id: int
    field_id: int

class ValueUpdate(ValueCreate):
    """ Schema to update a Value (PUT). """
    # In a PUT, I expect the client to send all fields, 
    # so inheriting from ValueBase is correct.
    pass