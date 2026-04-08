import os
import json
from datetime import datetime
from langchain_core.tools import tool
from packages.agents.core.clients import youtube_api_get, perplexity_search


@tool
async def get_channel_stats() -> str:
    """Get YouTube channel overview statistics including subscribers, total views, and video count."""
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID")
    if not channel_id:
        return "YOUTUBE_CHANNEL_ID not configured. Cannot fetch channel data."

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
            f"- **Subscribers:** {int(stats.get('subscriberCount', 0)):,}\n"
            f"- **Total Views:** {int(stats.get('viewCount', 0)):,}\n"
            f"- **Video Count:** {int(stats.get('videoCount', 0)):,}\n"
        )

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching channel stats: {e}"


@tool
async def get_video_performance(limit: int = 10) -> str:
    """Get recent video performance with views, likes, comments, and engagement rates.

    Args:
        limit: Number of recent videos to analyze (default 10).
    """
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID")
    if not channel_id:
        return "YOUTUBE_CHANNEL_ID not configured. Cannot fetch video data."

    try:
        # Step 1: Get recent video IDs
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

        # Step 2: Get detailed stats
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
            engagement = round(((likes + comments) / views) * 100, 2)

            output += f"## {snippet['title']}\n"
            output += f"- Published: {snippet['publishedAt'][:10]}\n"
            output += f"- Views: {views:,} | Likes: {likes:,} | Comments: {comments:,}\n"
            output += f"- **Engagement Rate: {engagement}%**\n"
            output += f"- Duration: {item['contentDetails']['duration']}\n\n"

        return output

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching video performance: {e}"


@tool
async def search_trending_topics() -> str:
    """Search for trending topics in the conservative/2A/firearms space using Perplexity real-time search."""
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. What are the top trending topics in conservative media, Second Amendment communities, and firearms/tactical content on YouTube and social media right now?

Return a JSON object:
{{
    "trending": [
        {{
            "topic": "Topic name",
            "platform": "Where it's trending (YouTube, X/Twitter, etc.)",
            "description": "Brief description of why it's trending",
            "momentum": "rising/stable/declining",
            "content_angle": "How a conservative firearms YouTube channel could cover this"
        }}
    ]
}}

Focus on the last 48 hours. Return 8-10 topics. Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are a social media trend analyst. Return only valid JSON.",
        )
        data = json.loads(raw)

        output = "# Trending Topics in Conservative/2A Space\n\n"
        for i, t in enumerate(data.get("trending", []), 1):
            output += f"{i}. **{t.get('topic', 'N/A')}** [{t.get('platform', '')}]\n"
            output += f"   {t.get('description', '')}\n"
            output += f"   Momentum: {t.get('momentum', 'unknown')}\n"
            output += f"   Content angle: {t.get('content_angle', '')}\n\n"

        return output

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error searching trends: {e}"


def get_intel_tools():
    return [get_channel_stats, get_video_performance, search_trending_topics]
