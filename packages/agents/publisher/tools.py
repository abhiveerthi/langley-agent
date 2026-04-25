import json
from datetime import datetime

import httpx
from langchain_core.tools import tool

from packages.agents.core.clients import perplexity_search, youtube_api_get
from packages.integrations.context import current_org_id, current_supabase
from packages.integrations.x.client import (
    get_fresh_access_token as x_get_fresh_access_token,
    post_tweet as x_post_tweet,
)
from packages.integrations.youtube.client import (
    get_connection,
    get_fresh_access_token,
)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


def _oauth_context():
    org_id = current_org_id.get()
    supabase = current_supabase.get()
    if not org_id or supabase is None:
        return None, None, "No authenticated session. Sign in before using this tool."
    return org_id, supabase, None


async def _access_token(org_id, supabase) -> tuple[str | None, str | None]:
    import os
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None, "Google OAuth is not configured on the server."
    try:
        token = await get_fresh_access_token(supabase, org_id, client_id, client_secret)
        return token, None
    except RuntimeError as e:
        return None, str(e)


@tool
async def get_video_details(video_id: str) -> str:
    """Get full details of a YouTube video: title, description, tags, stats, duration.

    Args:
        video_id: The YouTube video ID (the bit after `v=` in the URL).
    """
    try:
        data = await youtube_api_get("videos", {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
        })
        items = data.get("items", [])
        if not items:
            return f"Video {video_id} not found."

        item = items[0]
        snippet = item["snippet"]
        stats = item["statistics"]
        content = item["contentDetails"]

        return (
            f"# {snippet['title']}\n\n"
            f"- Video ID: {video_id}\n"
            f"- Published: {snippet['publishedAt']}\n"
            f"- Channel: {snippet.get('channelTitle', 'N/A')}\n"
            f"- Duration: {content['duration']}\n"
            f"- Views: {int(stats.get('viewCount', 0)):,} | "
            f"Likes: {int(stats.get('likeCount', 0)):,} | "
            f"Comments: {int(stats.get('commentCount', 0)):,}\n\n"
            f"## Current Description\n{snippet.get('description', '(empty)')}\n\n"
            f"## Current Tags\n{', '.join(snippet.get('tags', [])) or '(none)'}\n"
        )
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching video: {e}"


@tool
async def get_video_comments(video_id: str, max_comments: int = 25) -> str:
    """Get recent top-level comments on a video — useful for FAQs and pinned-comment ideas.

    Args:
        video_id: The YouTube video ID.
        max_comments: Max comments to return (default 25, max 50).
    """
    max_comments = min(max(max_comments, 1), 50)
    try:
        data = await youtube_api_get("commentThreads", {
            "part": "snippet",
            "videoId": video_id,
            "order": "relevance",
            "maxResults": max_comments,
        })
        items = data.get("items", [])
        if not items:
            return "No comments found."

        output = f"# Top {len(items)} Comments — {video_id}\n\n"
        for i, c in enumerate(items, 1):
            s = c["snippet"]["topLevelComment"]["snippet"]
            output += f"{i}. ({s.get('likeCount', 0)} likes) {s['textDisplay'][:240]}\n"
        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching comments: {e}"


@tool
async def suggest_seo_keywords(topic: str) -> str:
    """Get current search keywords, long-tail queries, and People-Also-Ask questions for a topic.

    Args:
        topic: The video topic (e.g. 'investing at 25', 'AR-15 maintenance').
    """
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. For a YouTube video on '{topic}', return current search-intent data.

Return JSON:
{{
    "primary_keywords": ["5-8 head keywords people actually search"],
    "long_tail": ["8-12 long-tail queries with clear intent"],
    "people_also_ask": ["6-10 questions people are asking right now"],
    "related_rising": ["topics adjacent to this one that are trending up"]
}}

Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are an SEO analyst. Return only valid JSON.",
        )
        data = json.loads(raw)

        output = f"# SEO Keywords — {topic}\n\n"
        output += "## Primary keywords\n"
        output += "\n".join(f"- {k}" for k in data.get("primary_keywords", [])) + "\n\n"
        output += "## Long-tail queries\n"
        output += "\n".join(f"- {k}" for k in data.get("long_tail", [])) + "\n\n"
        output += "## People also ask\n"
        output += "\n".join(f"- {q}" for q in data.get("people_also_ask", [])) + "\n\n"
        output += "## Related / rising\n"
        output += "\n".join(f"- {t}" for t in data.get("related_rising", [])) + "\n"
        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching keywords: {e}"


