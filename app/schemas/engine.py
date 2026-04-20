import datetime as dt
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

# --- INPUT: from client ---


class FieldInputState(BaseModel):
    """Represents the raw value entered by the user for a specific field."""

    field_id: int
    value: Any


class CalculationRequest(BaseModel):
    """Request for status calculation."""

    entity_id: int
    current_state: list[FieldInputState]
    entity_version_id: int | None = None
    price_list_id: int | None = None
    price_date: dt.date | None = None
    configuration_id: str | None = None


# --- OUTPUT: to client ---


class ValueOption(BaseModel):
    """An available option."""

    id: int
    value: str
    label: str | None = None
    is_default: bool


class FieldOutputState(BaseModel):
    """The recalculated status of a field."""

    field_id: int
    field_name: str
    field_label: str | None
    current_value: Any  # The actual current value (after validation and default)
    available_options: list[ValueOption]  # List of options that can be selected at this time
    is_required: bool
    is_readonly: bool
    is_hidden: bool
    error_message: str | None = None


class BOMLineItem(BaseModel):
    """A single BOM line item in the calculation output, with nested children."""

    bom_item_id: int | None = None
    bom_type: str
    part_number: str
    description: str | None = None
    category: str | None = None
    quantity: Decimal
    unit_of_measure: str | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    is_custom: bool = False
    children: list["BOMLineItem"] = []


class BOMOutput(BaseModel):
    """BOM evaluation result split by type with commercial total."""

    technical: list[BOMLineItem]
    commercial: list[BOMLineItem]
    commercial_total: Decimal | None = None
    warnings: list[str] = []


class CalculationResponse(BaseModel):
    """Complete response with the status of all fields in the entity."""

    entity_id: int
    fields: list[FieldOutputState]
    is_complete: bool = True
    generated_sku: str | None = None
    bom: BOMOutput | None = None
