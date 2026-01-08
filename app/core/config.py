# app/core/config.py
import os
import json
from typing import List, Union
from pathlib import Path
from pydantic import field_validator
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
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:8000", "http://localhost:3000"]

    # To allow URLs to be written as comma separated instead of a JSON
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        # Already a list
        if isinstance(v, list):
            return v
        
        # As a string
        if isinstance(v, str):
            v_clean = v.strip()
            
            # It's a JSON
            if v_clean.startswith("["):
                try:
                    return json.loads(v_clean)
                except json.JSONDecodeError:
                    # Broken JSON, go to next check
                    pass 
            
            # Comma separated string (es: url1,url2)
            return [i.strip() for i in v.split(",") if i.strip()]
                
        return v

    # Pydantic configuration to read the .env file
    model_config = SettingsConfigDict(
        env_file=ENV_PATH, 
        env_ignore_empty=True,
        extra="ignore"
    )

# Singleton
settings = Settings()