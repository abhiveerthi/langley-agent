"""Higgsfield media-generation integration.

Exposes a key-gated async client for the B-Roll Producer agent (clip
chain: text2image → image2video) plus direct still-image generation
(thumbnails/memes). See packages/integrations/higgsfield/client.py for
the live-verified contract.
"""
from packages.integrations.higgsfield.client import (
    HiggsfieldUnavailable,
    HiggsfieldError,
    GeneratedClip,
    GeneratedImage,
    generate_clip,
    generate_image,
    is_configured,
)

__all__ = [
    "HiggsfieldUnavailable",
    "HiggsfieldError",
    "GeneratedClip",
    "GeneratedImage",
    "generate_clip",
    "generate_image",
    "is_configured",
]
