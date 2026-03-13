from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://omnidiff:omnidiff@localhost:5432/omnidiff"

    # Embedding provider
    embedding_provider: Literal["voyage", "gemini"] = "voyage"
    embedding_model: str = "voyage-code-3"

    # LLM provider (interactive RAG)
    llm_provider: Literal["gemini", "groq"] = "gemini"
    llm_model: str = "gemini-2.0-flash"

    # LLM batch provider (NL descriptions)
    llm_batch_provider: Literal["groq", "gemini"] = "groq"
    llm_batch_model: str = "llama-3.1-8b-instant"

    # API keys
    voyage_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # Application
    app_version: str = "0.1.0"
    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
