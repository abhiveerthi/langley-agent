"""Slack-originated agent runs.

This module is the Slack equivalent of `apps/api/app/routers/stream.py`'s
HTTP handler: it takes a Slack message event, resolves it to a Marcus
(org, user, thread), invokes the existing graph orchestrator, accumulates
the SSE stream, and posts the final reply back to the Slack thread.

Two entry points share the same SSE-consumption + posting logic via
`_run_and_post`:
  - `handle_message`: a fresh user message → `stream_new_run`
  - `handle_resume`:   an Approve/Reject button click → `stream_resume_*`

When the run pauses at an approval gate, `_run_and_post` posts a Block
Kit approval card in the Slack thread and persists `slack_message_ts` /
`slack_channel_id` onto the `approvals` row. The interactive handler
later uses these to `chat.update` the same card with the resolution.

Per-Slack-thread = per-Marcus-thread:
  - A top-level Slack message starts a new Marcus thread (UUID generated
    here, persisted to `slack_channels` keyed on the user's message ts).
  - Replies in the same Slack thread reuse the Marcus thread, so agent
    context (and the LangGraph checkpointer state) accumulates.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator
from uuid import uuid4

from app.auth import with_tool_context
from app.services.graph_orchestrator import (
    stream_new_run,
    stream_resume_approved,
    stream_resume_rejected,
)
from packages.integrations.slack import client as slack_client
from packages.integrations.slack.blocks import build_approval_card
from packages.integrations.slack.identity import resolve_marcus_user
from packages.integrations.slack.oauth import persona_for


LINK_ACCOUNT_FALLBACK = (
    "I can't link your Slack account to Backroom — your Slack email doesn't "
    "match a Backroom user in this workspace's org. Sign in to Backroom with "
    "the same email you use on Slack and try again."
)

# ── Attachment handling (Agent #6: screenshots + voice, natively in Slack) ──
# Claude's vision API rejects images over ~5MB; voice notes are short but
# users can share arbitrary audio files.
MAX_IMAGES_PER_MESSAGE = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024

# DMs have no per-agent channel mapping — they route to the Image Reader,
# the suite's designated front door: it answers general questions, reads
# screenshots, transcribes voice, and can delegate_task() to the right
# specialist. This is the on-the-go surface (phone/watch DMs to the bot).
DM_AGENT_SLUG = "image-reader"


def resolve_route(
    chan: dict | None, channel_type: str | None, install: dict | None
) -> tuple[str, str] | None:
    """(org_id, agent_slug) for an inbound message, or None to ignore.

    Provisioned channel → its mapped agent. Unmapped DM → the DM front-door
    agent, org resolved from the workspace's Slack install. Anything else
    unmapped (random channels the bot was invited to) stays ignored.
    """
    if chan is not None:
        return chan["org_id"], chan["agent_slug"]
    if channel_type == "im" and install and install.get("org_id"):
        return install["org_id"], DM_AGENT_SLUG
    return None

# Anthropic's vision API accepts exactly these; Slack will happily deliver
# HEIC (default iPhone shares), TIFF, BMP, SVG — attaching those would fail
# the whole model call, so they're skipped with a note instead.
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Global cap on concurrent Slack file downloads across all in-flight events
# — each can hold up to ~25MB in memory, and event dispatch is unbounded.
import asyncio as _asyncio

_download_sem = _asyncio.Semaphore(4)


async def _bounded_download(bot_token: str, url: str, *, max_bytes: int) -> bytes:
    async with _download_sem:
        return await slack_client.download_file(bot_token, url, max_bytes=max_bytes)


def _split_files(files: list[dict]) -> tuple[list[dict], list[dict]]:
    """(images, audios) from a Slack files[] payload, by mimetype. Slack
    voice clips carry subtype slack_audio; regular uploads audio/*."""
    images = [
        f for f in (files or [])
        if (f.get("mimetype") or "").startswith("image/")
    ]
    audios = [
        f for f in (files or [])
        if (f.get("mimetype") or "").startswith("audio/")
        or f.get("subtype") == "slack_audio"
    ]
    return images, audios


async def _transcribe_slack_audio(bot_token: str, file: dict) -> tuple[str | None, str]:
    """Voice note → text, accuracy-first. Returns (transcript|None, note).

    Order of preference:
      1. Our transcription seam (core/transcription.py — full-fidelity
         whisper, local or hosted) over the downloaded bytes. Accuracy is a
         hard requirement ("must be extremely accurate"), and Slack's
         built-in transcript is a truncated preview.
      2. Slack's native transcription as fallback when no whisper backend
         is configured — from the event payload, or files.info if it
         hadn't been attached yet (Slack fills it in asynchronously).
    """
    from packages.agents.core.transcription import (
        TranscriptionUnavailable,
        transcribe_audio,
    )

    note = ""
    try:
        url = file.get("url_private_download") or file.get("url_private")
        if url:
            audio_bytes = await _bounded_download(
                bot_token, url, max_bytes=MAX_AUDIO_BYTES
            )
            transcript = await transcribe_audio(
                audio_bytes, content_type=file.get("mimetype")
            )
            if transcript:
                return transcript, "whisper"
            note = "transcription produced no text"
        else:
            note = "file had no download URL"
    except TranscriptionUnavailable as e:
        note = str(e)
    except Exception as e:
        note = f"transcription failed: {e!r}"

    # Fallback: Slack's own (preview) transcript.
    transcription = file.get("transcription") or {}
    if transcription.get("status") != "complete" and file.get("id"):
        try:
            info = await slack_client.get_file_info(bot_token, file["id"])
            transcription = info.get("transcription") or {}
        except Exception:
            pass
    preview = ((transcription.get("preview") or {}).get("content") or "").strip()
    if preview:
        return preview, "slack-native preview"
    return None, note or "no transcript available"


async def _image_content_blocks(
    bot_token: str, images: list[dict], text: str
) -> tuple[list[dict], list[str]]:
    """Download Slack images and build the Anthropic content-block message
    the Image Reader's vision path expects. Returns (blocks, skipped_notes);
    blocks is empty when no image survived the caps."""
    import base64

    blocks: list[dict] = [{
        "type": "text",
        "text": text or "Read and analyze the attached screenshot(s).",
    }]
    skipped: list[str] = []
    attached = 0
    for f in images:
        if attached >= MAX_IMAGES_PER_MESSAGE:
            skipped.append(f"{f.get('name') or 'image'}: over the {MAX_IMAGES_PER_MESSAGE}-image limit")
            continue
        mimetype = (f.get("mimetype") or "").lower()
        if mimetype not in SUPPORTED_IMAGE_TYPES:
            skipped.append(
                f"{f.get('name') or 'image'}: {mimetype or 'unknown type'} isn't "
                f"readable — send PNG/JPEG/WebP (or screenshot it)"
            )
            continue
        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            skipped.append(f"{f.get('name') or 'image'}: no download URL")
            continue
        try:
            img_bytes = await _bounded_download(
                bot_token, url, max_bytes=MAX_IMAGE_BYTES
            )
        except Exception as e:
            skipped.append(f"{f.get('name') or 'image'}: {e}")
            continue
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": f.get("mimetype") or "image/png",
                "data": base64.b64encode(img_bytes).decode(),
            },
        })
        attached += 1
    if attached == 0:
        return [], skipped
    return blocks, skipped


async def handle_message(
    *,
    supabase: Any,
    slack_team_id: str,
    slack_channel_id: str,
    slack_user_id: str,
    slack_thread_ts: str | None,
    slack_message_ts: str,
    text: str,
    files: list[dict] | None = None,
    channel_type: str | None = None,
) -> None:
    """Run the agent for one inbound Slack message and post a reply.

    Caller (the events webhook) is expected to dispatch this in a
    background task — the orchestrator can take 30+ seconds and Slack
    times the webhook out at 3.

    Attachments (Agent #6, everything natively in Slack):
      - a VOICE NOTE is transcribed and then handled exactly as if the
        transcript had been typed — same channel agent, same flow;
      - IMAGES route the run to the Image Reader (the only agent with the
        vision/report lane) with the pixels as Anthropic content blocks.
    DMs (`channel_type == "im"`) have no channel mapping and route to the
    Image Reader front door — see resolve_route().
    """
    chan = _lookup_channel_mapping(supabase, slack_channel_id)
    install = _lookup_install(supabase, slack_team_id)
    if install is None:
        # Workspace's Slack install was deleted; nothing to do.
        return

    route = resolve_route(chan, channel_type, install)
    if route is None:
        # Not a provisioned channel and not a DM; ignore quietly.
        return
    org_id, agent_slug = route
    bot_token = install["access_token"]
    persona = persona_for(agent_slug, install.get("scopes") or [])

    images, audios = _split_files(files or [])
    voice_prefix = ""

    if audios:
        transcript, note = await _transcribe_slack_audio(bot_token, audios[0])
        if transcript:
            # "Proceed as if he had typed it manually."
            text = f"{text}\n\n{transcript}".strip() if text.strip() else transcript
            voice_prefix = "🎙️ "
        else:
            # NEVER silently drop voice input — even when a caption or
            # screenshot rides along, the voice note usually carried the
            # actual ask ("context in the voice note: ...").
            await slack_client.post_message_in_thread(
                bot_token,
                slack_channel_id,
                f"I couldn't transcribe that voice note ({note}). "
                f"Try again, or type it out.",
                thread_ts=slack_thread_ts or slack_message_ts,
                **persona,
            )
            if not images and not text.strip():
                return  # voice was the whole message — nothing left to run
        if len(audios) > 1:
            await slack_client.post_message_in_thread(
                bot_token,
                slack_channel_id,
                f"Heads up: I only transcribe the first voice note per "
                f"message — {len(audios) - 1} other audio file(s) ignored.",
                thread_ts=slack_thread_ts or slack_message_ts,
                **persona,
            )

    extra_state: dict | None = None
    if images:
        blocks, skipped = await _image_content_blocks(bot_token, images, text)
        if blocks:
            from langchain_core.messages import HumanMessage

            # Vision lives in the Image Reader — override the channel's
            # mapped agent for this one message (it's the suite's designated
            # reader/delegator for visual input).
            agent_slug = "image-reader"
            persona = persona_for(agent_slug, install.get("scopes") or [])
            extra_state = {"messages": [HumanMessage(content=blocks)]}
            if not text.strip():
                text = "Read and analyze the attached screenshot(s)."
        if skipped:
            await slack_client.post_message_in_thread(
                bot_token,
                slack_channel_id,
                "Note: I skipped " + "; ".join(skipped),
                thread_ts=slack_thread_ts or slack_message_ts,
                **persona,
            )

    # Nothing runnable — file_share admits any file type, so a PDF/video
    # with no caption (or images that all failed the caps) can land here
    # with empty text and no attachments. Running would send Anthropic an
    # empty HumanMessage (a 400) and persist a blank user turn. Say what
    # happened instead.
    if not text.strip() and extra_state is None:
        await slack_client.post_message_in_thread(
            bot_token,
            slack_channel_id,
            "I can read images (PNG/JPEG/WebP screenshots) and voice notes — "
            "I couldn't process that upload. Add a caption telling me what "
            "you need, or send it as a screenshot.",
            thread_ts=slack_thread_ts or slack_message_ts,
            **persona,
        )
        return

    ident = await resolve_marcus_user(
        supabase=supabase,
        slack_team_id=slack_team_id,
        slack_user_id=slack_user_id,
        slack_bot_token=bot_token,
    )
    if ident is None:
        await slack_client.post_message_in_thread(
            bot_token,
            slack_channel_id,
            LINK_ACCOUNT_FALLBACK,
            thread_ts=slack_thread_ts or slack_message_ts,
            **persona,
        )
        return

    # Top-level Slack message → root_ts is the user's own ts.
    # Reply in an existing Slack thread → root_ts is the parent's thread_ts.
    root_ts = slack_thread_ts or slack_message_ts
    marcus_thread_id = _resolve_marcus_thread(
        supabase,
        org_id=org_id,
        agent_slug=agent_slug,
        slack_team_id=slack_team_id,
        slack_channel_id=slack_channel_id,
        slack_thread_root_ts=root_ts,
    )

    _ensure_thread(
        supabase,
        thread_id=marcus_thread_id,
        org_id=org_id,
        user_id=ident["user_id"],
        title=f"#backroom-{agent_slug} (Slack)",
    )

    _insert_message(
        supabase,
        thread_id=marcus_thread_id,
        role="user",
        content=f"{voice_prefix}{text}",
        metadata={
            "source": "slack",
            "slack_user_id": slack_user_id,
            "slack_message_ts": slack_message_ts,
            "slack_channel_id": slack_channel_id,
            "had_images": bool(extra_state),
            "was_voice": bool(voice_prefix),
        },
    )

    stream = with_tool_context(
        stream_new_run(
            agent_slug=agent_slug,
            message=text,
            thread_id=marcus_thread_id,
            org_id=org_id,
            user_id=ident["user_id"],
            extra_state=extra_state,
        ),
        org_id=org_id,
        user_id=ident["user_id"],
        supabase=supabase,
    )
    await _run_and_post(
        stream=stream,
        supabase=supabase,
        bot_token=bot_token,
        slack_channel_id=slack_channel_id,
        root_ts=root_ts,
        persona=persona,
        marcus_thread_id=marcus_thread_id,
    )


async def handle_resume(
    *,
    supabase: Any,
    approval_id: str,
    decision: str,                # "approved" | "rejected"
    feedback: str | None = None,
    reviewer_user_id: str,
) -> None:
    """Resume a paused agent run after a Slack button click.

    Reads the `approvals` row to find the org, agent, Slack channel, and
    Slack message ts (set when the card was posted). Calls the matching
    `stream_resume_*` orchestrator entry point, then runs continuation
    output through `_run_and_post` so any continuation tokens / further
    approval gates land in the same Slack thread.
    """
    approval = (
        supabase.table("approvals")
        .select("*")
        .eq("id", approval_id)
        .limit(1)
        .execute()
    )
    if not approval.data:
        return
    row = approval.data[0]
    if row.get("status") != "pending":
        # Already resolved (probably from the web UI or a duplicate click).
        return

    slack_channel_id = row.get("slack_channel_id")
    if not slack_channel_id:
        # Approval wasn't surfaced in Slack — nothing to post back to.
        return

    install = _lookup_install(supabase, _slack_team_for_channel(supabase, slack_channel_id))
    if install is None:
        return
    bot_token = install["access_token"]
    persona = persona_for(row["requested_by_agent"], install.get("scopes") or [])

    marcus_thread_id = row["thread_id"]
    # Resume continues posting in the same Slack thread the card was in;
    # find that thread root by looking up the per-thread row.
    chan_row = (
        supabase.table("slack_channels")
        .select("slack_thread_root_ts")
        .eq("marcus_thread_id", marcus_thread_id)
        .not_.is_("slack_thread_root_ts", "null")
        .limit(1)
        .execute()
    )
    root_ts = chan_row.data[0]["slack_thread_root_ts"] if chan_row.data else None

    if decision == "approved":
        gen = stream_resume_approved(
            approval_id=approval_id, reviewer_user_id=reviewer_user_id
        )
    else:
        gen = stream_resume_rejected(
            approval_id=approval_id,
            reviewer_user_id=reviewer_user_id,
            feedback=feedback,
        )

    org_id = row["org_id"]
    stream = with_tool_context(
        gen, org_id=org_id, user_id=reviewer_user_id, supabase=supabase
    )
    await _run_and_post(
        stream=stream,
        supabase=supabase,
        bot_token=bot_token,
        slack_channel_id=slack_channel_id,
        root_ts=root_ts,
        persona=persona,
        marcus_thread_id=marcus_thread_id,
    )


# ── Shared SSE consumer + Slack poster ────────────────────────────────────

async def _run_and_post(
    *,
    stream: AsyncIterator[str],
    supabase: Any,
    bot_token: str,
    slack_channel_id: str,
    root_ts: str | None,
    persona: dict,
    marcus_thread_id: str,
) -> None:
    """Drain an orchestrator SSE stream and post results to Slack.

    Three terminal states on the stream:
      - `done`             → post accumulated tokens as a single message
      - `error`            → post a "Run failed: ..." message
      - `waiting_approval` → post the accumulated tokens (if any) as a
                             pre-card message, then post the approval
                             card and persist its ts onto the approvals
                             row. Return; the next event arrives via the
                             interactive webhook.
    """
    accumulated: list[str] = []
    last_token: str | None = None
    error_msg: str | None = None
    paused: dict | None = None

    async for sse in stream:
        ev = _parse_sse(sse)
        if ev is None:
            continue
        kind = ev["type"]
        data = ev.get("data") or {}
        if kind == "token":
            content = data.get("content") or ""
            # The orchestrator emits a `token` event per AIMessage, per
            # node update (stream_mode="updates"). When the same final
            # AIMessage is seen by multiple node updates (e.g. the
            # `agent` and `respond` nodes both surface it), we get the
            # exact same content back-to-back — which would render in
            # Slack as the message twice in a row. Dedupe.
            if content and content != last_token:
                accumulated.append(content)
                last_token = content
        elif kind == "error":
            error_msg = data.get("message") or "unknown error"
        elif kind == "waiting_approval":
            paused = data
            break  # the run is paused; stop draining
        # tool_call_*, approval_recorded, done are no-ops here.

    preamble = "".join(accumulated).strip()

    if paused:
        # Post any preamble the agent produced before the gate (e.g. "I've
        # drafted the title — review below"), then the approval card.
        if preamble:
            _insert_message(
                supabase,
                thread_id=marcus_thread_id,
                role="assistant",
                content=preamble,
                metadata={"source": "slack"},
            )
            await slack_client.post_message_in_thread(
                bot_token,
                slack_channel_id,
                preamble,
                thread_ts=root_ts,
                blocks=_markdown_blocks(preamble),
                **persona,
            )

        card = build_approval_card(paused)
        posted = await slack_client.post_message_in_thread(
            bot_token,
            slack_channel_id,
            card["text"],
            thread_ts=root_ts,
            blocks=card["blocks"],
            **persona,
        )
        # Persist the Slack message coordinates onto the approvals row so
        # the interactive handler can chat.update the card on resolution.
        try:
            supabase.table("approvals").update(
                {
                    "slack_message_ts": posted.get("ts"),
                    "slack_channel_id": slack_channel_id,
                }
            ).eq("id", paused.get("approval_id")).execute()
        except Exception as e:
            print(f"[slack_runner] approval ts persist failed: {e!r}", flush=True)
        return

    final = preamble or "(no response)"
    if error_msg:
        final = f"Run failed: {error_msg}"

    _insert_message(
        supabase,
        thread_id=marcus_thread_id,
        role="assistant",
        content=final,
        metadata={"source": "slack"},
    )
    await slack_client.post_message_in_thread(
        bot_token,
        slack_channel_id,
        final,
        thread_ts=root_ts,
        blocks=_markdown_blocks(final),
        **persona,
    )


def _slack_team_for_channel(supabase: Any, slack_channel_id: str) -> str:
    """Look up the Slack team_id for a channel via slack_channels. Used by
    handle_resume to find the right install (bot token + scopes). Returns
    empty string on miss so _lookup_install short-circuits cleanly."""
    resp = (
        supabase.table("slack_channels")
        .select("slack_team_id")
        .eq("slack_channel_id", slack_channel_id)
        .limit(1)
        .execute()
    )
    return resp.data[0]["slack_team_id"] if resp.data else ""


# ── Lookup helpers ─────────────────────────────────────────────────────────

def _lookup_channel_mapping(supabase: Any, slack_channel_id: str) -> dict | None:
    """The "channel mapping" row for this Slack channel — the one with
    slack_thread_root_ts IS NULL. Tells us which agent + org owns it."""
    resp = (
        supabase.table("slack_channels")
        .select("org_id, agent_slug")
        .eq("slack_channel_id", slack_channel_id)
        .is_("slack_thread_root_ts", "null")
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _lookup_install(supabase: Any, slack_team_id: str) -> dict | None:
    """Bot token + granted scopes for this Slack workspace, by team_id.
    Scopes drive whether per-agent persona customization (username +
    icon_emoji) gets sent to chat.postMessage."""
    resp = (
        supabase.table("integrations")
        .select("access_token, scopes, org_id")
        .eq("provider", "slack")
        .filter("metadata->>team_id", "eq", slack_team_id)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def _resolve_marcus_thread(
    supabase: Any,
    *,
    org_id: str,
    agent_slug: str,
    slack_team_id: str,
    slack_channel_id: str,
    slack_thread_root_ts: str,
) -> str:
    """Find or create the Marcus thread for this Slack thread + agent.

    First time we see a given (channel, root_ts, agent) we mint a fresh
    Marcus thread UUID and persist the mapping; reply messages on the same
    Slack thread reuse it.

    agent_slug is PART OF THE KEY: a Marcus thread id is also the LangGraph
    checkpointer key, and every agent has a different graph — running two
    graphs over one checkpoint lineage corrupts state (an image posted into
    a Publisher thread would otherwise hand the Publisher's paused approval
    checkpoint to the Image Reader's graph, and later Publisher turns would
    inherit megabytes of base64 image blocks into every LLM call). One
    Slack thread can therefore map to two Marcus threads — one per graph
    that participated — which is the safe shape.
    """
    existing = (
        supabase.table("slack_channels")
        .select("marcus_thread_id")
        .eq("slack_channel_id", slack_channel_id)
        .eq("slack_thread_root_ts", slack_thread_root_ts)
        .eq("agent_slug", agent_slug)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0]["marcus_thread_id"]

    marcus_thread_id = str(uuid4())
    supabase.table("slack_channels").insert(
        {
            "org_id": org_id,
            "agent_slug": agent_slug,
            "slack_team_id": slack_team_id,
            "slack_channel_id": slack_channel_id,
            "slack_thread_root_ts": slack_thread_root_ts,
            "marcus_thread_id": marcus_thread_id,
        }
    ).execute()
    return marcus_thread_id


def _ensure_thread(
    supabase: Any,
    *,
    thread_id: str,
    org_id: str,
    user_id: str,
    title: str,
) -> None:
    """Idempotent upsert of a `threads` row, mirroring the orchestrator's
    _ensure_thread_row but with a Slack-flavored title and the resolved
    user_id attached so the web chat history surfaces it correctly."""
    try:
        supabase.table("threads").upsert(
            {
                "id": thread_id,
                "org_id": org_id,
                "user_id": user_id,
                "title": title,
                "status": "active",
            },
            on_conflict="id",
        ).execute()
    except Exception as e:
        # Non-fatal: if this fails the messages insert below will surface
        # the FK error with the real diagnostic.
        print(f"[slack_runner] _ensure_thread failed: {e!r}", flush=True)


def _insert_message(
    supabase: Any,
    *,
    thread_id: str,
    role: str,
    content: str,
    metadata: dict,
) -> None:
    try:
        supabase.table("messages").insert(
            {
                "thread_id": thread_id,
                "role": role,
                "content": content,
                "metadata": metadata,
            }
        ).execute()
    except Exception as e:
        # Persistence is best-effort; the user-visible reply still goes to
        # Slack. Log so we can spot if the chat history page misses runs.
        print(f"[slack_runner] message insert failed: {e!r}", flush=True)


def _markdown_blocks(text: str) -> list[dict]:
    """Wrap an agent reply in Slack's `markdown` Block Kit element so
    standard GitHub-flavored markdown (`**bold**`, `# headers`, bullet
    lists) renders correctly. Without this, Slack treats the text as
    `mrkdwn` (single-asterisk bold) and `**bold**` shows up as literal
    asterisks around the word.

    Slack's per-block text limit is 12000 chars. We chunk on paragraph
    boundaries to stay under that — agents shouldn't normally produce
    that much, but a transcript dump can.
    """
    LIMIT = 12000
    if len(text) <= LIMIT:
        return [{"type": "markdown", "text": text}]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > LIMIT:
        # Prefer to split on a double-newline near the limit; fall back to
        # a hard cut if there's no paragraph boundary in range.
        cut = remaining.rfind("\n\n", 0, LIMIT)
        if cut <= 0:
            cut = LIMIT
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return [{"type": "markdown", "text": c} for c in chunks]


def _parse_sse(line: str) -> dict | None:
    """The orchestrator's _sse() emits `data: {json}\\n\\n` strings. Parse
    one back into a dict so the runner can pattern-match on `type`."""
    line = line.strip()
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None
