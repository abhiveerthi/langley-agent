import json
from datetime import datetime
from langchain_core.tools import tool
from packages.agents.core.clients import perplexity_search, youtube_api_get


@tool
async def search_political_news(
    categories: list[dict],
    category: str = "all",
) -> str:
    """Search for current news using Perplexity AI real-time search.

    Args:
        categories: List of category dicts, each with `slug`, `label`, `query`.
            Supplied per-tenant via the agent node.
        category: Which category slug to fetch, or 'all' for every category.
    """
    categories_by_slug = {c["slug"]: c for c in categories}

    if category != "all" and category not in categories_by_slug:
        valid = ", ".join(categories_by_slug.keys())
        return f"Unknown category '{category}'. Options: {valid}, all"

    selected = categories if category == "all" else [categories_by_slug[category]]
    today = datetime.now().strftime("%B %d, %Y")
    sections: list[str] = []

    for cat in selected:
        cat_label = cat.get("label") or cat.get("slug", "Unknown")
        try:
            prompt = f"""Today is {today}. {cat["query"]}

Return a JSON object with this EXACT structure:
{{
    "items": [
        {{
            "headline": "Clear, specific headline about what happened",
            "summary": "2-3 sentence summary with key details, names, and implications",
            "source": "News outlet name",
            "why_it_matters": "One sentence on why this is significant"
        }}
    ],
    "key_topics": [
        {{"topic": "Topic name", "momentum": "rising/stable/declining"}}
    ]
}}

CRITICAL: Only news from the LAST 24-48 HOURS. Return 5-8 items. Return ONLY valid JSON."""

            raw = await perplexity_search(
                prompt,
                system_prompt=(
                    "You are a news aggregator focused on current events. "
                    "Return only valid JSON with no markdown formatting or code "
                    "blocks. Only include news from the last 24-48 hours."
                ),
            )
            data = json.loads(raw)

            section = f"## {cat_label.upper()}\n"
            for i, item in enumerate(data.get("items", []), 1):
                section += f"{i}. **{item.get('headline', 'N/A')}** [{item.get('source', '')}]\n"
                section += f"   {item.get('summary', '')}\n"
                section += f"   Significance: {item.get('why_it_matters', '')}\n\n"

            topics = data.get("key_topics", [])
            if topics:
                section += "Trending: " + ", ".join(
                    f"{t['topic']} ({t.get('momentum', 'stable')})" for t in topics
                )
            sections.append(section)

        except ValueError as e:
            return f"Error: {e}"
        except json.JSONDecodeError:
            sections.append(f"## {cat_label.upper()}\nReceived response but failed to parse it.")
        except Exception as e:
            sections.append(f"## {cat_label.upper()}\nError fetching news: {e}")

    return "\n\n".join(sections) if sections else "No news data collected."


@tool
async def get_polling_data() -> str:
    """Get the latest US political polling data via Perplexity real-time search."""
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. What are the latest US political polls released in the last week?

Include presidential approval ratings, congressional generic ballot, key Senate/Governor races, and any significant state-level polls.

Return a JSON object:
{{
    "polls": [
        {{
            "pollster": "Pollster name",
            "race_or_metric": "What was polled",
            "results": "Key numbers",
            "date": "Poll date",
            "significance": "Why this matters"
        }}
    ],
    "trends": "Brief summary of overall polling trends"
}}

Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are a political polling data aggregator. Return only valid JSON.",
        )
        data = json.loads(raw)

        output = "# Latest Polling Data\n\n"
        for i, poll in enumerate(data.get("polls", []), 1):
            output += f"{i}. **{poll.get('race_or_metric', 'N/A')}** — {poll.get('pollster', 'Unknown')}\n"
            output += f"   Results: {poll.get('results', 'N/A')}\n"
            output += f"   Date: {poll.get('date', 'N/A')}\n"
            output += f"   {poll.get('significance', '')}\n\n"

        if data.get("trends"):
            output += f"\n**Overall Trends:** {data['trends']}"

        return output

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching polling data: {e}"


@tool
async def get_youtube_comments(channel_id: str, max_videos: int = 5) -> str:
    """Get recent YouTube comments from a specific channel for audience sentiment analysis.

    Args:
        channel_id: The YouTube channel ID to pull comments from. Supplied per-tenant.
        max_videos: Number of recent videos to fetch comments for (default 5).
    """
    if not channel_id:
        return "No YouTube channel_id configured for this org."

    try:
        search_data = await youtube_api_get("search", {
            "part": "id,snippet",
            "channelId": channel_id,
            "order": "date",
            "type": "video",
            "maxResults": max_videos,
        })

        videos = []
        for item in search_data.get("items", []):
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]

            try:
                comments_data = await youtube_api_get("commentThreads", {
                    "part": "snippet",
                    "videoId": video_id,
                    "order": "relevance",
                    "maxResults": 15,
                })
                comments = []
                for c in comments_data.get("items", []):
                    snippet = c["snippet"]["topLevelComment"]["snippet"]
                    comments.append({
                        "text": snippet["textDisplay"][:200],
                        "likes": snippet.get("likeCount", 0),
                    })
                videos.append({"title": title, "comments": comments})
            except Exception:
                videos.append({"title": title, "comments": []})

        output = "# YouTube Channel Comments\n\n"
        for v in videos:
            output += f"## {v['title']}\n"
            if v["comments"]:
                for c in v["comments"]:
                    output += f"- ({c['likes']} likes) {c['text']}\n"
            else:
                output += "No comments available.\n"
            output += "\n"

        return output if videos else "No recent videos found."

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching YouTube data: {e}"


def get_research_tools():
    return [search_political_news, get_polling_data, get_youtube_comments]
