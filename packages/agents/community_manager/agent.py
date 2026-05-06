"""
Community Manager — triages comments, drafts replies, posts approved replies
to YouTube via OAuth.

Graph shape (mirrors Brand Manager so the approvals runtime drives both
the same way):

  START → load_profile → classify_intent
                              ↓
        ┌─────────────────────┼──────────────────────────┐
   triage / research          draft_reply
        ↓                              ↓
   triage_agent ⇄ tools        fetch_recent_comments
        ↓                              ↓
   persist_triage              pick_target
        ↓                              ↓
        respond
                                       ↓
                                 (no match? → respond with clarification)
                                       ↓
                                   draft_reply
                                       ↓
                              [INTERRUPT: approval_gate]
                                       ↓
                       ┌───────────────┼────────────────┐
                   approved                       rejected
                       ↓                              ↓
                   send_reply                  revise_reply
                       ↓                              ↓
                       └─────────→ respond ←──── approval_gate (loop)

The approval_gate is the only HITL: drafting and revision are LLM-driven;
the only thing that can hit the YouTube write API is `_send_reply_node`,
which only runs after the gate is cleared with approval_status="approved".
"""
from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.peer_context import _is_real_uuid
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.tasks import create_tasks_from_agent
from packages.agents.core.templates import render
from packages.agents.community_manager.tools import (
    get_recent_comments,
    lookup_channel,
    reply_to_comment,
)
from packages.integrations.context import current_supabase


def _priority_from_kind(kind: str | None) -> str:
    """Map a triage bucket to task priority. VIPs are red-border high-priority
    cards because a missed reply to a sponsor or fellow large creator is a
    real cost. Real questions are mid-priority — worth answering this week
    but not blocking. Superfans land low: nice-to-do, not urgent."""
    if kind == "vip":
        return "high"
    if kind == "question":
        return "medium"
    return "low"


# ── Structured output schemas ─────────────────────────────────────────────
class TriageItem(BaseModel):
    """A single actionable item the user should personally handle, extracted
    from the triage agent's free-form markdown response so it can be
    materialized as a task on /app/tasks."""
    kind: Literal["vip", "question", "superfan"] = Field(
        description="Which triage bucket the comment falls into."
    )
    commenter_name: str = Field(description="Display name of the commenter.")
    comment_id: str = Field(default="", description="YouTube top-level comment id, if known.")
    summary: str = Field(
        description="One-line summary — for VIPs, why they matter; for questions, the question itself."
    )
    draft_reply: str = Field(
        default="",
        description="The draft reply the agent already wrote, if any. Empty string for VIPs without drafts.",
    )
    video_title: str = Field(default="", description="Title of the video the comment is on, if known.")


class TriageOutput(BaseModel):
    items: list[TriageItem] = Field(
        default_factory=list,
        description="Every actionable comment from the triage report — VIPs first, then questions, then superfans.",
    )


# ── Structured output schema for the pick-target step ────────────────────
class TargetComment(BaseModel):
    """The comment the user wants to reply to, picked from a fetched batch.

    `target_comment_id == ""` means no good match — the agent surfaces
    `clarification_needed` to the user instead of drafting a wrong reply.
    """
    target_comment_id: str = Field(description="YouTube top-level comment id, or empty string if no match")
    target_author: str = Field(default="", description="Display name of the matched commenter")
    target_video_title: str = Field(default="", description="Title of the video the comment is on")
    target_comment_text: str = Field(default="", description="The matched comment's text body, for use in drafting")
    clarification_needed: str = Field(
        default="",
        description="Set when target_comment_id is empty — explain why no comment matched, surfaced to the user.",
    )


class CommunityManagerState(BaseAgentState):
    """State carried across CM nodes."""
    intent: str | None              # "triage" | "draft_reply" | "research"
    recent_comments_raw: str | None  # raw output of get_recent_comments, used by pick_target
    target_comment_id: str | None
    target_author: str | None
    target_video_title: str | None
    target_comment_text: str | None
    clarification_needed: str | None
    draft_reply: str | None
    approval_status: str | None      # "pending" | "approved" | "rejected"
    feedback: str | None             # set on rejection
    send_result: str | None


