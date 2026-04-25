"""
Publisher agent — packages YouTube videos into shippable metadata + social kits.

Four graph paths, chosen by `state.intent`:

  - create_package    : fetch video context → generate kit → extract structured → persist
  - regenerate_field  : load package → regenerate one field → persist (that field only)
  - push_metadata     : load package → prepare diff → [interrupt: approval_gate] →
                          approved: update_video_metadata → mark package pushed
                          rejected: revise_metadata → approval_gate (loop)
  - general           : ReAct loop over the 6 OAuth-backed tools for Q&A, SEO research

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
    update_video_metadata,
    post_tweet,
    get_publisher_tools,
)
from packages.integrations.context import current_supabase


# Valid intents — treat anything else as "general".
VALID_INTENTS = {"create_package", "regenerate_field", "push_metadata", "push_x", "general"}


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

    # Degraded-state marker, surfaced into publisher_packages.warning
    warning: str | None


class PublisherAgent(BaseAgent):
    slug = "publisher"
    name = "Publisher"
    description = (
        "Packages YouTube videos end-to-end: titles, descriptions, tags, chapters, "
        "thumbnail ideas, and social drafts (Twitter + newsletter). Pushes to "
        "YouTube and posts to X — both gated behind explicit approval."
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
                "general": "react_agent",
            },
        )

        # create_package: fetch → generate → extract → persist → respond
        graph.add_edge("fetch_video_context", "generate_kit")
        graph.add_edge("generate_kit", "extract_structured")
        graph.add_edge("extract_structured", "persist_package")
        graph.add_edge("persist_package", "respond")

        # load_package fan-out: regen vs push (YouTube) vs push (X)
        graph.add_conditional_edges(
            "load_package",
            self._route_after_load,
            {
                "regenerate_field": "regenerate_field",
                "push_metadata": "prepare_push",
                "push_x": "prepare_x_push",
            },
        )

        # regenerate_field: regen → persist → respond
        graph.add_edge("regenerate_field", "persist_regen")
        graph.add_edge("persist_regen", "respond")

        # push_metadata + push_x both flow through approval_gate; the post-gate
        # split is intent-aware so a YouTube push doesn't accidentally fire a tweet.
        graph.add_edge("prepare_push", "approval_gate")
        graph.add_edge("prepare_x_push", "approval_gate")
        graph.add_conditional_edges(
            "approval_gate",
            self._route_by_approval,
            {
                "approved_push_metadata": "push_metadata",
                "approved_push_x": "post_to_x",
                "rejected_push_metadata": "revise_metadata",
                "rejected_push_x": "revise_tweet",
            },
        )
        graph.add_edge("push_metadata", "mark_pushed")
        graph.add_edge("mark_pushed", "respond")
        graph.add_edge("revise_metadata", "approval_gate")
        graph.add_edge("post_to_x", "mark_x_pushed")
        graph.add_edge("mark_x_pushed", "respond")
        graph.add_edge("revise_tweet", "approval_gate")

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
        # `push_x` is the only non-default intent that hits this gate; default
        # everything else to the YouTube push lane.
        lane = "push_x" if intent == "push_x" else "push_metadata"
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
            response = await self.llm.ainvoke([
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
        if not vid:
            return {"warning": "no video_id supplied"}

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

        return {
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
            response = await self.llm.ainvoke([
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
            and not (social.get("twitter") or social.get("newsletter"))
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
            return {"package_id": saved.get("id") or state.get("package_id")}
        except Exception as e:
            return {"warning": f"persist failed: {e}"[:500]}

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
        if field == "social.twitter" or field == "social.newsletter":
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
        """Pull `social.twitter` off the package row as the proposed tweet."""
        pkg = state.get("existing_package") or {}
        social = pkg.get("social") or {}
        proposed = (social.get("twitter") or "").strip()
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
        """Persist x_posted_at + x_tweet_id on the package row.

        If post_to_x failed (string starts with "Error"), don't flip the row;
        the warning surfaces via the response.
        """
        result = state.get("x_push_result") or ""
        if not state.get("x_tweet_id") or (isinstance(result, str) and result.startswith("Error")):
            return {}
        supabase = current_supabase.get()
        pkg_id = state.get("package_id")
        if supabase is None or not pkg_id:
            return {}
        try:
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
    return {
        "twitter": str(value.get("twitter") or ""),
        "newsletter": str(value.get("newsletter") or ""),
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
