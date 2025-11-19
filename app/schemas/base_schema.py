from pydantic import BaseModel, ConfigDict
from typing import Optional

class BaseSchema(BaseModel):
    """
    Schema base per tutti i modelli Pydantic.
    Permette la lettura dei dati direttamente da un oggetto ORM (es. SQLAlchemy).
    """
    model_config = ConfigDict(from_attributes=True)
    
    id: Optional[int] = None # L'ID è opzionale per i modelli 'Create' ma presente in 'Read'