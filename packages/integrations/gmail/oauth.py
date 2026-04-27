"""
Gmail OAuth — same Google client as YouTube, different scope set + redirect.

Scope is `gmail.send` only (sensitive, not restricted) — this is the
lightest verification path with Google. If we later need to read inbox
replies (close the loop on Brand Manager pitches) that's `gmail.readonly`,
which is *restricted* and a separate, heavier verification track.

The state-token + redirect-URI dance mirrors `packages/integrations/youtube/oauth.py`
exactly — same Google account = same flow, just a different scope. We
deliberately *don't* import the YouTube oauth helpers because the scopes
are independent and a future migration shouldn't entangle the two.
"""
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

# `gmail.send` only — sensitive scope. Sufficient for Brand Manager-style
# outreach where the reply-to is the user's own Gmail (replies thread to
# their inbox without us needing to read it).
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    # Includes a userinfo scope so we can label the connection by the
    # connected email address in the UI.
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

STATE_TTL_SECONDS = 600


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str
    token_type: str
    id_token: str | None = None


# ── State signing (HMAC-SHA256 over a tiny JSON blob) ─────────────────────

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


# ── Auth + token endpoints ────────────────────────────────────────────────

def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        # offline + prompt=consent gets us a refresh_token even on
        # repeat-grants for the same Google account.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_code(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> OAuthTokens:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return OAuthTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_in=int(data.get("expires_in", 3600)),
        scope=data.get("scope", ""),
        token_type=data.get("token_type", "Bearer"),
        id_token=data.get("id_token"),
    )


async def refresh_access_token(
    refresh_token: str, client_id: str, client_secret: str
) -> OAuthTokens:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            TOKEN_ENDPOINT,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Token refresh failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return OAuthTokens(
        access_token=data["access_token"],
        # Google may not re-issue a refresh_token on refresh — keep the
        # original if absent.
        refresh_token=data.get("refresh_token") or refresh_token,
        expires_in=int(data.get("expires_in", 3600)),
        scope=data.get("scope", ""),
        token_type=data.get("token_type", "Bearer"),
        id_token=data.get("id_token"),
    )


async def fetch_userinfo(access_token: str) -> dict:
    """Returns the connected Google account's email + profile basics so
    the UI can label the connection (e.g. 'Gmail · sean@example.com')."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Userinfo fetch failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return {
        "email": data.get("email"),
        "name": data.get("name"),
        "picture": data.get("picture"),
        "verified_email": bool(data.get("email_verified")),
    }
