"""
Content Agent review queue — Monday.com board + two-tier approval engine.

The product requirement: the whole review happens IN Monday ("no Slack, no
manual logins"). Kaydi (reviewer) approves/rejects each generated asset as
its own board item; Braden (owner) flips one FINAL item per video; on his
approval the pipeline advances to `approved` and Phase D publishes exactly
the reviewer-approved subset.

Three layers here:

  ensure_review_board  — one-time-per-org provisioning: a dedicated board,
                         an "Approval" status column (Pending Review /
                         Approved / Rejected), and a webhook back to our
                         API. Persisted in agents.config["monday_review"]
                         so the pipeline reuses it forever after.
  queue_for_review     — called by the queue_review graph node: creates one
                         Monday item per asset + the FINAL item, and mirrors
                         them into content_review_items for webhook lookup.
  apply_status_change  — called by the webhook router: maps a Monday label
                         flip on one item to a decision, rolls the decisions
                         up, and advances the pipeline ledger
                         (ready_for_review → approved | rejected).

All best-effort in the established Monday posture: an org without a Monday
connection records queue_review as done-with-note and the pipeline waits at
ready_for_review — assets are in the ledger, review just has no board to
live on yet.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from packages.agents.core.monday_tasks import _is_real_uuid, _resolve_access_token
from packages.integrations.context import current_supabase
from packages.integrations.monday import client as monday_client

log = logging.getLogger("content.review")

BOARD_NAME = "Content Agent — Review Queue"
APPROVAL_COLUMN_TITLE = "Approval"
LABEL_PENDING = "Pending Review"
LABEL_APPROVED = "Approved"
LABEL_REJECTED = "Rejected"
APPROVAL_LABELS = [LABEL_PENDING, LABEL_APPROVED, LABEL_REJECTED]

_KIND_PREFIX = {
    "audio": "[Audio]",
    "clip": "[Clip]",
    "podcast_episode": "[Podcast]",
    "post_copy": "[Post]",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _api_url() -> str:
    """Public base URL for webhook registration. Prefer the API's Settings
    (when running inside the FastAPI process); fall back to the env var so
    this module never hard-depends on the app package (agents also run
    under the standalone LangGraph server)."""
    try:
        from app.config import get_settings

        return get_settings().api_url
    except Exception:
        import os

        return os.environ.get("API_URL", "http://localhost:8000")


def decision_for_label(label: str | None) -> str | None:
    """Map a Monday status label to a review decision. Text-matched (case-
    insensitive) because webhook payloads carry label text and label indexes
    are Monday-internal. Unknown labels → None (ignore the event)."""
    normalized = (label or "").strip().lower()
    if normalized == LABEL_APPROVED.lower():
        return "approved"
    if normalized == LABEL_REJECTED.lower():
        return "rejected"
    if normalized == LABEL_PENDING.lower():
        return "pending"
    return None


def item_name_for_asset(asset: dict, index: int) -> str:
    """Human-scannable Monday item name for one asset."""
    prefix = _KIND_PREFIX.get(asset.get("kind") or "", "[Asset]")
    title = (
        asset.get("title")
        or asset.get("video_seo_title")
        or asset.get("url")
        or asset.get("storage_path")
        or f"#{index + 1}"
    )
    return f"{prefix} {title}"[:255]


def review_body_for_asset(asset: dict) -> str | None:
    """The update posted INSIDE the Monday item — the AI-drafted copy the
    reviewer tone-QAs in place. None means no update (nothing to QA)."""
    from packages.agents.content.copy import (
        clip_copy_markdown,
        episode_copy_markdown,
        post_copy_markdown,
    )

    kind = asset.get("kind")
    if kind == "clip":
        return clip_copy_markdown(asset.get("copy") or {}) if asset.get("copy") else None
    if kind == "podcast_episode":
        return episode_copy_markdown(asset)
    if kind == "post_copy":
        return post_copy_markdown(asset)
    if kind == "audio":
        return "Source audio for the podcast episode — approve to include it in the drop."
    return None


# ── Board provisioning ──────────────────────────────────────────────────────

async def ensure_review_board(org_id: str, *, api_url: str) -> dict | None:
    """Get-or-create the org's review board row (content_review_boards):

        {"org_id", "board_id", "status_column_id", "webhook_id", "webhook_secret"}

    Provisioning is STAGED and each stage persists before the next runs, so
    a failure at any point is resumed (not re-done from scratch) on the next
    pipeline — never forking duplicate boards or rotating a live secret:

      1. board created            → row persisted (with the minted secret)
      2. Approval column created  → row updated
      3. webhook registered       → row updated

    Ordering of (1) vs (3) is load-bearing: Monday POSTs the {"challenge"}
    handshake DURING create_webhook, and the webhook router validates the
    URL secret against this table — the secret must already be persisted or
    the challenge 404s and Monday refuses the subscription.

    Returns None when Monday isn't connected OR the provisioning-state read
    fails (a transient DB blip must not look like "unprovisioned org" — that
    path would create a duplicate board). Stored service-role-only: the
    secret is the webhook's sole authentication and must not be readable by
    org members (agents.config is — that's why it doesn't live there).
    """
    supabase = current_supabase.get()
    if supabase is None or not _is_real_uuid(org_id):
        return None
    token = _resolve_access_token(org_id, supabase)
    if not token:
        return None

    try:
        resp = (
            supabase.table("content_review_boards")
            .select("*")
            .eq("org_id", org_id)
            .limit(1)
            .execute()
        )
        row = dict(resp.data[0]) if resp.data else None
    except Exception as e:
        log.warning("review-board state read failed for org=%s — not provisioning: %r", org_id, e)
        return None

    if row and row.get("board_id") and row.get("status_column_id") and row.get("webhook_id"):
        return row

    # Stage 1: board + row (secret minted and persisted here, before any
    # webhook registration can trigger a challenge).
    if row is None:
        try:
            board = await monday_client.create_board(token, BOARD_NAME)
            board_id = str(board.get("id") or "")
            if not board_id:
                return None
            row = {
                "org_id": org_id,
                "board_id": board_id,
                "status_column_id": None,
                "webhook_id": None,
                "webhook_secret": _uuid.uuid4().hex,
            }
            supabase.table("content_review_boards").upsert(
                {**row, "updated_at": _now_iso()}, on_conflict="org_id"
            ).execute()
        except Exception as e:
            log.warning("Monday board provisioning failed for org=%s: %r", org_id, e)
            return None

    def _patch(fields: dict) -> None:
        supabase.table("content_review_boards").update(
            {**fields, "updated_at": _now_iso()}
        ).eq("org_id", org_id).execute()
        row.update(fields)

    # Stage 2: Approval status column.
    if not row.get("status_column_id"):
        try:
            column = await monday_client.create_status_column(
                token, row["board_id"], APPROVAL_COLUMN_TITLE, APPROVAL_LABELS
            )
            if column.get("id"):
                _patch({"status_column_id": str(column["id"])})
        except Exception as e:
            log.warning("Approval column creation failed for org=%s: %r", org_id, e)

    # Stage 3: webhook subscription (retried each run until it sticks —
    # e.g. first attempts from a non-public localhost API will fail).
    if not row.get("webhook_id"):
        secret = row["webhook_secret"]
        webhook_url = f"{api_url.rstrip('/')}/api/webhooks/monday/{org_id}/{secret}"
        try:
            webhook = await monday_client.create_webhook(token, row["board_id"], webhook_url)
            if webhook.get("id"):
                _patch({"webhook_id": str(webhook["id"])})
        except Exception as e:
            log.warning("Monday webhook registration failed for org=%s: %r", org_id, e)

    return row


# ── Item creation (queue_review node) ───────────────────────────────────────

async def queue_for_review(
    org_id: str,
    *,
    video_id: str,
    video_title: str | None,
    assets: list[dict],
) -> str:
    """Drop every asset + the FINAL gate item onto the review board and
    mirror them into content_review_items. Returns a human detail string for
    the queue_review stage ledger entry ("5 item(s) on Monday" / why not).
    """
    supabase = current_supabase.get()
    if supabase is None or not _is_real_uuid(org_id):
        return "review board unavailable in dev mode"

    board_cfg = await ensure_review_board(org_id, api_url=_api_url())
    if not board_cfg:
        return "Monday not connected — assets await review in the ledger only"

    token = _resolve_access_token(org_id, supabase)
    if not token:
        return "Monday not connected — assets await review in the ledger only"

    status_col = board_cfg.get("status_column_id")
    column_values = {status_col: {"label": LABEL_PENDING}} if status_col else {}

    # Void the PREVIOUS run's review items for this video before creating
    # new ones. Stale rows are dangerous, not just untidy: a flip on an old
    # item would write approved/rejected into the NEW assets array at a
    # stale index, and an old [FINAL] item would remain a second live gate.
    # Deleted rows make old Monday items inert (webhook lookup misses).
    try:
        (
            supabase.table("content_review_items")
            .delete()
            .eq("org_id", org_id)
            .eq("video_id", video_id)
            .execute()
        )
    except Exception as e:
        log.warning("stale review-item cleanup failed for video %s: %r", video_id, e)

    pipeline_id = None
    try:
        r = (
            supabase.table("content_pipelines")
            .select("id")
            .eq("org_id", org_id)
            .eq("video_id", video_id)
            .limit(1)
            .execute()
        )
        pipeline_id = r.data[0]["id"] if r.data else None
    except Exception:
        pass

    created = 0
    rows: list[dict] = []
    for idx, asset in enumerate(assets):
        try:
            item = await monday_client.create_item(
                token,
                board_cfg["board_id"],
                item_name_for_asset(asset, idx),
                column_values=column_values,
            )
        except Exception as e:
            log.warning("Monday item create failed (asset %d, video %s): %r", idx, video_id, e)
            continue
        if not item.get("id"):
            continue
        created += 1
        # Post the AI-drafted copy into the item so tone-QA happens on the
        # board itself. Best-effort — a missing update never blocks review.
        body = review_body_for_asset(asset)
        if body:
            try:
                await monday_client.add_update(token, str(item["id"]), body)
            except Exception as e:
                log.warning("Monday update post failed for item %s: %r", item.get("id"), e)
        rows.append({
            "org_id": org_id,
            "pipeline_id": pipeline_id,
            "video_id": video_id,
            "board_id": str(board_cfg["board_id"]),
            "monday_item_id": str(item["id"]),
            "role": "asset",
            "asset_index": idx,
            "kind": asset.get("kind"),
        })

    # The owner's gate: one FINAL item per video. Created LAST so the board
    # reads top-down as assets-then-gate.
    try:
        final_item = await monday_client.create_item(
            token,
            board_cfg["board_id"],
            f"[FINAL] Publish drop — {video_title or video_id}"[:255],
            column_values=column_values,
        )
        if final_item.get("id"):
            created += 1
            rows.append({
                "org_id": org_id,
                "pipeline_id": pipeline_id,
                "video_id": video_id,
                "board_id": str(board_cfg["board_id"]),
                "monday_item_id": str(final_item["id"]),
                "role": "final",
                "asset_index": None,
                "kind": "final_approval",
            })
    except Exception as e:
        log.warning("Monday FINAL item create failed for video %s: %r", video_id, e)

    if rows:
        try:
            supabase.table("content_review_items").upsert(
                rows, on_conflict="org_id,monday_item_id"
            ).execute()
        except Exception as e:
            log.warning("content_review_items insert failed for video %s: %r", video_id, e)

    if not created:
        return "Monday item creation failed — assets await review in the ledger only"
    return f"{created} review item(s) on Monday board {board_cfg['board_id']}"


# ── Decision engine (webhook path) ──────────────────────────────────────────

def apply_status_change(
    supabase: Any,
    org_id: str,
    *,
    monday_item_id: str,
    label: str | None,
) -> dict | None:
    """Record one Monday status flip and advance the pipeline if warranted.

    Rules:
      - Asset item approved/rejected → record the reviewer's decision (and
        mirror it onto the pipeline's asset entry as `approved: bool`).
      - FINAL item approved → pipeline status `approved` (Phase D's publish
        gate keys off this; only reviewer-approved assets ship).
      - FINAL item rejected → pipeline status `rejected` — the drop is dead.
      - Flipping anything back to Pending Review reopens that decision.

    Returns {"role", "decision", "video_id"} for the router's log line, or
    None when the item is unknown / the label isn't one of ours.
    """
    decision = decision_for_label(label)
    if decision is None:
        return None

    resp = (
        supabase.table("content_review_items")
        .select("*")
        .eq("org_id", org_id)
        .eq("monday_item_id", str(monday_item_id))
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    item = resp.data[0]
    video_id = item["video_id"]

    supabase.table("content_review_items").update({
        "decision": decision,
        "decided_at": None if decision == "pending" else _now_iso(),
        "updated_at": _now_iso(),
    }).eq("org_id", org_id).eq("monday_item_id", str(monday_item_id)).execute()

    if item.get("role") == "asset" and item.get("asset_index") is not None:
        _mirror_asset_decision(supabase, org_id, video_id, item["asset_index"], decision)

    if item.get("role") == "final":
        _advance_final_gate(supabase, org_id, video_id, decision)

    return {"role": item.get("role"), "decision": decision, "video_id": video_id}


# Allowed FINAL-gate transitions: {decision: (allowed current statuses, new status)}.
# Anything outside these is ignored — a FINAL flip must never rewind a drop
# that's already publishing/published (double-publish hazard) or stamp
# 'approved' over a re-run that's still mid-processing.
_FINAL_TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    # approved-from-failed is the RETRY path: a total publish failure parks
    # the row at failed; the owner re-flips FINAL to Approved to try again.
    "approved": (("ready_for_review", "rejected", "failed"), "approved"),
    "rejected": (("ready_for_review", "approved"), "rejected"),
    "pending": (("approved", "rejected"), "ready_for_review"),
}


def _advance_final_gate(supabase: Any, org_id: str, video_id: str, decision: str) -> None:
    """Apply the owner's FINAL decision to the pipeline, guarded by the
    current status. Direct writes with the caller's client — the webhook
    router runs outside any request context, so the ContextVar-based tools
    helper would silently no-op here."""
    allowed, new_status = _FINAL_TRANSITIONS[decision]
    try:
        resp = (
            supabase.table("content_pipelines")
            .select("status")
            .eq("org_id", org_id)
            .eq("video_id", video_id)
            .limit(1)
            .execute()
        )
        current = resp.data[0].get("status") if resp.data else None
        if current not in allowed:
            log.info(
                "FINAL %s ignored for %s: pipeline is %r (allowed from %s)",
                decision, video_id, current, allowed,
            )
            return
        patch: dict[str, Any] = {
            "status": new_status,
            "updated_at": _now_iso(),
            # Re-approval / reopening clears the prior rejection note.
            "error": "rejected at final approval" if decision == "rejected" else None,
        }
        # CAS, not just check-then-write: the WHERE re-asserts an allowed
        # current status so a concurrent transition (e.g. run_publish's
        # approved→publishing claim between our select and this update)
        # makes this a no-op instead of stamping over a live publish.
        (
            supabase.table("content_pipelines")
            .update(patch)
            .eq("org_id", org_id)
            .eq("video_id", video_id)
            .in_("status", list(allowed))
            .execute()
        )
    except Exception as e:
        log.warning("FINAL gate write failed for %s → %s: %r", video_id, decision, e)


def _mirror_asset_decision(
    supabase: Any, org_id: str, video_id: str, asset_index: int, decision: str
) -> None:
    """Stamp `approved: True/False` (or clear it) onto the pipeline row's
    asset entry so Phase D publishes exactly the reviewer-approved subset
    without re-joining against content_review_items."""
    try:
        resp = (
            supabase.table("content_pipelines")
            .select("assets")
            .eq("org_id", org_id)
            .eq("video_id", video_id)
            .limit(1)
            .execute()
        )
        assets = (resp.data[0].get("assets") if resp.data else None) or []
        if not (0 <= asset_index < len(assets)):
            return
        if decision == "pending":
            assets[asset_index].pop("approved", None)
        else:
            assets[asset_index]["approved"] = decision == "approved"
        supabase.table("content_pipelines").update(
            {"assets": assets, "updated_at": _now_iso()}
        ).eq("org_id", org_id).eq("video_id", video_id).execute()
    except Exception as e:
        log.warning("asset decision mirror failed for %s[%d]: %r", video_id, asset_index, e)
