from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated app configuration loaded from environment variables
    (and a local .env if present). Add fields here as slices need them."""

    redis_url: str = "redis://localhost:6379"
    # HMAC signing key for impressions. The dev default is fine locally, but
    # production MUST override it via env — and it must stay CONSTANT across
    # restarts, or previously-served impressions would fail verification.
    secret_key: str = "dev-insecure-change-me"
    # How long (seconds) we remember an impression_id to reject replays.
    # Bounds the dedup store's memory; impressions are short-lived, so a day
    # is plenty (60 * 60 * 24 = 86400).
    dedup_ttl: int = 86400
    # PostgreSQL connection. The '+asyncpg' dialect selects the async driver.
    # Matches the docker-compose postgres service (user/pass/db all 'adclick').
    database_url: str = "postgresql+asyncpg://adclick:adclick@localhost:5433/adclick"
    # Flush (roll-up) tuning.
    # grace: a minute isn't flushed until it ended this many seconds ago, so
    #   lagging clicks have time to land before we call the minute "final".
    # interval: how often the flush loop wakes to check for eligible minutes.
    flush_grace_seconds: int = 90
    flush_interval_seconds: int = 10
    # How long a per-minute bucket lives in Redis before it auto-expires. Must
    # comfortably exceed flush_grace_seconds so a minute is safely in Postgres
    # first; after expiry the tiered read serves that minute from the cold tier.
    # 3600 = 1h, matching the dashboard's last-hour hot window.
    redis_retention_seconds: int = 3600
    # Frontend origins allowed to call the API (browser CORS). Comma-separated
    # so it's easy to add the deployed frontend URL via an env var later.
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env")


# One module-level instance, built once at import. The lifespan reads this at
# startup (before any request exists), so it can't be a request dependency.
settings = Settings()
