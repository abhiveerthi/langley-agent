from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.research.tools import (
    search_political_news,
    get_polling_data,
    get_youtube_comments,
)


class ResearchAgentState(BaseAgentState):
    """Extended state for the research agent workflow."""
    research_topic: str | None
    news_data: str | None
    polling_data: str | None
    youtube_data: str | None
    analysis: str | None
    report: str | None


class ResearchAgent(BaseAgent):
    slug = "research"
    name = "Research Agent"
    description = "Intelligence gathering, analysis, and content strategy."
    model = "claude-sonnet-4-6"

    def __init__(self):
        self.llm = ChatAnthropic(model=self.model)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(ResearchAgentState)

        graph.add_node("load_profile", self._load_profile_node)
        graph.add_node("interpret", self._interpret_node)
        graph.add_node("collect_news", self._collect_news_node)
        graph.add_node("collect_polling", self._collect_polling_node)
        graph.add_node("collect_youtube", self._collect_youtube_node)
        graph.add_node("analyze", self._analyze_node)
        graph.add_node("format_report", self._format_report_node)
        graph.add_node("respond", self._respond_node)

        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "interpret")
        graph.add_edge("interpret", "collect_news")
        graph.add_edge("collect_news", "collect_polling")
        graph.add_edge("collect_polling", "collect_youtube")
        graph.add_edge("collect_youtube", "analyze")
        graph.add_edge("analyze", "format_report")
        graph.add_edge("format_report", "respond")
        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: ResearchAgentState) -> OrgProfile:
        """Reconstruct the OrgProfile from state.metadata."""
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            # Defensive: should not happen because load_profile runs first.
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    # ── Node: load per-tenant profile from YAML into state.metadata ───────
    async def _load_profile_node(self, state: ResearchAgentState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    # ── Node: extract topic from user message ──────────────────────────────
    async def _interpret_node(self, state: ResearchAgentState):
        profile = self._profile(state)
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        user_text = last_human.content if last_human else "run full research cycle"

        prompt = render("research", "interpret.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_text),
        ])
        return {"research_topic": response.content.strip()}

    # ── Node: collect news via Perplexity (per-tenant categories) ──────────
    async def _collect_news_node(self, state: ResearchAgentState):
        profile = self._profile(state)
        categories = [c.model_dump() for c in profile.niche.research_categories]
        try:
            result = await search_political_news.ainvoke({
                "categories": categories,
                "category": "all",
            })
        except Exception as e:
            result = f"News collection failed: {e}"
        return {"news_data": result}

    # ── Node: collect polling data ─────────────────────────────────────────
    async def _collect_polling_node(self, state: ResearchAgentState):
        try:
            result = await get_polling_data.ainvoke({})
        except Exception as e:
            result = f"Polling collection failed: {e}"
        return {"polling_data": result}

    # ── Node: collect YouTube comments (per-tenant channel_id) ────────────
    async def _collect_youtube_node(self, state: ResearchAgentState):
        profile = self._profile(state)
        try:
            result = await get_youtube_comments.ainvoke({
                "channel_id": profile.youtube.channel_id or "",
                "max_videos": 5,
            })
        except Exception as e:
            result = f"YouTube collection failed: {e}"
        return {"youtube_data": result}

    # ── Node: LLM synthesizes all collected data ───────────────────────────
    async def _analyze_node(self, state: ResearchAgentState):
        profile = self._profile(state)
        context = f"""
TOPIC: {state.get("research_topic", "General research cycle")}

NEWS DATA:
{state.get("news_data") or "Not available"}

POLLING DATA:
{state.get("polling_data") or "Not available"}

YOUTUBE COMMENTS:
{state.get("youtube_data") or "Not available"}
""".strip()

        prompt = render("research", "analyze.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        return {"analysis": response.content}

    # ── Node: format analysis into the final brief structure ───────────────
    async def _format_report_node(self, state: ResearchAgentState):
        profile = self._profile(state)
        prompt = render("research", "format.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=state.get("analysis", "")),
        ])
        return {"report": response.content}

    # ── Node: append the final report to messages so it streams to the UI ──
    async def _respond_node(self, state: ResearchAgentState):
        report = state.get("report") or "Research cycle complete — no report generated."
        return {"messages": [AIMessage(content=report)]}
