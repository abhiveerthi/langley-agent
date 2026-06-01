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

    # Google OAuth (YouTube + Gmail share the same OAuth client; each
    # service has its own redirect URI registered in the Google console).
    google_client_id: str = ""
    google_client_secret: str = ""
    youtube_oauth_redirect_uri: str = "http://localhost:3000/auth/youtube/callback"
    gmail_oauth_redirect_uri: str = "http://localhost:3000/auth/gmail/callback"

    # X (Twitter) OAuth 2.0 with PKCE.
    # client_secret is optional — leave it blank for Public clients (PKCE only).
    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    twitter_oauth_redirect_uri: str = "http://localhost:3000/auth/twitter/callback"

    # Slack OAuth v2 (workspace install). client_secret is required.
    # Note: Slack requires https for redirect URIs once "Public Distribution"
    # is enabled. With Public Distribution off (Development app only), http
    # is accepted again.
    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_oauth_redirect_uri: str = "http://localhost:3000/auth/slack/callback"
    # Signing secret for the Events API webhook. Authenticates Slack → us
    # callbacks (HMAC-SHA256 over the raw body). Found in the Slack App
    # dashboard under Basic Information → Signing Secret.
    slack_signing_secret: str = ""

    # Dropbox OAuth 2.0. Uses token_access_type=offline so we get a refresh
    # token alongside the short-lived (4h) access token.
    dropbox_client_id: str = ""
    dropbox_client_secret: str = ""
    dropbox_oauth_redirect_uri: str = "http://localhost:3000/auth/dropbox/callback"

    # monday.com OAuth 2.0. Tokens are long-lived (no expiry, no refresh).
    monday_client_id: str = ""
    monday_client_secret: str = ""
    monday_oauth_redirect_uri: str = "http://localhost:3000/auth/monday/callback"

    # Resend transactional email — used for org-invite delivery. The
    # email_from domain must have SPF + DKIM configured on the registrar
    # before invitations land in inboxes instead of spam folders.
    resend_api_key: str = ""
    email_from: str = "Backroom <invites@backroom.app>"

    # Background scheduler (apps/api/app/services/scheduler.py). The poll loop
    # is started from the FastAPI lifespan ONLY when `scheduler_enabled` is
    # true. It defaults OFF so importing the app in tests / scripts never
    # spawns a live network loop; production turns it on via SCHEDULER_ENABLED=
    # true (set in the deploy env). `scheduler_poll_interval_seconds` is how
    # often the YouTube new-upload poller wakes; 300s (5 min) balances
    # freshness against YouTube Data API quota.
    scheduler_enabled: bool = False
    scheduler_poll_interval_seconds: int = 300

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
