"""
Long-term agent memory — "remembering/learning as the creator works with it".

The `agent_memory` table (migrations/001_core.sql) has had pgvector(1536) +
an ivfflat cosine index since day one, but nothing wrote to it or read from
it. This module is the wiring:

  - `embed_text(text)`        — turn a string into a 1536-dim embedding vector.
  - `write_memory(...)`       — embed a turn summary + insert one row.
  - `recall_memories(...)`    — embed a query + cosine-search the org's memories.

The conversational agents (Strategist, Brand Manager, Community Manager) call
`recall_memories` at the START of a run (hydrating `state.metadata["memories"]`,
parallel to peer_context) and `write_memory` at the END (persisting a concise
summary of the turn). Everything here is BEST-EFFORT: no Supabase, a non-UUID
org, or no embedding backend all degrade to a clean no-op (None / []) rather
than raising. An agent run must never fail because memory is unavailable.

## Embedding provider

Provider-abstracted via env so it's trivially swappable:

    MEMORY_EMBED_PROVIDER   — "openai" (default). Set to another value to plug
                              in a different backend in `_embed_<provider>`.
    OPENAI_API_KEY          — required for the OpenAI backend. Absent → embed
                              returns None and memory silently no-ops.
    OPENAI_EMBED_MODEL      — defaults to "text-embedding-3-small", which emits
                              1536-dim vectors to match the table's vector(1536)
                              column. Do not point this at a model with a
                              different dimension without migrating the column.

Uses httpx directly (already a project dep — see core/clients.py) rather than
the OpenAI SDK, mirroring core/transcription.py.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

from packages.integrations.context import current_supabase


# Must match the `embedding vector(1536)` column in agent_memory. OpenAI's
# text-embedding-3-small / ada-002 both emit exactly this dimension.
EMBED_DIM = 1536


def _is_real_uuid(value: str | None) -> bool:
    """True if `value` parses as a UUID. Dev-mode `org_id="dev"` returns False
    so we skip Supabase reads/writes (which would fail on a non-UUID column)."""
    if not value:
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# ── Embeddings ─────────────────────────────────────────────────────────────
async def embed_text(text: str) -> list[float] | None:
    """Embed `text` into a 1536-dim vector, or None if no backend is configured.

    Provider is chosen by `MEMORY_EMBED_PROVIDER` (default "openai"). The call
    is lazy — no client is constructed and no network request is made until the
    relevant API key is present. Returns None (never raises) when:
      - `text` is blank,
      - the configured provider has no API key,
      - the provider call errors.

    Returning None is the universal "memory is unavailable" signal that callers
    (write_memory / recall_memories) treat as a clean no-op.
    """
    if not (text or "").strip():
        return None

    provider = os.environ.get("MEMORY_EMBED_PROVIDER", "openai").strip().lower()
    if provider == "openai":
        return await _embed_openai(text)
    # Unknown provider → no backend. Don't guess; let memory no-op.
    return None


async def _embed_openai(text: str) -> list[float] | None:
    """OpenAI embeddings backend. Gated on OPENAI_API_KEY; returns None when
    the key is missing (local dev / test) so nothing hits the network."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    import httpx

    model = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
        vector = data["data"][0]["embedding"]
    except Exception as e:
        print(f"[memory] embed_text failed: {e!r}", flush=True)
        return None

    if not isinstance(vector, list) or not vector:
        return None
    return [float(x) for x in vector]


