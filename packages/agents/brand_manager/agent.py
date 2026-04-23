import json
from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.brand_manager.tools import (
    find_sponsor_leads,
    research_brand,
    get_channel_stats,
    send_pitch_email,
)


class BrandManagerState(BaseAgentState):
    """Extended state for the Brand Manager workflow."""
    intent: str | None              # "find_leads" | "research_brand" | "draft_pitch"
    brand_research: str | None      # output of research_brand tool, used for drafting
    media_kit: str | None           # cached channel_stats output
    draft: str | None               # full email draft text (To/Subject/Body)
    recipient: str | None
    subject: str | None
    body: str | None
    approval_status: str | None     # "pending" | "approved" | "rejected"
    feedback: str | None            # revision feedback when rejected
    leads: str | None               # output of find_leads
    research_response: str | None   # output of research-only branch
    send_result: str | None


class BrandManagerAgent(BaseAgent):
    slug = "brand-manager"
    name = "Brand Manager"
    description = (
        "Drafts sponsor outreach and tailored pitches, tracks deal stages. "
        "Sends approved pitches via Resend with a human-in-the-loop approval gate."
    )
    model = "claude-sonnet-4-6"

    # Pause for human approval before send_pitch_email actually fires.
    # Same pattern as the legacy comms agent: interrupt at a no-op gate node so
    # the downstream conditional edge can re-evaluate state.approval_status on resume.
    @property
    def interrupt_before_nodes(self) -> list[str]:
        return ["approval_gate"]

    def get_approval_request(self, state: dict) -> dict | None:
        """What the frontend needs to render when this graph pauses.

        The approval_gate always fires with a fully-extracted email ready to
        send — recipient/subject/body are populated by extract_email upstream.
        """
        recipient = state.get("recipient") or "unknown recipient"
        subject = state.get("subject") or "(no subject)"
        return {
            "action_type": "send_email",
            "action_payload": {
                "recipient": state.get("recipient"),
                "subject": state.get("subject"),
                "body": state.get("body"),
                "draft": state.get("draft"),
            },
            "preview": f"Sponsor pitch to {recipient} — {subject}"[:500],
        }

    def __init__(self):
        # ToolNode is used by the research/leads branch — it's still a small ReAct
        # loop for those because the LLM picks which of (find_sponsor_leads,
        # research_brand, get_channel_stats) to call.
        self.tools = [find_sponsor_leads, research_brand, get_channel_stats]
        self.llm_with_tools = ChatAnthropic(model=self.model).bind_tools(self.tools)
        self.tool_node = ToolNode(self.tools)
        # Plain LLM (no bound tools) for the drafting / classify nodes.
        self.llm = ChatAnthropic(model=self.model)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(BrandManagerState)

        graph.add_node("load_profile", self._load_profile_node)
        graph.add_node("classify_intent", self._classify_intent_node)

        # research / leads branch (ReAct sub-loop)
        graph.add_node("research_agent", self._research_agent_node)
        graph.add_node("research_tools", self.tool_node)

        # pitch drafting branch
        graph.add_node("fetch_media_kit", self._fetch_media_kit_node)
        graph.add_node("research_target_brand", self._research_target_brand_node)
        graph.add_node("draft_pitch", self._draft_pitch_node)
        graph.add_node("extract_email", self._extract_email_node)
        graph.add_node("approval_gate", self._approval_gate_node)
        graph.add_node("send_email", self._send_email_node)
        graph.add_node("revise_pitch", self._revise_pitch_node)

        graph.add_node("respond", self._respond_node)

        # ── Edges ──────────────────────────────────────────────────────────
        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "classify_intent")

        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
            {
                "find_leads": "research_agent",
                "research_brand": "research_agent",
                "draft_pitch": "fetch_media_kit",
            },
        )

        # Research / leads ReAct loop: agent -> tools -> agent -> end
        graph.add_conditional_edges(
            "research_agent",
            self._should_use_tools,
            {"tools": "research_tools", "end": "respond"},
        )
        graph.add_edge("research_tools", "research_agent")

        # Pitch drafting flow:
        # fetch_media_kit -> research_target_brand -> draft_pitch -> extract_email
        # -> [INTERRUPT: approval_gate] -> conditional:
        #     approved -> send_email -> respond
        #     rejected -> revise_pitch -> extract_email -> approval_gate (loop)
        graph.add_edge("fetch_media_kit", "research_target_brand")
        graph.add_edge("research_target_brand", "draft_pitch")
        graph.add_edge("draft_pitch", "extract_email")
        graph.add_edge("extract_email", "approval_gate")

        graph.add_conditional_edges(
            "approval_gate",
            self._route_by_approval,
            {
                "approved": "send_email",
                "rejected": "revise_pitch",
            },
        )

        graph.add_edge("revise_pitch", "extract_email")
        graph.add_edge("send_email", "respond")
        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: BrandManagerState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    def _last_user_text(self, state: BrandManagerState) -> str:
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        return last_human.content if last_human else ""

    # ── Routers ────────────────────────────────────────────────────────────
    def _route_by_intent(self, state: BrandManagerState) -> str:
        intent = state.get("intent") or "research_brand"
        if intent not in {"find_leads", "research_brand", "draft_pitch"}:
            return "research_brand"
        return intent

    def _route_by_approval(self, state: BrandManagerState) -> str:
        # Default to "approved" so a plain Studio resume sends. User must
        # explicitly set approval_status="rejected" + feedback to revise.
        status = (state.get("approval_status") or "approved").lower()
        if status == "rejected":
            return "rejected"
        return "approved"

    def _should_use_tools(self, state: BrandManagerState):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return "end"

    # ── Node: load per-tenant profile ─────────────────────────────────────
    async def _load_profile_node(self, state: BrandManagerState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    # ── Node: classify user intent ─────────────────────────────────────────
    async def _classify_intent_node(self, state: BrandManagerState):
        profile = self._profile(state)
        prompt = render("brand_manager", "classify.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=self._last_user_text(state)),
        ])
        intent = response.content.strip().strip("`").lower()
        return {"intent": intent}

    # ── research / leads branch (ReAct) ────────────────────────────────────
    async def _research_agent_node(self, state: BrandManagerState):
        profile = self._profile(state)
        system_prompt = render("brand_manager", "research_or_leads.j2", profile=profile)
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = await self.llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    # ── pitch branch ───────────────────────────────────────────────────────
    async def _fetch_media_kit_node(self, state: BrandManagerState):
        profile = self._profile(state)
        try:
            result = await get_channel_stats.ainvoke({
                "channel_id": profile.youtube.channel_id or "",
            })
        except Exception as e:
            result = f"Channel stats unavailable: {e}"
        return {"media_kit": result}

    async def _research_target_brand_node(self, state: BrandManagerState):
        # Use the user's message verbatim as the brand name to research.
        # In a future iteration we'd extract the brand name with the LLM.
        brand_to_research = self._last_user_text(state)
        try:
            result = await research_brand.ainvoke({"brand_name": brand_to_research})
        except Exception as e:
            result = f"Brand research failed: {e}"
        return {"brand_research": result}

    async def _draft_pitch_node(self, state: BrandManagerState):
        profile = self._profile(state)
        context = f"""USER REQUEST:
{self._last_user_text(state)}

BRAND RESEARCH:
{state.get("brand_research") or "Not available"}

MEDIA KIT NUMBERS:
{state.get("media_kit") or "Not available"}"""

        prompt = render("brand_manager", "draft.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        return {"draft": response.content, "approval_status": "pending"}

    async def _revise_pitch_node(self, state: BrandManagerState):
        profile = self._profile(state)
        context = f"""PREVIOUS DRAFT:
{state.get("draft", "")}

USER FEEDBACK:
{state.get("feedback", "No specific feedback")}"""

        prompt = render("brand_manager", "revise.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        return {
            "draft": response.content,
            "approval_status": "pending",
            "feedback": None,
        }

    async def _extract_email_node(self, state: BrandManagerState):
        profile = self._profile(state)
        prompt = render("brand_manager", "extract.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=state.get("draft", "")),
        ])
        try:
            cleaned = response.content.strip().lstrip("```json").rstrip("```").strip()
            parsed = json.loads(cleaned)
            return {
                "subject": parsed.get("subject", ""),
                "body": parsed.get("body", ""),
                "recipient": parsed.get("recipient", "marketing@example.com"),
            }
        except Exception:
            return {
                "subject": f"Sponsor opportunity — {profile.brand.name}",
                "body": state.get("draft", ""),
                "recipient": "marketing@example.com",
            }

    async def _approval_gate_node(self, state: BrandManagerState):
        # No-op router. Exists only as the interrupt point. On resume, the
        # downstream conditional re-evaluates state.approval_status.
        return {}

    async def _send_email_node(self, state: BrandManagerState):
        profile = self._profile(state)
        result = await send_pitch_email.ainvoke({
            "recipient": state.get("recipient", ""),
            "subject": state.get("subject", ""),
            "body": state.get("body", ""),
            "from_name": profile.brand.name,
            "reply_to": profile.brand.primary_email,
        })
        return {"send_result": result, "approval_status": "approved"}

    # ── shared terminal ────────────────────────────────────────────────────
    async def _respond_node(self, state: BrandManagerState):
        intent = state.get("intent")
        if intent == "draft_pitch":
            content = state.get("send_result") or state.get("draft") or "Pitch ready."
        else:
            # Either find_leads or research_brand — the ReAct loop's last assistant
            # message already has the answer; surface it as the user-facing reply.
            last_ai = next(
                (m for m in reversed(state["messages"]) if isinstance(m, AIMessage)),
                None,
            )
            content = (last_ai.content if last_ai else "") or "Done."
        return {"messages": [AIMessage(content=content)]}
