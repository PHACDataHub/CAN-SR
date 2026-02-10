import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # API settings
    API_V1_STR: str = os.getenv("API_V1_STR", "/api")
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY", "your-secret-key-here-change-in-production"
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080")
    )

    # Project settings
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "CAN-SR")
    VERSION: str = os.getenv("VERSION", "1.0.0")
    DESCRIPTION: str = os.getenv(
        "DESCRIPTION", "AI-powered systematic review platform for Government of Canada"
    )
    IS_DEPLOYED: bool = os.getenv("IS_DEPLOYED", "false").lower() == "true"

    # CORS
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    # Storage settings
    # Storage selection (strict): local | azure | entra
    STORAGE_TYPE: str = os.getenv("STORAGE_TYPE", "azure").lower().strip()
    AZURE_STORAGE_ACCOUNT_NAME: Optional[str] = os.getenv(
        "AZURE_STORAGE_ACCOUNT_NAME"
    )
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = os.getenv(
        "AZURE_STORAGE_CONNECTION_STRING"
    )
    AZURE_STORAGE_CONTAINER_NAME: str = os.getenv(
        "AZURE_STORAGE_CONTAINER_NAME", "can-sr-storage"
    )

    # Entra storage settings (used when STORAGE_TYPE=entra)
    ENTRA_AZURE_STORAGE_ACCOUNT_NAME: Optional[str] = os.getenv("ENTRA_AZURE_STORAGE_ACCOUNT_NAME")
    ENTRA_AZURE_STORAGE_CONTAINER_NAME: str = os.getenv("ENTRA_AZURE_STORAGE_CONTAINER_NAME", "can-sr-storage")

    # Local storage settings (used when STORAGE_TYPE=local)
    # In docker, default path is backed by the compose volume: ./uploads:/app/uploads
    # Default to a relative directory so it works both locally and in docker:
    # - locally: <repo>/backend/uploads
    # - in docker: /app/uploads
    LOCAL_STORAGE_BASE_PATH: str = os.getenv("LOCAL_STORAGE_BASE_PATH", "uploads")
    LOCAL_STORAGE_CONTAINER_NAME: str = os.getenv("LOCAL_STORAGE_CONTAINER_NAME", "users")

    # File upload settings
    MAX_FILE_SIZE: int = Field(default=52428800)  # 50MB in bytes
    ALLOWED_FILE_TYPES: List[str] = [".pdf", ".txt", ".docx", ".doc"]

    @field_validator("MAX_FILE_SIZE", mode="before")
    @classmethod
    def convert_max_file_size(cls, v):
        """Convert MAX_FILE_SIZE from MB to bytes if it's a string/small number"""
        if isinstance(v, str):
            return int(v) * 1024 * 1024
        elif isinstance(v, int) and v < 1000:  # Assume it's in MB if less than 1000
            return v * 1024 * 1024
        return v

    # External services (for CAN-SR document processing)
    GROBID_SERVICE_URL: str = os.getenv(
        "GROBID_SERVICE_URL", "http://grobid-service:8070"
    )

    # Azure OpenAI settings (Primary - GPT-4o)
    AZURE_OPENAI_API_KEY: Optional[str] = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT: Optional[str] = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_VERSION: str = os.getenv(
        "AZURE_OPENAI_API_VERSION", "2025-01-01-preview"
    )
    AZURE_OPENAI_DEPLOYMENT_NAME: str = os.getenv(
        "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o"
    )

    # GPT-4.1-mini configuration
    AZURE_OPENAI_GPT41_MINI_API_KEY: Optional[str] = os.getenv(
        "AZURE_OPENAI_GPT41_MINI_API_KEY"
    )
    AZURE_OPENAI_GPT41_MINI_ENDPOINT: Optional[str] = os.getenv(
        "AZURE_OPENAI_GPT41_MINI_ENDPOINT"
    )
    AZURE_OPENAI_GPT41_MINI_DEPLOYMENT: str = os.getenv(
        "AZURE_OPENAI_GPT41_MINI_DEPLOYMENT", "gpt-4.1-mini"
    )
    AZURE_OPENAI_GPT41_MINI_API_VERSION: str = os.getenv(
        "AZURE_OPENAI_GPT41_MINI_API_VERSION", "2025-01-01-preview"
    )

    # GPT-5-mini configuration
    AZURE_OPENAI_GPT5_MINI_API_KEY: Optional[str] = os.getenv(
        "AZURE_OPENAI_GPT5_MINI_API_KEY"
    )
    AZURE_OPENAI_GPT5_MINI_ENDPOINT: Optional[str] = os.getenv(
        "AZURE_OPENAI_GPT5_MINI_ENDPOINT"
    )
    AZURE_OPENAI_GPT5_MINI_DEPLOYMENT: str = os.getenv(
        "AZURE_OPENAI_GPT5_MINI_DEPLOYMENT", "gpt-5-mini"
    )
    AZURE_OPENAI_GPT5_MINI_API_VERSION: str = os.getenv(
        "AZURE_OPENAI_GPT5_MINI_API_VERSION", "2025-08-07"
    )

    # Default model to use
    DEFAULT_CHAT_MODEL: str = os.getenv("DEFAULT_CHAT_MODEL", "gpt-5-mini")

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Additional settings
    ALLOW_USER_REGISTRATION: bool = (
        os.getenv("ALLOW_USER_REGISTRATION", "true").lower() == "true"
    )
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # -------------------------------------------------------------------------
    # Postgres configuration
    # -------------------------------------------------------------------------
    # A single selector, with three isolated profiles (AZURE_/DOCKER_/LOCAL_)
    POSTGRES_MODE: str = os.getenv("POSTGRES_MODE", "docker").lower().strip()  # docker|local|azure

    # Docker profile (typically for docker-compose)
    DOCKER_POSTGRES_HOST: Optional[str] = os.getenv("DOCKER_POSTGRES_HOST")
    DOCKER_POSTGRES_DATABASE: Optional[str] = os.getenv("DOCKER_POSTGRES_DATABASE")
    DOCKER_POSTGRES_USER: Optional[str] = os.getenv("DOCKER_POSTGRES_USER")
    DOCKER_POSTGRES_PASSWORD: Optional[str] = os.getenv("DOCKER_POSTGRES_PASSWORD")
    DOCKER_POSTGRES_PORT: int = int(os.getenv("DOCKER_POSTGRES_PORT", "5432"))

    # Local profile (developer machine)
    LOCAL_POSTGRES_HOST: str = os.getenv("LOCAL_POSTGRES_HOST", "localhost")
    LOCAL_POSTGRES_DATABASE: Optional[str] = os.getenv("LOCAL_POSTGRES_DATABASE")
    LOCAL_POSTGRES_USER: Optional[str] = os.getenv("LOCAL_POSTGRES_USER")
    LOCAL_POSTGRES_PASSWORD: Optional[str] = os.getenv("LOCAL_POSTGRES_PASSWORD")
    LOCAL_POSTGRES_PORT: int = int(os.getenv("LOCAL_POSTGRES_PORT", "5432"))

    # Azure profile (Azure Database for PostgreSQL) using Entra token auth
    AZURE_POSTGRES_HOST: Optional[str] = os.getenv("AZURE_POSTGRES_HOST")
    AZURE_POSTGRES_DATABASE: Optional[str] = os.getenv("AZURE_POSTGRES_DATABASE")
    AZURE_POSTGRES_USER: Optional[str] = os.getenv("AZURE_POSTGRES_USER")
    AZURE_POSTGRES_PORT: int = int(os.getenv("AZURE_POSTGRES_PORT", "5432"))
    AZURE_POSTGRES_SSL_MODE: str = os.getenv("AZURE_POSTGRES_SSL_MODE", "require")

    # Deprecated (will be removed): legacy Postgres DSN
    POSTGRES_URI: Optional[str] = os.getenv("POSTGRES_URI")

    def postgres_profile(self, mode: Optional[str] = None) -> dict:
        """Return resolved Postgres connection settings for a specific mode."""
        m = (mode or self.POSTGRES_MODE or "").lower().strip()
        if m not in {"docker", "local", "azure"}:
            raise ValueError("POSTGRES_MODE must be one of: docker, local, azure")

        if m == "docker":
            return {
                "mode": "docker",
                "host": self.DOCKER_POSTGRES_HOST or "pgdb-service",
                "database": self.DOCKER_POSTGRES_DATABASE,
                "user": self.DOCKER_POSTGRES_USER,
                "password": self.DOCKER_POSTGRES_PASSWORD,
                "port": self.DOCKER_POSTGRES_PORT,
                "sslmode": None,
            }

        if m == "local":
            return {
                "mode": "local",
                "host": self.LOCAL_POSTGRES_HOST or "localhost",
                "database": self.LOCAL_POSTGRES_DATABASE,
                "user": self.LOCAL_POSTGRES_USER,
                "password": self.LOCAL_POSTGRES_PASSWORD,
                "port": self.LOCAL_POSTGRES_PORT,
                "sslmode": None,
            }

        # azure
        return {
            "mode": "azure",
            "host": self.AZURE_POSTGRES_HOST,
            "database": self.AZURE_POSTGRES_DATABASE,
            "user": self.AZURE_POSTGRES_USER,
            "password": None,
            "port": self.AZURE_POSTGRES_PORT,
            "sslmode": self.AZURE_POSTGRES_SSL_MODE or "require",
        }

    def has_local_fallback(self) -> bool:
        return bool(self.LOCAL_POSTGRES_DATABASE and self.LOCAL_POSTGRES_USER and self.LOCAL_POSTGRES_PASSWORD)

    # Databricks settings
    DATABRICKS_INSTANCE: str = os.getenv("DATABRICKS_INSTANCE", "")
    DATABRICKS_TOKEN: str = os.getenv("DATABRICKS_TOKEN", "")
    JOB_ID_EUROPEPMC: str = os.getenv("JOB_ID_EUROPEPMC", "")
    JOB_ID_PUBMED: str = os.getenv("JOB_ID_PUBMED", "")
    JOB_ID_SCOPUS: str = os.getenv("JOB_ID_SCOPUS", "")

    # OAuth
    OAUTH_CLIENT_ID: str = os.getenv("OAUTH_CLIENT_ID", "")
    OAUTH_CLIENT_SECRET: str = os.getenv("OAUTH_CLIENT_SECRET", "")
    REDIRECT_URI: str = os.getenv("REDIRECT_URI", "")
    SSO_LOGIN_URL: str = os.getenv("SSO_LOGIN_URL", "")

    # Entra
    USE_ENTRA_AUTH: bool = os.getenv("USE_ENTRA_AUTH", "false").lower() == "true"

    class Config:
        case_sensitive = True
        # Resolve to backend/.env regardless of current working directory.
        env_file = str(Path(__file__).resolve().parents[2] / ".env")
        extra = "ignore"  # Allow extra environment variables


settings = Settings()
