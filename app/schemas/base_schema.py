from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class BaseSchema(BaseModel):
    """Basic schema that configures ORM mode."""
    model_config = ConfigDict(from_attributes=True)


class AuditSchemaMixin(BaseModel):
    """
    Mixin to expose the following fields into API responses.
    Only Read schemas need them!
    """
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by_id: Optional[str] = None
    updated_by_id: Optional[str] = None