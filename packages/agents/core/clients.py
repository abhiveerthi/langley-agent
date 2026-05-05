"""Shared API client helpers for agent tools."""

import os
import httpx


async def perplexity_search(
    query: str,
    system_prompt: str = "You are a helpful assistant. Return only valid JSON when asked for JSON.",
    temperature: float = 0.1,
) -> str:
    """Call Perplexity AI sonar-pro model for real-time web search.

    Returns the raw response content string.
    Raises ValueError if API key is not configured.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY not set — add it to .env")

    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar-pro",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                "temperature": temperature,
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return _strip_code_blocks(content)


async def resend_send(
    to: str | list[str],
    subject: str,
    body_text: str,
    body_html: str | None = None,
    from_name: str | None = None,
    reply_to: str | None = None,
) -> dict:
    """Send an email via Resend.

    Args:
        to: Recipient email address (or list of addresses).
        subject: Email subject line.
        body_text: Plain-text body. Used as fallback if body_html not given.
        body_html: Optional HTML body.
        from_name: Optional sender display name. The actual From address
            is always EMAIL_FROM (configured in .env, must be a domain
            verified in Resend). The display name is what shows in inboxes.
        reply_to: Optional Reply-To address.

    Returns the parsed JSON response from Resend (`{"id": "..."}`).
    Raises ValueError if API key or sender is not configured.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise ValueError("RESEND_API_KEY not set — add it to .env")

    sender_addr = os.environ.get("EMAIL_FROM")
    if not sender_addr:
        raise ValueError("EMAIL_FROM not set — add it to .env")

    from_field = f"{from_name} <{sender_addr}>" if from_name else sender_addr
    payload: dict = {
        "from": from_field,
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
        "text": body_text,
    }
    if body_html:
        payload["html"] = body_html
    if reply_to:
        payload["reply_to"] = reply_to

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def youtube_api_get(endpoint: str, params: dict) -> dict:
    """Call YouTube Data API v3 with the static API key.

    Returns the parsed JSON response.
    Raises ValueError if API key is not configured.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY not set — add it to .env")

    params["key"] = api_key
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://www.googleapis.com/youtube/v3/{endpoint}",
            params=params,
        )
        response.raise_for_status()
        return response.json()


async def youtube_api_get_oauth(
    endpoint: str, params: dict, access_token: str
) -> dict:
    """Call YouTube Data API v3 as the connected creator (OAuth Bearer token)."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://www.googleapis.com/youtube/v3/{endpoint}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


def _strip_code_blocks(content: str) -> str:
    """Strip markdown code block wrappers from a string."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if len(lines) > 2:
            return "\n".join(lines[1:-1])
    return content
