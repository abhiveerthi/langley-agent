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

# Read+write scopes for boards/items + identity. me:read powers the post-install
# probe so we can show the connected user's name in the UI.
MONDAY_SCOPES = [
    "boards:read",
    "boards:write",
    "me:read",
]

AUTH_ENDPOINT = "https://auth.monday.com/oauth2/authorize"
TOKEN_ENDPOINT = "https://auth.monday.com/oauth2/token"
GRAPHQL_ENDPOINT = "https://api.monday.com/v2"

STATE_TTL_SECONDS = 600


@dataclass
class OAuthTokens:
    """monday.com tokens are long-lived (no expiry) and there are no refresh
    tokens. We still keep the dataclass shape for parity with other providers."""
    access_token: str
    token_type: str
    scope: str


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
        "state": state,
        # Space-separated per OAuth 2.0 spec; monday accepts this form.
        "scope": " ".join(MONDAY_SCOPES),
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> OAuthTokens:
    body = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_ENDPOINT, data=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"monday.com token exchange failed: {resp.status_code} {resp.text}")
    data = resp.json()
    if not data.get("access_token"):
        raise RuntimeError(f"monday.com response missing access_token: {data}")
    return OAuthTokens(
        access_token=data["access_token"],
        token_type=data.get("token_type", "Bearer"),
        scope=data.get("scope", ""),
    )


async def fetch_account_info(access_token: str) -> dict:
    """Hit the GraphQL API's `me` query to surface the connected user + account."""
    query = """
    query {
      me {
        id
        name
        email
        photo_thumb_small
        account { id name slug }
      }
    }
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            GRAPHQL_ENDPOINT,
            json={"query": query},
            headers={
                "Authorization": access_token,
                "Content-Type": "application/json",
                "API-Version": "2024-01",
            },
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"monday.com me-query failed: {resp.status_code} {resp.text}")
    body = resp.json() or {}
    if body.get("errors"):
        raise RuntimeError(f"monday.com graphql errors: {body['errors']}")
    me = ((body.get("data") or {}).get("me") or {})
    account = me.get("account") or {}
    return {
        "user_id": me.get("id"),
        "name": me.get("name"),
        "email": me.get("email"),
        "profile_image_url": me.get("photo_thumb_small"),
        "account_id": account.get("id"),
        "account_name": account.get("name"),
        "account_slug": account.get("slug"),
    }
