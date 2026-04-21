from langchain_core.tools import tool
from packages.agents.core.clients import youtube_api_get


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
        search_data = await youtube_api_get("search", {
            "part": "id,snippet",
            "channelId": channel_id,
            "order": "date",
            "type": "video",
            "maxResults": max_videos,
        })

        output = "# Recent Comments\n\n"
        for item in search_data.get("items", []):
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            output += f"## {title} (video_id: {video_id})\n"

            try:
                comments_data = await youtube_api_get("commentThreads", {
                    "part": "snippet",
                    "videoId": video_id,
                    "order": "time",
                    "maxResults": per_video,
                })
                comments = comments_data.get("items", [])
                if not comments:
                    output += "(no comments)\n\n"
                    continue
                for c in comments:
                    s = c["snippet"]["topLevelComment"]["snippet"]
                    author = s.get("authorDisplayName", "unknown")
                    author_channel = s.get("authorChannelId", {}).get("value", "")
                    likes = s.get("likeCount", 0)
                    text = s["textDisplay"][:280]
                    output += f"- **{author}** ({author_channel}) [{likes}👍]: {text}\n"
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
        data = await youtube_api_get("channels", params)
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


def get_community_manager_tools():
    return [get_recent_comments, lookup_channel]
