from fastapi import FastAPI

from app.database import engine, Base
from app.models import domain # Importa i modelli

Base.metadata.create_all(bind=engine)

# Inizializzazione dell'app
app = FastAPI(
    title="Rule Engine Service",
    description="Generic configurable rule engine backend",
    version="0.1.0"
)

@app.get("/")
def health_check() -> dict[str, str]:
    """
    Simple health check endpoint.
    """
    return {"status": "ok", "message": "Rule Engine is running"}