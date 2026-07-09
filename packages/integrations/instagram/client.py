"""
Instagram (Meta Graph API) client — Reels publishing for approved clips.

DORMANT UNTIL CONFIGURED: the client's Instagram must be a Business/Creator
account linked to a Facebook Page, and the Meta app needs content-publish
approval — none of which exists yet (client account details pending). The
implementation is complete behind `is_configured()` so the day the
credentials land it's a .env change, not a code sprint:

    INSTAGRAM_ACCESS_TOKEN        — long-lived Page/system-user token
    INSTAGRAM_BUSINESS_ACCOUNT_ID — the IG Business account id (17841...)

Reels publish is Meta's standard two-step: create a media container with a
public video URL, poll until Meta finishes ingesting, then publish the
container. Same graceful-degradation contract as Riverside/Opus: the
publish runner records "skipped — not configured" until the keys exist.
"""
from __future__ import annotations

import asyncio
import os

import httpx

GRAPH_BASE = "https://graph.facebook.com/v21.0"

# Meta ingests the video server-side; poll the container until it's ready.
CONTAINER_POLL_SECONDS = 10
CONTAINER_TIMEOUT_SECONDS = 600


class InstagramUnavailable(RuntimeError):
    """Instagram isn't configured (token / business account id missing)."""


class InstagramError(RuntimeError):
    """Instagram is configured but a Graph API call failed."""


def is_configured() -> bool:
    return bool(
        os.environ.get("INSTAGRAM_ACCESS_TOKEN")
        and os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    )


def _creds() -> tuple[str, str]:
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    account = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    if not token or not account:
        raise InstagramUnavailable(
            "Instagram isn't configured — set INSTAGRAM_ACCESS_TOKEN and "
            "INSTAGRAM_BUSINESS_ACCOUNT_ID (requires a Business/Creator "
            "account linked to a Facebook Page)."
        )
    return token, account


async def publish_reel(video_url: str, caption: str = "") -> dict:
    """Publish a Reel from a publicly-reachable video URL.

    Returns {"media_id"}. Raises InstagramUnavailable when unconfigured,
    InstagramError on any Graph API failure or ingest timeout.
    """
    token, account = _creds()
    # Token rides in the Authorization header, NEVER in the query string —
    # httpx logs full request URLs at INFO, and a long-lived Meta token in
    # any access/proxy log is a standing credential leak.
    auth = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=60, headers=auth) as client:
        create = await client.post(
            f"{GRAPH_BASE}/{account}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption[:2200],
            },
        )
        if create.status_code >= 400:
            raise InstagramError(f"Reel container create failed: {create.status_code} {create.text[:300]}")
        container_id = (create.json() or {}).get("id")
        if not container_id:
            raise InstagramError(f"Reel container create returned no id: {create.text[:200]}")

        # Wait for Meta to finish ingesting the video (wall-clock bounded).
        import time

        deadline = time.monotonic() + CONTAINER_TIMEOUT_SECONDS
        while True:
            status = await client.get(
                f"{GRAPH_BASE}/{container_id}",
                params={"fields": "status_code"},
            )
            code = (status.json() or {}).get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise InstagramError(f"Reel container ingest failed for {container_id}")
            if time.monotonic() >= deadline:
                raise InstagramError(
                    f"Reel container {container_id} not ready after {CONTAINER_TIMEOUT_SECONDS}s"
                )
            await asyncio.sleep(CONTAINER_POLL_SECONDS)

        publish = await client.post(
            f"{GRAPH_BASE}/{account}/media_publish",
            data={"creation_id": container_id},
        )
    if publish.status_code >= 400:
        raise InstagramError(f"Reel publish failed: {publish.status_code} {publish.text[:300]}")
    media_id = (publish.json() or {}).get("id")
    return {"media_id": media_id}
