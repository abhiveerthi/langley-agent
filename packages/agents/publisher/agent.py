"""
Publisher agent — packages YouTube videos into shippable metadata + social kits.

Six graph paths, chosen by `state.intent`:

  - create_package    : fetch video context → generate kit → extract structured → persist
  - regenerate_field  : load package → regenerate one field → persist (that field only)
  - push_metadata     : load package → prepare diff → [interrupt: approval_gate] →
                          approved: update_video_metadata → mark package pushed
                          rejected: revise_metadata → approval_gate (loop)
  - push_x            : load package → prepare tweet → [interrupt] → post_to_x → mark
  - push_newsletter   : load package → prepare email → [interrupt] → send_via_gmail → mark
  - general           : ReAct loop over the OAuth-backed tools for Q&A, SEO research

The orchestrator pre-sets `state.intent`, `state.video_id`, `state.package_id`, and
`state.regen_field` when the Publisher API router kicks off a run via a one-click
action. If those aren't set (i.e. a free-form chat message), classify_intent falls
back to an LLM classifier and routes accordingly.

Mirrors Brand Manager's interrupt-before pattern for HITL approval.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.publisher.tools import (
    get_video_details,
    get_video_transcript,
    get_video_comments,
    get_latest_upload,
    update_video_metadata,
    post_tweet,
    get_publisher_tools,
)
from packages.integrations.context import current_supabase


# Valid intents — treat anything else as "general".
VALID_INTENTS = {
    "create_package",
    "regenerate_field",
    "push_metadata",
    "push_x",
    "push_newsletter",
    "general",
}


class PublisherState(BaseAgentState):
    """Extended state for the Publisher workflow."""
    # Intent routing
    intent: str | None

    # Shared context across all flows
    video_id: str | None
    video_title: str | None
    package_id: str | None

    # Create-package flow
    transcript: str | None
    video_details: str | None
    comments: str | None
    draft_markdown: str | None
    structured: dict | None

    # Regenerate-field flow
    regen_field: str | None
    regen_value: Any
    regen_feedback: str | None

    # Push-metadata flow
    existing_package: dict | None
    selected_title: str | None
    proposed_title: str | None
    proposed_description: str | None
    proposed_tags: list | None
    current_title: str | None
    current_description: str | None
    current_tags: list | None
    approval_status: str | None
    feedback: str | None
    push_result: str | None

    # Push-X (Twitter) flow
    proposed_tweet: str | None
    x_push_result: str | None
    x_tweet_id: str | None

    # Push-newsletter (Gmail) flow
    proposed_newsletter_subject: str | None
    proposed_newsletter_body: str | None
    newsletter_recipient: str | None
    newsletter_push_result: str | None
    newsletter_message_id: str | None

    # Degraded-state marker, surfaced into publisher_packages.warning
    warning: str | None


class PublisherAgent(BaseAgent):
    slug = "publisher"
    name = "Publisher"
    description = (
        "Packages YouTube videos end-to-end: titles, descriptions, tags, chapters, "
        "thumbnail ideas, and social drafts (Twitter + newsletter). Pushes to "
        "YouTube, posts to X, and sends the newsletter via the connected Gmail "
        "account — all gated behind explicit approval."
    )
    model = "claude-sonnet-4-6"

    @property
    def interrupt_before_nodes(self) -> list[str]:
        return ["approval_gate"]

    def get_approval_request(self, state: dict) -> dict | None:
        """Approval card payload surfaced when `approval_gate` pauses the graph."""
        intent = state.get("intent")
        title = state.get("video_title") or state.get("video_id") or "video"
        if intent == "push_metadata":
            return {
                "action_type": "youtube_metadata_update",
                "action_payload": {
                    "package_id": state.get("package_id"),
                    "video_id": state.get("video_id"),
                    "proposed_title": state.get("proposed_title"),
                    "proposed_description": state.get("proposed_description"),
                    "proposed_tags": state.get("proposed_tags") or [],
                    "current_title": state.get("current_title"),
                    "current_description": state.get("current_description"),
                    "current_tags": state.get("current_tags") or [],
                },
                "preview": f"Push metadata to YouTube: {title}"[:500],
            }
        if intent == "push_x":
            tweet = state.get("proposed_tweet") or ""
            return {
                "action_type": "x_post",
                "action_payload": {
                    "package_id": state.get("package_id"),
                    "video_id": state.get("video_id"),
                    "proposed_tweet": tweet,
                    "tweet_char_count": len(tweet),
                },
                "preview": f"Post to X: {tweet[:80]}…" if len(tweet) > 80 else f"Post to X: {tweet}",
            }
        if intent == "push_newsletter":
            subject = state.get("proposed_newsletter_subject") or ""
            body = state.get("proposed_newsletter_body") or ""
            recipient = state.get("newsletter_recipient") or ""
            return {
                "action_type": "send_newsletter",
                "action_payload": {
                    "package_id": state.get("package_id"),
                    "video_id": state.get("video_id"),
                    "to": recipient,
                    "subject": subject,
                    "body": body,
                    "body_word_count": len(body.split()) if body else 0,
                },
                "preview": f"Send newsletter to {recipient}: {subject}"[:500],
            }
        return None

    def __init__(self):
        self.tools = get_publisher_tools()
        # Tool-bound LLM for the general ReAct branch. Plain LLM for the
        # deterministic create/regen/push nodes (they don't need tool use).
        self.llm_with_tools = ChatAnthropic(model=self.model).bind_tools(self.tools)
        self.llm = ChatAnthropic(model=self.model)
        self.tool_node = ToolNode(self.tools)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(PublisherState)

        graph.add_node("load_profile", self._load_profile_node)
        graph.add_node("classify_intent", self._classify_intent_node)

        # create_package branch
        graph.add_node("fetch_video_context", self._fetch_video_context_node)
        graph.add_node("generate_kit", self._generate_kit_node)
        graph.add_node("extract_structured", self._extract_structured_node)
        graph.add_node("persist_package", self._persist_package_node)

        # regenerate_field branch
        graph.add_node("load_package", self._load_package_node)
        graph.add_node("regenerate_field", self._regenerate_field_node)
        graph.add_node("persist_regen", self._persist_regen_node)

        # push_metadata branch
        graph.add_node("prepare_push", self._prepare_push_node)
        graph.add_node("approval_gate", self._approval_gate_node)
        graph.add_node("push_metadata", self._push_metadata_node)
        graph.add_node("mark_pushed", self._mark_pushed_node)
        graph.add_node("revise_metadata", self._revise_metadata_node)

        # push_x branch (X / Twitter post). Reuses approval_gate.
        graph.add_node("prepare_x_push", self._prepare_x_push_node)
        graph.add_node("post_to_x", self._post_to_x_node)
        graph.add_node("mark_x_pushed", self._mark_x_pushed_node)
        graph.add_node("revise_tweet", self._revise_tweet_node)

        # push_newsletter branch (Gmail send). Reuses approval_gate.
        graph.add_node("prepare_newsletter_push", self._prepare_newsletter_push_node)
        graph.add_node("send_newsletter", self._send_newsletter_node)
        graph.add_node("mark_newsletter_sent", self._mark_newsletter_sent_node)
        graph.add_node("revise_newsletter", self._revise_newsletter_node)

        # general branch (ReAct)
        graph.add_node("react_agent", self._react_agent_node)
        graph.add_node("react_tools", self.tool_node)

        graph.add_node("respond", self._respond_node)

        # ── Edges ──────────────────────────────────────────────────────────
        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "classify_intent")

        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
            {
                "create_package": "fetch_video_context",
                "regenerate_field": "load_package",
                "push_metadata": "load_package",
                "push_x": "load_package",
                "push_newsletter": "load_package",
                "general": "react_agent",
            },
        )

        # create_package: fetch → generate → extract → persist → respond
        graph.add_edge("fetch_video_context", "generate_kit")
        graph.add_edge("generate_kit", "extract_structured")
        graph.add_edge("extract_structured", "persist_package")
        graph.add_edge("persist_package", "respond")

        # load_package fan-out: regen vs push (YouTube) vs push (X) vs push (newsletter)
        graph.add_conditional_edges(
            "load_package",
            self._route_after_load,
            {
                "regenerate_field": "regenerate_field",
                "push_metadata": "prepare_push",
                "push_x": "prepare_x_push",
                "push_newsletter": "prepare_newsletter_push",
            },
        )

        # regenerate_field: regen → persist → respond
        graph.add_edge("regenerate_field", "persist_regen")
        graph.add_edge("persist_regen", "respond")

        # All three push lanes (metadata / X / newsletter) flow through the
        # same approval_gate; the post-gate split is intent-aware so a
        # YouTube push doesn't accidentally fire a tweet or send an email.
        graph.add_edge("prepare_push", "approval_gate")
        graph.add_edge("prepare_x_push", "approval_gate")
        graph.add_edge("prepare_newsletter_push", "approval_gate")
        graph.add_conditional_edges(
            "approval_gate",
            self._route_by_approval,
            {
                "approved_push_metadata": "push_metadata",
                "approved_push_x": "post_to_x",
                "approved_push_newsletter": "send_newsletter",
                "rejected_push_metadata": "revise_metadata",
                "rejected_push_x": "revise_tweet",
                "rejected_push_newsletter": "revise_newsletter",
            },
        )
        graph.add_edge("push_metadata", "mark_pushed")
        graph.add_edge("mark_pushed", "respond")
        graph.add_edge("revise_metadata", "approval_gate")
        graph.add_edge("post_to_x", "mark_x_pushed")
        graph.add_edge("mark_x_pushed", "respond")
        graph.add_edge("revise_tweet", "approval_gate")
        graph.add_edge("send_newsletter", "mark_newsletter_sent")
        graph.add_edge("mark_newsletter_sent", "respond")
        graph.add_edge("revise_newsletter", "approval_gate")

        # general ReAct sub-loop: react_agent ↔ react_tools; exits on no tool_calls
        graph.add_conditional_edges(
            "react_agent",
            self._should_use_tools,
            {"tools": "react_tools", "end": "respond"},
        )
        graph.add_edge("react_tools", "react_agent")

        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: PublisherState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    def _last_user_text(self, state: PublisherState) -> str:
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        return last_human.content if last_human else ""

    def _strip_json_fences(self, text: str) -> str:
        t = text.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else t
        if t.endswith("```"):
            t = t.rsplit("```", 1)[0]
        return t.strip().lstrip("json").strip()

    # ── Routers ────────────────────────────────────────────────────────────
    def _route_by_intent(self, state: PublisherState) -> str:
        intent = (state.get("intent") or "general").lower()
        return intent if intent in VALID_INTENTS else "general"

    def _route_after_load(self, state: PublisherState) -> str:
        return state.get("intent") or "push_metadata"

    def _route_by_approval(self, state: PublisherState) -> str:
        status = (state.get("approval_status") or "approved").lower()
        intent = state.get("intent") or "push_metadata"
        # Three push lanes hit this gate; everything else defaults to the
        # YouTube metadata lane (the original gated path).
        if intent == "push_x":
            lane = "push_x"
        elif intent == "push_newsletter":
            lane = "push_newsletter"
        else:
            lane = "push_metadata"
        outcome = "rejected" if status == "rejected" else "approved"
        return f"{outcome}_{lane}"

    def _should_use_tools(self, state: PublisherState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return "end"

    # ── Node: load per-tenant profile ─────────────────────────────────────
    async def _load_profile_node(self, state: PublisherState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    # ── Node: classify intent (LLM fallback) ──────────────────────────────
    async def _classify_intent_node(self, state: PublisherState):
        # If the orchestrator pre-set intent (one-click action), keep it.
        if state.get("intent"):
            return {}
        profile = self._profile(state)
        prompt = render("publisher", "classify.j2", profile=profile)
        try:
            # `marcus:silent` keeps the classifier's bare-slug response out of
            # the chat stream — see graph_orchestrator on_chat_model_stream filter.
            response = await self.llm.with_config(tags=["marcus:silent"]).ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=self._last_user_text(state)),
            ])
            intent = response.content.strip().strip("`").lower()
        except Exception:
            intent = "general"
        if intent not in VALID_INTENTS:
            intent = "general"
        return {"intent": intent}

    # ── create_package: fetch details / transcript / comments ─────────────
    async def _fetch_video_context_node(self, state: PublisherState):
        vid = state.get("video_id")
        title_from_latest: str | None = None

        # No explicit video_id (free-form chat like "package my latest" or just
        # "make a kit for the new one"). Publisher's PRODUCT spec says this is
        # the "latest upload" entry point — call get_latest_upload, parse the
        # video_id out of its text response, and continue with that. If the
        # tool errors (YouTube not connected, no uploads), bail with the same
        # warning the FE renders today so the user knows to attach a video.
        if not vid:
            latest = await _safe_tool(get_latest_upload, {})
            vid, title_from_latest = _parse_latest_upload(latest)
            if not vid:
                # Surface a friendlier message than the raw tool error.
                msg = "no video_id supplied"
                if latest and latest.startswith("Error"):
                    msg = latest[: 200]
                elif latest and latest.startswith("No videos"):
                    msg = "no videos on the connected channel yet"
                return {"warning": msg}

        # Pull these sequentially so we can attribute failures to the right source.
        details = await _safe_tool(get_video_details, {"video_id": vid})
        transcript = await _safe_tool(get_video_transcript, {"video_id": vid})
        comments = await _safe_tool(
            get_video_comments, {"video_id": vid, "max_comments": 20}
        )

        warning = None
        if transcript and transcript.lower().startswith("no captions"):
            warning = "transcript not yet available"
        elif transcript and transcript.startswith("Error"):
            warning = "transcript fetch failed"

        # Seed video_title from details if we don't have it yet.
        title = state.get("video_title")
        if not title and details and details.startswith("# "):
            title = details.split("\n", 1)[0].removeprefix("# ").strip()
        if not title and title_from_latest:
            title = title_from_latest

        return {
            # Propagate the resolved video_id so downstream nodes (persist,
            # storage export, respond) see the same value the user implicitly
            # asked for via "my latest".
            "video_id": vid,
            "video_details": details,
            "transcript": transcript,
            "comments": comments,
            "video_title": title,
            "warning": warning,
        }

    # ── create_package: generate the free-form kit ────────────────────────
    async def _generate_kit_node(self, state: PublisherState):
        profile = self._profile(state)
        transcript = state.get("transcript") or ""
        details = state.get("video_details") or ""
        context = (
            f"CURRENT VIDEO (from YouTube):\n{details or '(unavailable)'}\n\n"
            f"TRANSCRIPT:\n{transcript[:18000] if transcript else '(unavailable)'}\n\n"
            f"TOP COMMENTS:\n{state.get('comments') or '(none)'}"
        )
        prompt = render("publisher", "generate.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        content = response.content if isinstance(response.content, str) else _flatten_content(response.content)
        # Dev diagnostic — print the first 400 chars so uvicorn logs show whether
        # the model actually produced a kit.
        print(
            f"[publisher.generate_kit] video={state.get('video_id')} "
            f"transcript_len={len(transcript)} details_len={len(details)} "
            f"draft_len={len(content)} draft_head={content[:400]!r}",
            flush=True,
        )
        return {"draft_markdown": content}

    # ── create_package: extract into structured JSON ──────────────────────
    async def _extract_structured_node(self, state: PublisherState):
        profile = self._profile(state)
        prompt = render("publisher", "extract.j2", profile=profile)
        draft = state.get("draft_markdown") or ""

        async def _attempt() -> tuple[dict | None, str]:
            # Internal JSON extraction — never streamed to chat.
            response = await self.llm.with_config(tags=["marcus:silent"]).ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=draft),
            ])
            raw = response.content if isinstance(response.content, str) else _flatten_content(response.content)
            cleaned = self._strip_json_fences(raw)
            try:
                return json.loads(cleaned), cleaned
            except Exception:
                return None, cleaned

        parsed, raw_json = await _attempt()
        if parsed is None:
            parsed, raw_json = await _attempt()  # one retry

        print(
            f"[publisher.extract_structured] video={state.get('video_id')} "
            f"draft_len={len(draft)} parsed={parsed is not None} "
            f"raw_head={raw_json[:300]!r}",
            flush=True,
        )

        if parsed is None:
            return {
                "structured": {},
                "warning": _append_warning(state.get("warning"), "extraction returned invalid JSON"),
            }

        # Light normalization to match the DB column types.
        structured = {
            "title_variants": _as_str_list(parsed.get("title_variants")),
            "description": str(parsed.get("description") or ""),
            "tags": _as_str_list(parsed.get("tags")),
            "chapters": _as_chapters(parsed.get("chapters")),
            "thumbnail_ideas": _as_str_list(parsed.get("thumbnail_ideas")),
            "social": _as_social(parsed.get("social")),
        }
        return {"structured": structured}

    # ── create_package: upsert into publisher_packages ────────────────────
    async def _persist_package_node(self, state: PublisherState):
        supabase = current_supabase.get()
        org_id = state.get("org_id")
        if supabase is None or not org_id:
            return {}

        # No video_id = the user is chatting with Publisher generically (no
        # video attached). The `publisher_packages.video_id` column is
        # NOT NULL, so attempting the upsert would 23502 and the agent
        # would surface "persist failed: …" in chat. Skip persistence —
        # the kit still lives in the conversation history (which IS persisted
        # via the chat message rows), and the user can revisit it there.
        if not state.get("video_id"):
            return {}

        structured = state.get("structured") or {}
        title_variants = structured.get("title_variants") or []
        description = structured.get("description") or ""
        tags = structured.get("tags") or []
        chapters = structured.get("chapters") or []
        thumbnail_ideas = structured.get("thumbnail_ideas") or []
        social = structured.get("social") or {}

        # Flag a clear warning when EVERY field came back empty so the UI shows
        # something actionable instead of silently landing on a blank "draft".
        warning = state.get("warning")
        all_empty = (
            not title_variants and not description and not tags
            and not chapters and not thumbnail_ideas
            and not (
                social.get("twitter")
                or social.get("newsletter")
                or social.get("newsletter_subject")
                or social.get("newsletter_body")
            )
        )
        if all_empty:
            warning = _append_warning(warning, "agent produced empty kit — check transcript + retry")

        row = {
            "org_id": org_id,
            "video_id": state.get("video_id"),
            "video_title": state.get("video_title") or state.get("video_id") or "(untitled)",
            "status": "draft",
            "title_variants": title_variants,
            "description": description,
            "tags": tags,
            "chapters": chapters,
            "thumbnail_ideas": thumbnail_ideas,
            "social": social,
            "warning": warning,
            "updated_at": _now_iso(),
        }
        try:
            resp = (
                supabase.table("publisher_packages")
                .upsert(row, on_conflict="org_id,video_id")
                .execute()
            )
            saved = resp.data[0] if resp.data else {}
            package_id = saved.get("id") or state.get("package_id")
        except Exception as e:
            return {"warning": f"persist failed: {e}"[:500]}

        # Drop a JSON snapshot of the kit into Storage Library so the creator
        # can browse old packages at /app/storage even after they've pushed
        # to YouTube. The DB row is the live record; this is the archival
        # copy. Best-effort — does not affect the user-facing flow.
        import json as _json
        from packages.agents.core.storage_export import export_to_storage

        export_payload = {
            "video_id": row["video_id"],
            "video_title": row["video_title"],
            "title_variants": title_variants,
            "description": description,
            "tags": tags,
            "chapters": chapters,
            "thumbnail_ideas": thumbnail_ideas,
            "social": social,
            "warning": warning,
        }
        safe_video_id = row["video_id"] or "package"
        await export_to_storage(
            org_id=org_id,
            agent_slug=self.slug,
            kind="package",
            filename=f"{safe_video_id}-package.json",
            content=_json.dumps(export_payload, indent=2, ensure_ascii=False),
            mime_type="application/json",
            source_id=package_id,
            tags=[safe_video_id],
        )

        return {"package_id": package_id}

    # ── regen + push: load an existing package ────────────────────────────
    async def _load_package_node(self, state: PublisherState):
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        if supabase is None or not pkg_id:
            return {"existing_package": None}
        try:
            resp = (
                supabase.table("publisher_packages")
                .select("*")
                .eq("id", pkg_id)
                .limit(1)
                .execute()
            )
            row = resp.data[0] if resp.data else None
        except Exception:
            row = None
        if not row:
            return {"existing_package": None}
        return {
            "existing_package": row,
            "video_id": row.get("video_id"),
            "video_title": row.get("video_title"),
        }

    # ── regenerate_field branch ───────────────────────────────────────────
    async def _regenerate_field_node(self, state: PublisherState):
        profile = self._profile(state)
        field = state.get("regen_field") or ""
        pkg = state.get("existing_package") or {}
        feedback = state.get("regen_feedback") or ""

        # If user provided feedback in the message itself, fall back to it.
        if not feedback and state.get("messages"):
            feedback = self._last_user_text(state)

        prompt = render("publisher", "regenerate.j2", profile=profile, field=field)
        context = (
            f"EXISTING PACKAGE (JSON):\n{json.dumps(pkg, default=str)[:6000]}\n\n"
            f"TRANSCRIPT:\n{(state.get('transcript') or pkg.get('description') or '(unavailable)')[:10000]}\n\n"
            f"USER FEEDBACK:\n{feedback or '(none)'}"
        )
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        raw = response.content if isinstance(response.content, str) else str(response.content)
        cleaned = self._strip_json_fences(raw)
        try:
            value = json.loads(cleaned)
        except Exception:
            # If the LLM returned a bare string not quoted, wrap it.
            value = cleaned
        return {"regen_value": value}

    async def _persist_regen_node(self, state: PublisherState):
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        field = state.get("regen_field") or ""
        value = state.get("regen_value")
        if supabase is None or not pkg_id or not field:
            return {}

        patch: dict[str, Any] = {"updated_at": _now_iso()}
        if field in {
            "social.twitter",
            "social.newsletter",
            "social.newsletter_subject",
            "social.newsletter_body",
        }:
            existing = (state.get("existing_package") or {}).get("social") or {}
            key = field.split(".", 1)[1]
            patch["social"] = {**existing, key: value}
        elif field in {
            "title_variants",
            "description",
            "tags",
            "chapters",
            "thumbnail_ideas",
        }:
            patch[field] = value
        else:
            return {"warning": f"unknown regen field: {field}"}

        try:
            supabase.table("publisher_packages").update(patch).eq("id", pkg_id).execute()
        except Exception as e:
            return {"warning": f"regen persist failed: {e}"[:500]}
        return {}

    # ── push_metadata branch ──────────────────────────────────────────────
    async def _prepare_push_node(self, state: PublisherState):
        """Build the proposed vs. current diff that the approval card will show."""
        pkg = state.get("existing_package") or {}
        variants = pkg.get("title_variants") or []
        proposed_title = state.get("selected_title") or (variants[0] if variants else (pkg.get("video_title") or ""))
        proposed_description = pkg.get("description") or ""
        proposed_tags = pkg.get("tags") or []

        # Pull current YouTube metadata so the approval UI can show a before/after.
        current_title = pkg.get("video_title") or ""
        current_description = ""
        current_tags: list = []
        vid = pkg.get("video_id") or state.get("video_id")
        if vid:
            details_text = await _safe_tool(get_video_details, {"video_id": vid})
            current_title, current_description, current_tags = _parse_details_preview(details_text)

        # Mark the row as pending_push so the UI can reflect it while the gate waits.
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        if supabase is not None and pkg_id:
            try:
                (
                    supabase.table("publisher_packages")
                    .update({"status": "pending_push", "updated_at": _now_iso()})
                    .eq("id", pkg_id)
                    .execute()
                )
            except Exception:
                pass

        return {
            "proposed_title": proposed_title,
            "proposed_description": proposed_description,
            "proposed_tags": proposed_tags,
            "current_title": current_title,
            "current_description": current_description,
            "current_tags": current_tags,
            "approval_status": "pending",
        }

    async def _approval_gate_node(self, state: PublisherState):
        # No-op. Interrupt point. On resume, conditional edge reads approval_status.
        return {}

    async def _push_metadata_node(self, state: PublisherState):
        result = await _safe_tool(
            update_video_metadata,
            {
                "video_id": state.get("video_id"),
                "title": state.get("proposed_title") or "",
                "description": state.get("proposed_description") or "",
                "tags": state.get("proposed_tags") or [],
            },
        )
        return {"push_result": result, "approval_status": "approved"}

    async def _mark_pushed_node(self, state: PublisherState):
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        if supabase is None or not pkg_id:
            return {}
        try:
            supabase.table("publisher_packages").update({
                "status": "pushed",
                "video_title": state.get("proposed_title") or state.get("video_title"),
                "description": state.get("proposed_description"),
                "tags": state.get("proposed_tags") or [],
                "youtube_pushed_at": _now_iso(),
                "updated_at": _now_iso(),
            }).eq("id", pkg_id).execute()
        except Exception:
            pass
        return {}

    async def _revise_metadata_node(self, state: PublisherState):
        """User rejected the push — revise title/description per feedback, loop back to approval_gate."""
        profile = self._profile(state)
        context = (
            f"CURRENT PROPOSED TITLE: {state.get('proposed_title') or ''}\n\n"
            f"CURRENT PROPOSED DESCRIPTION:\n{state.get('proposed_description') or ''}\n\n"
            f"CURRENT PROPOSED TAGS: {', '.join(state.get('proposed_tags') or [])}\n\n"
            f"USER FEEDBACK:\n{state.get('feedback') or '(no specific feedback)'}\n\n"
            "Revise the title, description, and tags. Return JSON only:\n"
            '{"title": "...", "description": "...", "tags": ["...", "..."]}'
        )
        system_msg = (
            f"You are revising YouTube metadata for {profile.brand.name} "
            f"(voice: {profile.brand.voice}) based on user feedback. "
            "Return ONLY a JSON object with keys title, description, tags."
        )
        response = await self.llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=context),
        ])
        raw = response.content if isinstance(response.content, str) else str(response.content)
        cleaned = self._strip_json_fences(raw)
        try:
            parsed = json.loads(cleaned)
        except Exception:
            parsed = {}
        return {
            "proposed_title": parsed.get("title") or state.get("proposed_title"),
            "proposed_description": parsed.get("description") or state.get("proposed_description"),
            "proposed_tags": _as_str_list(parsed.get("tags")) or state.get("proposed_tags"),
            "approval_status": "pending",
            "feedback": None,
        }

    # ── push_x branch (Twitter) ───────────────────────────────────────────
    async def _prepare_x_push_node(self, state: PublisherState):
        """Pull `social.twitter` off the package row as the proposed tweet.

        The kit-generator prompt instructs the LLM to use `[link]` as a
        placeholder URL (so it doesn't hallucinate one). We resolve that
        to the actual `https://youtu.be/<video_id>` here, right before
        the user reviews the tweet for approval — so what they approve is
        exactly what gets posted.
        """
        pkg = state.get("existing_package") or {}
        social = pkg.get("social") or {}
        proposed = (social.get("twitter") or "").strip()
        video_id = pkg.get("video_id") or state.get("video_id")
        proposed = _resolve_video_link(proposed, video_id)
        return {
            "proposed_tweet": proposed,
            "approval_status": "pending",
        }

    async def _post_to_x_node(self, state: PublisherState):
        """Resume path on approve — call the post_tweet tool."""
        result = await _safe_tool(post_tweet, {"text": state.get("proposed_tweet") or ""})
        # Pull the tweet_id back out of the success line, if present.
        tweet_id = None
        if isinstance(result, str) and "tweet_id=" in result:
            try:
                tweet_id = result.split("tweet_id=", 1)[1].split()[0].split("(")[0].strip()
            except Exception:
                tweet_id = None
        return {
            "x_push_result": result,
            "x_tweet_id": tweet_id,
            "approval_status": "approved",
        }

    async def _mark_x_pushed_node(self, state: PublisherState):
        """Persist x_posted_at + x_tweet_id on the package row, OR stamp a
        warning on failure so the UI sees the error instead of silently
        appearing to succeed."""
        result = state.get("x_push_result") or ""
        failed = (
            not state.get("x_tweet_id")
            or (isinstance(result, str) and result.startswith("Error"))
        )
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        if supabase is None or not pkg_id:
            return {}
        try:
            if failed:
                supabase.table("publisher_packages").update({
                    "warning": f"X post failed: {str(result)[:200]}",
                    "updated_at": _now_iso(),
                }).eq("id", pkg_id).execute()
            else:
                supabase.table("publisher_packages").update({
                    "x_posted_at": _now_iso(),
                    "x_tweet_id": state.get("x_tweet_id"),
                    "updated_at": _now_iso(),
                }).eq("id", pkg_id).execute()
        except Exception:
            pass
        return {}

    async def _revise_tweet_node(self, state: PublisherState):
        """User rejected the tweet — rewrite per feedback, loop back to approval_gate."""
        profile = self._profile(state)
        context = (
            f"CURRENT PROPOSED TWEET ({len(state.get('proposed_tweet') or '')} chars):\n"
            f"{state.get('proposed_tweet') or ''}\n\n"
            f"USER FEEDBACK:\n{state.get('feedback') or '(no specific feedback)'}\n\n"
            "Rewrite the tweet. Stay ≤280 chars. Return ONLY a JSON object:\n"
            '{"tweet": "..."}'
        )
        system_msg = (
            f"You are revising a single tweet for {profile.brand.name} "
            f"(voice: {profile.brand.voice}) based on user feedback. Return ONLY a JSON "
            'object with key "tweet". Keep ≤280 chars.'
        )
        response = await self.llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=context),
        ])
        raw = response.content if isinstance(response.content, str) else _flatten_content(response.content)
        cleaned = self._strip_json_fences(raw)
        new_tweet = state.get("proposed_tweet") or ""
        try:
            parsed = json.loads(cleaned)
            candidate = (parsed.get("tweet") or "").strip()
            if candidate:
                new_tweet = candidate[:280]
        except Exception:
            pass

        # Mirror the YouTube revise pattern: also persist back to social.twitter
        # so the package detail page reflects the revision in real time.
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        if supabase is not None and pkg_id:
            existing_social = (state.get("existing_package") or {}).get("social") or {}
            try:
                supabase.table("publisher_packages").update({
                    "social": {**existing_social, "twitter": new_tweet},
                    "updated_at": _now_iso(),
                }).eq("id", pkg_id).execute()
            except Exception:
                pass

        return {
            "proposed_tweet": new_tweet,
            "approval_status": "pending",
            "feedback": None,
        }

    # ── push_newsletter branch (Gmail) ────────────────────────────────────
    async def _prepare_newsletter_push_node(self, state: PublisherState):
        """Pull `social.newsletter_subject` + `social.newsletter_body` off the
        package row and resolve a recipient. Recipient precedence:

          1. `state.newsletter_recipient` — explicit override from the API
             call or chat ("send the newsletter to list@example.com")
          2. `profile.brand.primary_email` — the creator's own address;
             default for "email me the newsletter" usage. Self-send is the
             honest v1 — Gmail isn't a newsletter platform, so we land
             the polished draft in their inbox to forward / paste from.

        If neither resolves, surface a "no recipient" warning that the
        approval card can render so the user knows what to fix before
        approving.
        """
        pkg = state.get("existing_package") or {}
        social = pkg.get("social") or {}

        # Newsletter copy can live as a single blob (`social.newsletter`)
        # or as the richer subject+body split. Prefer the split when it
        # exists; fall back to the blob as the body with a derived subject.
        subject = (social.get("newsletter_subject") or "").strip()
        body = (social.get("newsletter_body") or social.get("newsletter") or "").strip()
        if not subject:
            video_title = (state.get("video_title") or pkg.get("video_title") or "").strip()
            subject = f"New video: {video_title}" if video_title else "New video drop"

        explicit = (state.get("newsletter_recipient") or "").strip()
        profile = self._profile(state)
        fallback = (profile.brand.primary_email or "").strip()
        recipient = explicit or fallback

        # Same `[link]` placeholder substitution as the X push — the kit
        # generator was told to write `[link]` so it doesn't fabricate URLs;
        # we resolve to the real video URL at push time.
        video_id = pkg.get("video_id") or state.get("video_id")
        subject = _resolve_video_link(subject, video_id)
        body = _resolve_video_link(body, video_id)

        return {
            "proposed_newsletter_subject": subject,
            "proposed_newsletter_body": body,
            "newsletter_recipient": recipient,
            "approval_status": "pending",
        }

    async def _send_newsletter_node(self, state: PublisherState):
        """Resume on approve — call send_newsletter_via_gmail with the
        approved subject/body/recipient."""
        from packages.agents.publisher.tools import send_newsletter_via_gmail

        recipient = (state.get("newsletter_recipient") or "").strip()
        subject = (state.get("proposed_newsletter_subject") or "").strip()
        body = (state.get("proposed_newsletter_body") or "").strip()

        if not recipient or not subject or not body:
            missing = ", ".join(
                k for k, v in (
                    ("recipient", recipient), ("subject", subject), ("body", body)
                ) if not v
            )
            return {
                "newsletter_push_result": f"Error: missing required field(s): {missing}",
                "approval_status": "approved",
            }

        result = await _safe_tool(send_newsletter_via_gmail, {
            "to": recipient,
            "subject": subject,
            "body": body,
        })
        # Pull message_id back out of the success line, if present.
        message_id = None
        if isinstance(result, str) and "message_id=" in result:
            try:
                message_id = result.split("message_id=", 1)[1].split()[0].strip()
            except Exception:
                message_id = None
        return {
            "newsletter_push_result": result,
            "newsletter_message_id": message_id,
            "approval_status": "approved",
        }

    async def _mark_newsletter_sent_node(self, state: PublisherState):
        """Persist newsletter_sent_at + newsletter_message_id on success,
        OR stamp `warning` with the error string on failure. Previously
        this returned silently on failure, which left the UI looking like
        the send succeeded — the platforms sidebar would still show
        'Send newsletter' (no timestamp) but no surfaced reason."""
        result = state.get("newsletter_push_result") or ""
        failed = (
            not state.get("newsletter_message_id")
            or (isinstance(result, str) and result.startswith("Error"))
        )
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        if supabase is None or not pkg_id:
            return {}
        try:
            if failed:
                supabase.table("publisher_packages").update({
                    "warning": f"newsletter send failed: {str(result)[:200]}",
                    "updated_at": _now_iso(),
                }).eq("id", pkg_id).execute()
            else:
                supabase.table("publisher_packages").update({
                    "newsletter_sent_at": _now_iso(),
                    "newsletter_message_id": state.get("newsletter_message_id"),
                    "updated_at": _now_iso(),
                }).eq("id", pkg_id).execute()
        except Exception:
            pass
        return {}

    async def _revise_newsletter_node(self, state: PublisherState):
        """User rejected the newsletter — rewrite subject + body per feedback,
        persist back to social.newsletter_{subject,body}, loop to gate."""
        profile = self._profile(state)
        current_subject = state.get("proposed_newsletter_subject") or ""
        current_body = state.get("proposed_newsletter_body") or ""
        context = (
            f"CURRENT SUBJECT: {current_subject}\n\n"
            f"CURRENT BODY:\n{current_body}\n\n"
            f"USER FEEDBACK:\n{state.get('feedback') or '(no specific feedback)'}\n\n"
            "Rewrite the newsletter subject + body. Body 80–200 words, "
            'plain text with paragraph breaks. Return ONLY JSON: '
            '{"subject": "...", "body": "..."}'
        )
        system_msg = (
            f"You are revising a newsletter for {profile.brand.name} "
            f"(voice: {profile.brand.voice}) based on user feedback. Return ONLY a "
            'JSON object with keys "subject" and "body".'
        )
        response = await self.llm.ainvoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=context),
        ])
        raw = response.content if isinstance(response.content, str) else _flatten_content(response.content)
        cleaned = self._strip_json_fences(raw)
        new_subject = current_subject
        new_body = current_body
        try:
            parsed = json.loads(cleaned)
            cand_s = (parsed.get("subject") or "").strip()
            cand_b = (parsed.get("body") or "").strip()
            if cand_s:
                new_subject = cand_s
            if cand_b:
                new_body = cand_b
        except Exception:
            pass

        # Mirror the X / YouTube revise pattern: persist back to the package
        # so the detail page reflects the revision in real time.
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        if supabase is not None and pkg_id:
            existing_social = (state.get("existing_package") or {}).get("social") or {}
            try:
                supabase.table("publisher_packages").update({
                    "social": {
                        **existing_social,
                        "newsletter_subject": new_subject,
                        "newsletter_body": new_body,
                    },
                    "updated_at": _now_iso(),
                }).eq("id", pkg_id).execute()
            except Exception:
                pass

        return {
            "proposed_newsletter_subject": new_subject,
            "proposed_newsletter_body": new_body,
            "approval_status": "pending",
            "feedback": None,
        }

    # ── general branch (ReAct) ────────────────────────────────────────────
    async def _react_agent_node(self, state: PublisherState):
        profile = self._profile(state)
        system_prompt = render("publisher", "system.j2", profile=profile)
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await self.llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    # ── Terminal respond node ─────────────────────────────────────────────
    async def _respond_node(self, state: PublisherState):
        intent = state.get("intent") or "general"
        if intent == "create_package":
            pkg_id = state.get("package_id")
            warn = state.get("warning")
            parts = [f"Package ready ({pkg_id or 'no id'})."]
            if warn:
                parts.append(f"Note: {warn}")
            content = " ".join(parts)
        elif intent == "regenerate_field":
            content = f"Regenerated {state.get('regen_field') or 'field'}."
        elif intent == "push_metadata":
            content = state.get("push_result") or "Push complete."
        elif intent == "push_x":
            content = state.get("x_push_result") or "Tweet posted."
        elif intent == "push_newsletter":
            content = state.get("newsletter_push_result") or "Newsletter sent."
        else:
            last_ai = next(
                (m for m in reversed(state["messages"]) if isinstance(m, AIMessage)),
                None,
            )
            content = (last_ai.content if last_ai else "") or "Done."
        return {"messages": [AIMessage(content=content)]}


# ── Module-level helpers (no self) ────────────────────────────────────────

def _now_iso() -> str:
    """ISO-8601 UTC timestamp Postgres accepts for timestamptz columns."""
    return datetime.now(timezone.utc).isoformat()


def _flatten_content(content: Any) -> str:
    """Claude sometimes returns `content` as a list of blocks rather than a string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def _append_warning(existing: str | None, new_part: str) -> str:
    existing = (existing or "").strip()
    if not existing:
        return new_part
    return f"{existing}; {new_part}"


async def _safe_tool(tool_obj, args: dict) -> str:
    """Invoke a @tool and return the string payload; swallow errors to a string."""
    try:
        return await tool_obj.ainvoke(args)
    except Exception as e:
        return f"Error: {e}"


def _resolve_video_link(text: str, video_id: str | None) -> str:
    """Replace `[link]` (and a few common variants) with the real YouTube URL.

    The kit-generation prompt instructs the LLM to write `[link]` as a
    placeholder so it doesn't hallucinate URLs. Push nodes call this right
    before the user approves the draft so the proposed copy is exactly
    what will be posted/sent. No-op when video_id is missing.
    """
    if not text or not video_id:
        return text or ""
    url = f"https://youtu.be/{video_id}"
    # Order matters: longest/most-specific first so we don't half-replace.
    for token in ("[link]", "[LINK]", "[Link]", "[url]", "[URL]", "[video_url]"):
        text = text.replace(token, url)
    return text


def _parse_latest_upload(text: str | None) -> tuple[str | None, str | None]:
    """Pull (video_id, title) out of `get_latest_upload`'s string payload.

    The tool returns a Markdown-ish block:

        # <title>
        - Video ID: <vid>
        - Published: ...
        - Current description:
        ...

    Returns (None, None) on anything that doesn't match (errors, empty
    channel, unexpected shape).
    """
    if not text or text.startswith("Error") or text.startswith("No videos"):
        return None, None
    vid: str | None = None
    title: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip() or None
        elif s.startswith("- Video ID:"):
            vid = s.split(":", 1)[1].strip() or None
            if vid:
                break
    return vid, title


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str) and value.strip():
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def _as_chapters(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value:
        if isinstance(item, dict) and item.get("time") and item.get("label"):
            out.append({"time": str(item["time"]), "label": str(item["label"])})
    return out


def _as_social(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    # `newsletter` (legacy single-blob blurb) is preserved for back-compat
    # with packages generated before the subject/body split. New packages
    # produce the split fields; both shapes are accepted by the push lane.
    return {
        "twitter": str(value.get("twitter") or ""),
        "newsletter": str(value.get("newsletter") or ""),
        "newsletter_subject": str(value.get("newsletter_subject") or ""),
        "newsletter_body": str(value.get("newsletter_body") or ""),
    }


def _parse_details_preview(details_text: str | None) -> tuple[str, str, list[str]]:
    """Pull (title, description, tags) from the markdown that get_video_details returns.

    That tool returns a string with sections like:
        # <title>
        - Video ID: ...
        ## Current Description
        <description>
        ## Current Tags
        tag1, tag2, ...
    """
    if not details_text or not isinstance(details_text, str):
        return "", "", []
    lines = details_text.splitlines()
    title = ""
    if lines and lines[0].startswith("# "):
        title = lines[0].removeprefix("# ").strip()

    def _section(header: str) -> str:
        try:
            idx = lines.index(f"## {header}")
        except ValueError:
            return ""
        chunk: list[str] = []
        for ln in lines[idx + 1:]:
            if ln.startswith("## "):
                break
            chunk.append(ln)
        return "\n".join(chunk).strip()

    description = _section("Current Description")
    tags_line = _section("Current Tags")
    tags = [t.strip() for t in tags_line.split(",") if t.strip()] if tags_line else []
    return title, description, tags
