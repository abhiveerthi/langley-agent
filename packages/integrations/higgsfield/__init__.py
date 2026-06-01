"""Higgsfield video-generation integration.

Exposes a key-gated async client for the B-Roll Producer agent. See
packages/integrations/higgsfield/client.py for the contract.
"""
from packages.integrations.higgsfield.client import (
    HiggsfieldUnavailable,
    HiggsfieldError,
    GeneratedClip,
    generate_clip,
    is_configured,
)

__all__ = [
    "HiggsfieldUnavailable",
    "HiggsfieldError",
    "GeneratedClip",
    "generate_clip",
    "is_configured",
]
