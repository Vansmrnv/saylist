from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://saylist:saylist@localhost:5433/saylist"

    business_bot_token: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""  # speech-to-text only; voice notes are disabled without it
    llm_model: str = "claude-sonnet-5-5"
    llm_effort: str = "low"
    timezone: str = "Asia/Nicosia"
    request_timeout_minutes: float = 10
    draft_timeout_minutes: float = 30
    # Base for customer tracking links. Empty: taken from the incoming request (the tunnel URL).
    public_url: str = ""
    # Start the Telegram bot, outbox worker and expiry loop with the app.
    run_workers: bool = True

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def now_local() -> datetime:
    settings = get_settings()
    return datetime.now(settings.tz)