@tool
async def get_latest_upload() -> str:
    """Get the newest video on the creator's connected YouTube channel (including unlisted). Returns video ID, title, publish time, and current description — use this to start packaging 'my latest'."""
    org_id, supabase, err = _oauth_context()
    if err:
        return f"Error: {err}"

    conn = get_connection(supabase, org_id)
    if not conn:
        return "Error: YouTube is not connected yet. The creator needs to click 'Connect YouTube' on the Publisher page."
    uploads = (conn.get("metadata") or {}).get("uploads_playlist_id")
    if not uploads:
        return "Error: no uploads playlist on the connection — ask the creator to reconnect YouTube."

    token, err = await _access_token(org_id, supabase)
    if err:
        return f"Error: {err}"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{YOUTUBE_API}/playlistItems",
            params={"part": "snippet,contentDetails", "playlistId": uploads, "maxResults": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code >= 400:
        return f"Error listing uploads: {resp.status_code} {resp.text[:200]}"
    items = resp.json().get("items", [])
    if not items:
        return "No videos on this channel yet."
    snip = items[0]["snippet"]
    video_id = items[0]["contentDetails"]["videoId"]
    return (
        f"# {snip['title']}\n"
        f"- Video ID: {video_id}\n"
        f"- Published: {snip['publishedAt']}\n"
        f"- Current description:\n{(snip.get('description') or '(empty)')[:1200]}"
    )


@tool
async def get_video_transcript(video_id: str) -> str:
    """Fetch the auto-generated or uploaded captions for a YouTube video. Use this before writing chapters, pinned comments, or social copy so everything is grounded in what was actually said.

    Args:
        video_id: The YouTube video ID.
    """
    org_id, supabase, err = _oauth_context()
    if err:
        return f"Error: {err}"

    token, err = await _access_token(org_id, supabase)
    if err:
        return f"Error: {err}"

    async with httpx.AsyncClient(timeout=30) as client:
        list_resp = await client.get(
            f"{YOUTUBE_API}/captions",
            params={"part": "snippet", "videoId": video_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        if list_resp.status_code >= 400:
            return f"Error listing captions: {list_resp.status_code} {list_resp.text[:200]}"
        items = list_resp.json().get("items", [])
        if not items:
            return "No captions are available yet. YouTube usually takes 5–15 minutes after upload. Try again shortly."
        pick = next(
            (c for c in items if (c["snippet"].get("language") or "").startswith("en")),
            items[0],
        )
        caption_id = pick["id"]

        dl = await client.get(
            f"{YOUTUBE_API}/captions/{caption_id}",
            params={"tfmt": "srt"},
            headers={"Authorization": f"Bearer {token}"},
        )
    if dl.status_code >= 400:
        return f"Error downloading transcript: {dl.status_code} {dl.text[:200]}"
    text = dl.text
    return text[:20000] + ("\n\n… (truncated)" if len(text) > 20000 else "")


@tool
async def update_video_metadata(
    video_id: str,
    title: str,
    description: str,
    tags: list[str],
) -> str:
    """Write title, description, and tags to a YouTube video via videos.update.

    APPROVAL REQUIRED. Never call this without first showing the creator the exact proposed title, description, and tags and receiving an explicit 'yes' / 'push it' / 'approved'. If the creator has not explicitly approved this specific push, refuse.

    Args:
        video_id: The YouTube video ID.
        title: New title (≤100 chars).
        description: New description.
        tags: Tag list.
    """
    org_id, supabase, err = _oauth_context()
    if err:
        return f"Error: {err}"

    token, err = await _access_token(org_id, supabase)
    if err:
        return f"Error: {err}"

    async with httpx.AsyncClient(timeout=30) as client:
        cur = await client.get(
            f"{YOUTUBE_API}/videos",
            params={"part": "snippet", "id": video_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        if cur.status_code >= 400:
            return f"Error fetching current video: {cur.status_code} {cur.text[:200]}"
        items = cur.json().get("items", [])
        if not items:
            return f"Video {video_id} not found on this channel."
        category_id = items[0]["snippet"].get("categoryId", "22")

        resp = await client.put(
            f"{YOUTUBE_API}/videos",
            params={"part": "snippet"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "id": video_id,
                "snippet": {
                    "title": title[:100],
                    "description": description,
                    "tags": tags,
                    "categoryId": category_id,
                },
            },
        )
    if resp.status_code >= 400:
        return f"Error updating video: {resp.status_code} {resp.text[:300]}"
    return (
        f"✓ Pushed to YouTube: title='{title}', {len(tags)} tags, "
        f"description {len(description)} chars. Creator should review in Studio."
    )


async def _x_access_token(org_id, supabase) -> tuple[str | None, str | None]:
    import os
    client_id = os.environ.get("TWITTER_CLIENT_ID", "")
    client_secret = os.environ.get("TWITTER_CLIENT_SECRET", "") or None
    if not client_id:
        return None, "X (Twitter) OAuth is not configured on the server."
    try:
        token = await x_get_fresh_access_token(supabase, org_id, client_id, client_secret)
        return token, None
    except RuntimeError as e:
        return None, str(e)


@tool
async def post_tweet(text: str) -> str:
    """Post a single tweet to the connected X (Twitter) account.

    APPROVAL REQUIRED. Only call after the creator has explicitly approved this exact tweet.

    Args:
        text: The tweet text (≤280 chars). Anything longer is rejected by X.
    """
    org_id, supabase, err = _oauth_context()
    if err:
        return f"Error: {err}"

    token, err = await _x_access_token(org_id, supabase)
    if err:
        return f"Error: {err}"

    if len(text) > 280:
        return f"Error: tweet is {len(text)} chars, max is 280."

    try:
        result = await x_post_tweet(token, text)
    except RuntimeError as e:
        return f"Error: {e}"

    tweet_id = result.get("id")
    username = None
    try:
        from packages.integrations.x.client import get_connection as x_get_connection
        conn = x_get_connection(supabase, org_id)
        username = ((conn or {}).get("metadata") or {}).get("username")
    except Exception:
        pass

    url = f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else None
    suffix = f" ({url})" if url else ""
    return f"✓ Posted to X: tweet_id={tweet_id}{suffix}"


def get_publisher_tools():
    return [
        get_video_details,
        get_video_comments,
        suggest_seo_keywords,
        get_latest_upload,
        get_video_transcript,
        update_video_metadata,
        post_tweet,
    ]
