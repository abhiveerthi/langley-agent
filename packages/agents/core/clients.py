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
