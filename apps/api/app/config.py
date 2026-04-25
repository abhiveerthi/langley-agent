from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase — accept either the standard name or the NEXT_PUBLIC_ prefixed one
    supabase_url: str = Field(
        "",
        validation_alias=AliasChoices("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL"),
    )
    supabase_anon_key: str = Field(
        "",
        validation_alias=AliasChoices("SUPABASE_ANON_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY"),
    )
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

    # Google OAuth (YouTube + future Google services)
    google_client_id: str = ""
    google_client_secret: str = ""
    youtube_oauth_redirect_uri: str = "http://localhost:3000/auth/youtube/callback"

    # X (Twitter) OAuth 2.0 with PKCE.
    # client_secret is optional — leave it blank for Public clients (PKCE only).
    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    twitter_oauth_redirect_uri: str = "http://localhost:3000/auth/twitter/callback"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
