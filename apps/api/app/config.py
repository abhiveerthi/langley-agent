from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    database_url: str = "postgresql://postgres:postgres@localhost:54322/postgres"

    # Anthropic
    anthropic_api_key: str = ""

    # App
    environment: str = "development"
    api_url: str = "http://localhost:8000"
    app_url: str = "http://localhost:3000"
    jwt_secret: str = ""

    # Encryption
    encryption_key: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
