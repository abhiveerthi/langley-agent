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

X_SCOPES = [
    "tweet.read",
    "tweet.write",
    "users.read",
    "offline.access",
]

AUTH_ENDPOINT = "https://x.com/i/oauth2/authorize"
TOKEN_ENDPOINT = "https://api.x.com/2/oauth2/token"

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


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE verifier/challenge pair using S256."""
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url_encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


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


def build_auth_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(X_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _basic_auth_header(client_id: str, client_secret: str) -> dict[str, str]:
    blob = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    return {"Authorization": f"Basic {blob}"}


async def exchange_code(
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    *,
    client_secret: str | None = None,
) -> OAuthTokens:
    """Exchange an auth code for tokens.

    Confidential clients (with a `client_secret`) authenticate via HTTP Basic
    header — the body must NOT include `client_id` in that case. Public clients
    (no secret) include `client_id` in the body and skip the header. X enforces
    this distinction strictly.
    """
    body: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    headers: dict[str, str] = {}
    if client_secret:
        headers.update(_basic_auth_header(client_id, client_secret))
    else:
        body["client_id"] = client_id

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_ENDPOINT, data=body, headers=headers)
    if resp.status_code >= 400:
        raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return OAuthTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token"),
        expires_in=int(data.get("expires_in", 7200)),
        scope=data.get("scope", ""),
        token_type=data.get("token_type", "bearer"),
    )


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    *,
    client_secret: str | None = None,
) -> OAuthTokens:
    body: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers: dict[str, str] = {}
    if client_secret:
        headers.update(_basic_auth_header(client_id, client_secret))
    else:
        body["client_id"] = client_id

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_ENDPOINT, data=body, headers=headers)
    if resp.status_code >= 400:
        raise RuntimeError(f"Token refresh failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return OAuthTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token") or refresh_token,
        expires_in=int(data.get("expires_in", 7200)),
        scope=data.get("scope", ""),
        token_type=data.get("token_type", "bearer"),
    )


async def fetch_user_info(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.x.com/2/users/me",
            params={"user.fields": "profile_image_url,username,name"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"User lookup failed: {resp.status_code} {resp.text}")
    item = (resp.json().get("data") or {}) or {}
    if not item:
        raise RuntimeError("No user payload returned from X")
    return {
        "user_id": item.get("id"),
        "username": item.get("username"),
        "name": item.get("name"),
        "profile_image_url": item.get("profile_image_url"),
    }
