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
from packages.integrations.x import client as x_client


def _owner_already_replied(thread: dict, owner_channel_id: str) -> bool:
    """True if any reply in this commentThread was authored by the channel
    owner. Uses up to 5 most recent replies returned by `part=replies` —
    enough for typical creator threads (a single owner reply is the norm).
    Threads with replies but no `replies` block (very deep threads) fall
    back to a conservative `totalReplyCount` heuristic: if the count is >0
    we don't filter, since we can't be sure the owner is among them.
    """
    replies = (thread.get("replies") or {}).get("comments") or []
    for r in replies:
        author_ch = (
            (r.get("snippet") or {}).get("authorChannelId") or {}
        ).get("value")
        if author_ch and author_ch == owner_channel_id:
            return True
    return False


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


async def _x_oauth_access_token() -> tuple[str, str]:
    """Resolve a fresh X OAuth access token and the connected user_id.

    Both pieces are needed for every X read: the token authorizes the call,
    the user_id scopes it to the creator's own tweets / their conversations.
    """
    org_id = current_org_id.get()
    supabase = current_supabase.get()
    if not org_id or supabase is None:
        raise RuntimeError("no org context (running without auth)")

    client_id = os.environ.get("TWITTER_CLIENT_ID") or os.environ.get("X_CLIENT_ID")
    client_secret = (
        os.environ.get("TWITTER_CLIENT_SECRET") or os.environ.get("X_CLIENT_SECRET")
    )
    if not client_id:
        raise RuntimeError("TWITTER_CLIENT_ID not configured")

    user = x_client.get_authenticated_user(supabase, org_id)
    if not user or not user.get("user_id"):
        raise RuntimeError("X is not connected for this org")

    token = await x_client.get_fresh_access_token(
        supabase, org_id, client_id, client_secret=client_secret or None
    )
    return token, user["user_id"]


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
        total_skipped_replied = 0
        for item in search_data.get("items", []):
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            output += f"## {title} (video_id: {video_id})\n"

            try:
                # `part=snippet,replies` returns the top-level comment plus up
                # to 5 most recent replies in one call — we use the replies
                # block to detect whether the channel owner already responded
                # so the agent never proposes a duplicate reply.
                comments_data = await youtube_api_get_oauth("commentThreads", {
                    "part": "snippet,replies",
                    "videoId": video_id,
                    "order": "time",
                    "maxResults": per_video,
                }, access_token)
                threads = comments_data.get("items", [])
                if not threads:
                    output += "(no comments)\n\n"
                    continue

                rendered_any = False
                skipped_replied = 0
                for c in threads:
                    snippet = c["snippet"]
                    if _owner_already_replied(c, channel_id):
                        skipped_replied += 1
                        continue
                    top = snippet["topLevelComment"]
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
                    rendered_any = True

                if skipped_replied:
                    total_skipped_replied += skipped_replied
                    output += (
                        f"_(skipped {skipped_replied} comment"
                        f"{'s' if skipped_replied != 1 else ''} the channel "
                        f"already replied to)_\n"
                    )
                if not rendered_any and not skipped_replied:
                    output += "(no comments)\n"
                output += "\n"
            except Exception as e:
                output += f"(error fetching comments: {e})\n\n"

        if total_skipped_replied:
            output += (
                f"\n> Note: {total_skipped_replied} comment"
                f"{'s' if total_skipped_replied != 1 else ''} that the channel "
                f"already replied to were filtered out — never propose a reply "
                f"to those.\n"
            )
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


# ── Read-only tools (X / Twitter via OAuth) ──────────────────────────────

def _fmt_x_reply(reply: dict) -> str:
    """One bullet line for an incoming reply on the user's own thread."""
    rid = reply.get("id") or "?"
    name = reply.get("author_name") or reply.get("author_username") or "unknown"
    handle = reply.get("author_username") or ""
    followers = reply.get("author_followers")
    metrics = reply.get("metrics") or {}
    likes = metrics.get("like_count") or 0
    text = (reply.get("text") or "")[:280].replace("\n", " ").strip()
    f_str = f"{followers:,} followers" if isinstance(followers, int) else "followers ?"
    handle_str = f" @{handle}" if handle else ""
    return f"- [{rid}] **{name}**{handle_str} ({f_str}) [{likes}❤️]: {text}"


