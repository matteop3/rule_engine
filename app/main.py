# app/main.py
from fastapi import FastAPI

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