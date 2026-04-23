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

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.upload",
]

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

STATE_TTL_SECONDS = 600


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str
    token_type: str


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
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
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
        refresh_token=data.get("refresh_token") or refresh_token,
        expires_in=int(data.get("expires_in", 3600)),
        scope=data.get("scope", ""),
        token_type=data.get("token_type", "Bearer"),
    )


async def fetch_channel_info(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet,contentDetails,statistics", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Channel lookup failed: {resp.status_code} {resp.text}")
    items = resp.json().get("items") or []
    if not items:
        raise RuntimeError("No channel on this Google account")
    item = items[0]
    snippet = item["snippet"]
    return {
        "channel_id": item["id"],
        "channel_title": snippet.get("title"),
        "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url"),
        "uploads_playlist_id": item.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads"),
        "subscriber_count": int(item.get("statistics", {}).get("subscriberCount", 0)),
    }
