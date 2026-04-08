from datetime import datetime, timezone
from typing import Any, AsyncIterator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def calculate_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    costs = {
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
        "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    }
    model_cost = costs.get(model, {"input": 1.0, "output": 5.0})
    return (input_tokens * model_cost["input"] + output_tokens * model_cost["output"]) / 1_000_000


class RunTracker:
    """Wraps an agent run and emits structured events for SSE + persistence."""

    def __init__(self, run_id: str, org_id: str, supabase: Any):
        self.run_id = run_id
        self.org_id = org_id
        self.supabase = supabase
        self.steps: list[dict] = []
        self.tool_calls: list[dict] = []
        self.input_tokens = 0
        self.output_tokens = 0

    async def track(self, agent, input_data: dict, thread_id: str) -> AsyncIterator[dict]:
        """Stream agent events, persisting state as we go."""
        try:
            event_stream = await agent.run(input_data, thread_id, stream=True)
            async for event in event_stream:
                event_type = event.get("event", "")

                if event_type == "on_chain_start":
                    self.steps.append({
                        "node": event.get("name", ""),
                        "started_at": now_iso(),
                        "input": event.get("data", {}).get("input"),
                    })
                    yield {
                        "type": "agent_thinking",
                        "data": {"node": event.get("name", ""), "step_index": len(self.steps) - 1},
                    }

                elif event_type == "on_chain_end":
                    name = event.get("name", "")
                    for step in reversed(self.steps):
                        if step["node"] == name and "completed_at" not in step:
                            step["output"] = event.get("data", {}).get("output")
                            step["completed_at"] = now_iso()
                            break

                elif event_type == "on_tool_start":
                    tc = {
                        "id": event.get("run_id", ""),
                        "tool": event.get("name", ""),
                        "input": event.get("data", {}).get("input"),
                        "status": "running",
                        "started_at": now_iso(),
                    }
                    self.tool_calls.append(tc)
                    yield {"type": "tool_call_start", "data": tc}

                elif event_type == "on_tool_end":
                    name = event.get("name", "")
                    for tc in reversed(self.tool_calls):
                        if tc["tool"] == name and tc["status"] == "running":
                            tc["output"] = event.get("data", {}).get("output")
                            tc["status"] = "success"
                            tc["completed_at"] = now_iso()
                            yield {"type": "tool_call_end", "data": tc}
                            break

                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield {"type": "token", "data": {"content": chunk.content}}

                elif event_type == "on_chat_model_end":
                    usage = event.get("data", {}).get("output")
                    if usage and hasattr(usage, "usage_metadata"):
                        meta = usage.usage_metadata
                        self.input_tokens += getattr(meta, "input_tokens", 0)
                        self.output_tokens += getattr(meta, "output_tokens", 0)

                # Persist incremental state
                await self._persist(agent.model)

            # Mark complete
            self.supabase.table("agent_runs").update({
                "status": "completed",
                "completed_at": now_iso(),
                "steps": self.steps,
                "tool_calls": self.tool_calls,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": calculate_cost(self.input_tokens, self.output_tokens, agent.model),
            }).eq("id", self.run_id).execute()

            yield {"type": "done", "data": {}}

        except Exception as e:
            self.supabase.table("agent_runs").update({
                "status": "failed",
                "error": str(e),
                "completed_at": now_iso(),
            }).eq("id", self.run_id).execute()

            yield {"type": "error", "data": {"message": str(e)}}

    async def _persist(self, model: str):
        self.supabase.table("agent_runs").update({
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": calculate_cost(self.input_tokens, self.output_tokens, model),
        }).eq("id", self.run_id).execute()
