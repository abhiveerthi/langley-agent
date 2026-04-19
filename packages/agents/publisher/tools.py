import json
from datetime import datetime
from langchain_core.tools import tool
from packages.agents.core.clients import perplexity_search, youtube_api_get


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


def get_publisher_tools():
    return [get_video_details, get_video_comments, suggest_seo_keywords]
