import json
from datetime import datetime
from langchain_core.tools import tool
from packages.agents.core.clients import perplexity_search


@tool
async def find_partnership_leads(category: str, niche_descriptor: str) -> str:
    """Search for potential partnership and sponsorship leads in a specific category using Perplexity AI.

    Args:
        category: The industry/product category to search for leads in
            (e.g. 'Tactical Gear', 'Gaming Peripherals', 'Apparel'). Per-tenant.
        niche_descriptor: Short description of the channel's niche so leads
            are scoped correctly (e.g. 'firearms/tactical YouTube channel',
            'gaming/esports YouTube channel'). Per-tenant.
    """
    try:
        prompt = f"""Find 5-10 specific potential partnership leads for a {niche_descriptor} in the '{category}' space.

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
async def search_content_trends(focus: str) -> str:
    """Search for current trending topics in the channel's niche to inform content strategy.

    Args:
        focus: The niche/audience focus to scope the search to. Per-tenant.
    """
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. What are the most viral and engaging topics in {focus} right now?

Return a JSON object:
{{
    "trends": [
        {{
            "topic": "Topic name",
            "why_trending": "Brief explanation",
            "video_angle": "Suggested video approach for a YouTube channel in this niche",
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

        output = f"# Current Content Trends — {focus}\n\n"
        for i, t in enumerate(data.get("trends", []), 1):
            output += f"{i}. **{t.get('topic', 'N/A')}** (Urgency: {t.get('urgency', 'unknown')})\n"
            output += f"   Why: {t.get('why_trending', '')}\n"
            output += f"   Video angle: {t.get('video_angle', '')}\n\n"

        return output

    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error searching trends: {e}"


@tool
async def send_email(recipient: str, subject: str, body: str) -> str:
    """Send an email. This is a stub — wire up real SMTP/Resend later.

    Args:
        recipient: Email address of the recipient.
        subject: Email subject line.
        body: Email body (plain text or HTML).
    """
    # TODO: integrate Resend or SMTP. For now, log what we would have sent.
    return (
        f"[STUB] Email dispatched to {recipient}\n"
        f"Subject: {subject}\n"
        f"Length: {len(body)} chars"
    )


def get_comms_tools():
    return [find_partnership_leads, search_content_trends, send_email]