@tool
async def get_recent_x_comments(
    max_tweets: int = 5,
    per_tweet: int = 30,
) -> str:
    """Get recent replies / comments on the user's OWN recent tweets and threads.

    Pulls the creator's most recent original tweets (excluding retweets and
    replies), then for each one queries the conversation for incoming replies
    from other users. Use this for X comment triage — analogous to
    `get_recent_comments` but for X instead of YouTube.

    Args:
        max_tweets: How many of the user's recent tweets to scan (default 5, max 10).
        per_tweet: How many replies to pull per tweet (default 30, max 100).
    """
    max_tweets = min(max(max_tweets, 1), 10)
    per_tweet = min(max(per_tweet, 10), 100)

    try:
        access_token, user_id = await _x_oauth_access_token()
    except Exception as e:
        return f"Error: X OAuth not available ({e}). Connect X in Settings."

    try:
        tweets = await x_client.get_user_tweets(
            access_token, user_id, max_results=max_tweets
        )
    except RuntimeError as e:
        return f"Error fetching your recent tweets: {e}"
    except Exception as e:
        return f"Error fetching your recent tweets: {e}"

    if not tweets:
        return "# Recent X Comments\n\nNo recent original tweets found on the connected account."

    output = "# Recent X Comments\n\n"
    for tw in tweets:
        tweet_id = tw.get("id") or ""
        text_preview = (tw.get("text") or "")[:120].replace("\n", " ").strip()
        metrics = tw.get("public_metrics") or {}
        reply_count = metrics.get("reply_count", 0)
        conv_id = tw.get("conversation_id") or tweet_id
        output += f"## Tweet [{tweet_id}] ({reply_count} replies)\n"
        output += f"> {text_preview}\n\n"

        if not conv_id:
            output += "(no conversation_id — skipping)\n\n"
            continue
        if reply_count == 0:
            output += "(no replies)\n\n"
            continue

        try:
            replies = await x_client.get_tweet_replies(
                access_token,
                conv_id,
                author_id=user_id,
                max_results=per_tweet,
            )
        except RuntimeError as e:
            output += f"(error fetching replies: {e})\n\n"
            continue
        except Exception as e:
            output += f"(error fetching replies: {e})\n\n"
            continue

        if not replies:
            output += "(no replies returned in window)\n\n"
            continue

        for r in replies:
            output += _fmt_x_reply(r) + "\n"
        output += "\n"

    return output


@tool
async def lookup_x_user(handle_or_id: str) -> str:
    """Look up an X user by handle (e.g. '@elonmusk') or numeric user_id — useful for flagging VIP repliers.

    Args:
        handle_or_id: Username (with or without @) or numeric X user_id.
    """
    if not handle_or_id:
        return "Error: empty handle_or_id."

    try:
        access_token, _user_id = await _x_oauth_access_token()
    except Exception as e:
        return f"Error: X OAuth not available ({e}). Connect X in Settings."

    try:
        user = await x_client.lookup_user(access_token, handle_or_id)
    except RuntimeError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching user: {e}"

    if not user:
        return f"No X user found for '{handle_or_id}'."

    metrics = user.get("public_metrics") or {}
    followers = int(metrics.get("followers_count", 0))
    tier = "major" if followers >= 100_000 else "mid" if followers >= 10_000 else "small"
    verified = "✓ verified" if user.get("verified") else "unverified"
    return (
        f"# {user.get('name') or user.get('username') or '(unknown)'}\n"
        f"- Handle: @{user.get('username','')}\n"
        f"- User ID: {user.get('id','')}\n"
        f"- Followers: {followers:,} ({tier}) — {verified}\n"
        f"- Following: {int(metrics.get('following_count', 0)):,}\n"
        f"- Tweets: {int(metrics.get('tweet_count', 0)):,}\n"
        f"- Created: {(user.get('created_at') or 'N/A')[:10]}\n"
        f"- Bio: {(user.get('description') or '')[:300]}\n"
    )


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


async def reply_to_x_comment(parent_tweet_id: str, text: str) -> str:
    """Post a reply to an X tweet as the connected user.

    Like `reply_to_comment` (YouTube), this is NOT exposed to the LLM as a
    `@tool`. The agent calls it directly from `_send_reply_node` only AFTER
    the approval_gate clears. The graph-level interrupt is what protects
    writes; the LLM never has access to this function as a tool.

    Args:
        parent_tweet_id: The tweet's X id (the reply targets this tweet).
        text: The reply body. Plain text; ≤280 chars or X will reject.
    """
    try:
        access_token, _user_id = await _x_oauth_access_token()
    except Exception as e:
        return f"Cannot post reply: X OAuth not available ({e})."

    try:
        result = await x_client.reply_to_tweet(access_token, parent_tweet_id, text)
        posted_id = (result or {}).get("id") or "(unknown)"
        return f"Reply posted on X (tweet id: {posted_id})."
    except RuntimeError as e:
        return f"X rejected the reply: {e}"
    except Exception as e:
        return f"Error posting X reply: {e}"


def get_community_manager_tools():
    return [
        get_recent_comments,
        lookup_channel,
        get_recent_x_comments,
        lookup_x_user,
    ]
