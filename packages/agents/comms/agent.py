import json
from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.comms.tools import (
    find_partnership_leads,
    search_content_trends,
    send_email,
)


class CommsAgentState(BaseAgentState):
    """Extended state for the comms agent workflow."""
    intent: str | None           # "draft_email" | "find_leads" | "content_trends"
    draft: str | None            # current email draft (subject + body)
    recipient: str | None
    subject: str | None
    body: str | None
    approval_status: str | None  # "pending" | "approved" | "rejected"
    feedback: str | None         # revision feedback when rejected
    leads: str | None
    trends: str | None
    send_result: str | None


class CommsAgent(BaseAgent):
    slug = "comms"
    name = "Comms Agent"
    description = "Email marketing, lead generation, and content strategy."
    model = "claude-sonnet-4-6"

    # Pause for human approval before send_email actually fires.
    # The pause point is `approval_gate` (a no-op router) so the downstream
    # conditional edge can re-evaluate state.approval_status on resume.
    @property
    def interrupt_before_nodes(self) -> list[str]:
        return ["approval_gate"]

    def __init__(self):
        self.llm = ChatAnthropic(model=self.model)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(CommsAgentState)

        # Profile loader (runs first for every branch)
        graph.add_node("load_profile", self._load_profile_node)

        # Intent routing
        graph.add_node("classify_intent", self._classify_intent_node)

        # Email branch
        graph.add_node("draft_email", self._draft_email_node)
        graph.add_node("extract_email", self._extract_email_node)
        graph.add_node("approval_gate", self._approval_gate_node)
        graph.add_node("send_email", self._send_email_node)
        graph.add_node("revise_email", self._revise_email_node)

        # Other branches
        graph.add_node("find_leads", self._find_leads_node)
        graph.add_node("content_trends", self._content_trends_node)

        # Shared terminal
        graph.add_node("respond", self._respond_node)

        # ── Edges ──────────────────────────────────────────────────────────
        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "classify_intent")

        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
            {
                "draft_email": "draft_email",
                "find_leads": "find_leads",
                "content_trends": "content_trends",
            },
        )

        # Email flow:
        #   draft -> extract -> [INTERRUPT: approval_gate] -> conditional:
        #       approved -> send_email -> respond
        #       rejected -> revise_email -> extract -> approval_gate (loop)
        graph.add_edge("draft_email", "extract_email")
        graph.add_edge("extract_email", "approval_gate")

        graph.add_conditional_edges(
            "approval_gate",
            self._route_by_approval,
            {
                "approved": "send_email",
                "rejected": "revise_email",
            },
        )

        graph.add_edge("revise_email", "extract_email")
        graph.add_edge("send_email", "respond")

        graph.add_edge("find_leads", "respond")
        graph.add_edge("content_trends", "respond")
        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: CommsAgentState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    # ── Routers ────────────────────────────────────────────────────────────
    def _route_by_intent(self, state: CommsAgentState) -> str:
        intent = state.get("intent") or "content_trends"
        if intent not in {"draft_email", "find_leads", "content_trends"}:
            return "content_trends"
        return intent

    def _route_by_approval(self, state: CommsAgentState) -> str:
        # Default to "approved" so a plain Studio resume sends the email.
        # User must explicitly set approval_status="rejected" in state to revise.
        status = (state.get("approval_status") or "approved").lower()
        if status == "rejected":
            return "rejected"
        return "approved"

    # ── Node: load per-tenant profile ─────────────────────────────────────
    async def _load_profile_node(self, state: CommsAgentState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    # ── Node: classify user intent ─────────────────────────────────────────
    async def _classify_intent_node(self, state: CommsAgentState):
        profile = self._profile(state)
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        user_text = last_human.content if last_human else ""

        prompt = render("comms", "classify.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_text),
        ])
        intent = response.content.strip().strip("`").lower()
        return {"intent": intent}

    # ── Node: draft a marketing email ──────────────────────────────────────
    async def _draft_email_node(self, state: CommsAgentState):
        profile = self._profile(state)
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        user_text = last_human.content if last_human else ""

        prompt = render("comms", "draft.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_text),
        ])
        return {
            "draft": response.content,
            "approval_status": "pending",
        }

    # ── Node: revise the draft based on user feedback ──────────────────────
    async def _revise_email_node(self, state: CommsAgentState):
        profile = self._profile(state)
        context = f"""PREVIOUS DRAFT:
{state.get("draft", "")}

USER FEEDBACK:
{state.get("feedback", "No specific feedback")}"""

        prompt = render("comms", "revise.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        return {
            "draft": response.content,
            "approval_status": "pending",
            "feedback": None,
        }

    # ── Node: parse draft into structured subject/body/recipient fields ────
    async def _extract_email_node(self, state: CommsAgentState):
        profile = self._profile(state)
        prompt = render("comms", "extract.j2", profile=profile)
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
                "recipient": parsed.get("recipient", profile.brand.primary_email),
            }
        except Exception:
            return {
                "subject": f"{profile.brand.name} Update",
                "body": state.get("draft", ""),
                "recipient": profile.brand.primary_email,
            }

    # ── Node: approval gate (no-op, interrupt lands here) ─────────────────
    async def _approval_gate_node(self, state: CommsAgentState):
        return {}

    # ── Node: actually send the email (gated by interrupt) ────────────────
    async def _send_email_node(self, state: CommsAgentState):
        result = await send_email.ainvoke({
            "recipient": state.get("recipient", ""),
            "subject": state.get("subject", ""),
            "body": state.get("body", ""),
        })
        return {
            "send_result": result,
            "approval_status": "approved",
        }

    # ── Node: find partnership leads (per-tenant category + descriptor) ───
    async def _find_leads_node(self, state: CommsAgentState):
        profile = self._profile(state)
        category = (
            profile.niche.lead_categories[0]
            if profile.niche.lead_categories
            else "General"
        )
        try:
            result = await find_partnership_leads.ainvoke({
                "category": category,
                "niche_descriptor": (
                    f"{profile.niche.audience_descriptor} YouTube channel"
                ),
            })
        except Exception as e:
            result = f"Lead search failed: {e}"
        return {"leads": result}

    # ── Node: fetch niche-scoped content trends ───────────────────────────
    async def _content_trends_node(self, state: CommsAgentState):
        profile = self._profile(state)
        try:
            result = await search_content_trends.ainvoke({
                "focus": profile.niche.trends_query_focus,
            })
        except Exception as e:
            result = f"Trend search failed: {e}"
        return {"trends": result}

    # ── Node: emit the final user-facing message ──────────────────────────
    async def _respond_node(self, state: CommsAgentState):
        intent = state.get("intent")
        if intent == "draft_email":
            content = state.get("send_result") or state.get("draft") or "Email ready."
        elif intent == "find_leads":
            content = state.get("leads") or "No leads found."
        else:
            content = state.get("trends") or "No trends found."
        return {"messages": [AIMessage(content=content)]}
