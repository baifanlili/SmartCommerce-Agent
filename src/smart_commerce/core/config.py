from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SmartCommerce-Agent"
    environment: str = "development"
    redis_url: str = "redis://localhost:6379/0"
    llm_provider: str = "mock"
    llm_api_key: str | None = None
    llm_model: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
