import os
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

    # CORS
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    # Storage settings
    STORAGE_TYPE: str = os.getenv("STORAGE_TYPE", "azure")
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = os.getenv(
        "AZURE_STORAGE_CONNECTION_STRING"
    )
    AZURE_STORAGE_CONTAINER_NAME: str = os.getenv(
        "AZURE_STORAGE_CONTAINER_NAME", "can-sr-storage"
    )

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

    # GPT-3.5-turbo configuration
    AZURE_OPENAI_GPT35_API_KEY: Optional[str] = os.getenv("AZURE_OPENAI_GPT35_API_KEY")
    AZURE_OPENAI_GPT35_ENDPOINT: Optional[str] = os.getenv(
        "AZURE_OPENAI_GPT35_ENDPOINT"
    )
    AZURE_OPENAI_GPT35_DEPLOYMENT: str = os.getenv(
        "AZURE_OPENAI_GPT35_DEPLOYMENT", "gpt-35-turbo"
    )
    AZURE_OPENAI_GPT35_API_VERSION: str = os.getenv(
        "AZURE_OPENAI_GPT35_API_VERSION", "2023-03-15-preview"
    )

    # GPT-4o-mini configuration
    AZURE_OPENAI_GPT4O_MINI_API_KEY: Optional[str] = os.getenv(
        "AZURE_OPENAI_GPT4O_MINI_API_KEY"
    )
    AZURE_OPENAI_GPT4O_MINI_ENDPOINT: Optional[str] = os.getenv(
        "AZURE_OPENAI_GPT4O_MINI_ENDPOINT"
    )
    AZURE_OPENAI_GPT4O_MINI_DEPLOYMENT: str = os.getenv(
        "AZURE_OPENAI_GPT4O_MINI_DEPLOYMENT", "gpt-4o-mini"
    )
    AZURE_OPENAI_GPT4O_MINI_API_VERSION: str = os.getenv(
        "AZURE_OPENAI_GPT4O_MINI_API_VERSION", "2025-01-01-preview"
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

    # Default model to use
    DEFAULT_CHAT_MODEL: str = os.getenv("DEFAULT_CHAT_MODEL", "gpt-4o")

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Additional settings
    ALLOW_USER_REGISTRATION: bool = (
        os.getenv("ALLOW_USER_REGISTRATION", "true").lower() == "true"
    )
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Database and external system environment variables
    # Postgres DSN used for systematic reviews and screening databases
    POSTGRES_URI: str = os.getenv("POSTGRES_URI")

    # Databricks settings
    DATABRICKS_INSTANCE: str = os.getenv("DATABRICKS_INSTANCE")
    DATABRICKS_TOKEN: str = os.getenv("DATABRICKS_TOKEN")
    JOB_ID_EUROPEPMC: str = os.getenv("JOB_ID_EUROPEPMC")
    JOB_ID_PUBMED: str = os.getenv("JOB_ID_PUBMED")
    JOB_ID_SCOPUS: str = os.getenv("JOB_ID_SCOPUS")

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"  # Allow extra environment variables


settings = Settings()
