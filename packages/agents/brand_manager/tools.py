import json
from datetime import datetime
from langchain_core.tools import tool
from packages.agents.core.clients import perplexity_search, resend_send, youtube_api_get
from packages.integrations.context import current_org_id


@tool
async def find_sponsor_leads(category: str) -> str:
    """Find potential sponsors for a YouTube creator in a given product category.

    Args:
        category: Product/industry category (e.g. 'men's skincare', 'productivity SaaS', 'tactical gear').
    """
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. Find 6-10 specific potential sponsor leads in the '{category}' space for a YouTube creator.

Prioritize:
1. Brands actively sponsoring YouTube creators in 2025-2026
2. DTC brands with visible marketing spend (have run creator campaigns)
3. Emerging brands with funding — they need awareness

Return JSON:
[
    {{
        "company": "Company Name",
        "website": "URL",
        "product_fit": "What they sell and why it fits a YouTube audience",
        "recent_sponsorships": "Any known recent creator campaigns",
        "contact_hint": "Marketing Dept / named person if publicly known / LinkedIn profile URL",
        "tier": "enterprise/mid/emerging"
    }}
]

Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are a B2B lead research analyst. Return only valid JSON.",
        )
        leads = json.loads(raw)

        output = f"# Sponsor Leads — {category}\n\n"
        for i, lead in enumerate(leads, 1):
            output += f"{i}. **{lead.get('company', 'Unknown')}** ({lead.get('tier', 'unknown')})\n"
            output += f"   Site: {lead.get('website', 'N/A')}\n"
            output += f"   Fit: {lead.get('product_fit', 'N/A')}\n"
            output += f"   Recent: {lead.get('recent_sponsorships', 'N/A')}\n"
            output += f"   Contact: {lead.get('contact_hint', 'N/A')}\n\n"
        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error finding leads: {e}"


@tool
async def research_brand(brand_name: str) -> str:
    """Research a specific brand: recent creator sponsorships, marketing direction, contact leads.

    Args:
        brand_name: The brand to research.
    """
    today = datetime.now().strftime("%B %d, %Y")
    try:
        prompt = f"""Today is {today}. Research the brand '{brand_name}' for a YouTube creator considering an outreach pitch.

Return JSON:
{{
    "company_summary": "1-2 sentences on what they do and their target customer",
    "recent_creator_campaigns": ["List of recent YouTube/creator sponsorships with creator name and rough date if known"],
    "marketing_direction": "What their current marketing looks like — any pivots, new products, expansion",
    "public_contacts": ["Any publicly known Marketing/Partnership/BD contacts with LinkedIn/title"],
    "pitch_angle": "The strongest angle a creator could open a pitch with — reference something specific and current"
}}

Return ONLY valid JSON."""

        raw = await perplexity_search(
            prompt,
            system_prompt="You are a competitive intelligence analyst. Return only valid JSON.",
        )
        data = json.loads(raw)

        output = f"# Brand Research: {brand_name}\n\n"
        output += f"**Summary:** {data.get('company_summary', 'N/A')}\n\n"
        output += "## Recent creator campaigns\n"
        for c in data.get("recent_creator_campaigns", []):
            output += f"- {c}\n"
        output += f"\n## Marketing direction\n{data.get('marketing_direction', 'N/A')}\n\n"
        output += "## Public contacts\n"
        for c in data.get("public_contacts", []):
            output += f"- {c}\n"
        output += f"\n## Pitch angle\n{data.get('pitch_angle', 'N/A')}\n"
        return output
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error researching brand: {e}"


@tool
async def get_channel_stats(channel_id: str) -> str:
    """Pull the creator's channel stats for media-kit numbers in outreach.

    Args:
        channel_id: The YouTube channel ID. Supplied per-tenant via the system prompt.
    """
    if not channel_id:
        return "No YouTube channel_id supplied."

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
        subs = int(stats.get("subscriberCount", 0))
        views = int(stats.get("viewCount", 0))
        videos = int(stats.get("videoCount", 0))
        avg_views = views // max(videos, 1)

        return (
            f"# Media Kit Numbers\n"
            f"- Channel: {snippet['title']}\n"
            f"- Subscribers: {subs:,}\n"
            f"- Total views: {views:,}\n"
            f"- Video count: {videos:,}\n"
            f"- Lifetime avg views/video: {avg_views:,}\n"
        )
    except ValueError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error fetching stats: {e}"


@tool
async def send_pitch_email(
    recipient: str,
    subject: str,
    body: str,
    from_name: str | None = None,
    reply_to: str | None = None,
) -> str:
    """Send a sponsor pitch email via Resend.

    Args:
        recipient: Email address of the sponsor contact.
        subject: Email subject line.
        body: Plain-text body. (Resend will accept this as text/plain.)
        from_name: Display name to show in the From line — typically the brand name
            (e.g. "Langley Outdoors Academy"). Sender domain is fixed via EMAIL_FROM env.
        reply_to: Optional Reply-To address — usually the creator's real email so
            replies don't go to the noreply sender.
    """
    if not recipient:
        return "Error: no recipient supplied."

    try:
        result = await resend_send(
            to=recipient,
            subject=subject,
            body_text=body,
            from_name=from_name,
            reply_to=reply_to,
        )
        return f"Sent. Resend message id: {result.get('id', 'unknown')}"
    except ValueError as e:
        return f"Email config error: {e}"
    except Exception as e:
        return f"Send failed: {e}"


@tool
async def list_active_deals_tool(limit: int = 10) -> str:
    """List the creator's recent sponsor deals across all stages.

    Returns the deal pipeline (pitched, replied, negotiating, signed, declined,
    paused) sorted by most recently updated. Use this when the user asks
    "who have we pitched", "show me the pipeline", "what's the status with
    Magpul", or before drafting a new pitch (so you can avoid pitching a
    brand we're already negotiating with).

    Args:
        limit: How many deals to surface (default 10, max 50).
    """
    # Avoid circular import at module load — deals.py imports tools-ish stuff.
    from packages.agents.brand_manager.deals import list_active_deals

    org_id = current_org_id.get()
    deals = await list_active_deals(org_id=org_id, limit=limit)
    if not deals:
        return (
            "No deals logged yet. Pitches sent through this agent are recorded "
            "here automatically as 'pitched'; future stage updates will land here too."
        )

    output = "# Sponsor Pipeline\n\n"
    for d in deals:
        last = (d.get("last_updated_at") or "")[:10]
        output += (
            f"- **{d.get('brand_name', '?')}** "
            f"({d.get('stage', '?')}) — "
            f"{d.get('recipient', '(no recipient)')}, last updated {last}\n"
        )
    return output


def get_brand_manager_tools():
    return [
        find_sponsor_leads,
        research_brand,
        get_channel_stats,
        send_pitch_email,
        list_active_deals_tool,
    ]
