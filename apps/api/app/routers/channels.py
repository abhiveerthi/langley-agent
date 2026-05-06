"""
Team channels API — Slack-style in-house chat where humans and agents
are first-class participants in the same channel.

The killer feature: posting `@strategist what should we make next?` in a
channel kicks off the Strategist agent, whose response posts back into
the channel as a regular message everyone can see. See
`app/services/channel_dispatch.py` for the dispatch glue.

Endpoints:
  GET    /api/channels                  — list channels (excludes archived)
  POST   /api/channels                  — create a channel
  GET    /api/channels/{id}/messages    — paginated message history
  POST   /api/channels/{id}/messages    — post a user message + parse mentions
  POST   /api/channels/{id}/join        — idempotent membership upsert
  GET    /api/channels/mentionable      — autocomplete data for @-popover

Org-scoping: every read is filtered by `eq("org_id", user.org_id)` and
every write asserts the channel belongs to the caller's org. The DB has
RLS policies on top, but the router is the primary tenancy gate because
we use the service-role key.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from supabase import Client

from app.dependencies import CurrentUser, get_current_user, get_supabase
from app.services.channel_dispatch import (
    run_dispatch_safely,
    run_resume_to_channel_safely,
)

router = APIRouter(tags=["channels"])


# ── Schemas ───────────────────────────────────────────────────────────────
class CreateChannelRequest(BaseModel):
    """Channel name is the slug shown with `#` in the UI. The FE
    slugifies user input but we enforce the same regex server-side so a
    direct API caller can't slip a space / unicode / quote in."""
    name: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    description: Optional[str] = None


class RejectApprovalInChannelRequest(BaseModel):
    """Optional feedback piped to the agent's revision logic — same
    contract as the standalone `/api/approvals/{id}/reject` endpoint."""
    feedback: Optional[str] = None


class CreateMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


# ── Mention parsing ───────────────────────────────────────────────────────
# `@token` runs of [a-z0-9_-] up to 64 chars. Case-insensitive on input;
# tokens are lowercased for comparison. Word-boundary on the leading `@`
# avoids `email@host` — actual `@`-mentions are preceded by start-of-string
# or whitespace/punctuation. We use a negative lookbehind for word chars
# so `foo@bar` (where `foo` is word-chars) doesn't match.
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([a-zA-Z0-9_-]{1,64})")


def _extract_mention_tokens(body: str) -> list[str]:
    """Return the raw mention tokens (lowercased, deduped, order-preserved)."""
    seen: set[str] = set()
    out: list[str] = []
    for match in _MENTION_RE.finditer(body):
        token = match.group(1).lower()
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def parse_mentions(
    body: str,
    *,
    org_id: str,
    supabase: Client,
) -> tuple[list[str], list[str]]:
    """Parse a message body into `(mentioned_user_ids, mentioned_agent_slugs)`.

    Resolution rules per token:
      1. If `token.lower()` matches an `agents.slug` for this org
         (case-insensitive), it's an agent mention.
      2. Else if it matches a user's `full_name` (lowercased + spaces
         stripped) OR the prefix of `users.email` (before `@`) for a
         user in this org, it's a user mention.
      3. Else dropped silently (FE can't currently distinguish typos
         from unknown handles, so we don't error on them).

    Both result lists are deduped, in order of first appearance.
    """
    tokens = _extract_mention_tokens(body)
    if not tokens:
        return [], []

    # Pull the org's agent slugs and member users in two queries so
    # resolution stays O(N) per token without N+1 lookups.
    agent_slugs_lower: dict[str, str] = {}
    try:
        agents_resp = (
            supabase.table("agents")
            .select("slug")
            .eq("org_id", org_id)
            .execute()
        )
        for row in agents_resp.data or []:
            slug = (row.get("slug") or "").lower()
            if slug:
                agent_slugs_lower[slug] = slug
    except Exception:
        agent_slugs_lower = {}

    # Org members → users join. We need each member's id, full_name, email.
    user_index: dict[str, str] = {}  # match-key → user_id
    try:
        members_resp = (
            supabase.table("org_members")
            .select("user_id, users(id, full_name, email)")
            .eq("org_id", org_id)
            .execute()
        )
        for row in members_resp.data or []:
            u = row.get("users") or {}
            uid = u.get("id") or row.get("user_id")
            if not uid:
                continue
            full_name = (u.get("full_name") or "").lower().replace(" ", "")
            email = (u.get("email") or "").lower()
            email_prefix = email.split("@", 1)[0] if "@" in email else email
            if full_name:
                user_index.setdefault(full_name, uid)
            if email_prefix:
                user_index.setdefault(email_prefix, uid)
    except Exception:
        user_index = {}

    mentioned_agent_slugs: list[str] = []
    mentioned_user_ids: list[str] = []
    seen_users: set[str] = set()

    for token in tokens:
        if token in agent_slugs_lower:
            # Already deduped at the token level, so safe to append directly.
            mentioned_agent_slugs.append(token)
            continue
        uid = user_index.get(token)
        if uid and uid not in seen_users:
            seen_users.add(uid)
            mentioned_user_ids.append(uid)

    return mentioned_user_ids, mentioned_agent_slugs


