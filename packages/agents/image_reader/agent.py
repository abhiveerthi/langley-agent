"""
Image Reader / Voice — reads screenshots with Claude's native vision and
turns voice notes into text the rest of the system can handle.

Two capabilities, three intents:

  read_image  — the user attached one or more screenshots (YouTube analytics,
                competitor channels, news articles, social posts, bills /
                lawsuits, infographics). Claude's vision reads them directly —
                no external OCR API — extracts the data, summarizes, analyzes,
                and (for multi-shot uploads) reasons about the trend across
                them. The structured analysis is rendered to Markdown and
                best-effort exported to Storage as kind="report" so the creator
                can reopen it from /app/storage. A separate agent turns reports
                into PDFs; we only emit clean Markdown here.
  transcribe  — the user sent a voice note. The audio bytes ride in on
                `state.metadata.audio` ({"bytes_b64", "content_type"}); we
                transcribe to text (packages/agents/core/transcription.py),
                splice the transcript in as the user's message, and answer it
                as a normal request.
  general     — anything text-only (questions about a prior analysis, "what can
                you read for me", etc.).

Graph shape (mirrors the other agents so the orchestrator drives it the same):

  START → load_profile → load_peer_context → classify_intent
                                                   ↓
                       ┌───────────────────────────┼────────────────────┐
                  read_image                    transcribe            general
                       ↓                              ↓                   ↓
                  analyze_image                  transcribe_audio  ──────►│
                       ↓                                                  │
                  persist_report                                         │
                       ↓                                                  ↓
                       └──────────────────────────► respond ◄────── general_answer

There are no write tools and no HITL gate — reading an image and transcribing
audio are read-only, so nothing is interrupted.
"""
from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END, START
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field

from packages.agents.core.base import BaseAgent, BaseAgentState
from packages.agents.core.peer_context import _is_real_uuid
from packages.agents.core.profile import OrgProfile, load_profile
from packages.agents.core.templates import render
from packages.integrations.context import current_supabase


# ── Structured output schema ──────────────────────────────────────────────
# Doubles as the JSON contract the frontend can render as an analysis card.
# `analyze_image` fills it via ChatAnthropic.with_structured_output(ImageAnalysis).
class ExtractedDatum(BaseModel):
    label: str = Field(description="What the figure is — 'Views (28d)', 'CTR', 'Subscribers gained'.")
    value: str = Field(description="The value exactly as shown, including units / % / currency.")


class TrendInsight(BaseModel):
    metric: str = Field(description="The metric trending — 'Monthly views', 'Subscribers', 'Water temp'.")
    direction: str = Field(description="'up' | 'down' | 'flat' — as shown by the data, never inferred.")
    assessment: str = Field(
        description="What this trend is WORTH: is it meaningful or noise, how "
        "long has it run, and what it implies for the creator's positioning."
    )


class ImageAnalysis(BaseModel):
    title: str = Field(description="Short title for the report, e.g. 'YouTube analytics — last 28 days'.")
    summary: str = Field(description="2–4 sentence plain-language summary of what the image(s) show.")
    data_points: list[ExtractedDatum] = Field(
        default_factory=list,
        description="Every concrete figure/metric/quote read off the image(s). Empty if none.",
    )
    analysis: str = Field(
        description="The interpretation — what the data means, notable patterns, and (for "
        "multiple screenshots) the trend across them.",
    )
    trends: list[TrendInsight] = Field(
        default_factory=list,
        description="Long-term trends visible in the data, each with a value "
        "judgment — not just direction. Empty when the image has no time axis.",
    )
    competitor_position: str = Field(
        default="",
        description="When the image(s) show peer/competitor channels: how the "
        "creator stacks up (subs, monthly views, momentum) and the positioning "
        "takeaway. Empty when not a competitor comparison.",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="0–5 concrete next actions the creator could take based on what was read.",
    )


# ── Extended state ────────────────────────────────────────────────────────
class ImageReaderState(BaseAgentState):
    """Extends BaseAgentState with intent routing + structured analysis output."""
    intent: str | None        # "read_image" | "transcribe" | "general"
    analysis: dict | None      # ImageAnalysis.model_dump(), surfaced for the frontend


