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
    updated_at: datetime | None = None
    created_by_id: str | None = None
    updated_by_id: str | None = None
