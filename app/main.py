from fastapi import FastAPI
from app.database import engine, Base
from app.models import domain
from app.routers import entities, fields, values, rules, engine as engine_router, versions, configurations, auth

# DB tables creation
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Rule Engine Service",
    description="Generic configurable rule engine backend",
    version="0.2.0"
)

# Router registration
app.include_router(auth.router)
app.include_router(entities.router)
app.include_router(versions.router)
app.include_router(fields.router)
app.include_router(values.router)
app.include_router(rules.router)
app.include_router(engine_router.router)
app.include_router(configurations.router)

@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "ok", "message": "Rule Engine is running"}