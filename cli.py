#!/usr/bin/env python3
"""
Marcus Agent System — Interactive CLI

Run and interact with the Research, Intel, and Comms agents
independently of the web frontend.

Usage:
    python cli.py                  # Interactive agent selection
    python cli.py research         # Jump straight to Research Agent
    python cli.py intel            # Jump straight to Intel Agent
    python cli.py comms            # Jump straight to Comms Agent
"""

import sys
import asyncio
from uuid import uuid4
from pathlib import Path

# Ensure project root is on the Python path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage
from packages.agents.registry import get_agent, AGENT_REGISTRY


AGENT_INFO = {
    "research": ("Research Agent", "Political intelligence gathering & analysis"),
    "intel": ("Intel Agent", "Brand intelligence, YouTube analytics & content ideation"),
    "comms": ("Comms Agent", "Email marketing, lead generation & content strategy"),
    "general": ("General Assistant", "General-purpose tasks, planning & writing"),
}


def print_banner():
    print()
    print("=" * 56)
    print("  MARCUS — Agent System v2")
    print("=" * 56)
    print()


def print_agents():
    print("  Available agents:\n")
    for i, (slug, (name, desc)) in enumerate(AGENT_INFO.items(), 1):
        print(f"    {i}. {slug:<12} {name}")
        print(f"       {desc}")
    print()


def select_agent() -> str:
    """Prompt user to select an agent. Returns the slug."""
    print_agents()

    slug_list = list(AGENT_INFO.keys())

    while True:
        choice = input("  Select agent (name or number): ").strip().lower()

        if choice in AGENT_INFO:
            return choice

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(slug_list):
                return slug_list[idx]
        except ValueError:
            pass

        print(f"  Unknown choice '{choice}'. Try again.\n")


async def run_agent_loop(slug: str):
    """Main conversation loop with a single agent."""
    info = AGENT_INFO.get(slug, (slug, ""))
    print(f"\n  Connected to {info[0]}.")
    print("  Type 'quit' to exit, 'switch' to change agent.\n")

    agent = get_agent(slug)
    agent._custom_checkpointer = MemorySaver()

    app = await agent.compile()
    thread_id = str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        try:
            user_input = input("  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n")
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            break
        if user_input.lower() == "switch":
            return "switch"

        input_data = {
            "messages": [HumanMessage(content=user_input)],
            "org_id": "cli",
            "user_id": "cli",
            "thread_id": thread_id,
            "task_id": None,
            "metadata": {},
        }

        print(f"\n  Marcus: ", end="", flush=True)

        try:
            full_response = ""
            async for event in app.astream_events(input_data, config, version="v2"):
                kind = event.get("event", "")

                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = getattr(chunk, "content", "")
                        if isinstance(content, str) and content:
                            print(content, end="", flush=True)
                            full_response += content

                elif kind == "on_tool_start":
                    tool_name = event.get("name", "tool")
                    print(f"\n  [{tool_name}...]", end="", flush=True)

                elif kind == "on_tool_end":
                    print(" done", flush=True)
                    print("  ", end="", flush=True)

            if not full_response:
                # Fallback: get final state if streaming produced no text
                state = await app.aget_state(config)
                messages = state.values.get("messages", [])
                if messages:
                    last = messages[-1]
                    content = getattr(last, "content", "")
                    if isinstance(content, str):
                        print(content, end="")

            print("\n")

        except Exception as e:
            print(f"\n  Error: {e}\n")

    return "quit"


async def main():
    print_banner()

    # Check for command-line agent selection
    initial_slug = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in AGENT_INFO:
            initial_slug = arg
        else:
            print(f"  Unknown agent '{arg}'.")
            print(f"  Available: {', '.join(AGENT_INFO.keys())}\n")
            sys.exit(1)

    # Check for required env vars
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  WARNING: ANTHROPIC_API_KEY not set. Agents will not work.\n")

    optional_keys = {
        "PERPLEXITY_API_KEY": "news search (Research/Comms)",
        "YOUTUBE_API_KEY": "YouTube data (Research/Intel)",
        "YOUTUBE_CHANNEL_ID": "YouTube channel monitoring (Research/Intel)",
    }
    missing = [f"{k} ({v})" for k, v in optional_keys.items() if not os.environ.get(k)]
    if missing:
        print("  Optional API keys not set (some tools will be unavailable):")
        for m in missing:
            print(f"    - {m}")
        print()

    slug = initial_slug or select_agent()

    while True:
        result = await run_agent_loop(slug)
        if result == "switch":
            slug = select_agent()
        else:
            break

    print("  Goodbye.\n")


if __name__ == "__main__":
    asyncio.run(main())
