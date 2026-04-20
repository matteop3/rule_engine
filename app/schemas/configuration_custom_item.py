from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from .base_schema import AuditSchemaMixin, BaseSchema


class ConfigurationCustomItemBase(BaseSchema):
    """Base properties shared by create and read operations."""

    description: str = Field(..., min_length=1)
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)
    unit_of_measure: str | None = Field(None, max_length=20)
    sequence: int = 0

    @field_validator("description")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("description must not be empty")
        return stripped


class ConfigurationCustomItemCreate(ConfigurationCustomItemBase):
    """Schema for creating a custom item (POST).

    The `custom_key` is server-generated; any value provided by the
    client is ignored silently.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_custom_key(cls, data: object) -> object:
        if isinstance(data, dict):
            data.pop("custom_key", None)
        return data


class ConfigurationCustomItemUpdate(BaseSchema):
    """Schema for partially updating a custom item (PATCH).

    The `custom_key` is immutable and any payload containing it is
    rejected at the schema layer.
    """

    description: str | None = Field(None, min_length=1)
    quantity: Decimal | None = Field(None, gt=0)
    unit_price: Decimal | None = Field(None, ge=0)
    unit_of_measure: str | None = Field(None, max_length=20)
    sequence: int | None = None

    @field_validator("description")
    @classmethod
    def _strip_non_empty(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("description must not be empty")
        return stripped

    @model_validator(mode="before")
    @classmethod
    def _reject_custom_key(cls, data: object) -> object:
        if isinstance(data, dict) and "custom_key" in data:
            raise ValueError("custom_key is immutable and cannot be modified")
        return data


class ConfigurationCustomItemRead(ConfigurationCustomItemBase, AuditSchemaMixin):
    """Schema for reading custom item data (GET responses)."""

    id: int
    configuration_id: str
    custom_key: str
