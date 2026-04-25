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
        respond                   pick_target
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

from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.community_manager.tools import (
    get_recent_comments,
    lookup_channel,
    reply_to_comment,
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

        # Triage / research ReAct loop
        graph.add_conditional_edges(
            "triage_agent",
            self._should_use_tools,
            {"tools": "triage_tools", "end": "respond"},
        )
        graph.add_edge("triage_tools", "triage_agent")

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

    async def _fetch_recent_comments_node(self, state: CommunityManagerState):
        """Pull a batch of recent comments to feed the pick_target step.

        Uses fewer videos / fewer-per-video than the triage default since
        we just need enough surface area to find the comment the user named.
        """
        profile = self._profile(state)
        try:
            raw = await get_recent_comments.ainvoke({
                "channel_id": profile.youtube.channel_id or "",
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
        return {"draft_reply": response.content.strip(), "approval_status": "pending"}

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
        return {
            "draft_reply": response.content.strip(),
            "approval_status": "pending",
            "feedback": None,
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
