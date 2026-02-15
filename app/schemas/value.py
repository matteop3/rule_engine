from pydantic import Field, field_validator

from .base_schema import BaseSchema


class ValueBase(BaseSchema):
    value: str = Field(..., max_length=255)
    label: str | None = Field(None, max_length=255)
    is_default: bool = False
    sku_modifier: str | None = Field(None, max_length=50)


class ValueCreate(ValueBase):
    """Schema to create a Value (POST)."""

    field_id: int

    # Validator to forbid empty or whitespace-only strings
    @field_validator("value")
    @classmethod
    def value_must_not_be_empty(cls, v: str) -> str:
        if v.strip() == "":
            raise ValueError("The value cannot be empty or just whitespace")
        return v


class ValueRead(ValueBase):
    """Schema to read a Value (GET)."""

    id: int
    field_id: int


class ValueUpdate(BaseSchema):
    """Schema for updating a Value (PATCH). All fields optional."""

    value: str | None = Field(None, max_length=255)
    label: str | None = Field(None, max_length=255)
    is_default: bool | None = None
    field_id: int | None = None
    sku_modifier: str | None = Field(None, max_length=50)

    @field_validator("value")
    @classmethod
    def value_must_not_be_empty(cls, v: str | None) -> str | None:
        if v is not None and v.strip() == "":
            raise ValueError("The value cannot be empty or just whitespace")
        return v
