from pydantic import BaseModel, ConfigDict

class BaseSchema(BaseModel):
    """Basic schema that configures ORM mode."""
    model_config = ConfigDict(from_attributes=True)