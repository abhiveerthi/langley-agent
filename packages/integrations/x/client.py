from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx
from supabase import Client

from packages.integrations.x.oauth import (
    OAuthTokens,
    refresh_access_token,
)

PROVIDER = "twitter"
REFRESH_SKEW_SECONDS = 120


def _expires_at(expires_in: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()


def get_connection(supabase: Client, org_id: str) -> dict | None:
    resp = (
        supabase.table("integrations")
        .select("*")
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def save_connection(
    supabase: Client,
    org_id: str,
    tokens: OAuthTokens,
    user: dict,
) -> dict:
    row = {
        "org_id": org_id,
        "provider": PROVIDER,
        "status": "active",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_expires_at": _expires_at(tokens.expires_in),
        "scopes": tokens.scope.split() if tokens.scope else [],
        "metadata": user,
    }
    resp = (
        supabase.table("integrations")
        .upsert(row, on_conflict="org_id,provider")
        .execute()
    )
    return resp.data[0]


def delete_connection(supabase: Client, org_id: str) -> None:
    (
        supabase.table("integrations")
        .delete()
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )


async def get_fresh_access_token(
    supabase: Client,
    org_id: str,
    client_id: str,
    client_secret: str | None = None,
) -> str:
    conn = get_connection(supabase, org_id)
    if not conn:
        raise RuntimeError("X is not connected for this org")

    expires_at_iso = conn.get("token_expires_at")
    expired = True
    if expires_at_iso:
        expires_dt = datetime.fromisoformat(expires_at_iso.replace("Z", "+00:00"))
        expired = expires_dt.timestamp() - time.time() < REFRESH_SKEW_SECONDS

    if not expired:
        return conn["access_token"]

    if not conn.get("refresh_token"):
        raise RuntimeError(
            "No refresh token on file; reconnect X (the offline.access scope is required)"
        )

    tokens = await refresh_access_token(
        conn["refresh_token"], client_id, client_secret=client_secret
    )
    (
        supabase.table("integrations")
        .update(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_expires_at": _expires_at(tokens.expires_in),
                "scopes": tokens.scope.split() if tokens.scope else conn.get("scopes", []),
                "status": "active",
            }
        )
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )
    return tokens.access_token


async def mark_connection_error(supabase: Client, org_id: str, error: str) -> None:
    conn = get_connection(supabase, org_id)
    metadata = (conn or {}).get("metadata") or {}
    metadata["last_error"] = error
    (
        supabase.table("integrations")
        .update({"status": "error", "metadata": metadata})
        .eq("org_id", org_id)
        .eq("provider", PROVIDER)
        .execute()
    )


def get_authenticated_user(supabase: Client, org_id: str) -> dict | None:
    """Return the X user record stored at connect time (id, username, name).

    The Community Manager needs the authenticated user_id to pull *the user's
    own tweets* — without it we can't scope the timeline read to the right
    account. Stored in `integrations.metadata` by `save_connection`.
    """
    conn = get_connection(supabase, org_id)
    if not conn:
        return None
    meta = conn.get("metadata") or {}
    if not meta.get("user_id"):
        return None
    return {
        "user_id": meta.get("user_id"),
        "username": meta.get("username"),
        "name": meta.get("name"),
    }


async def get_user_tweets(
    access_token: str,
    user_id: str,
    *,
    max_results: int = 10,
) -> list[dict]:
    """GET /2/users/:id/tweets — the authenticated user's recent original tweets.

    Excludes retweets and replies so the triage pass only operates on the
    user's *own* threads. Returns a list of {id, text, created_at,
    public_metrics, conversation_id} dicts.

    Raises RuntimeError with a friendly message on the usual failure modes
    (rate limit, expired token, free-tier read block).
    """
    # X caps max_results in [5, 100] for this endpoint.
    capped = max(5, min(int(max_results), 100))
    params = {
        "max_results": capped,
        "exclude": "retweets,replies",
        "tweet.fields": "created_at,public_metrics,conversation_id",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"https://api.x.com/2/users/{user_id}/tweets",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code == 200:
        return list((resp.json().get("data") or []))
    _raise_for_x_status(resp, what="fetch user tweets")
    return []


async def get_tweet_replies(
    access_token: str,
    conversation_id: str,
    *,
    author_id: str,
    max_results: int = 100,
) -> list[dict]:
    """Replies to one of the user's tweets, fetched via the recent-search
    endpoint with a `conversation_id:<id>` query.

    `author_id` is the connected user's own id; we use it to filter out their
    own replies inside their own thread (so a self-reply doesn't get triaged
    as an incoming comment) and to detect whether the user already replied to
    a given commenter — analogous to the YouTube "owner already replied" guard.

    Returns a list of reply tweet dicts with author + text + metrics expanded.
    """
    capped = max(10, min(int(max_results), 100))
    params = {
        "query": f"conversation_id:{conversation_id}",
        "max_results": capped,
        "tweet.fields": "created_at,public_metrics,in_reply_to_user_id,author_id,conversation_id",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics,verified",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.x.com/2/tweets/search/recent",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        _raise_for_x_status(resp, what="fetch tweet replies")
        return []

    payload = resp.json()
    tweets = payload.get("data") or []
    users_by_id = {
        u["id"]: u for u in ((payload.get("includes") or {}).get("users") or [])
    }
    out: list[dict] = []
    for t in tweets:
        a_id = t.get("author_id") or ""
        # Skip the user's own contributions to their thread.
        if a_id == author_id:
            continue
        user = users_by_id.get(a_id) or {}
        out.append({
            "id": t.get("id"),
            "text": t.get("text") or "",
            "created_at": t.get("created_at"),
            "author_id": a_id,
            "author_username": user.get("username"),
            "author_name": user.get("name"),
            "author_followers": ((user.get("public_metrics") or {}).get("followers_count")),
            "author_verified": user.get("verified", False),
            "in_reply_to_user_id": t.get("in_reply_to_user_id"),
            "metrics": t.get("public_metrics") or {},
            "conversation_id": t.get("conversation_id"),
        })
    return out


async def lookup_user(access_token: str, handle_or_id: str) -> dict | None:
    """GET /2/users by username or id. Returns dict or None when not found."""
    is_id = handle_or_id.isdigit() and len(handle_or_id) >= 5
    base = "https://api.x.com/2"
    if is_id:
        url = f"{base}/users/{handle_or_id}"
    else:
        url = f"{base}/users/by/username/{handle_or_id.lstrip('@')}"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            url,
            params={"user.fields": "public_metrics,verified,description,created_at"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        _raise_for_x_status(resp, what="lookup user")
        return None
    return resp.json().get("data") or None


async def reply_to_tweet(access_token: str, parent_tweet_id: str, text: str) -> dict:
    """POST /2/tweets with `reply.in_reply_to_tweet_id` set — posts a reply to
    an existing tweet as the authenticated user.

    Symmetric with `post_tweet` so the Community Manager's `_send_reply_node`
    can call this when the target lives on X (vs `reply_to_comment` for YT).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.x.com/2/tweets",
            json={"text": text, "reply": {"in_reply_to_tweet_id": parent_tweet_id}},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code == 201:
        data = resp.json().get("data") or {}
        return {"id": data.get("id"), "text": data.get("text") or text}
    _raise_for_x_status(resp, what="reply to tweet")
    return {}


def _raise_for_x_status(resp: httpx.Response, *, what: str) -> None:
    """Translate non-2xx X API responses into a friendly RuntimeError.

    Mirrors the messaging in `post_tweet` so every X call surfaces the same
    "this is the actual cause" hint for free-tier blocks, rate limits, and
    expired tokens — instead of a bare HTTP status the LLM has to interpret.
    """
    body = resp.text
    if resp.status_code == 403:
        raise RuntimeError(
            f"X rejected the {what} call (403). Reads/writes beyond the Free "
            f"tier require Basic ($200/mo) or higher, or the connected app "
            f"may be missing the required scope. Body: {body}"
        )
    if resp.status_code == 429:
        retry_after = resp.headers.get("x-rate-limit-reset") or resp.headers.get("retry-after")
        raise RuntimeError(
            f"X rate limit hit while trying to {what} (429). "
            f"Retry after {retry_after or 'unknown'}: {body}"
        )
    if resp.status_code == 401:
        raise RuntimeError(
            f"X access token rejected while trying to {what} (401). Reconnect X. Body: {body}"
        )
    raise RuntimeError(f"X {what} failed: {resp.status_code} {body}")


async def post_tweet(access_token: str, text: str) -> dict:
    """POST /2/tweets. Returns {id, text} on success.

    Raises RuntimeError with a friendly message on common failure modes
    (free-tier write block, rate limit, expired token).
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.x.com/2/tweets",
            json={"text": text},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    if resp.status_code == 201:
        data = resp.json().get("data") or {}
        return {"id": data.get("id"), "text": data.get("text") or text}

    body = resp.text
    if resp.status_code == 403:
        # Most common cause: free tier doesn't allow POST /2/tweets.
        raise RuntimeError(
            "X rejected the post (403). Writes require the Basic ($200/mo) tier or "
            f"higher, or the connected app may be missing tweet.write scope. Body: {body}"
        )
    if resp.status_code == 429:
        retry_after = resp.headers.get("x-rate-limit-reset") or resp.headers.get("retry-after")
        raise RuntimeError(
            f"X rate limit hit (429). Retry after {retry_after or 'unknown'}: {body}"
        )
    if resp.status_code == 401:
        raise RuntimeError(f"X access token rejected (401). Reconnect X. Body: {body}")
    raise RuntimeError(f"X tweet failed: {resp.status_code} {body}")
