"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Use DATABASE_URL to connect to Neon or another PostgreSQL server."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data/purchasing.db"
    allow_database_reset: bool = False
    llm_provider: Literal["none", "openai", "gemini"] = "none"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = ""

    approval_threshold: float = 500.00
    safety_stock_days: int = 1
    review_horizon_days: int = 1
    stale_forecast_hours: int = 72
    demand_spike_threshold: float = 0.25
    max_agent_retries: int = 2

    demo_approver: str = "buyer.demo"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()
