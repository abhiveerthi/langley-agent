"""
Content routing policy — which lanes a detected video enters.

Pure decision logic (unit-tested, no I/O) implementing the client's rules:

  - The NIGHTLY LIVE STREAM is the podcast source: only live broadcasts at
    or over the podcast threshold (default 30 minutes, configurable via
    agents.config `podcast_min_minutes`) enter the podcast flow.
  - Midday / later long-forms route to Opus Clip, NOT podcast creation —
    8–10 minute videos must never trigger podcast conversion.
  - YouTube Shorts (≤ ~75s) are already short-form: no clipping, no podcast.

`classify_video` needs the video's duration + live flag, fetched by
init_pipeline via youtube.get_video_details. When the lookup fails we
route CONSERVATIVELY (clips yes, podcast no) — a mis-routed podcast is
worse than a missed one, because the podcast feed is public.

The whole podcast lane additionally sits behind `podcast_enabled`
(default OFF): per the 2026-08-06 client call, podcast production is
paused while Braden's PR consultant shapes the strategy. Infrastructure
stays in place; no episodes are drafted until the flag flips.
"""
from __future__ import annotations

DEFAULT_PODCAST_MIN_MINUTES = 30

# YouTube Shorts ceiling with a little slack (60s product limit; some land
# at 61-75s in the API depending on trim).
SHORT_MAX_SECONDS = 75


def podcast_min_seconds(config: dict | None) -> int:
    """Threshold from agents.config, defaulting to 30 minutes."""
    try:
        minutes = float((config or {}).get("podcast_min_minutes") or DEFAULT_PODCAST_MIN_MINUTES)
    except (TypeError, ValueError):
        minutes = DEFAULT_PODCAST_MIN_MINUTES
    return int(max(1.0, minutes) * 60)


def podcast_lane_enabled(config: dict | None) -> bool:
    """Master switch for the podcast lane — agents.config `podcast_enabled`.

    Defaults OFF: the client paused podcast production (2026-08-06 call)
    until his PR consultant sets the strategy. Everything downstream of
    routing (draft, package, RSS) is built and waiting on this flag.
    """
    return bool((config or {}).get("podcast_enabled"))


def classify_video(
    *,
    duration_seconds: int | None,
    is_live: bool,
    config: dict | None = None,
) -> dict:
    """Return the routing decision for one video:

        {"video_kind": "short"|"longform"|"live",
         "podcast_eligible": bool, "clips_eligible": bool, "reason": str}

    Unknown duration (details lookup failed → None) routes conservatively:
    clips yes, podcast no.
    """
    threshold = podcast_min_seconds(config)

    if duration_seconds is None:
        return {
            "video_kind": "live" if is_live else "longform",
            "podcast_eligible": False,
            "clips_eligible": True,
            "reason": "duration unknown — routing conservatively (clips only)",
        }

    if duration_seconds <= SHORT_MAX_SECONDS:
        return {
            "video_kind": "short",
            "podcast_eligible": False,
            "clips_eligible": False,
            "reason": "already short-form — no clipping, no podcast",
        }

    if is_live:
        long_enough = duration_seconds >= threshold
        enabled = podcast_lane_enabled(config)
        if not long_enough:
            reason = f"live stream under {threshold // 60}min — clips only"
        elif not enabled:
            reason = "podcast lane paused (podcast_enabled off) — clips only"
        else:
            reason = f"live stream ≥ {threshold // 60}min — podcast + clips"
        return {
            "video_kind": "live",
            "podcast_eligible": long_enough and enabled,
            "clips_eligible": True,
            "reason": reason,
        }

    return {
        "video_kind": "longform",
        "podcast_eligible": False,
        "clips_eligible": True,
        "reason": "long-form routes to Opus Clip, not podcast creation",
    }
