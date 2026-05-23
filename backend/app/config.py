"""Application configuration loaded from environment variables."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Loaded from env / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql+asyncpg://cryptobot:devpass@localhost:5432/cryptobot",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://cryptobot:devpass@localhost:5432/cryptobot",
        alias="DATABASE_URL_SYNC",
    )
    test_database_url: str = Field(
        default="postgresql+asyncpg://cryptobot:devpass@localhost:5432/cryptobot_test",
        alias="TEST_DATABASE_URL",
    )


settings = Settings()
