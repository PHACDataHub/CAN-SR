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
    STORAGE_MODE: str = os.getenv("STORAGE_MODE", "azure").lower().strip()
    # Canonical storage container name used across all storage types.
    # - local: folder name under LOCAL_STORAGE_BASE_PATH
    # - azure/entra: blob container name
    STORAGE_CONTAINER_NAME: str = os.getenv("STORAGE_CONTAINER_NAME", "can-sr-storage")
    # Azure Storage
    # - STORAGE_MODE=azure requires account name + account key
    # - STORAGE_MODE=entra requires only account name (uses DefaultAzureCredential)
    AZURE_STORAGE_ACCOUNT_NAME: Optional[str] = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    AZURE_STORAGE_ACCOUNT_KEY: Optional[str] = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")

    # Local storage settings (used when STORAGE_MODE=local)
    # In docker, default path is backed by the compose volume: ./uploads:/app/uploads
    # Default to a relative directory so it works both locally and in docker:
    # - locally: <repo>/backend/uploads
    # - in docker: /app/uploads
    LOCAL_STORAGE_BASE_PATH: str = os.getenv("LOCAL_STORAGE_BASE_PATH", "uploads")

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
    # Azure OpenAI auth selection
    # key -> uses AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY
    # entra -> uses AZURE_OPENAI_ENDPOINT + DefaultAzureCredential
    # Backwards/alternate env var: OPENAI_TYPE
    AZURE_OPENAI_MODE: str = os.getenv("AZURE_OPENAI_MODE", "key").lower().strip()

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
    # Select primary Postgres mode.
    # docker/local use password auth; azure uses Entra token auth.
    POSTGRES_MODE: str = os.getenv("POSTGRES_MODE", "docker").lower().strip()  # docker|local|azure

    # Canonical Postgres connection settings (single profile; values vary by environment)
    POSTGRES_HOST: Optional[str] = os.getenv("POSTGRES_HOST")
    POSTGRES_DATABASE: Optional[str] = os.getenv("POSTGRES_DATABASE")
    POSTGRES_USER: Optional[str] = os.getenv("POSTGRES_USER")
    POSTGRES_PASSWORD: Optional[str] = os.getenv("POSTGRES_PASSWORD")

    # Optional overrides
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_SSL_MODE: str = os.getenv("POSTGRES_SSL_MODE", "require")

    # Deprecated (will be removed): legacy Postgres DSN
    POSTGRES_URI: Optional[str] = os.getenv("POSTGRES_URI")

    def postgres_profile(self, mode: Optional[str] = None) -> dict:
        """Return resolved Postgres connection settings for a specific mode.

        The application uses a single set of environment variables:
        POSTGRES_HOST, POSTGRES_DATABASE, POSTGRES_USER, POSTGRES_PASSWORD.

        POSTGRES_MODE controls *how* authentication is performed:
        - docker/local: password auth (POSTGRES_PASSWORD required)
        - azure: Entra token auth (password ignored) + sslmode=require
        """
        m = (mode or self.POSTGRES_MODE or "").lower().strip()
        if m not in {"docker", "local", "azure"}:
            raise ValueError("POSTGRES_MODE must be one of: docker, local, azure")

        # Provide sensible defaults for host depending on mode.
        default_host = "pgdb-service" if m == "docker" else "localhost" if m == "local" else None

        prof = {
            "mode": m,
            "host": self.POSTGRES_HOST or default_host,
            "database": self.POSTGRES_DATABASE,
            "user": self.POSTGRES_USER,
            # For azure we intentionally ignore password (token auth)
            "password": None if m == "azure" else self.POSTGRES_PASSWORD,
            "port": self.POSTGRES_PORT,
            "sslmode": (self.POSTGRES_SSL_MODE or "require") if m == "azure" else None,
        }

        return prof

    def has_local_fallback(self) -> bool:
        # Deprecated: legacy behavior. Kept for compatibility with older code paths.
        return False

    # Databricks settings
    DATABRICKS_INSTANCE: str = os.getenv("DATABRICKS_INSTANCE", "")
    DATABRICKS_TOKEN: str = os.getenv("DATABRICKS_TOKEN", "")
    JOB_ID_EUROPEPMC: str = os.getenv("JOB_ID_EUROPEPMC", "")
    JOB_ID_PUBMED: str = os.getenv("JOB_ID_PUBMED", "")
    JOB_ID_SCOPUS: str = os.getenv("JOB_ID_SCOPUS", "")

    # OAuth
    OAUTH_CLIENT_ID: str = os.getenv("OAUTH_CLIENT_ID", "")
    OAUTH_CLIENT_SECRET: str = os.getenv("OAUTH_CLIENT_SECRET", "")
    WEB_APP_URL: str = os.getenv("WEB_APP_URL", "")
    API_URL: str = os.getenv("API_URL", "")

    # Entra
    USE_ENTRA_AUTH: bool = os.getenv("USE_ENTRA_AUTH", "false").lower() == "true"

    class Config:
        case_sensitive = True
        # Resolve to backend/.env regardless of current working directory.
        env_file = str(Path(__file__).resolve().parents[2] / ".env")
        extra = "ignore"  # Allow extra environment variables


settings = Settings()
