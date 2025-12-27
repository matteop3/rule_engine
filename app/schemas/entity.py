from typing import Optional
from pydantic import Field
from .base_schema import BaseSchema, AuditSchemaMixin

class EntityBase(BaseSchema):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None

class EntityCreate(EntityBase):
    """ Schema to create an Entity (POST). """
    # In a POST, I expect the client to send all fields, so 
    # inheriting from EntityBase (which has name) is correct.
    pass

class EntityRead(EntityBase, AuditSchemaMixin):
    """ Schema to read an Entity (GET). """
    id: int

class EntityUpdate(EntityBase):
    """ Schema to update an Entity (PUT). """
    # In a PUT, I expect the client to send all fields, so 
    # inheriting from EntityBase (which has name) is correct.
    pass