# ── agents.id resolution (mirrors core/tasks.py) ────────────────────────────
def _resolve_agent_id(supabase: Any, org_id: str, agent_slug: str) -> str | None:
    """Look up the `agents.id` for a slug within the org. Returns None when the
    slug isn't registered (system agents may not have a row); the memory row
    still inserts cleanly with `agent_id = NULL`. Same pattern as
    core/tasks.py::_resolve_agent_id."""
    try:
        result = (
            supabase.table("agents")
            .select("id")
            .eq("org_id", org_id)
            .eq("slug", agent_slug)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    if result.data:
        return result.data[0].get("id")
    return None


# ── Write ────────────────────────────────────────────────────────────────--
async def save_fact(
    org_id: str | None,
    agent_slug: str,
    thread_id: str | None,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Embed `content` and insert one row into `agent_memory` — REPORTING
    the outcome: returns None on a confirmed insert, otherwise a short
    human-readable reason the save did not happen.

    This is the backing for explicit "remember this" tools, which must never
    claim success falsely (the failure mode that burned the client's old
    system: "saving it" followed by a red-X). Automatic turn-summary memory
    goes through `write_memory`, which discards the reason.

    `agent_slug` is mapped to `agent_memory.agent_id` via a quick lookup so
    call sites stay slug-friendly (matches core/tasks.py). `thread_id` is only
    written when it's a real UUID — the column FKs to `threads(id)`.
    """
    supabase = current_supabase.get()
    if supabase is None or not _is_real_uuid(org_id):
        return "long-term memory isn't available in this environment (no workspace database)"
    if not (content or "").strip():
        return "the fact was empty"

    embedding = await embed_text(content)
    if embedding is None:
        return "the memory backend isn't configured yet (needs OPENAI_API_KEY for embeddings)"

    agent_id = _resolve_agent_id(supabase, org_id, agent_slug)
    payload: dict[str, Any] = {
        "org_id": org_id,
        "agent_id": agent_id,
        "thread_id": thread_id if _is_real_uuid(thread_id) else None,
        "content": content.strip(),
        "embedding": embedding,
        "metadata": metadata or {},
    }
    try:
        supabase.table("agent_memory").insert(payload).execute()
    except Exception as e:
        print(f"[memory] save_fact insert failed: {e!r}", flush=True)
        return "the database write failed — try again in a moment"
    return None


async def write_memory(
    org_id: str | None,
    agent_slug: str,
    thread_id: str | None,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Embed `content` and insert one row into `agent_memory`.

    Best-effort and silent. No-ops (returns None without raising) when:
      - Supabase isn't configured (local dev),
      - `org_id` isn't a real UUID (dev fallback "dev"),
      - `content` is blank,
      - no embedding backend is configured (embed_text → None),
      - the insert errors.

    Thin façade over `save_fact` that discards the reason — the auto-memory
    path (turn summaries at run end) must stay fire-and-forget.
    """
    await save_fact(org_id, agent_slug, thread_id, content, metadata)


# ── Recall ──────────────────────────────────────────────────────────────--─
async def recall_memories(
    org_id: str | None,
    agent_slug: str,
    query: str,
    *,
    limit: int = 5,
) -> list[dict]:
    """Embed `query` and cosine-search `agent_memory` for the org's most
    relevant past memories.

    Returns a list of `{"content": str, "metadata": dict, "created_at": str,
    "similarity": float}` dicts, most-similar first — or `[]` on any no-op
    path (no Supabase / non-UUID org / no embedding backend / DB error).

    Scoped to the org and (by default) the calling agent's own memories via
    the `match_agent_memory` RPC (migrations/021_agent_memory_search.sql). The
    RPC does the cosine distance ordering against the ivfflat index; we pass
    `agent_slug` through so an agent recalls what IT learned, not every agent's
    notes. Pass a blank slug to search across all agents in the org.
    """
    supabase = current_supabase.get()
    if supabase is None or not _is_real_uuid(org_id) or not (query or "").strip():
        return []

    embedding = await embed_text(query)
    if embedding is None:
        return []

    try:
        result = supabase.rpc(
            "match_agent_memory",
            {
                "p_org_id": org_id,
                "p_agent_slug": agent_slug or None,
                "p_query_embedding": embedding,
                "p_match_count": limit,
            },
        ).execute()
    except Exception as e:
        print(f"[memory] recall_memories failed: {e!r}", flush=True)
        return []

    rows = result.data or []
    out: list[dict] = []
    for row in rows:
        content = (row.get("content") or "").strip()
        if not content:
            continue
        out.append({
            "content": content,
            "metadata": row.get("metadata") or {},
            "created_at": row.get("created_at"),
            "similarity": row.get("similarity"),
        })
    return out
