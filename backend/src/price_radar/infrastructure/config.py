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

    # Encryption (Fernet key for encrypting access tokens in DB)
    # Generate with: python -c "from cryptography.fernet import Fernet;
    # print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    # JWT
    jwt_secret_key: str = ""  # Should be a secure random string in production
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24  # JWT token expiration time
    jwt_max_refresh_days: int = 7  # Max days after expiry a token can still be refreshed

    # Frontend
    frontend_url: str = "http://localhost:3000"  # Frontend dashboard URL

    # Monitoring
    monitoring_api_key: str = ""  # API key for /internal/* endpoints (empty = no auth)
    monitoring_alert_webhook_url: str = ""  # Webhook URL for alerts (empty = disabled)
    monitoring_alert_threshold: float = 50.0  # Success rate % below which alerts fire

    # Proxy — Decodo (Smartproxy) residential proxy
    # Format: http://user:pass@gate.smartproxy.com:10001
    # Leave empty to disable proxy routing (all requests go direct).
    decodo_proxy_url: str = ""
    # Multiple residential proxy endpoints (comma-separated).
    # When set, the proxy resolver rotates across all endpoints in
    # round-robin order, spreading traffic across gateway nodes.
    # Takes precedence over decodo_proxy_url.
    # Example: http://user:pass@gate.smartproxy.com:10001,http://user:pass@gate.smartproxy.com:10002,...
    decodo_proxy_urls: str = ""
    # Re-classify domains whose proxy tier was learned more than N days ago.
    proxy_tier_ttl_days: int = 7

    # Decodo Web Scraping API — last-resort fetch tier for CAPTCHA-blocked sites
    # Requires a Decodo Web Scraping API subscription (Advanced for JS rendering).
    # Token is found in the Decodo dashboard → Scraping tab → Authentication.
    decodo_api_token: str = ""


settings = Settings()
