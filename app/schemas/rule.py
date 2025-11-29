from typing import Any, Dict, Optional
from pydantic import Field
from .base_schema import BaseSchema

class RuleBase(BaseSchema):
    conditions: Dict[str, Any] # JSON logic

class RuleCreate(RuleBase):
    """ Schema to create a Rule (POST). """
    entity_id: int
    target_field_id: int
    target_value_id: int

class RuleRead(RuleBase):
    """ Schema to read a Rule (GET). """
    id: int
    entity_id: int
    target_field_id: int
    target_value_id: int

class RuleUpdate(RuleCreate):
    """ Schema to update a Rule (PUT). """
    # In a PUT, I expect the client to send all fields, 
    # so inheriting from RuleBase is correct.
    pass