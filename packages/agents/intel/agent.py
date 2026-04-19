from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.agents.intel.tools import (
    get_channel_stats,
    get_video_performance,
    search_trending_topics,
)


class IntelAgentState(BaseAgentState):
    """Extended state for the intel agent workflow."""
    channel_stats: str | None
    video_performance: str | None
    trending_topics: str | None
    analysis: str | None
    brief: str | None


class IntelAgent(BaseAgent):
    slug = "intel"
    name = "Intel Agent"
    description = "Brand intelligence, YouTube analytics, trend spotting, and content ideation."
    model = "claude-sonnet-4-6"

    def __init__(self):
        self.llm = ChatAnthropic(model=self.model)
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(IntelAgentState)

        graph.add_node("load_profile", self._load_profile_node)
        graph.add_node("interpret", self._interpret_node)
        graph.add_node("fetch_channel", self._fetch_channel_node)
        graph.add_node("fetch_videos", self._fetch_videos_node)
        graph.add_node("spot_trends", self._spot_trends_node)
        graph.add_node("analyze", self._analyze_node)
        graph.add_node("format_brief", self._format_brief_node)
        graph.add_node("respond", self._respond_node)

        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "interpret")
        graph.add_edge("interpret", "fetch_channel")
        graph.add_edge("fetch_channel", "fetch_videos")
        graph.add_edge("fetch_videos", "spot_trends")
        graph.add_edge("spot_trends", "analyze")
        graph.add_edge("analyze", "format_brief")
        graph.add_edge("format_brief", "respond")
        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: IntelAgentState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    # ── Node: load per-tenant profile ─────────────────────────────────────
    async def _load_profile_node(self, state: IntelAgentState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    # ── Node: acknowledge intent (no-op LLM ping for Studio visibility) ───
    async def _interpret_node(self, state: IntelAgentState):
        profile = self._profile(state)
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        user_text = last_human.content if last_human else "run brand intel cycle"

        prompt = render("intel", "interpret.j2", profile=profile)
        await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_text),
        ])
        return {}

    # ── Node: fetch channel stats (per-tenant channel_id) ────────────────
    async def _fetch_channel_node(self, state: IntelAgentState):
        profile = self._profile(state)
        try:
            result = await get_channel_stats.ainvoke({
                "channel_id": profile.youtube.channel_id or "",
            })
        except Exception as e:
            result = f"Channel stats unavailable: {e}"
        return {"channel_stats": result}

    # ── Node: fetch recent video performance ──────────────────────────────
    async def _fetch_videos_node(self, state: IntelAgentState):
        profile = self._profile(state)
        try:
            result = await get_video_performance.ainvoke({
                "channel_id": profile.youtube.channel_id or "",
                "limit": 10,
            })
        except Exception as e:
            result = f"Video performance unavailable: {e}"
        return {"video_performance": result}

    # ── Node: search niche-specific trending topics ───────────────────────
    async def _spot_trends_node(self, state: IntelAgentState):
        profile = self._profile(state)
        try:
            result = await search_trending_topics.ainvoke({
                "focus": profile.niche.trends_query_focus,
            })
        except Exception as e:
            result = f"Trend data unavailable: {e}"
        return {"trending_topics": result}

    # ── Node: LLM synthesizes all three data sources ──────────────────────
    async def _analyze_node(self, state: IntelAgentState):
        profile = self._profile(state)
        context = f"""
CHANNEL STATS:
{state.get("channel_stats") or "Not available"}

RECENT VIDEO PERFORMANCE:
{state.get("video_performance") or "Not available"}

TRENDING TOPICS:
{state.get("trending_topics") or "Not available"}
""".strip()

        prompt = render("intel", "analyze.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=context),
        ])
        return {"analysis": response.content}

    # ── Node: format into the Brand Brief structure ────────────────────────
    async def _format_brief_node(self, state: IntelAgentState):
        profile = self._profile(state)
        prompt = render("intel", "format.j2", profile=profile)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=state.get("analysis", "")),
        ])
        return {"brief": response.content}

    # ── Node: stream the brief back to the user ────────────────────────────
    async def _respond_node(self, state: IntelAgentState):
        brief = state.get("brief") or "Intel cycle complete — no brief generated."
        return {"messages": [AIMessage(content=brief)]}
