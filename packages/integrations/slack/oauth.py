from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

# Bot scopes for posting on behalf of the workspace.
# `chat:write.public` lets the bot post in public channels it hasn't joined.
# `groups:write` + `groups:history` are for the per-agent private channels:
# the OAuth callback creates `#marcus-publisher` and the Events API delivers
# message.groups events from it so the agent can reply in-thread.
# `users:read.email` is the identity hook — Slack messages → Marcus user via
# email match. (`users:read` is required alongside it for users.info to work.)
# `im:write` is the fallback path: when no Marcus user matches the Slack
# email, we DM the user a "link your account" prompt.
SLACK_BOT_SCOPES = [
    "chat:write",
    "chat:write.public",
    "channels:read",
    "groups:read",
    "groups:write",
    "groups:history",
    "team:read",
    "users:read",
    "users:read.email",
    "im:write",
]


# Agent slug → Slack channel name. Provisioned in the OAuth callback,
# one private channel per agent. Slugs match `packages/agents/registry.py`.
# Channel names are constrained by Slack: 1–80 chars, lowercase, no spaces,
# no periods. The `marcus-` prefix keeps them grouped in the workspace
# sidebar; future work can make this configurable per-org.
SLACK_AGENT_CHANNELS: list[tuple[str, str]] = [
    ("strategist", "marcus-strategist"),
    ("publisher", "marcus-publisher"),
    ("brand-manager", "marcus-brand-manager"),
    ("community-manager", "marcus-community-manager"),
]

AUTH_ENDPOINT = "https://slack.com/oauth/v2/authorize"
TOKEN_ENDPOINT = "https://slack.com/api/oauth.v2.access"

STATE_TTL_SECONDS = 600


@dataclass
class OAuthInstall:
    """Successful response from oauth.v2.access.

    Slack tokens don't expire by default (token rotation is opt-in), so there's
    no `expires_in`. We still record the install timestamp for auditing.
    """
    access_token: str        # bot token, format `xoxb-...`
    token_type: str          # always "bot" for the bot access_token
    scope: str               # space-or-comma-separated granted scopes
    bot_user_id: str | None
    app_id: str | None
    team_id: str | None
    team_name: str | None
    authed_user_id: str | None
    authed_user_token: str | None  # xoxp- if user_scope was requested


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def sign_state(payload: dict, secret: str) -> str:
    payload = {**payload, "nonce": secrets.token_urlsafe(16), "iat": int(time.time())}
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(sig)}"


def verify_state(token: str, secret: str) -> dict:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise ValueError("Malformed state")

    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_decode(sig), expected):
        raise ValueError("Bad state signature")

    payload = json.loads(_b64url_decode(body))
    if int(time.time()) - int(payload.get("iat", 0)) > STATE_TTL_SECONDS:
        raise ValueError("State expired")
    return payload


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        # Slack expects comma-separated, not space-separated.
        "scope": ",".join(SLACK_BOT_SCOPES),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_code(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> OAuthInstall:
    """Exchange an auth code for a Slack install payload.

    `redirect_uri` is required by Slack and must exactly match the one used
    in the authorize URL — different domains will reject it silently with
    `bad_redirect_uri`.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Slack token exchange failed: {resp.status_code} {resp.text}")
    body = resp.json()
    if not body.get("ok"):
        # Slack returns 200 with `ok: false` for OAuth failures — that's the real
        # error path here, not the HTTP status above.
        raise RuntimeError(f"Slack rejected install: {body.get('error') or body}")

    team = body.get("team") or {}
    authed_user = body.get("authed_user") or {}
    return OAuthInstall(
        access_token=body["access_token"],
        token_type=body.get("token_type", "bot"),
        scope=body.get("scope", ""),
        bot_user_id=body.get("bot_user_id"),
        app_id=body.get("app_id"),
        team_id=team.get("id"),
        team_name=team.get("name"),
        authed_user_id=authed_user.get("id"),
        authed_user_token=authed_user.get("access_token"),
    )


async def auth_test(access_token: str) -> dict:
    """Hit auth.test to verify the token + pull a friendly team name/url back."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"Slack auth.test failed: {body.get('error') or body}")
    return {
        "team": body.get("team"),
        "team_id": body.get("team_id"),
        "user": body.get("user"),
        "user_id": body.get("user_id"),
        "url": body.get("url"),
    }
