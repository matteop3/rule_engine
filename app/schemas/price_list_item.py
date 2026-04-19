import datetime as dt
from decimal import Decimal

from pydantic import Field, model_validator

from .base_schema import AuditSchemaMixin, BaseSchema


class PriceListItemBase(BaseSchema):
    """Base properties shared by create and read operations."""

    part_number: str = Field(..., max_length=100)
    unit_price: Decimal
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None


class PriceListItemCreate(PriceListItemBase):
    """Schema for creating a price list item (POST)."""

    price_list_id: int


class PriceListItemRead(PriceListItemBase, AuditSchemaMixin):
    """Schema for reading price list item data (GET responses)."""

    id: int
    price_list_id: int
    valid_from: dt.date  # type: ignore[assignment]
    valid_to: dt.date  # type: ignore[assignment]


class PriceListItemUpdate(BaseSchema):
    """Schema for partially updating a price list item (PATCH)."""

    part_number: str | None = Field(None, max_length=100)
    unit_price: Decimal | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None

    @model_validator(mode="after")
    def _dates_ordered(self) -> "PriceListItemUpdate":
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_from >= self.valid_to:
                raise ValueError("valid_from must be strictly less than valid_to")
        return self
