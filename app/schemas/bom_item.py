from decimal import Decimal

from pydantic import Field

from app.models.domain import BOMType

from .base_schema import BaseSchema


class BOMItemBase(BaseSchema):
    """Base properties shared by create and read operations."""

    bom_type: BOMType
    part_number: str = Field(..., max_length=100)
    description: str | None = None
    category: str | None = Field(None, max_length=100)
    quantity: Decimal = Decimal("1")
    quantity_from_field_id: int | None = None
    unit_of_measure: str | None = Field(None, max_length=20)
    unit_price: Decimal | None = None
    sequence: int = 0


class BOMItemCreate(BOMItemBase):
    """Schema for creating a BOM item (POST)."""

    entity_version_id: int
    parent_bom_item_id: int | None = None


class BOMItemUpdate(BaseSchema):
    """Schema for partially updating a BOM item (PATCH)."""

    parent_bom_item_id: int | None = None
    bom_type: BOMType | None = None
    part_number: str | None = Field(None, max_length=100)
    description: str | None = None
    category: str | None = Field(None, max_length=100)
    quantity: Decimal | None = None
    quantity_from_field_id: int | None = None
    unit_of_measure: str | None = Field(None, max_length=20)
    unit_price: Decimal | None = None
    sequence: int | None = None


class BOMItemRead(BOMItemBase):
    """Schema for reading BOM item data (GET responses)."""

    id: int
    entity_version_id: int
    parent_bom_item_id: int | None = None
