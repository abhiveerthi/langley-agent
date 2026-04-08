import json
from datetime import datetime
from langchain_core.tools import tool
from packages.agents.core.clients import perplexity_search


@tool
async def find_partnership_leads(category: str = "Tactical Gear") -> str:
    """Search for potential partnership and sponsorship leads in a specific category using Perplexity AI.

    Args:
        category: The industry/product category to search for leads in (e.g. 'Tactical Gear', 'Ammunition', 'Optics', 'Outdoor Apparel').
    """
    try:
        prompt = f"""Find 5-10 specific potential partnership leads for a firearms/tactical YouTube channel in the '{category}' space.

Focus on:
1. Companies that are actively sponsoring YouTube channels
2. Marketing Directors or Partnership Managers if publicly known
3. Emerging brands that have funding/growth

Return the response strictly as a JSON list:
[
    {{
        "company": "Company Name",
        "contact_name": "Person Name (or 'Marketing Dept' if unknown)",
        "role": "Job Title",
        "website": "URL",
        "notes": "Why they are a good fit / recent sponsorships"
    }}
]

Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are a precise lead generation assistant. Output only valid JSON.",
        )
        leads = json.loads(raw)

        output = f"# Partnership Leads: {category}\n\n"
        for i, lead in enumerate(leads, 1):
            output += f"{i}. **{lead.get('company', 'Unknown')}**\n"
            output += f"   Contact: {lead.get('contact_name', 'N/A')} — {lead.get('role', 'N/A')}\n"
            output += f"   Website: {lead.get('website', 'N/A')}\n"
            output += f"   Fit: {lead.get('notes', 'N/A')}\n\n"

        return output

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error finding leads: {e}"


@tool
async def search_content_trends() -> str:
    """Search for current trending topics in conservative/2A media to inform content strategy and video ideas."""
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. What are the most viral and engaging topics in conservative media and firearms/2A YouTube content right now?

Return a JSON object:
{{
    "trends": [
        {{
            "topic": "Topic name",
            "why_trending": "Brief explanation",
            "video_angle": "Suggested video approach for a conservative firearms YouTube channel",
            "urgency": "high/medium/low — how time-sensitive is this topic"
        }}
    ]
}}

Focus on the last 48 hours. Return 6-8 topics. Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are a content strategy analyst for digital media. Return only valid JSON.",
        )
        data = json.loads(raw)

        output = "# Current Content Trends\n\n"
        for i, t in enumerate(data.get("trends", []), 1):
            output += f"{i}. **{t.get('topic', 'N/A')}** (Urgency: {t.get('urgency', 'unknown')})\n"
            output += f"   Why: {t.get('why_trending', '')}\n"
            output += f"   Video angle: {t.get('video_angle', '')}\n\n"

        return output

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error searching trends: {e}"


def get_comms_tools():
    return [find_partnership_leads, search_content_trends]