class CommunityManagerAgent(BaseAgent):
    slug = "community-manager"
    name = "Community Manager"
    description = (
        "Triages comments, drafts replies in the creator's voice, and posts "
        "approved replies to YouTube via the connected OAuth account. Reply "
        "posting is gated by a human-in-the-loop approval before the write "
        "actually fires."
    )
    model = "claude-sonnet-4-6"

    # The only thing gated is posting an approved reply. Triage and research
    # are read-only, no gate. Mirrors Brand Manager exactly so the existing
    # approvals runtime drives both agents the same way.
    @property
    def interrupt_before_nodes(self) -> list[str]:
        return ["approval_gate"]

    def get_approval_request(self, state: dict) -> dict | None:
        """Tell the API runtime what the frontend should render in the
        approval card when this graph pauses."""
        author = state.get("target_author") or "(unknown commenter)"
        video = state.get("target_video_title") or "(unknown video)"
        return {
            "action_type": "reply_comment",
            "action_payload": {
                "parent_comment_id": state.get("target_comment_id"),
                "parent_comment_text": state.get("target_comment_text"),
                "parent_author": state.get("target_author"),
                "parent_video_title": state.get("target_video_title"),
                "reply_draft": state.get("draft_reply"),
            },
            "preview": f"Reply to {author} on '{video}'"[:500],
        }

    def __init__(self):
        # Tool-bound LLM is used by the triage/research ReAct branch — same
        # pattern as Brand Manager's research/leads branch. The drafting nodes
        # use a plain LLM so they can't accidentally call write tools.
        self.tools = [get_recent_comments, lookup_channel]
        self.llm_with_tools = ChatAnthropic(model=self.model).bind_tools(self.tools)
        self.tool_node = ToolNode(self.tools)
        self.llm = ChatAnthropic(model=self.model)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(CommunityManagerState)

        graph.add_node("load_profile", self._load_profile_node)
        # peer_context: latest Strategist brief (for voice/direction reference
        # when replying) + latest Publisher package once that table lands on
        # main. Hydrated once at the top so triage and draft prompts can both
        # cite it via state.metadata.peer_context.
        graph.add_node("load_peer_context", self._load_peer_context_node)
        graph.add_node("classify_intent", self._classify_intent_node)

        # triage / research branch — ReAct sub-loop
        graph.add_node("triage_agent", self._triage_agent_node)
        graph.add_node("triage_tools", self.tool_node)
        # persist_triage spawns one /app/tasks To-Do per VIP / real question
        # the triage agent surfaced. No-op for research intent and dev mode.
        graph.add_node("persist_triage", self._persist_triage_node)

        # draft_reply branch — sequential
        graph.add_node("fetch_recent_comments", self._fetch_recent_comments_node)
        graph.add_node("pick_target", self._pick_target_node)
        graph.add_node("draft_reply", self._draft_reply_node)
        graph.add_node("approval_gate", self._approval_gate_node)
        graph.add_node("send_reply", self._send_reply_node)
        graph.add_node("revise_reply", self._revise_reply_node)

        graph.add_node("respond", self._respond_node)

        # ── Edges ──────────────────────────────────────────────────────────
        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "load_peer_context")
        graph.add_edge("load_peer_context", "classify_intent")

        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
            {
                "triage": "triage_agent",
                "research": "triage_agent",
                "draft_reply": "fetch_recent_comments",
            },
        )

        # Triage / research ReAct loop. When the loop exits (no more tool
        # calls), drop into persist_triage which extracts actionable items
        # and spawns tasks before the user-facing respond fires.
        graph.add_conditional_edges(
            "triage_agent",
            self._should_use_tools,
            {"tools": "triage_tools", "end": "persist_triage"},
        )
        graph.add_edge("triage_tools", "triage_agent")
        graph.add_edge("persist_triage", "respond")

        # Draft-reply pipeline
        graph.add_edge("fetch_recent_comments", "pick_target")
        # If pick_target couldn't find a match, short-circuit to respond.
        graph.add_conditional_edges(
            "pick_target",
            self._after_pick_target,
            {"draft": "draft_reply", "no_match": "respond"},
        )
        graph.add_edge("draft_reply", "approval_gate")
        graph.add_conditional_edges(
            "approval_gate",
            self._route_by_approval,
            {"approved": "send_reply", "rejected": "revise_reply"},
        )
        graph.add_edge("revise_reply", "approval_gate")
        graph.add_edge("send_reply", "respond")

        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: CommunityManagerState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    def _peer_context(self, state: CommunityManagerState) -> dict:
        """Latest Strategist brief / Publisher package, hydrated by the
        load_peer_context node. Empty dict in dev mode."""
        return (state.get("metadata") or {}).get("peer_context") or {}

    def _channel_id(self, state: CommunityManagerState) -> str:
        """Channel ID for tool arguments. Already overlaid from OAuth onto
        the profile in `_load_profile_node`, so just read it back."""
        return self._profile(state).youtube.channel_id or ""

    def _last_user_text(self, state: CommunityManagerState) -> str:
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        return last_human.content if last_human else ""

    # ── Routers ────────────────────────────────────────────────────────────
    def _route_by_intent(self, state: CommunityManagerState) -> str:
        intent = (state.get("intent") or "triage").lower()
        if intent not in {"triage", "draft_reply", "research"}:
            return "triage"
        return intent

    def _route_by_approval(self, state: CommunityManagerState) -> str:
        # Default approved on a plain Studio resume, mirroring Brand Manager.
        status = (state.get("approval_status") or "approved").lower()
        return "rejected" if status == "rejected" else "approved"

    def _after_pick_target(self, state: CommunityManagerState) -> str:
        return "draft" if state.get("target_comment_id") else "no_match"

    def _should_use_tools(self, state: CommunityManagerState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return "end"

    # ── Nodes ──────────────────────────────────────────────────────────────
    async def _load_profile_node(self, state: CommunityManagerState):
        # `load_profile` overlays the OAuth-connected channel_id onto the
        # profile when the brand row's `youtube_channel_id` is empty — see
        # `_overlay_oauth_channel_id` in core/profile.py.
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    async def _classify_intent_node(self, state: CommunityManagerState):
        profile = self._profile(state)
        prompt = render("community_manager", "classify.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=self._last_user_text(state)),
        ])
        raw = response.content.strip().strip("`").lower()
        intent = raw if raw in {"triage", "draft_reply", "research"} else "triage"
        return {"intent": intent}

    async def _triage_agent_node(self, state: CommunityManagerState):
        profile = self._profile(state)
        # `triage` and `research` use slightly different system prompts:
        # triage produces the structured alert / needs-reply / hide format;
        # research is a free-form ad-hoc analysis path.
        template = "triage.j2" if state.get("intent") == "triage" else "research.j2"
        system_prompt = render(
            "community_manager",
            template,
            profile=profile,
            peer_context=self._peer_context(state),
        )
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await self.llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    async def _persist_triage_node(self, state: CommunityManagerState):
        """Spawn one workspace task per VIP / real question / superfan the
        triage agent surfaced.

        Triage produces free-form markdown for the chat — great for the
        creator to skim, but useless once they close the tab. This node
        runs a structured-extraction pass over the same markdown and drops
        each actionable item onto /app/tasks so they can move it across
        the Kanban as they work the inbox.

        No-op when:
          - intent != 'triage' (research is exploratory, draft_reply has its
            own approval flow, neither produces a list of items to chase)
          - org_id isn't a real UUID or Supabase isn't configured (dev mode)
          - the triage agent didn't emit a final assistant message

        Best-effort: extraction or task-insert failures are swallowed so a
        flaky LLM call or DB blip can't break the user-facing reply.
        """
        if (state.get("intent") or "").lower() != "triage":
            return {}

        last_ai = next(
            (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content),
            None,
        )
        if not last_ai:
            return {}

        try:
            structured = self.llm.with_structured_output(TriageOutput)
            extraction: TriageOutput = await structured.ainvoke([
                SystemMessage(content=(
                    "Extract every actionable comment from the triage report below as structured items. "
                    "VIPs go in 'vip', real questions in 'question', superfans in 'superfan'. "
                    "Skip spam and ignore-bucket items. If a draft reply was written, include it verbatim. "
                    "If no comment_id appears in [brackets], leave that field empty."
                )),
                HumanMessage(content=last_ai.content),
            ])
        except Exception as e:
            print(f"[community_manager] triage extraction failed: {e!r}", flush=True)
            return {}

        if not extraction.items:
            return {}

        # Cache the drafts the triage agent already wrote, keyed by comment_id.
        # Saves a second LLM call when the user later says "send the reply to
        # X" — we reuse the exact text the user already saw in chat instead of
        # redrafting (which would produce slightly different wording and break
        # the user's expectation that "what I see" == "what gets posted").
        triage_drafts: dict[str, str] = {
            item.comment_id: item.draft_reply
            for item in extraction.items
            if item.comment_id and item.draft_reply
        }
        existing_meta = state.get("metadata") or {}
        meta_update: dict = {**existing_meta}
        if triage_drafts:
            meta_update["triage_drafts"] = {
                **(existing_meta.get("triage_drafts") or {}),
                **triage_drafts,
            }

        org_id = state.get("org_id") or ""
        supabase = current_supabase.get()
        if supabase is None or not _is_real_uuid(org_id):
            return {"metadata": meta_update}

        thread_id = state.get("thread_id") or ""
        items = []
        for item in extraction.items:
            commenter = (item.commenter_name or "commenter").strip() or "commenter"
            title = (
                f"Reply to {commenter} (VIP)" if item.kind == "vip"
                else f"Reply to {commenter}"
            )
            description_parts = []
            if item.video_title:
                description_parts.append(f"Video: {item.video_title}")
            if item.summary:
                description_parts.append(item.summary)
            if item.draft_reply:
                description_parts.append(f"Draft: {item.draft_reply}")
            description = "\n\n".join(description_parts) or None
            items.append({
                "title": title,
                "description": description,
                "priority": _priority_from_kind(item.kind),
                "status": "todo",
                "metadata": {
                    "source": "cm_triage",
                    "thread_id": thread_id if _is_real_uuid(thread_id) else None,
                    "kind": item.kind,
                    "comment_id": item.comment_id or None,
                },
            })

        try:
            await create_tasks_from_agent(
                org_id=org_id,
                agent_slug=self.slug,
                items=items,
            )
        except Exception as e:
            print(f"[community_manager] task spawn failed: {e!r}", flush=True)

        return {"metadata": meta_update}

    async def _fetch_recent_comments_node(self, state: CommunityManagerState):
        """Pull a batch of recent comments to feed the pick_target step.

        Uses fewer videos / fewer-per-video than the triage default since
        we just need enough surface area to find the comment the user named.
        """
        try:
            raw = await get_recent_comments.ainvoke({
                "channel_id": self._channel_id(state),
                "max_videos": 5,
                "per_video": 30,
            })
        except Exception as e:
            raw = f"Error fetching recent comments: {e}"
        return {"recent_comments_raw": raw}

    async def _pick_target_node(self, state: CommunityManagerState):
        profile = self._profile(state)
        context = (
            f"USER REQUEST:\n{self._last_user_text(state)}\n\n"
            f"RECENT COMMENTS:\n{state.get('recent_comments_raw') or '(none fetched)'}"
        )
        prompt = render("community_manager", "pick_target.j2", profile=profile)
        structured = self.llm.with_structured_output(TargetComment)
        result: TargetComment = await structured.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        return {
            "target_comment_id": result.target_comment_id or None,
            "target_author": result.target_author or None,
            "target_video_title": result.target_video_title or None,
            "target_comment_text": result.target_comment_text or None,
            "clarification_needed": result.clarification_needed or None,
        }

    async def _draft_reply_node(self, state: CommunityManagerState):
        profile = self._profile(state)

        # If triage already wrote a draft for this exact comment in chat,
        # reuse it verbatim — what the user saw is what gets sent. Re-running
        # the LLM here would produce slightly different wording and break the
        # match between "the draft you proposed" and "the draft in approval".
        target_id = state.get("target_comment_id") or ""
        triage_drafts = ((state.get("metadata") or {}).get("triage_drafts") or {})
        cached = triage_drafts.get(target_id)
        if cached:
            draft = cached.strip()
            author = state.get("target_author") or "the commenter"
            chat_msg = (
                f"Drafted a reply to **{author}** — review and approve below:\n\n> {draft}"
            )
            return {
                "draft_reply": draft,
                "approval_status": "pending",
                "messages": [AIMessage(content=chat_msg)],
            }

        context = (
            f"ORIGINAL COMMENT:\n"
            f"  Author: {state.get('target_author') or '(unknown)'}\n"
            f"  Video: {state.get('target_video_title') or '(unknown)'}\n"
            f"  Text: {state.get('target_comment_text') or ''}\n\n"
            f"USER'S DIRECTION:\n{self._last_user_text(state)}"
        )
        prompt = render(
            "community_manager",
            "draft.j2",
            profile=profile,
            peer_context=self._peer_context(state),
        )
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        draft = response.content.strip()
        # Surface the draft in chat alongside the approval card. Without this
        # the approval_gate interrupt fires with no visible AIMessage and the
        # bot bubble is empty — UX reads as "stalled" even though the graph
        # is correctly paused waiting for approve/reject.
        author = state.get("target_author") or "the commenter"
        chat_msg = f"Drafted a reply to **{author}** — review and approve below:\n\n> {draft}"
        return {
            "draft_reply": draft,
            "approval_status": "pending",
            "messages": [AIMessage(content=chat_msg)],
        }

    async def _revise_reply_node(self, state: CommunityManagerState):
        profile = self._profile(state)
        context = (
            f"PREVIOUS REPLY:\n{state.get('draft_reply') or ''}\n\n"
            f"USER FEEDBACK:\n{state.get('feedback') or 'No specific feedback'}"
        )
        prompt = render(
            "community_manager",
            "revise.j2",
            profile=profile,
            peer_context=self._peer_context(state),
        )
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        draft = response.content.strip()
        chat_msg = f"Revised draft based on your feedback — review and approve below:\n\n> {draft}"
        return {
            "draft_reply": draft,
            "approval_status": "pending",
            "feedback": None,
            "messages": [AIMessage(content=chat_msg)],
        }

    async def _approval_gate_node(self, state: CommunityManagerState):
        # Pure router. The interrupt fires BEFORE this node runs, so on
        # resume the conditional edge re-evaluates approval_status.
        return {}

    async def _send_reply_node(self, state: CommunityManagerState):
        result = await reply_to_comment(
            parent_comment_id=state.get("target_comment_id") or "",
            text=state.get("draft_reply") or "",
        )
        return {"send_result": result, "approval_status": "approved"}

    async def _respond_node(self, state: CommunityManagerState):
        intent = state.get("intent") or "triage"

        # draft_reply branch terminal cases
        if intent == "draft_reply":
            if state.get("clarification_needed") and not state.get("target_comment_id"):
                content = (
                    f"I couldn't pick a comment to reply to: "
                    f"{state['clarification_needed']}\n\n"
                    "Try paraphrasing — name the commenter, the video, or quote a phrase from the comment."
                )
            elif state.get("send_result"):
                content = state["send_result"]
            else:
                # Fallthrough — shouldn't normally hit if the graph completes.
                content = state.get("draft_reply") or "Done."
        else:
            # triage / research — surface the ReAct loop's last message.
            last_ai = next(
                (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content),
                None,
            )
            content = (last_ai.content if last_ai else "") or "Done."

        return {"messages": [AIMessage(content=content)]}
