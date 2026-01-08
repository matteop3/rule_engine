from typing import List, Optional, Any
from pydantic import BaseModel

# --- INPUT: from client ---

class FieldInputState(BaseModel):
    """Represents the raw value entered by the user for a specific field."""
    field_id: int
    value: Any

class CalculationRequest(BaseModel):
    """Request for status calculation."""
    entity_id: int
    current_state: List[FieldInputState]
    entity_version_id: Optional[int] = None


# --- OUTPUT: to client ---

class ValueOption(BaseModel):
    """An available option."""
    id: int
    value: str
    label: Optional[str] = None
    is_default: bool

class FieldOutputState(BaseModel):
    """The recalculated status of a field."""
    field_id: int
    field_name: str
    field_label: Optional[str]
    current_value: Any # The actual current value (after validation and default)    
    available_options: List[ValueOption] # List of options that can be selected at this time
    is_required: bool
    is_readonly: bool
    is_hidden: bool
    error_message: Optional[str] = None

class CalculationResponse(BaseModel):
    """Complete response with the status of all fields in the entity."""
    entity_id: int
    fields: List[FieldOutputState]
    is_complete: bool = True