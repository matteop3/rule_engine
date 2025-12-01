from typing import Any, Dict, Optional, Literal
from pydantic import Field, field_validator, model_validator
from .base_schema import BaseSchema

# Valid rule_type
RuleTypeEnum = Literal['availability', 'visibility', 'editability']

class RuleBase(BaseSchema):
    conditions: Dict[str, Any] # JSON logic
    rule_type: RuleTypeEnum = "availability"

class RuleCreate(RuleBase):
    """ Schema to create a Rule (POST). """
    entity_id: int
    target_field_id: int
    target_value_id: Optional[int] = None

    # Criteria validator: empty rules are considered as unintended
    @field_validator('conditions')
    @classmethod
    def check_conditions_not_empty(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensures that the rule contains at least one criterion.
        Empty rules are not allowed as they can act as unintended overrides.
        """
        criteria = v.get("criteria")
        
        # Structural check: must be a list
        if not isinstance(criteria, list):
            raise ValueError("The 'conditions' JSON must contain a 'criteria' key with a list of conditions.")
        
        # Content check: must not be empty
        if len(criteria) == 0:
            raise ValueError("The 'criteria' list cannot be empty. You must define at least one condition.")
        
        return v
    
    @model_validator(mode='after')
    def check_rule_type_consistency(self):
        r_type = self.rule_type
        t_value = self.target_value_id

        # Specific Rule on a Value (with target_value_id)
        if t_value is not None:
            if r_type != 'availability':
                raise ValueError(
                    f"Consistency Error: If 'target_value_id' is provided, "
                    f"rule_type must be 'availability'. Got '{r_type}'."
                )
        
        # Generic Rule on a Value (without target_value_id)
        else:
            if r_type == 'availability':
                 raise ValueError(
                    "Consistency Error: If 'target_value_id' is None (Field-Level Rule), "
                    "rule_type cannot be 'availability'. Use 'visibility' or 'editability'."
                )
        
        return self

class RuleRead(RuleBase):
    """ Schema to read a Rule (GET). """
    id: int
    entity_id: int
    target_field_id: int
    target_value_id: Optional[int] = None

class RuleUpdate(RuleCreate):
    """ Schema to update a Rule (PUT). """
    # In a PUT, I expect the client to send all fields, 
    # so inheriting from RuleBase is correct.
    pass