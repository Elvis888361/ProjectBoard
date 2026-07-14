from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://taskboard:taskboard@localhost:5432/taskboard"

    # No default. If this isn't set the app must refuse to start rather than sign
    # tokens with a value an attacker can read off GitHub.
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 60 * 12

    # `secure` is off for local http. Everything else about the cookie is the same
    # in dev and prod, which is the point -- I don't want auth behaving differently
    # in the environment where I test it.
    cookie_name: str = "taskboard_session"
    cookie_secure: bool = False

    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 60

    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
