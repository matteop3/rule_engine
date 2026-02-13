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
    set_value: Optional[str] = None

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
        err_msg = self.error_message
        s_value = self.set_value

        # target_value_id: only AVAILABILITY
        if t_value is not None:
            if r_type != RuleType.AVAILABILITY:
                raise ValueError(f"Consistency error: if 'target_value_id' is provided, rule_type must be '{RuleType.AVAILABILITY}'. Got '{r_type}'.")
        else:
            if r_type == RuleType.AVAILABILITY:
                 raise ValueError(f"Consistency error: if 'target_value_id' is None, rule_type cannot be '{RuleType.AVAILABILITY}'.")

        # error_message: only VALIDATION
        if err_msg is not None and r_type != RuleType.VALIDATION:
            raise ValueError(f"Consistency error: 'error_message' is only allowed for rule_type '{RuleType.VALIDATION}'. Got '{r_type}'.")

        # set_value: only CALCULATION (and mandatory for it)
        if s_value is not None and r_type != RuleType.CALCULATION:
            raise ValueError(f"Consistency error: 'set_value' is only allowed for rule_type '{RuleType.CALCULATION}'. Got '{r_type}'.")
        if r_type == RuleType.CALCULATION and s_value is None:
            raise ValueError(f"Consistency error: 'set_value' is required for rule_type '{RuleType.CALCULATION}'.")

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
    set_value: Optional[str] = None
    target_field_id: Optional[int] = None
    target_value_id: Optional[int] = None

    @model_validator(mode='after')
    def check_partial_rule_type_consistency(self):
        """
        Validates consistency when fields are explicitly provided together.
        When only one is provided, full validation happens at the router/service layer.
        """
        # Validate target_value_id + rule_type consistency
        if self.rule_type is not None and self.target_value_id is not None:
            if self.rule_type != RuleType.AVAILABILITY:
                raise ValueError(
                    f"Consistency error: if 'target_value_id' is provided, "
                    f"rule_type must be '{RuleType.AVAILABILITY}'. Got '{self.rule_type}'."
                )

        # Validate error_message + rule_type consistency
        if self.error_message is not None and self.rule_type is not None:
            if self.rule_type != RuleType.VALIDATION:
                raise ValueError(
                    f"Consistency error: 'error_message' is only allowed for "
                    f"rule_type '{RuleType.VALIDATION}'. Got '{self.rule_type}'."
                )

        # Validate set_value + rule_type consistency
        if self.set_value is not None and self.rule_type is not None:
            if self.rule_type != RuleType.CALCULATION:
                raise ValueError(
                    f"Consistency error: 'set_value' is only allowed for "
                    f"rule_type '{RuleType.CALCULATION}'. Got '{self.rule_type}'."
                )

        return self

class RuleRead(RuleBase):
    """ Output schema for API responses. """
    id: int
    entity_version_id: int
    target_field_id: int
    target_value_id: Optional[int] = None