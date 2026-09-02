from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SmartCommerce-Agent"
    environment: str = "development"
    identity_mode: Literal["development", "gateway"] = "development"
    identity_gateway_token: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    llm_provider: str = "mock"
    llm_api_key: str | None = None
    llm_model: str | None = "deepseekflash"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_mode: Literal["chat", "responses"] = "chat"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    admin_token: str | None = None
    runtime_config_db_path: str = "runtime-config.sqlite3"
    runtime_config_encryption_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
