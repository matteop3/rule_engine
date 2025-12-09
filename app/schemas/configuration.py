from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime
from .base_schema import BaseSchema

# Reuse engine input structure
class ConfigItem(BaseModel):
    field_id: int
    value: Any

class ConfigurationBase(BaseSchema):
    name: Optional[str] = None
    data: List[ConfigItem] 

class ConfigurationCreate(ConfigurationBase):
    entity_version_id: int

class ConfigurationRead(ConfigurationBase):
    id: str # UUID
    entity_version_id: int
    created_at: datetime
    updated_at: datetime

class ConfigurationUpdate(BaseSchema):
    """ Allows updating name or data, but not the version linkage. """
    name: Optional[str] = None
    data: Optional[List[ConfigItem]] = None