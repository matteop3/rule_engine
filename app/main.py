from fastapi import FastAPI
from slowapi.errors import RateLimitExceeded

from app.core.config import settings
from app.database import engine, Base
from app.routers import entities, fields, values, rules, engine as engine_router, versions, configurations, auth
from app.core.rate_limit import limiter, rate_limit_exceeded_handler

# DB tables creation
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version="0.1.0"
)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

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
    return {"status": "ok", "message": f"{settings.PROJECT_NAME} is running"}