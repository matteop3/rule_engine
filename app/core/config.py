# app/core/config.py
import os
from typing import List
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Calculate absolute project root.
# __file__ is this file (config.py). 
# .parent is 'core', .parent is 'app', .parent is the project root.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = os.path.join(BASE_DIR, ".env")

class Settings(BaseSettings):
    # App Info
    PROJECT_NAME: str = "Rule Engine Service"
    PROJECT_DESCRIPTION: str = "Generic configurable rule engine backend"
    API_V1_STR: str = "/api/v1"
    
    # Database (mandatory)
    DATABASE_URL: str

    # Security (mandatory)
    SECRET_KEY: str

    # CORS (who can invoke the API?)
    # Example input .env: ["http://localhost:3000", "https://mio-dominio.com"]
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:8000", "http://localhost:3000"]

    # Pydantic configuration to read the .env file
    model_config = SettingsConfigDict(
        env_file=ENV_PATH, 
        env_ignore_empty=True,
        extra="ignore"
    )

# Singleton
settings = Settings()