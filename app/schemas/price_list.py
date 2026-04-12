import datetime as dt

from pydantic import Field, model_validator

from .base_schema import AuditSchemaMixin, BaseSchema

FAR_FUTURE = dt.date(9999, 12, 31)


class PriceListBase(BaseSchema):
    """Base properties shared by create and read operations."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    valid_from: dt.date
    valid_to: dt.date = FAR_FUTURE

    @model_validator(mode="after")
    def _dates_ordered(self) -> "PriceListBase":
        if self.valid_from >= self.valid_to:
            raise ValueError("valid_from must be strictly less than valid_to")
        return self


class PriceListCreate(PriceListBase):
    """Schema for creating a price list (POST)."""


class PriceListRead(PriceListBase, AuditSchemaMixin):
    """Schema for reading price list data (GET responses)."""

    id: int


class PriceListUpdate(BaseSchema):
    """Schema for partially updating a price list (PATCH)."""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    valid_from: dt.date | None = None
    valid_to: dt.date | None = None

    @model_validator(mode="after")
    def _dates_ordered(self) -> "PriceListUpdate":
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_from >= self.valid_to:
                raise ValueError("valid_from must be strictly less than valid_to")
        return self
