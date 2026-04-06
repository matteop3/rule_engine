from .base_schema import BaseSchema
from .rule import RuleConditions


class BOMItemRuleBase(BaseSchema):
    """Base properties shared by create and read operations."""

    conditions: RuleConditions
    description: str | None = None


class BOMItemRuleCreate(BOMItemRuleBase):
    """Schema for creating a BOM item rule (POST)."""

    bom_item_id: int
    entity_version_id: int


class BOMItemRuleUpdate(BaseSchema):
    """Schema for partially updating a BOM item rule (PATCH)."""

    conditions: RuleConditions | None = None
    description: str | None = None


class BOMItemRuleRead(BOMItemRuleBase):
    """Schema for reading BOM item rule data (GET responses)."""

    id: int
    bom_item_id: int
    entity_version_id: int
