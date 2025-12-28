from typing import Optional, Any, Dict, Literal
from pydantic import Field, model_validator, field_validator
from .base_schema import BaseSchema
from app.models.domain import RuleType

# Define valid rule types
RuleTypeEnum = Literal['availability', 'visibility', 'editability']

class RuleBase(BaseSchema):
    """ Base properties shared by create and read operations. """
    conditions: Dict[str, Any]
    description: Optional[str] = None
    rule_type: RuleType = RuleType.AVAILABILITY  # Default
    error_message: Optional[str] = None

class RuleCreate(RuleBase):
    """ Payload to create a new version. """
    entity_version_id: int 
    
    target_field_id: int
    target_value_id: Optional[int] = None

    # Criteria validator: empty rules block ---
    @field_validator('conditions')
    @classmethod
    def check_conditions_not_empty(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """ Ensures that the rule contains at least one criterion. """
        criteria = v.get("criteria")
        if not isinstance(criteria, list):
            raise ValueError("The 'conditions' JSON must contain a 'criteria' key with a list of conditions.")
        if len(criteria) == 0:
            raise ValueError("The 'criteria' list cannot be empty. You must define at least one condition.")
        return v

    # Consistency validator: bad rule_type blocks ---
    @model_validator(mode='after')
    def check_rule_type_consistency(self):
        r_type = self.rule_type
        t_value = self.target_value_id

        if t_value is not None:
            if r_type != RuleType.AVAILABILITY:
                raise ValueError(f"Consistency error: if 'target_value_id' is provided, rule_type must be '{RuleType.AVAILABILITY}'. Got '{r_type}'.")
        else:
            if r_type == RuleType.AVAILABILITY:
                 raise ValueError(f"Consistency error: if 'target_value_id' is None, rule_type cannot be '{RuleType.AVAILABILITY}'.")
        return self

class RuleUpdate(RuleCreate):
    """ Schema for updating version metadata. """
    pass

class RuleRead(RuleBase):
    """ Output schema for API responses. """
    id: int
    entity_version_id: int
    target_field_id: int
    target_value_id: Optional[int] = None