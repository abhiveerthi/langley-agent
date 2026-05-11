"""
Manifest-vs-reality guard.

Each agent's manifest.json is the single source of truth the frontend reads
to describe what the agent can do (capabilities, tools, gated writes,
required integrations). When code drifts from the manifest, users see
features the agent can't deliver — or miss features it can.

This test fails CI on three classes of drift:

  1. Tools listed in `manifest.tools` that aren't actually registered in
     `get_<agent>_tools()`.
  2. Tools registered in `get_<agent>_tools()` but absent from
     `manifest.tools` (the FE's tool chips would lie by omission).
  3. `manifest.writes[].tool` references that don't appear anywhere — either
     in the agent's tool list (LLM-callable writes) OR in the agent module
     (graph-node writes like `reply_to_comment` that the agent calls
     directly after the approval gate). Both are legitimate; what's not
     legitimate is naming a write tool that doesn't exist.

Update the manifest in the SAME PR as the code change; that's the contract.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


# ── Discovery ─────────────────────────────────────────────────────────────
_AGENTS_ROOT = Path(__file__).resolve().parents[1] / "packages" / "agents"


def _agent_dirs() -> list[tuple[str, Path]]:
    """Yield (slug, dir) for every agent that has a manifest.json.

    Slug comes from manifest itself rather than directory name because the
    convention is kebab-case slug (`community-manager`) ↔ snake_case dir
    (`community_manager`).
    """
    out: list[tuple[str, Path]] = []
    for child in sorted(_AGENTS_ROOT.iterdir()):
        if not child.is_dir():
            continue
        m = child / "manifest.json"
        if not m.exists():
            continue
        manifest = json.loads(m.read_text(encoding="utf-8"))
        out.append((manifest["slug"], child))
    return out


def _registered_tool_names(agent_dir: Path) -> set[str]:
    """Import the agent's tools module and return the set of registered
    LangChain tool names from its `get_<dir>_tools()` factory.

    Editor returns an empty list (it's the coming-soon stub) — that's fine,
    we still assert the manifest agrees by being empty.
    """
    module_name = f"packages.agents.{agent_dir.name}.tools"
    mod = importlib.import_module(module_name)
    factory_name = f"get_{agent_dir.name}_tools"
    factory = getattr(mod, factory_name, None)
    assert callable(factory), (
        f"{module_name} is missing the `{factory_name}()` factory — "
        f"either add it or update _registered_tool_names() to find the new convention."
    )
    return {t.name for t in factory()}


def _module_symbols(agent_dir: Path) -> set[str]:
    """Top-level symbols defined in the agent module + its tools module.

    Used to validate `writes[].tool` entries that aren't registered as
    LangChain tools but ARE invoked from a graph node (e.g. CM's
    `reply_to_comment` is called from `_send_reply_node` directly so the
    LLM can't trigger it — see CM agent docstring)."""
    syms: set[str] = set()
    for sub in ("agent", "tools"):
        try:
            mod = importlib.import_module(f"packages.agents.{agent_dir.name}.{sub}")
        except ModuleNotFoundError:
            continue
        syms.update(name for name in dir(mod) if not name.startswith("_"))
    return syms


# ── The actual tests ─────────────────────────────────────────────────────
@pytest.mark.parametrize(("slug", "agent_dir"), _agent_dirs(), ids=lambda x: x if isinstance(x, str) else x.name)
def test_manifest_tools_match_registered_tools(slug: str, agent_dir: Path) -> None:
    """`manifest.tools` ↔ `get_<agent>_tools()` must agree exactly."""
    manifest = json.loads((agent_dir / "manifest.json").read_text(encoding="utf-8"))
    declared = set(manifest.get("tools") or [])
    registered = _registered_tool_names(agent_dir)

    extra_in_manifest = declared - registered
    extra_in_code = registered - declared

    assert not extra_in_manifest, (
        f"[{slug}] manifest.json claims tools that aren't registered in "
        f"get_{agent_dir.name}_tools(): {sorted(extra_in_manifest)}. "
        f"Either implement them or remove them from the manifest."
    )
    assert not extra_in_code, (
        f"[{slug}] get_{agent_dir.name}_tools() registers tools missing from "
        f"manifest.json: {sorted(extra_in_code)}. "
        f"Add them to manifest.tools so the frontend can surface them."
    )


@pytest.mark.parametrize(("slug", "agent_dir"), _agent_dirs(), ids=lambda x: x if isinstance(x, str) else x.name)
def test_manifest_writes_reference_real_callables(slug: str, agent_dir: Path) -> None:
    """Every `manifest.writes[].tool` must exist either as a registered tool
    or as a top-level symbol in the agent module (graph-node writes)."""
    manifest = json.loads((agent_dir / "manifest.json").read_text(encoding="utf-8"))
    writes = manifest.get("writes") or []
    if not writes:
        return

    registered = _registered_tool_names(agent_dir)
    module_syms = _module_symbols(agent_dir)
    knowable = registered | module_syms

    for entry in writes:
        tool_name = entry.get("tool")
        assert tool_name, f"[{slug}] manifest.writes entry missing 'tool': {entry}"
        assert tool_name in knowable, (
            f"[{slug}] manifest.writes references '{tool_name}' but it's neither "
            f"a registered LLM tool nor a symbol in the agent module. "
            f"Add the implementation or remove the manifest entry — promising a "
            f"write the agent can't perform is exactly the drift this guard catches."
        )


@pytest.mark.parametrize(("slug", "agent_dir"), _agent_dirs(), ids=lambda x: x if isinstance(x, str) else x.name)
def test_manifest_required_fields_present(slug: str, agent_dir: Path) -> None:
    """Sanity check: every manifest must declare the fields the FE reads."""
    manifest = json.loads((agent_dir / "manifest.json").read_text(encoding="utf-8"))
    for field in ("slug", "name", "description", "tagline", "icon", "tools", "writes"):
        assert field in manifest, f"[{slug}] manifest.json missing required field '{field}'"
    assert manifest["slug"] == slug