# ── Helpers ───────────────────────────────────────────────────────────────
def _serialize_channel(row: dict, member_count: int) -> dict:
    """Shape a channels row + member count into the FE Channel contract."""
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "description": row.get("description"),
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
        "archived_at": row.get("archived_at"),
        "member_count": member_count,
    }


def _serialize_message(row: dict) -> dict:
    """Shape a channel_messages row into the FE Message contract.

    Postgrest joins land as nested objects keyed by the alias used in
    `select(...)`. We tolerate both keyed shapes (`users:sender_user_id`
    landing as `users` or as `sender_user`) since Supabase's postgrest
    client picks the shorter alias when there's no collision.
    """
    sender_user_blob = row.get("sender_user") or row.get("users")
    sender_agent_blob = row.get("sender_agent") or row.get("agents")
    sender_user = None
    if sender_user_blob and sender_user_blob.get("id"):
        sender_user = {
            "id": sender_user_blob.get("id"),
            "full_name": sender_user_blob.get("full_name"),
            "email": sender_user_blob.get("email"),
        }
    sender_agent = None
    if sender_agent_blob and sender_agent_blob.get("id"):
        sender_agent = {
            "id": sender_agent_blob.get("id"),
            "slug": sender_agent_blob.get("slug"),
            "name": sender_agent_blob.get("name"),
            "icon": sender_agent_blob.get("icon"),
        }
    return {
        "id": row.get("id"),
        "channel_id": row.get("channel_id"),
        "org_id": row.get("org_id"),
        "sender_user_id": row.get("sender_user_id"),
        "sender_agent_id": row.get("sender_agent_id"),
        "sender_user": sender_user,
        "sender_agent": sender_agent,
        "body": row.get("body"),
        "mentioned_user_ids": row.get("mentioned_user_ids") or [],
        "mentioned_agent_slugs": row.get("mentioned_agent_slugs") or [],
        "agent_run_id": row.get("agent_run_id"),
        "in_reply_to_message_id": row.get("in_reply_to_message_id"),
        # `metadata.kind` drives FE rich-card rendering (currently
        # `"approval"`; future kinds slot in here).
        "metadata": row.get("metadata") or {},
        "created_at": row.get("created_at"),
        "edited_at": row.get("edited_at"),
    }


