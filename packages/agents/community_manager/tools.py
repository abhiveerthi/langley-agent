"""
Community Manager tools.

Two read-only Data-API tools (`get_recent_comments`, `lookup_channel`) plus
one OAuth-backed write tool (`reply_to_comment`) — every YouTube call is
made on behalf of the connected creator using their per-org refresh token.
The write tool is additionally gated by the agent's approval_gate at the
graph level so a draft must be approved before it fires.
"""
from __future__ import annotations

import os

import httpx
from langchain_core.tools import tool

from packages.agents.core.clients import youtube_api_get_oauth
from packages.integrations.context import current_org_id, current_supabase
from packages.integrations.youtube.client import get_fresh_access_token


async def _oauth_access_token() -> str:
    """Resolve a fresh YouTube OAuth access token for the current org.

    Raises RuntimeError on misconfiguration / missing connection so callers
    can surface a friendly error message back to the LLM.
    """
    org_id = current_org_id.get()
    supabase = current_supabase.get()
    if not org_id or supabase is None:
        raise RuntimeError("no org context (running without auth)")

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("GOOGLE_CLIENT_ID/SECRET not configured")

    return await get_fresh_access_token(supabase, org_id, client_id, client_secret)


# ── Read-only tools (Data API via OAuth) ──────────────────────────────────

@tool
async def get_recent_comments(
    channel_id: str,
    max_videos: int = 5,
    per_video: int = 20,
) -> str:
    """Get recent comments across the creator's most recent uploads.

    Args:
        channel_id: The YouTube channel ID. Supplied per-tenant via the system prompt.
        max_videos: How many recent videos to pull comments from (default 5, max 10).
        per_video: Comments per video (default 20, max 50).
    """
    if not channel_id:
        return "No YouTube channel_id supplied."

    max_videos = min(max(max_videos, 1), 10)
    per_video = min(max(per_video, 1), 50)

    try:
        access_token = await _oauth_access_token()
    except Exception as e:
        return f"Error: YouTube OAuth not available ({e}). Connect YouTube in Settings."

    try:
        search_data = await youtube_api_get_oauth("search", {
            "part": "id,snippet",
            "channelId": channel_id,
            "order": "date",
            "type": "video",
            "maxResults": max_videos,
        }, access_token)

        output = "# Recent Comments\n\n"
        for item in search_data.get("items", []):
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            output += f"## {title} (video_id: {video_id})\n"

            try:
                comments_data = await youtube_api_get_oauth("commentThreads", {
                    "part": "snippet",
                    "videoId": video_id,
                    "order": "time",
                    "maxResults": per_video,
                }, access_token)
                comments = comments_data.get("items", [])
                if not comments:
                    output += "(no comments)\n\n"
                    continue
                for c in comments:
                    top = c["snippet"]["topLevelComment"]
                    s = top["snippet"]
                    comment_id = top["id"]
                    author = s.get("authorDisplayName", "unknown")
                    author_channel = s.get("authorChannelId", {}).get("value", "")
                    likes = s.get("likeCount", 0)
                    text = s["textDisplay"][:280]
                    output += (
                        f"- [{comment_id}] **{author}** ({author_channel}) "
                        f"[{likes}👍]: {text}\n"
                    )
                output += "\n"
            except Exception as e:
                output += f"(error fetching comments: {e})\n\n"

        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool
async def lookup_channel(handle_or_id: str) -> str:
    """Look up a YouTube channel by handle (e.g. '@MrBeast') or channel ID — useful for flagging VIP commenters.

    Args:
        handle_or_id: Channel handle (with or without @) or channel ID.
    """
    is_id = handle_or_id.startswith("UC") and len(handle_or_id) > 20
    params: dict = {"part": "snippet,statistics"}
    if is_id:
        params["id"] = handle_or_id
    else:
        params["forHandle"] = handle_or_id.lstrip("@")

    try:
        access_token = await _oauth_access_token()
    except Exception as e:
        return f"Error: YouTube OAuth not available ({e}). Connect YouTube in Settings."

    try:
        data = await youtube_api_get_oauth("channels", params, access_token)
        items = data.get("items", [])
        if not items:
            return f"No channel found for '{handle_or_id}'."

        it = items[0]
        s = it["snippet"]
        st = it["statistics"]
        subs = int(st.get("subscriberCount", 0))
        tier = "major" if subs >= 100_000 else "mid" if subs >= 10_000 else "small"
        return (
            f"# {s['title']}\n"
            f"- Channel ID: {it['id']}\n"
            f"- Subscribers: {subs:,} ({tier})\n"
            f"- Total views: {int(st.get('viewCount', 0)):,}\n"
            f"- Videos: {int(st.get('videoCount', 0)):,}\n"
            f"- Created: {s.get('publishedAt', 'N/A')[:10]}\n"
            f"- Description: {s.get('description', '')[:300]}\n"
        )
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching channel: {e}"


# ── OAuth-backed write tool ───────────────────────────────────────────────

async def reply_to_comment(parent_comment_id: str, text: str) -> str:
    """Post a reply to a top-level comment as the connected creator.

    NOTE: Not exposed to the LLM as a `@tool` — the agent calls this directly
    from `_send_reply_node` only AFTER the approval_gate has been cleared.
    The graph-level interrupt is what protects writes; the LLM never has
    access to this function as a tool.

    Uses the per-org OAuth refresh token from the `integrations` table.
    Required scope: `https://www.googleapis.com/auth/youtube.force-ssl`
    (already requested in packages/integrations/youtube/oauth.py).

    Args:
        parent_comment_id: The top-level comment's YouTube ID.
        text: The reply body. Plain text; YouTube auto-renders.

    Returns a short confirmation string suitable for the chat reply, or an
    error message if the call failed (token issues, missing scope, etc.).
    """
    try:
        access_token = await _oauth_access_token()
    except Exception as e:
        return f"Cannot post reply: YouTube OAuth not available ({e})."

    payload = {
        "snippet": {
            "parentId": parent_comment_id,
            "textOriginal": text,
        }
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://www.googleapis.com/youtube/v3/comments",
                params={"part": "snippet"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            posted_id = data.get("id", "(unknown)")
            return f"Reply posted (comment id: {posted_id})."
    except httpx.HTTPStatusError as e:
        return f"YouTube rejected the reply ({e.response.status_code}): {e.response.text[:200]}"
    except Exception as e:
        return f"Error posting reply: {e}"


def get_community_manager_tools():
    return [get_recent_comments, lookup_channel]
