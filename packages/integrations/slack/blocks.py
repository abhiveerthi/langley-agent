"""Block Kit builders for approval cards.

When an agent run pauses at an approval gate, the Slack runner posts one
of these cards into the same Slack thread the user is chatting in. The
card has Approve / Reject buttons; clicks land at /api/slack/interactive
which resumes the run via the existing orchestrator entry points.

Action layout per agent (currently Publisher-specific; Brand Manager
will add `send_email` here when its Phase C wiring lands):

  - youtube_metadata_update: shows proposed title + description + tags
  - x_post:                  shows proposed tweet + char count

Slack constraints baked in:
  - Section `text` ≤ 3000 chars (we truncate descriptions to fit).
  - `action_id` ≤ 255 chars; `value` ≤ 2000 chars. We carry `approval_id`
    in `value` and keep `action_id` short (`approve` / `reject`).
"""
from __future__ import annotations

from typing import Any

# Section text limit per Slack Block Kit. Beyond this Slack rejects the
# whole post with `invalid_blocks`, so we have to truncate proactively.
_MAX_SECTION_TEXT = 3000


def build_approval_card(approval: dict) -> dict:
    """Build a Block Kit message for an approval `waiting_approval` event.

    `approval` has the shape orchestrator emits:
        {approval_id, thread_id, agent_slug, action_type, preview, payload}

    Returns a dict ready to splat into `chat.postMessage`:
        {"blocks": [...], "text": "..."}

    `text` is the fallback for notifications + accessibility — Slack
    requires it even when blocks are present.
    """
    action_type = approval.get("action_type") or "unknown"
    approval_id = approval.get("approval_id") or ""
    preview = approval.get("preview") or "An agent action is waiting for review."
    payload = approval.get("payload") or {}

    if action_type == "youtube_metadata_update":
        detail_blocks = _youtube_metadata_blocks(payload)
        header_text = "📺 Approval needed — YouTube metadata"
    elif action_type == "x_post":
        detail_blocks = _x_post_blocks(payload)
        header_text = "🐦 Approval needed — X post"
    else:
        # Generic fallback so unknown action_types still render *something*.
        detail_blocks = [_section(f"Action: `{action_type}`")]
        header_text = "Approval needed"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        _section(_truncate(preview, _MAX_SECTION_TEXT)),
        {"type": "divider"},
        *detail_blocks,
        {"type": "divider"},
        _action_buttons(approval_id),
    ]
    return {"blocks": blocks, "text": preview}


def build_resolution_card(
    *,
    original_card: dict,
    decision: str,
    reviewer_user_id: str,
    feedback: str | None = None,
) -> dict:
    """Build the post-resolution form of an approval card. Called when
    Slack receives an Approve/Reject click; we `chat.update` the original
    card so the buttons disappear and the row reads as resolved.

    Strips the action buttons + replaces them with a context block stating
    who decided and (for rejections) what feedback was given.
    """
    blocks = list(original_card.get("blocks") or [])
    # Trim trailing divider + action buttons (the last 2 blocks we added
    # in build_approval_card). If the shape doesn't match, leave alone.
    if (
        len(blocks) >= 2
        and blocks[-1].get("type") == "actions"
        and blocks[-2].get("type") == "divider"
    ):
        blocks = blocks[:-2]

    if decision == "approved":
        verdict = f":white_check_mark: Approved by <@{reviewer_user_id}>"
    elif decision == "rejected":
        if feedback:
            verdict = (
                f":x: Rejected by <@{reviewer_user_id}> — _{_truncate(feedback, 500)}_"
            )
        else:
            verdict = f":x: Rejected by <@{reviewer_user_id}>"
    else:
        verdict = f"Resolved by <@{reviewer_user_id}>"

    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": verdict}],
        }
    )
    return {"blocks": blocks, "text": verdict}


def build_reject_modal(approval_id: str) -> dict:
    """`views.open` payload for the Reject feedback modal. The modal's
    private_metadata carries approval_id back to the view_submission
    handler so we know which run to resume."""
    return {
        "type": "modal",
        "callback_id": "reject_with_feedback",
        "private_metadata": approval_id,
        "title": {"type": "plain_text", "text": "Reject with feedback"},
        "submit": {"type": "plain_text", "text": "Send"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "feedback_block",
                "label": {
                    "type": "plain_text",
                    "text": "What needs to change?",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "feedback",
                    "multiline": True,
                    "max_length": 1000,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. Title is too clickbait — go more direct",
                    },
                },
                "optional": False,
            }
        ],
    }


# ── Per-action detail blocks ──────────────────────────────────────────────

def _youtube_metadata_blocks(payload: dict) -> list[dict]:
    title = payload.get("proposed_title") or "(no title)"
    description = payload.get("proposed_description") or ""
    tags = payload.get("proposed_tags") or []
    blocks: list[dict] = [
        _section(f"*Title*\n{_truncate(title, 200)}"),
    ]
    if description:
        blocks.append(_section(f"*Description*\n{_truncate(description, 1500)}"))
    if tags:
        # Format tags as inline backticks; truncate the whole list.
        tag_str = ", ".join(f"`{t}`" for t in tags)
        blocks.append(_section(f"*Tags*\n{_truncate(tag_str, 800)}"))
    return blocks


def _x_post_blocks(payload: dict) -> list[dict]:
    tweet = payload.get("proposed_tweet") or ""
    char_count = payload.get("tweet_char_count") or len(tweet)
    return [
        _section(f"*Tweet ({char_count} chars)*\n{_truncate(tweet, 1500)}"),
    ]


# ── Helpers ────────────────────────────────────────────────────────────────

def _section(markdown_text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": markdown_text}}


def _action_buttons(approval_id: str) -> dict:
    return {
        "type": "actions",
        "block_id": "approval_actions",
        "elements": [
            {
                "type": "button",
                "action_id": "approve",
                "style": "primary",
                "text": {"type": "plain_text", "text": "Approve"},
                "value": approval_id,
            },
            {
                "type": "button",
                "action_id": "reject",
                "style": "danger",
                "text": {"type": "plain_text", "text": "Reject"},
                "value": approval_id,
            },
        ],
    }


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
