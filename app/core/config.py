# app/core/config.py
import json
import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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

    # Environment
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Database (mandatory)
    DATABASE_URL: str

    # Security (mandatory)
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REFRESH_TOKEN_ROTATION: bool = False

    # Password Policy
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_REQUIRE_UPPERCASE: bool = True
    PASSWORD_REQUIRE_LOWERCASE: bool = True
    PASSWORD_REQUIRE_DIGIT: bool = True
    PASSWORD_REQUIRE_SPECIAL: bool = True

    # CORS (who can invoke the API?)
    BACKEND_CORS_ORIGINS: list[str] = ["http://localhost:8000", "http://localhost:3000"]

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # Caching
    CACHE_TTL_SECONDS: int = 300
    CACHE_MAX_SIZE: int = 100

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_LOGIN_ATTEMPTS: int = 5
    RATE_LIMIT_LOGIN_WINDOW_MINUTES: int = 15
    RATE_LIMIT_REFRESH_ATTEMPTS: int = 10
    RATE_LIMIT_REFRESH_WINDOW_MINUTES: int = 5
    RATE_LIMIT_API_PER_MINUTE: int = 60

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """
        Validate SECRET_KEY meets minimum security requirements.
        Must be at least 32 characters for proper JWT security.
        """
        if len(v) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters long for security reasons. "
                "Generate a secure key using: openssl rand -hex 32"
            )
        return v

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str]:
        """
        Parse CORS origins from various formats:
        - List: ["url1", "url2"]
        - JSON string: '["url1", "url2"]'
        - Comma-separated: "url1,url2"
        """
        # Already a list
        if isinstance(v, list):
            return v

        # As a string
        if isinstance(v, str):
            v_clean = v.strip()

            # It's a JSON
            if v_clean.startswith("["):
                try:
                    return list(json.loads(v_clean))
                except json.JSONDecodeError:
                    # Broken JSON, go to next check
                    pass

            # Comma separated string (es: url1,url2)
            return [i.strip() for i in v.split(",") if i.strip()]

        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid Python logging level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(valid_levels)}")
        return v_upper

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment is valid."""
        valid_envs = ["development", "production", "test"]
        v_lower = v.lower()
        if v_lower not in valid_envs:
            raise ValueError(f"ENVIRONMENT must be one of: {', '.join(valid_envs)}")
        return v_lower

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


# Singleton
settings = Settings()
