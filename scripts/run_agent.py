#!/usr/bin/env python3
"""
Run a single agent end-to-end against a tenant profile and print the trace.

Usage:
    python3 scripts/run_agent.py
    python3 scripts/run_agent.py --agent strategist --org langley-outdoors-academy \
                                  --prompt "Give me my weekly brief"
    python3 scripts/run_agent.py --agent brand-manager --org langley-outdoors-academy \
                                  --prompt "research Magpul"

Prints per-node updates as the graph executes, then the final assistant message.
Useful for offline QA without spinning up Studio.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Make the repo root importable (so `from packages.agents...` works when run
# from anywhere).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()  # pull RESEND/PERPLEXITY/YOUTUBE/ANTHROPIC keys

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage  # noqa: E402

from packages.agents.registry import AGENT_REGISTRY, get_agent  # noqa: E402


def _truncate(s: str, n: int = 400) -> str:
    s = str(s)
    return s if len(s) <= n else s[:n] + f"… (+{len(s) - n} chars)"


async def run(slug: str, org_id: str, prompt: str) -> None:
    if slug not in AGENT_REGISTRY:
        raise SystemExit(
            f"Unknown agent '{slug}'. Available: {', '.join(AGENT_REGISTRY)}"
        )

    agent = get_agent(slug)
    app = agent.graph.compile(interrupt_before=agent.interrupt_before_nodes)

    thread_id = f"eval-{slug}-{uuid.uuid4().hex[:8]}"
    initial = {
        "messages": [HumanMessage(content=prompt)],
        "org_id": org_id,
        "user_id": "eval-user",
        "thread_id": thread_id,
        "task_id": None,
        "metadata": {},
    }

    bar = "=" * 78
    print(f"\n{bar}")
    print(f"agent  : {slug}")
    print(f"org    : {org_id}")
    print(f"prompt : {prompt}")
    print(f"thread : {thread_id}")
    print(bar)

    final_state: dict | None = None
    async for chunk in app.astream(initial, stream_mode="updates"):
        for node_name, node_output in chunk.items():
            print(f"\n── [{node_name}] ──")
            if not node_output:
                print("  (no state changes)")
                continue
            for k, v in node_output.items():
                if k == "messages":
                    for m in v:
                        if isinstance(m, ToolMessage):
                            print(f"  TOOL_RESULT  {_truncate(m.content)}")
                        elif isinstance(m, AIMessage):
                            if m.content:
                                print(f"  AI_TEXT      {_truncate(m.content)}")
                            for tc in getattr(m, "tool_calls", []) or []:
                                print(f"  TOOL_CALL    {tc['name']}({tc.get('args', {})})")
                elif k == "metadata":
                    profile = (v or {}).get("profile") or {}
                    if profile:
                        brand = profile.get("brand", {}).get("name", "?")
                        niche = profile.get("niche", {}).get("display_name", "?")
                        print(f"  profile      brand={brand!r} niche={niche!r}")
                    else:
                        print(f"  metadata     {_truncate(v)}")
                else:
                    print(f"  {k:12} {_truncate(v)}")
            final_state = node_output

    print(f"\n{bar}")
    print("FINAL ASSISTANT MESSAGE")
    print(bar)
    if final_state and "messages" in final_state:
        for m in final_state["messages"]:
            if isinstance(m, AIMessage) and m.content:
                print(m.content)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default="strategist", choices=list(AGENT_REGISTRY.keys()))
    p.add_argument("--org", default="langley-outdoors-academy")
    p.add_argument(
        "--prompt",
        default="Give me my weekly brief — what should I make next?",
    )
    args = p.parse_args()
    asyncio.run(run(args.agent, args.org, args.prompt))


if __name__ == "__main__":
    main()
