from typing import Optional, Any, List, Union, Literal
from pydantic import BaseModel, model_validator, field_validator
from .base_schema import BaseSchema
from app.models.domain import RuleType

CriterionOperator = Literal[
    'EQUALS', 'NOT_EQUALS',
    'GREATER_THAN', 'GREATER_THAN_OR_EQUAL',
    'LESS_THAN', 'LESS_THAN_OR_EQUAL',
    'IN'
]

# Strict validation models
class RuleCriterion(BaseModel):
    field_id: int
    operator: CriterionOperator
    value: Union[str, int, float, bool, List[Any], None] = None

class RuleConditions(BaseModel):
    # Implicit AND
    criteria: List[RuleCriterion]

    # Ensures that the rule contains at least one criterion.
    @field_validator('criteria')
    @classmethod
    def check_not_empty(cls, v):
        if not v:
            raise ValueError("The 'criteria' list cannot be empty. You must define at least one condition.")
        return v


# Rule schemas
class RuleBase(BaseSchema):
    """ Base properties shared by create and read operations. """
    conditions: RuleConditions
    description: Optional[str] = None
    rule_type: RuleType = RuleType.AVAILABILITY # Default
    error_message: Optional[str] = None

class RuleCreate(RuleBase):
    """ Payload to create a new version. """
    entity_version_id: int 
    
    target_field_id: int
    target_value_id: Optional[int] = None

    # Consistency validator: bad rule_type blocks
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

class RuleUpdate(BaseSchema):
    """
    Schema for updating existing rule (PATCH). All fields optional.

    Note: entity_version_id is not included because moving rules between versions is forbidden.
    Full consistency validation (rule_type vs target_value_id) is performed at the service layer
    where the existing rule data is available.
    """
    conditions: Optional[RuleConditions] = None
    description: Optional[str] = None
    rule_type: Optional[RuleType] = None
    error_message: Optional[str] = None
    target_field_id: Optional[int] = None
    target_value_id: Optional[int] = None

    @model_validator(mode='after')
    def check_partial_rule_type_consistency(self):
        """
        Validates consistency when both rule_type and target_value_id are explicitly provided.
        When only one is provided, full validation happens at the router/service layer.
        """
        # Only validate if both fields are explicitly set in this update
        if self.rule_type is not None and self.target_value_id is not None:
            if self.rule_type != RuleType.AVAILABILITY:
                raise ValueError(
                    f"Consistency error: if 'target_value_id' is provided, "
                    f"rule_type must be '{RuleType.AVAILABILITY}'. Got '{self.rule_type}'."
                )
        return self

class RuleRead(RuleBase):
    """ Output schema for API responses. """
    id: int
    entity_version_id: int
    target_field_id: int
    target_value_id: Optional[int] = None