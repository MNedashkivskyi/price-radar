"""Application configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "Price Radar API"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/price_radar"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Shopify
    shopify_api_key: str = ""
    shopify_api_secret: str = ""
    shopify_app_url: str = "http://localhost:8000"
    shopify_scopes: str = "read_products,write_products,read_orders"
    shopify_api_version: str = "2024-01"


settings = Settings()
