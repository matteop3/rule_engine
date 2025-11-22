from typing import Any, Dict, Optional
from pydantic import Field
from .base_schema import BaseSchema

class RuleBase(BaseSchema):
    conditions: Dict[str, Any] # JSON logic

class RuleCreate(RuleBase):
    entity_id: int
    target_field_id: int
    target_value_id: int

class RuleRead(RuleBase):
    id: int
    entity_id: int
    target_field_id: int
    target_value_id: int