def _assert_channel_in_org(
    supabase: Client, *, channel_id: str, org_id: str,
) -> dict:
    """Fetch a channel and 404 if it doesn't belong to this org.

    Cross-tenant `channel_id`s come back as 404 (not 403) — leaking
    the existence-elsewhere is a smaller harm than silent success.
    """
    resp = (
        supabase.table("channels")
        .select("*")
        .eq("id", channel_id)
        .eq("org_id", org_id)
        .limit(1)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Channel not found")
    return resp.data[0]


def _member_counts_for(
    supabase: Client, *, channel_ids: list[str],
) -> dict[str, int]:
    """Single grouped query: count `channel_members` rows per channel.

    We pull all rows for the relevant channels and bucket in Python —
    Postgrest doesn't expose GROUP BY directly. Cheap because the working
    set is "channels in this org" (small) and members per channel is
    bounded by org size.
    """
    if not channel_ids:
        return {}
    try:
        resp = (
            supabase.table("channel_members")
            .select("channel_id")
            .in_("channel_id", channel_ids)
            .execute()
        )
    except Exception:
        return {cid: 0 for cid in channel_ids}
    counter: Counter = Counter()
    for row in resp.data or []:
        cid = row.get("channel_id")
        if cid:
            counter[cid] += 1
    return {cid: counter.get(cid, 0) for cid in channel_ids}


# ── Endpoints ─────────────────────────────────────────────────────────────
@router.get("/channels")
async def list_channels(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """List active channels in caller's org, latest-first.

    `member_count` is denormalized via a single grouped query so the
    sidebar doesn't pay an N+1 cost when an org has dozens of channels.
    """
    resp = (
        supabase.table("channels")
        .select("*")
        .eq("org_id", user.org_id)
        .is_("archived_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    rows = resp.data or []
    channel_ids = [r["id"] for r in rows if r.get("id")]
    counts = _member_counts_for(supabase, channel_ids=channel_ids)
    return [_serialize_channel(r, counts.get(r["id"], 0)) for r in rows]


@router.post("/channels")
async def create_channel(
    body: CreateChannelRequest,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Create a channel and auto-join the creator.

    Same `(org_id, name)` in two different orgs is fine — the unique
    constraint is per-org. Duplicate name in the SAME org → 409.
    """
    payload = {
        "org_id": user.org_id,
        "name": body.name,
        "description": body.description,
        "created_by": user.id,
    }
    try:
        result = supabase.table("channels").insert(payload).execute()
    except Exception as e:
        # Postgrest unique-violation surfaces as a generic exception; we
        # match the most common message shapes. The cleaner approach
        # (PostgREST returns 23505 in the JSON error body) is variant-
        # specific; falling back to a 409 on any insert exception when
        # the row exists already keeps the contract simple.
        msg = str(e).lower()
        if "duplicate" in msg or "unique" in msg or "23505" in msg:
            raise HTTPException(status_code=409, detail="Channel name already exists")
        raise

    if not result.data:
        # Some Postgrest builds return [] on conflict instead of raising —
        # double-check by looking up the existing row.
        existing = (
            supabase.table("channels")
            .select("id")
            .eq("org_id", user.org_id)
            .eq("name", body.name)
            .limit(1)
            .execute()
        )
        if existing.data:
            raise HTTPException(status_code=409, detail="Channel name already exists")
        raise HTTPException(status_code=500, detail="Channel insert returned no row")

    new_row = result.data[0]
    # Auto-add creator as a member. Idempotent upsert in case the FE
    # double-clicks create.
    try:
        supabase.table("channel_members").upsert(
            {"channel_id": new_row["id"], "user_id": user.id},
            on_conflict="channel_id,user_id",
        ).execute()
    except Exception as e:
        print(f"[channels] auto-join creator failed: {e!r}", flush=True)

    return _serialize_channel(new_row, member_count=1)


@router.get("/channels/{channel_id}/messages")
async def list_messages(
    channel_id: str,
    limit: int = Query(50, ge=1, le=200),
    before: Optional[str] = Query(None, description="ISO timestamp; returns messages with created_at < before"),
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Paginated message history, newest-first.

    `before` is an ISO timestamp cursor — the FE keeps scrolling up by
    sending the oldest `created_at` it has rendered so far. We keep the
    sort newest-first so the FE doesn't have to reverse on each page.
    """
    _assert_channel_in_org(supabase, channel_id=channel_id, org_id=user.org_id)

    query = (
        supabase.table("channel_messages")
        .select(
            # Postgrest implicit-join syntax. Aliases let us land users +
            # agents under stable keys regardless of FK ambiguity.
            "*, sender_user:sender_user_id(id, full_name, email),"
            " sender_agent:sender_agent_id(id, slug, name, icon)"
        )
        .eq("org_id", user.org_id)
        .eq("channel_id", channel_id)
    )
    if before:
        query = query.lt("created_at", before)
    resp = (
        query
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [_serialize_message(r) for r in (resp.data or [])]


@router.post("/channels/{channel_id}/messages")
async def create_message(
    channel_id: str,
    body: CreateMessageRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Insert a user-authored message. Parses mentions, dispatches agents.

    Agent dispatch runs in BackgroundTasks so the API returns the user
    message immediately — the agent reply lands later via the same
    `channel_messages` table (and the FE's Realtime subscription picks
    it up).
    """
    _assert_channel_in_org(supabase, channel_id=channel_id, org_id=user.org_id)

    mentioned_user_ids, mentioned_agent_slugs = parse_mentions(
        body.body, org_id=user.org_id, supabase=supabase,
    )

    payload = {
        "channel_id": channel_id,
        "org_id": user.org_id,
        "sender_user_id": user.id,
        "body": body.body,
        "mentioned_user_ids": mentioned_user_ids,
        "mentioned_agent_slugs": mentioned_agent_slugs,
    }
    result = supabase.table("channel_messages").insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Message insert returned no row")
    inserted = result.data[0]

    # Kick off background dispatch for each mentioned agent. Errors are
    # caught and logged in `run_dispatch_safely` — BackgroundTasks would
    # swallow them silently otherwise.
    for slug in mentioned_agent_slugs:
        background_tasks.add_task(
            run_dispatch_safely,
            agent_slug=slug,
            channel_id=channel_id,
            org_id=user.org_id,
            user_id=user.id,
            triggering_message_id=inserted["id"],
            triggering_message_body=body.body,
            supabase=supabase,
        )

    # Hydrate the response with the sender_user shape since the FE renders
    # the optimistic message using whatever we return here.
    inserted.setdefault(
        "sender_user",
        {"id": user.id, "full_name": None, "email": user.email},
    )
    inserted.setdefault("sender_agent", None)
    return _serialize_message(inserted)


@router.post("/channels/{channel_id}/join")
async def join_channel(
    channel_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Idempotent join. Calling twice is a no-op."""
    _assert_channel_in_org(supabase, channel_id=channel_id, org_id=user.org_id)
    try:
        supabase.table("channel_members").upsert(
            {"channel_id": channel_id, "user_id": user.id},
            on_conflict="channel_id,user_id",
        ).execute()
    except Exception as e:
        # If the upsert path isn't available, fall back to insert + ignore
        # the unique-violation that comes back when the row exists.
        try:
            supabase.table("channel_members").insert(
                {"channel_id": channel_id, "user_id": user.id}
            ).execute()
        except Exception as e2:
            msg = str(e2).lower()
            if "duplicate" not in msg and "unique" not in msg and "23505" not in msg:
                print(f"[channels] join failed: {e!r} / {e2!r}", flush=True)
                raise HTTPException(status_code=500, detail="Join failed")
    return {"joined": True}


@router.get("/channels/mentionable")
async def list_mentionable(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Autocomplete data for the @-mention popover.

    Returns the active agents in the caller's org and the org's user
    members. The FE filters by prefix client-side; we don't paginate
    because the working set per org is small.
    """
    # `id` is included so the FE can resolve the sender of an agent-authored
    # message from a realtime payload (which carries `sender_agent_id` only,
    # no joined info) without a one-shot refetch.
    agents_resp = (
        supabase.table("agents")
        .select("id, slug, name, icon")
        .eq("org_id", user.org_id)
        .eq("active", True)
        .order("name", desc=False)
        .execute()
    )
    members_resp = (
        supabase.table("org_members")
        .select("users(id, full_name, email)")
        .eq("org_id", user.org_id)
        .execute()
    )
    users_out: list[dict] = []
    seen_users: set[str] = set()
    for row in members_resp.data or []:
        u = row.get("users") or {}
        uid = u.get("id")
        if not uid or uid in seen_users:
            continue
        seen_users.add(uid)
        users_out.append({
            "id": uid,
            "full_name": u.get("full_name"),
            "email": u.get("email"),
        })
    return {
        "agents": [
            {"id": a.get("id"), "slug": a.get("slug"), "name": a.get("name"), "icon": a.get("icon")}
            for a in (agents_resp.data or [])
        ],
        "users": users_out,
    }


def _find_approval_card_message(
    supabase: Client, *, channel_id: str, org_id: str, approval_id: str,
) -> dict | None:
    """Locate the channel_messages row whose metadata.kind == "approval"
    and metadata.approval_id matches. We need this to UPDATE in place
    (not insert a new row) so the inline card transitions from
    "needs decision" → "approved/rejected by X" without creating
    duplicate timeline entries.

    Postgrest's jsonb arrow-equality lets us filter directly:
    `metadata->>approval_id=eq.<id>`. We still org-scope and channel-
    scope to be safe even though the approval_id alone is unique.
    """
    try:
        resp = (
            supabase.table("channel_messages")
            .select("id, metadata")
            .eq("channel_id", channel_id)
            .eq("org_id", org_id)
            .filter("metadata->>approval_id", "eq", approval_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        print(f"[channels] approval-card lookup failed: {e!r}", flush=True)
        return None
    if not resp.data:
        return None
    return resp.data[0]


def _mark_approval_card_resolved(
    supabase: Client,
    *,
    card_message_id: str,
    org_id: str,
    approval_id: str,
    decision: str,
    reviewed_by: str,
) -> None:
    """UPDATE the approval-card channel_messages row's metadata in place
    so the FE renders the resolved state. The supabase_realtime
    publication includes UPDATE events on this table, so this fires the
    FE to re-render.

    Best-effort — failure leaves the card showing the buttons, but the
    underlying approval row is already decided so a refresh re-syncs."""
    try:
        supabase.table("channel_messages").update({
            "metadata": {
                "kind": "approval",
                "approval_id": approval_id,
                "status": decision,
                "reviewed_by": reviewed_by,
            }
        }).eq("id", card_message_id).eq("org_id", org_id).execute()
    except Exception as e:
        print(f"[channels] approval-card UPDATE failed: {e!r}", flush=True)


@router.post("/channels/{channel_id}/approvals/{approval_id}/approve")
async def approve_in_channel(
    channel_id: str,
    approval_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Approve a paused agent run from the inline channel card.

    Splits the work in two:
      1. Synchronous: locate the approval-card message and UPDATE its
         metadata to {status: "approved", reviewed_by: <user>}. The
         realtime UPDATE event fires immediately so the user sees the
         card collapse to "approved by you" with no perceptible delay.
      2. Background: drain the resume stream (the agent finishes its
         work — sends the email, posts the YouTube comment, etc.) and
         post the result back into the channel as a follow-up message.
         If the resumed run pauses again at another gate, a fresh
         approval card is posted.

    The 202 Accepted response is intentional — the BG task races with
    the user's next interaction. Returns the same Message shape as
    other endpoints so the FE can drop it into local state immediately.
    """
    _assert_channel_in_org(supabase, channel_id=channel_id, org_id=user.org_id)

    card = _find_approval_card_message(
        supabase, channel_id=channel_id, org_id=user.org_id, approval_id=approval_id,
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Approval card not found in this channel")

    _mark_approval_card_resolved(
        supabase,
        card_message_id=card["id"],
        org_id=user.org_id,
        approval_id=approval_id,
        decision="approved",
        reviewed_by=user.id,
    )

    background_tasks.add_task(
        run_resume_to_channel_safely,
        approval_id=approval_id,
        decision="approved",
        feedback=None,
        channel_id=channel_id,
        org_id=user.org_id,
        user_id=user.id,
        triggering_message_id=card["id"],
        supabase=supabase,
    )

    return {"status": "approved", "approval_id": approval_id}


@router.post("/channels/{channel_id}/approvals/{approval_id}/reject")
async def reject_in_channel(
    channel_id: str,
    approval_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[RejectApprovalInChannelRequest] = None,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Reject a paused agent run from the inline channel card.

    Mirrors `approve_in_channel` but routes the resume through the
    `revise` branch so the agent regenerates the draft using the
    provided feedback. The revised draft pauses at the same gate again,
    and a fresh approval card is posted to the channel.
    """
    _assert_channel_in_org(supabase, channel_id=channel_id, org_id=user.org_id)

    feedback = body.feedback if body else None

    card = _find_approval_card_message(
        supabase, channel_id=channel_id, org_id=user.org_id, approval_id=approval_id,
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Approval card not found in this channel")

    _mark_approval_card_resolved(
        supabase,
        card_message_id=card["id"],
        org_id=user.org_id,
        approval_id=approval_id,
        decision="rejected",
        reviewed_by=user.id,
    )

    background_tasks.add_task(
        run_resume_to_channel_safely,
        approval_id=approval_id,
        decision="rejected",
        feedback=feedback,
        channel_id=channel_id,
        org_id=user.org_id,
        user_id=user.id,
        triggering_message_id=card["id"],
        supabase=supabase,
    )

    return {"status": "rejected", "approval_id": approval_id}
