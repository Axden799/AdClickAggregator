from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated app configuration loaded from environment variables
    (and a local .env if present). Add fields here as slices need them."""

    redis_url: str = "redis://localhost:6379"
    # HMAC signing key for impressions. The dev default is fine locally, but
    # production MUST override it via env — and it must stay CONSTANT across
    # restarts, or previously-served impressions would fail verification.
    secret_key: str = "dev-insecure-change-me"

    model_config = SettingsConfigDict(env_file=".env")


# One module-level instance, built once at import. The lifespan reads this at
# startup (before any request exists), so it can't be a request dependency.
settings = Settings()