class ImageReaderAgent(BaseAgent):
    slug = "image-reader"
    name = "Image Reader"
    description = (
        "Reads screenshots with native vision — YouTube analytics, competitor "
        "channels, articles, social posts, bills, infographics — extracts the "
        "data, analyzes it (including trends across multiple shots), and files a "
        "report. Also transcribes voice notes into text."
    )
    # Sonnet for vision quality — OCR/analysis on dense analytics screenshots
    # needs the stronger model, not Haiku.
    model = "claude-sonnet-4-6"
    # The DM front door remembers: auto-recall before each turn + a turn
    # summary at run end, and the explicit remember_fact tool writes here
    # too (all under this agent's slug — see core/memory.py).
    memory_enabled = True

    def get_structured_outputs(self, state: dict, visited_nodes: list[str]) -> dict[str, dict]:
        """Surface the ImageAnalysis as a structured frontend card — but only
        when `analyze_image` actually ran this turn. The analysis field
        persists on state across turns (LangGraph checkpointer), so gating on
        visited_nodes prevents re-rendering the same card on follow-ups."""
        out: dict[str, dict] = {}
        if "analyze_image" in visited_nodes and state.get("analysis"):
            out["analysis"] = state["analysis"]
        return out

    def __init__(self):
        # Vision content rides in on HumanMessage content blocks; one
        # ChatAnthropic instance handles classification, vision analysis,
        # and free-form answers. The general lane additionally binds
        # `delegate_task` so the reader can act as the suite's middle man.
        self.llm = ChatAnthropic(model=self.model)
        from packages.agents.image_reader.tools import get_image_reader_tools

        self.tools = get_image_reader_tools()
        super().__init__()

    def build_graph(self) -> StateGraph:
        graph = StateGraph(ImageReaderState)

        graph.add_node("load_profile", self._load_profile_node)
        # peer_context: latest Strategist brief etc. — lets an analytics
        # screenshot be read against what the channel was already planning.
        graph.add_node("load_peer_context", self._load_peer_context_node)
        # load_memory: recall relevant long-term notes (facts the creator
        # asked us to remember, past reads) — hydrates metadata.memories.
        graph.add_node("load_memory", self._load_memory_node)
        graph.add_node("classify_intent", self._classify_intent_node)

        graph.add_node("analyze_image", self._analyze_image_node)
        graph.add_node("persist_report", self._persist_report_node)
        graph.add_node("transcribe_audio", self._transcribe_audio_node)
        graph.add_node("compile_report", self._compile_report_node)
        graph.add_node("general_answer", self._general_answer_node)
        graph.add_node("respond", self._respond_node)

        graph.add_edge(START, "load_profile")
        graph.add_edge("load_profile", "load_peer_context")
        graph.add_edge("load_peer_context", "load_memory")
        graph.add_edge("load_memory", "classify_intent")

        graph.add_conditional_edges(
            "classify_intent",
            self._route_by_intent,
            {
                "read_image": "analyze_image",
                "transcribe": "transcribe_audio",
                "compile_report": "compile_report",
                "general": "general_answer",
            },
        )

        graph.add_edge("compile_report", "respond")
        graph.add_edge("analyze_image", "persist_report")
        graph.add_edge("persist_report", "respond")
        # A transcribed voice note becomes a normal text question — answer it.
        graph.add_edge("transcribe_audio", "general_answer")
        graph.add_edge("general_answer", "respond")
        graph.add_edge("respond", END)

        return graph

    # ── Helpers ────────────────────────────────────────────────────────────
    def _profile(self, state: ImageReaderState) -> OrgProfile:
        raw = (state.get("metadata") or {}).get("profile")
        if not raw:
            return load_profile(state.get("org_id"))
        return OrgProfile.model_validate(raw)

    def _peer_context(self, state: ImageReaderState) -> dict:
        return (state.get("metadata") or {}).get("peer_context") or {}

    def _last_human_message(self, state: ImageReaderState) -> HumanMessage | None:
        return next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )

    def _last_user_text(self, state: ImageReaderState) -> str:
        """The text portion of the last human message. A vision message's
        content is a list of blocks (text + image); flatten just the text so
        the classifier and prompts get a clean string."""
        last = self._last_human_message(state)
        if last is None:
            return ""
        return _text_from_content(last.content)

    def _render_report(self, state: ImageReaderState, analysis: dict) -> str:
        """Render an ImageAnalysis dict to clean Markdown via the
        analysis_report.j2 template. One render shared by the chat reply and
        the Storage export so they never drift."""
        return render(
            "image_reader",
            "analysis_report.j2",
            profile=self._profile(state),
            analysis=analysis,
        ).rstrip() + "\n"

    def _has_image(self, state: ImageReaderState) -> bool:
        """True when the last human message carries at least one image block.

        Image content reaches us as Anthropic-format content blocks already on
        the HumanMessage — the orchestrator (or Slack ingestion) builds them
        as `{"type": "image", "source": {...}}`. We don't fetch or decode
        anything here; we just detect their presence to route to vision."""
        last = self._last_human_message(state)
        return _content_has_image(last.content if last else None)

    # ── Routers ────────────────────────────────────────────────────────────
    def _route_by_intent(self, state: ImageReaderState) -> str:
        intent = (state.get("intent") or "general").lower()
        if intent not in {"read_image", "transcribe", "compile_report", "general"}:
            return "general"
        return intent

    # ── Nodes ──────────────────────────────────────────────────────────────
    async def _load_profile_node(self, state: ImageReaderState):
        profile = load_profile(state.get("org_id"))
        existing_meta = state.get("metadata") or {}
        return {
            "metadata": {
                **existing_meta,
                "profile": profile.model_dump(mode="json"),
            }
        }

    async def _classify_intent_node(self, state: ImageReaderState):
        """Route by signal first, LLM second.

        Attachments are unambiguous: an image present → read_image; audio
        present → transcribe. We only fall back to the LLM classifier for
        text-only messages (read a prior analysis vs general chatter), and
        even then default to general — there's nothing to read."""
        if self._has_image(state):
            return {"intent": "read_image"}
        if (state.get("metadata") or {}).get("audio"):
            return {"intent": "transcribe"}

        profile = self._profile(state)
        prompt = render("image_reader", "classify.j2", profile=profile)
        # `marcus:silent` keeps the bare-slug classifier response out of chat.
        response = await self.llm.with_config(tags=["marcus:silent"]).ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=self._last_user_text(state)),
        ])
        raw = response.content.strip().strip("`").lower()
        intent = raw if raw in {"read_image", "transcribe", "compile_report", "general"} else "general"
        return {"intent": intent}

    async def _analyze_image_node(self, state: ImageReaderState):
        """Run native-vision OCR + analysis over the attached screenshot(s).

        The image blocks live on the last HumanMessage already in
        Anthropic content-block format, so we pass the message straight to
        ChatAnthropic with `with_structured_output(ImageAnalysis)` — the
        model reads the pixels and fills the schema in one pass. Multiple
        images in one message are analyzed together, which is how the
        "trend over time" case (several analytics screenshots) works.
        """
        profile = self._profile(state)
        system_prompt = render(
            "image_reader",
            "system.j2",
            profile=profile,
            intent="read_image",
            peer_context=self._peer_context(state),
        )
        last_human = self._last_human_message(state)
        # Defensive: router only sends us here when an image exists, but if it
        # somehow didn't, degrade to a clear ask rather than a vision call on
        # text-only content.
        if last_human is None or not _content_has_image(last_human.content):
            return {
                "messages": [AIMessage(content=(
                    "I didn't get an image to read. Attach a screenshot "
                    "(analytics, a competitor channel, an article, a post) and I'll analyze it."
                ))]
            }

        structured_llm = self.llm.with_structured_output(ImageAnalysis)
        analysis: ImageAnalysis = await structured_llm.ainvoke([
            SystemMessage(content=system_prompt),
            last_human,
        ])
        return {"analysis": analysis.model_dump(mode="json")}

    async def _persist_report_node(self, state: ImageReaderState):
        """Best-effort export of the analysis Markdown to Storage as a report.

        Mirrors the Strategist's brief export: the structured object already
        streams to the frontend; this drops a human-readable copy into the
        org-assets bucket so the creator can reopen it from /app/storage. A
        separate agent renders reports into PDFs — we only emit Markdown.

        No-op in dev mode (no Supabase / non-UUID org) and on any storage
        error — never breaks the user-facing reply.
        """
        analysis = state.get("analysis")
        org_id = state.get("org_id") or ""
        supabase = current_supabase.get()
        if not analysis or supabase is None or not _is_real_uuid(org_id):
            return {}

        from datetime import datetime, timezone
        from packages.agents.core.storage_export import export_to_storage

        md_body = self._render_report(state, analysis)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        await export_to_storage(
            org_id=org_id,
            agent_slug=self.slug,
            kind="report",
            filename=f"image-analysis-{ts}.md",
            content=md_body,
            mime_type="text/markdown",
            tags=["image-analysis"],
        )
        # PDF sibling (product clarification: "PDF-style outputs are
        # valuable" — bills, lawsuits, infographics become analyzable,
        # shareable documents he can reference in videos / email blasts).
        from packages.agents.core.storage_export import export_pdf_to_storage

        await export_pdf_to_storage(
            org_id=org_id,
            agent_slug=self.slug,
            kind="report",
            filename=f"image-analysis-{ts}.pdf",
            title=analysis.get("title") or "Image analysis",
            markdown_body=md_body,
            brand_name=self._profile(state).brand.name,
            tags=["image-analysis"],
        )
        return {}

    async def _transcribe_audio_node(self, state: ImageReaderState):
        """Turn a voice note into text and splice it in as the user's message.

        Audio rides in on `state.metadata.audio`:
            {"bytes_b64": "<base64>", "content_type": "audio/ogg"}
        We decode, transcribe via the env-selected backend, and append a new
        HumanMessage carrying the transcript so `general_answer` (and the rest
        of the system) treats it exactly like a typed message.

        If no backend is configured, transcription.py raises
        TranscriptionUnavailable — we surface that as a clear AIMessage and
        skip straight to respond-style handling instead of crashing the run.
        """
        import base64

        from packages.agents.core.transcription import (
            TranscriptionUnavailable,
            transcribe_audio,
        )

        audio = (state.get("metadata") or {}).get("audio") or {}
        b64 = audio.get("bytes_b64")
        if not b64:
            return {"messages": [HumanMessage(content="(empty voice note)")]}

        try:
            raw = base64.b64decode(b64)
            transcript = await transcribe_audio(
                raw, content_type=audio.get("content_type")
            )
        except TranscriptionUnavailable as e:
            return {
                "intent": "general",
                "messages": [AIMessage(content=(
                    f"I couldn't transcribe that voice note — {e} "
                    "You can also just type your message."
                ))],
            }
        except Exception as e:  # noqa: BLE001
            return {
                "intent": "general",
                "messages": [AIMessage(content=f"Transcription failed: {e}")],
            }

        transcript = transcript.strip()
        if not transcript:
            return {"messages": [HumanMessage(content="(the voice note had no audible speech)")]}

        # Surface what we heard, then hand the transcript to the normal answer
        # path as a fresh user turn.
        return {
            "intent": "general",
            "messages": [HumanMessage(content=transcript)],
        }

    async def _compile_report_node(self, state: ImageReaderState):
        """Roll the window's filed analyses into one research report.

        The product loop: Braden feeds daily screenshots (channel stats,
        competitor pages, fish-tracking data); each becomes a filed report;
        this intent compiles a 30–60 day window of them into a single
        detailed document, exported as Markdown + PDF for reuse in videos
        or email blasts."""
        from datetime import datetime, timezone

        from packages.agents.image_reader.tools import (
            download_report_texts,
            fetch_recent_image_reports,
            parse_window_days,
        )

        org_id = state.get("org_id") or ""
        last = self._last_human_message(state)
        days = parse_window_days(_text_from_content(last.content) if last else "")

        rows = fetch_recent_image_reports(org_id, days)
        texts = await download_report_texts(rows) if rows else []
        if not texts:
            return {"messages": [AIMessage(content=(
                f"I don't have any filed image analyses from the last {days} "
                f"days to compile. Send me the daily screenshots as they come "
                f"in — each one gets filed, and the research report builds "
                f"itself from the archive."
            ))]}

        profile = self._profile(state)
        system_prompt = render(
            "image_reader",
            "research_report.j2",
            profile=profile,
            days=days,
            report_count=len(texts),
        )
        corpus = "\n\n".join(texts)
        response = await self.llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"Compile the {days}-day research report from these "
                f"{len(texts)} filed analyses:\n\n{corpus}"
            )),
        ])
        md_body = response.content if isinstance(response.content, str) else str(response.content)

        # Best-effort archive (Markdown + PDF), same posture as persist_report.
        supabase = current_supabase.get()
        if supabase is not None and _is_real_uuid(org_id):
            from packages.agents.core.storage_export import (
                export_pdf_to_storage,
                export_to_storage,
            )

            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
            await export_to_storage(
                org_id=org_id, agent_slug=self.slug, kind="report",
                filename=f"research-report-{days}d-{ts}.md",
                content=md_body, mime_type="text/markdown",
                tags=["research-report", f"{days}d"],
            )
            await export_pdf_to_storage(
                org_id=org_id, agent_slug=self.slug, kind="report",
                filename=f"research-report-{days}d-{ts}.pdf",
                title=f"{profile.brand.name} — {days}-day research report",
                markdown_body=md_body, brand_name=profile.brand.name,
                tags=["research-report", f"{days}d"],
            )

        return {"messages": [response]}

    async def _general_answer_node(self, state: ImageReaderState):
        """Free-form text answer — used for the general intent and as the
        continuation after a voice note is transcribed."""
        profile = self._profile(state)
        # If a prior node already produced an apology/error AIMessage (e.g.
        # transcription unavailable), don't talk over it — let respond surface it.
        last = state["messages"][-1] if state["messages"] else None
        if isinstance(last, AIMessage) and last.content:
            return {}

        system_prompt = render(
            "image_reader",
            "system.j2",
            profile=profile,
            intent="general",
            peer_context=self._peer_context(state),
            memories=(state.get("metadata") or {}).get("memories") or [],
        )
        messages = [SystemMessage(content=system_prompt)] + state["messages"]

        # One bounded tool round: the reader can delegate follow-up work,
        # send an ad-hoc email, or save a fact, then finishes its answer.
        llm_with_tools = self.llm.bind_tools(self.tools) if self.tools else self.llm
        response = await llm_with_tools.ainvoke(messages)
        if not getattr(response, "tool_calls", None):
            return {"messages": [response]}

        from langchain_core.messages import ToolMessage

        # Cap executions per round: the transcript/screenshot content that
        # reaches this node is external input, and these tools act on the
        # world (tasks on other agents' boards, outbound email, memory
        # writes) — an injected "delegate 50 tasks" / "send 50 emails" must
        # not fan out unbounded.
        MAX_TOOL_CALLS = 3
        tool_by_name = {t.name: t for t in self.tools}
        tool_msgs: list[ToolMessage] = []
        for i, call in enumerate(response.tool_calls):
            if i >= MAX_TOOL_CALLS:
                result = f"Skipped: at most {MAX_TOOL_CALLS} tool actions per message."
            else:
                impl = tool_by_name.get(call["name"])
                if impl is None:
                    result = f"Unknown tool {call['name']!r}."
                else:
                    try:
                        result = await impl.ainvoke(call["args"])
                    except Exception as e:  # noqa: BLE001 — surface, don't crash
                        result = f"Tool failed: {e}"
            tool_msgs.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

        # Final pass with the PLAIN llm (tools unbound): the closing message
        # can't emit new tool_calls — an unexecuted tool_call stored on the
        # thread would 400 the next turn's Anthropic request.
        followup = await self.llm.ainvoke(messages + [response, *tool_msgs])
        return {"messages": [response, *tool_msgs, followup]}

    async def _respond_node(self, state: ImageReaderState):
        # If THIS run already produced an assistant message (general answer,
        # compiled research report, transcription apology), surface it and
        # stop. This check comes FIRST because `analysis` is a LastValue
        # channel that persists across turns on the checkpointer thread — an
        # unconditional analysis render here would re-emit turn 1's image
        # report after every later turn in the same thread.
        last = state["messages"][-1] if state["messages"] else None
        if isinstance(last, AIMessage) and last.content:
            content = last.content
        elif state.get("analysis"):
            # Fresh analyze_image path (its nodes emit no AIMessage — the
            # last message is still the user's). Render the structured
            # analysis as Markdown; same render as the Storage export.
            content = self._render_report(state, state["analysis"])
        else:
            last_ai = next(
                (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.content),
                None,
            )
            content = (last_ai.content if last_ai else "") or "Done."
        # Persist a concise turn summary to long-term memory (truncated —
        # a full analysis report doesn't belong in one memory row). Explicit
        # remember_fact saves already happened in their tool call.
        await self._persist_turn_memory(state, takeaway=str(content)[:2000])
        return {"messages": [AIMessage(content=content)]}


# ── Module-level content helpers ──────────────────────────────────────────
def _text_from_content(content) -> str:
    """Flatten a LangChain message `content` (string or list of blocks) into
    its plain text. Image blocks are dropped; only text survives."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(p for p in parts if p).strip()
    return ""


def _content_has_image(content) -> bool:
    """True if a message `content` list carries an image block.

    Accepts both Anthropic's native shape (`{"type": "image", "source": …}`)
    and the LangChain `image_url` shape, since either can reach the agent
    depending on how the message was constructed."""
    if not isinstance(content, list):
        return False
    for block in content:
        if isinstance(block, dict) and block.get("type") in {"image", "image_url"}:
            return True
    return False
