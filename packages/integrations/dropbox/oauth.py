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

# Standard read+write scopes. account_info.read powers the post-install
# users/get_current_account probe so we can show the user's name in the UI.
DROPBOX_SCOPES = [
    "account_info.read",
    "files.metadata.read",
    "files.metadata.write",
    "files.content.read",
    "files.content.write",
]

AUTH_ENDPOINT = "https://www.dropbox.com/oauth2/authorize"
TOKEN_ENDPOINT = "https://api.dropboxapi.com/oauth2/token"

STATE_TTL_SECONDS = 600


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str
    token_type: str
    account_id: str | None
    team_id: str | None
    uid: str | None


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
    """Build authorize URL.

    `token_access_type=offline` is the magic param that asks Dropbox for a
    refresh_token alongside the short-lived access_token. Without it, the
    access token is long-lived but you get no refresh, and revocation is
    harder to recover from. `force_reapprove=false` lets returning users
    skip the consent screen.
    """
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "token_access_type": "offline",
        "scope": " ".join(DROPBOX_SCOPES),
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> OAuthTokens:
    body = {
        "code": code,
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_ENDPOINT, data=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"Dropbox token exchange failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return OAuthTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_in=int(data.get("expires_in", 14400)),
        scope=data.get("scope", ""),
        token_type=data.get("token_type", "bearer"),
        account_id=data.get("account_id"),
        team_id=data.get("team_id"),
        uid=data.get("uid"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> OAuthTokens:
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_ENDPOINT, data=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"Dropbox token refresh failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return OAuthTokens(
        access_token=data["access_token"],
        # Dropbox doesn't always re-issue the refresh on rotation; reuse the
        # old one if missing.
        refresh_token=data.get("refresh_token") or refresh_token,
        expires_in=int(data.get("expires_in", 14400)),
        scope=data.get("scope", ""),
        token_type=data.get("token_type", "bearer"),
        account_id=data.get("account_id"),
        team_id=data.get("team_id"),
        uid=data.get("uid"),
    )


async def fetch_account_info(access_token: str) -> dict:
    """POST /2/users/get_current_account — used to display name + email post-install."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.dropboxapi.com/2/users/get_current_account",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Dropbox account lookup failed: {resp.status_code} {resp.text}")
    item = resp.json() or {}
    name = item.get("name") or {}
    return {
        "account_id": item.get("account_id"),
        "display_name": name.get("display_name"),
        "given_name": name.get("given_name"),
        "email": item.get("email"),
        "profile_photo_url": item.get("profile_photo_url"),
        "team_name": (item.get("team") or {}).get("name"),
    }
