import json
from datetime import datetime
from langchain_core.tools import tool
from packages.agents.core.clients import perplexity_search, youtube_api_get


@tool
async def get_channel_stats(channel_id: str) -> str:
    """Get YouTube channel overview: subscribers, total views, video count.

    Args:
        channel_id: The YouTube channel ID. Supplied per-tenant via the system prompt.
    """
    if not channel_id:
        return "No YouTube channel_id supplied. Cannot fetch stats."

    try:
        data = await youtube_api_get("channels", {
            "part": "statistics,snippet",
            "id": channel_id,
        })
        items = data.get("items", [])
        if not items:
            return "Channel not found."

        stats = items[0]["statistics"]
        snippet = items[0]["snippet"]
        return (
            f"# Channel: {snippet['title']}\n\n"
            f"- Subscribers: {int(stats.get('subscriberCount', 0)):,}\n"
            f"- Total Views: {int(stats.get('viewCount', 0)):,}\n"
            f"- Video Count: {int(stats.get('videoCount', 0)):,}\n"
            f"- Description: {snippet.get('description', '')[:300]}\n"
        )
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching channel stats: {e}"


@tool
async def get_recent_video_performance(channel_id: str, limit: int = 10) -> str:
    """Get the creator's most recent videos with views, likes, comments, and engagement rate.

    Args:
        channel_id: The YouTube channel ID. Supplied per-tenant via the system prompt.
        limit: Number of recent videos to analyze (default 10, max 25).
    """
    if not channel_id:
        return "No YouTube channel_id supplied."

    limit = min(max(limit, 1), 25)

    try:
        search_data = await youtube_api_get("search", {
            "part": "id",
            "channelId": channel_id,
            "order": "date",
            "type": "video",
            "maxResults": limit,
        })
        video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
        if not video_ids:
            return "No videos found."

        stats_data = await youtube_api_get("videos", {
            "part": "statistics,snippet,contentDetails",
            "id": ",".join(video_ids),
        })

        output = "# Recent Video Performance\n\n"
        for item in stats_data.get("items", []):
            stats = item["statistics"]
            snippet = item["snippet"]
            views = int(stats.get("viewCount", 1))
            likes = int(stats.get("likeCount", 0))
            comments = int(stats.get("commentCount", 0))
            engagement = round(((likes + comments) / max(views, 1)) * 100, 2)

            output += f"## {snippet['title']}\n"
            output += f"- Published: {snippet['publishedAt'][:10]}\n"
            output += f"- Views: {views:,} | Likes: {likes:,} | Comments: {comments:,}\n"
            output += f"- Engagement: {engagement}%\n"
            output += f"- Duration: {item['contentDetails']['duration']}\n\n"

        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching video performance: {e}"


@tool
async def search_niche_trends(niche: str) -> str:
    """Search for current trending topics in the creator's niche (last 48 hours).

    Args:
        niche: The channel's niche (e.g. 'personal finance', 'tactical gear', 'home fitness').
            Supplied per-tenant via the system prompt.
    """
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. What are the most viral and engaging topics in the '{niche}' space right now across YouTube, X, and news?

Return a JSON object:
{{
    "trends": [
        {{
            "topic": "Topic name",
            "why_trending": "Brief explanation grounded in a specific event or data point",
            "momentum": "rising/stable/declining",
            "video_angle": "Suggested angle for a YouTube video in this niche",
            "urgency": "high/medium/low"
        }}
    ]
}}

Focus on the last 48 hours. Return 6-8 topics. Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are a content strategy analyst. Return only valid JSON.",
        )
        data = json.loads(raw)

        output = f"# Trending in '{niche}'\n\n"
        for i, t in enumerate(data.get("trends", []), 1):
            output += f"{i}. **{t.get('topic', 'N/A')}** (Urgency: {t.get('urgency', 'unknown')}, Momentum: {t.get('momentum', 'unknown')})\n"
            output += f"   Why: {t.get('why_trending', '')}\n"
            output += f"   Angle: {t.get('video_angle', '')}\n\n"
        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error searching niche trends: {e}"


@tool
async def search_competitor_videos(niche: str, top_n: int = 5) -> str:
    """Find top-performing videos from competitor channels in the niche over the last 30 days.

    Args:
        niche: The channel's niche. Supplied per-tenant via the system prompt.
        top_n: Number of top videos to surface (default 5, max 10).
    """
    top_n = min(max(top_n, 1), 10)
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. Identify the top {top_n} highest-performing YouTube videos uploaded in the last 30 days in the '{niche}' niche that aren't from major mainstream-media channels.

Return JSON:
{{
    "videos": [
        {{
            "title": "Video title",
            "channel": "Channel name",
            "published_days_ago": 0,
            "views": "Approximate view count",
            "hook": "What the video opens with / its hook",
            "gap": "What the video didn't cover — an opening for a competing take"
        }}
    ]
}}

Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are a YouTube competitive intelligence analyst. Return only valid JSON.",
        )
        data = json.loads(raw)

        output = f"# Top Competitor Videos — '{niche}' (last 30 days)\n\n"
        for i, v in enumerate(data.get("videos", []), 1):
            output += f"{i}. **{v.get('title', 'N/A')}** — {v.get('channel', 'Unknown')}\n"
            output += f"   {v.get('published_days_ago', '?')}d ago | {v.get('views', 'N/A')}\n"
            output += f"   Hook: {v.get('hook', '')}\n"
            output += f"   Gap: {v.get('gap', '')}\n\n"
        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error searching competitors: {e}"


def get_strategist_tools():
    # OAuth-backed Analytics API tools live in analytics_tools.py — separated
    # so it's obvious which tools need YouTube to be connected for the org.
    # Imported here so callers get a single flat list to bind to the LLM.
    from packages.agents.strategist.analytics_tools import (
        get_strategist_analytics_tools,
    )
    return [
        # Public Data API — works for any channel by ID, no OAuth needed.
        get_channel_stats,
        get_recent_video_performance,
        # Niche-level external research (Perplexity).
        search_niche_trends,
        search_competitor_videos,
    ] + get_strategist_analytics_tools()
