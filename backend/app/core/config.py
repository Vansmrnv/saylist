from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://saylist:saylist@localhost:5433/saylist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
