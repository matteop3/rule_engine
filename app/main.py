from fastapi import FastAPI
from app.database import engine, Base
from app.models import domain
from app.routers import entities, fields, values, rules # Router importing
from app.routers import engine as engine_router

# DB tables creation
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Rule Engine Service",
    description="Generic configurable rule engine backend",
    version="0.1.0"
)

# Router registration
app.include_router(entities.router)
app.include_router(fields.router)
app.include_router(values.router)
app.include_router(rules.router)
app.include_router(engine_router.router)

def health_check() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok", "message": "Rule Engine is running"}