from typing import Optional
from pydantic import Field
from .base_schema import BaseSchema

class EntityBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=100)

class EntityCreate(EntityBase):
    pass

class EntityRead(EntityBase):
    id: int