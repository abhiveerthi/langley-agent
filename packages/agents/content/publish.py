"""
Content Agent publish fan-out — what happens after Braden's FINAL approval.

Entry point `run_publish(supabase, org_id, video_id)` is invoked from two
places with the same idempotency story:

  - the Monday webhook router, immediately after a FINAL flip advances the
    pipeline to `approved` (low latency — the noon CST target is why the
    trigger is the approval itself, not the next poll), and
  - the scheduler sweep's catch-up pass, which retries anything sitting at
    `approved` (crash between approval and publish, or a prior total
    publish failure re-approved by the owner).

Idempotency is a status CLAIM: the first thing run_publish does is flip
`approved → publishing` with a guarded update; whoever loses the race (or
arrives at any other status) walks away. Every asset records its own
publish outcome onto assets[i]["publish"] — a partial failure ships what it
can and says exactly what didn't go out.

Targets by asset kind (each best-effort, each gated on its integration):
  clip            → YouTube Shorts upload (existing OAuth, upload scope) and,
                    when configured, an Instagram Reel from the clip URL.
  podcast_episode → audio copied to the public podcast bucket + the show's
                    RSS feed rebuilt (rss.py). Spotify/Apple ingest from it.
  audio           → not published directly; it rides inside the episode.
Plus one X post announcing the drop when X is connected.

Only assets with approved == True (the reviewer's explicit per-item flip)
are ever published — an undecided item is treated as NOT approved.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from packages.agents.content import rss

log = logging.getLogger("content.publish")

# Clip downloads (from Opus's CDN) share the audio byte budget.
from packages.agents.content.media import max_audio_bytes


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings_value(attr: str, env: str, default: str = "") -> str:
    try:
        from app.config import get_settings

        return getattr(get_settings(), attr, "") or default
    except Exception:
        return os.environ.get(env, default)


def claim_pipeline(supabase: Any, org_id: str, video_id: str) -> dict | None:
    """CAS-claim the pipeline for publishing: approved → publishing.

    Returns the claimed row, or None when it wasn't claimable (already
    publishing/published, reverted, or gone). The `.eq("status","approved")`
    filter is the guard — a concurrent claimer's update matches zero rows.
    """
    try:
        resp = (
            supabase.table("content_pipelines")
            .update({"status": "publishing", "updated_at": _now_iso()})
            .eq("org_id", org_id)
            .eq("video_id", video_id)
            .eq("status", "approved")
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception as e:
        log.warning("publish claim failed for %s: %r", video_id, e)
        return None


def _assert_safe_url(url: str) -> None:
    """SSRF guard for third-party-supplied media URLs (Opus clip CDN links):
    https only, and no loopback/private/link-local IP-literal hosts. The
    fetched bytes get published to public platforms, so a poisoned URL is a
    content-injection vector, not just an internal-network probe."""
    import ipaddress
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    if parsed.scheme != "https":
        raise RuntimeError(f"refusing non-https media URL: {url!r}")
    host = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise RuntimeError(f"refusing private-address media URL: {url!r}")
    except ValueError:
        pass  # hostname, not an IP literal
    if host in ("localhost",):
        raise RuntimeError(f"refusing localhost media URL: {url!r}")


async def _download(url: str, *, cap: int) -> bytes:
    _assert_safe_url(url)
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(f"download failed: {resp.status_code}")
            chunks, total = [], 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > cap:
                    raise RuntimeError(f"download exceeded {cap // (1024*1024)}MB cap")
                chunks.append(chunk)
    return b"".join(chunks)


async def _publish_clip(supabase: Any, org_id: str, asset: dict, video_title: str) -> dict:
    """One clip → YouTube Short (+ Instagram Reel when configured).
    Returns the publish record stamped onto the asset.

    RETRY-AWARE: any target whose PRIOR record (asset["publish"] from an
    earlier attempt) says ok=True is carried forward, never re-posted — a
    partial failure retried by the owner must not double-upload the Short
    or double-post the Reel that already went out.
    """
    from packages.agents.content.copy import ig_caption, shorts_description, shorts_title
    from packages.agents.content.media import max_clip_bytes
    from packages.integrations.youtube import client as yt

    prior = asset.get("publish") or {}
    record: dict[str, Any] = {"at": _now_iso()}
    clip_url = asset.get("url")
    title = asset.get("title") or video_title

    prior_yt = prior.get("youtube_shorts") or {}
    if prior_yt.get("ok"):
        record["youtube_shorts"] = prior_yt  # already live — never re-upload
    else:
        try:
            token = await yt.get_fresh_access_token(
                supabase, org_id,
                _settings_value("google_client_id", "GOOGLE_CLIENT_ID"),
                _settings_value("google_client_secret", "GOOGLE_CLIENT_SECRET"),
            )
            clip_bytes = await _download(clip_url, cap=max_clip_bytes())
            uploaded = await yt.upload_video(
                token,
                video_bytes=clip_bytes,
                title=shorts_title(asset, title),
                description=shorts_description(asset, video_title),
            )
            record["youtube_shorts"] = {"ok": True, "url": uploaded["url"]}
        except Exception as e:
            log.warning("Shorts upload failed for %s: %r", clip_url, e)
            record["youtube_shorts"] = {"ok": False, "error": str(e)[:300]}

    from packages.integrations import instagram

    prior_ig = prior.get("instagram") or {}
    if prior_ig.get("ok"):
        record["instagram"] = prior_ig  # already posted
    elif instagram.is_configured():
        try:
            _assert_safe_url(clip_url)
            reel = await instagram.publish_reel(clip_url, caption=ig_caption(asset, title))
            record["instagram"] = {"ok": True, "media_id": reel.get("media_id")}
        except Exception as e:
            log.warning("Instagram reel failed for %s: %r", clip_url, e)
            record["instagram"] = {"ok": False, "error": str(e)[:300]}
    else:
        record["instagram"] = {"ok": False, "skipped": "not configured"}

    return record


async def _publish_episode(
    supabase: Any, org_id: str, asset: dict, *, published_at: str
) -> dict:
    """The approved episode → public audio copy + full feed rebuild.
    Retry-aware: a prior successful publish is carried forward untouched."""
    prior = (asset.get("publish") or {}).get("podcast_rss") or {}
    if prior.get("ok"):
        return {"at": _now_iso(), "podcast_rss": prior}

    record: dict[str, Any] = {"at": _now_iso()}
    supabase_url = _settings_value("supabase_url", "NEXT_PUBLIC_SUPABASE_URL")
    source_path = asset.get("audio_storage_path")
    if not source_path:
        record["podcast_rss"] = {"ok": False, "error": "episode has no archived audio"}
        return record

    try:
        public_path = await rss.copy_audio_to_public(
            supabase, org_id, asset.get("video_id") or "episode",
            source_storage_path=source_path,
            content_type=asset.get("audio_content_type") or "audio/mp4",
        )
        asset["public_audio_path"] = public_path

        from packages.agents.content.tools import load_agent_config

        # Feed identity: the configured show brand.
        config = load_agent_config(org_id)
        show_title = (config.get("podcast_brand") or "").strip() or asset.get("brand") or "Podcast"

        episodes = collect_episodes_including_current(
            supabase, org_id, supabase_url, current=asset, published_at=published_at
        )
        xml = rss.build_feed(
            show_title=show_title,
            show_description=f"{show_title} — daily episodes.",
            show_link=rss.public_url(supabase_url, rss.feed_path(org_id)),
            episodes=episodes,
        )
        await rss.upload_feed(supabase, org_id, xml)
        record["podcast_rss"] = {
            "ok": True,
            "feed_url": rss.public_url(supabase_url, rss.feed_path(org_id)),
            "audio_url": rss.public_url(supabase_url, public_path),
        }
    except Exception as e:
        log.exception("podcast publish failed for org=%s", org_id)
        record["podcast_rss"] = {"ok": False, "error": str(e)[:300]}
    return record


def collect_episodes_including_current(
    supabase: Any, org_id: str, supabase_url: str, *, current: dict, published_at: str
) -> list[dict]:
    """Feed episodes = everything already published + the one being
    published right now (its row is still status=publishing, so the ledger
    query alone would miss it)."""
    episodes = rss.collect_published_episodes(supabase, org_id, supabase_url)
    current_guid = f"content-agent-{org_id}-{current.get('video_id')}"
    episodes = [e for e in episodes if e.get("guid") != current_guid]
    episodes.insert(0, {
        "title": current.get("title"),
        "description": current.get("description"),
        "summary": current.get("summary"),
        "audio_url": rss.public_url(supabase_url, current.get("public_audio_path") or ""),
        "audio_type": current.get("audio_content_type") or "audio/mp4",
        "audio_size_bytes": current.get("audio_size_bytes") or 0,
        "guid": current_guid,
        "published_at": published_at,
        "chapters": current.get("chapters") or [],
    })
    return episodes


async def _announce_on_x(
    supabase: Any,
    org_id: str,
    video_title: str,
    links: list[str],
    post_copy: dict | None = None,
) -> dict:
    """One announcement tweet for the drop, when X is connected. Uses the
    reviewer-approved drafted post when one exists."""
    from packages.agents.content.copy import x_text
    from packages.integrations.x import client as x

    try:
        conn = x.get_connection(supabase, org_id)
        if not conn or conn.get("status") != "active":
            return {"ok": False, "skipped": "X not connected"}
        token = await x.get_fresh_access_token(
            supabase, org_id,
            _settings_value("x_client_id", "X_CLIENT_ID"),
            _settings_value("x_client_secret", "X_CLIENT_SECRET"),
        )
        tweet = await x.post_tweet(token, x_text(post_copy, video_title, links))
        return {"ok": True, "tweet_id": (tweet or {}).get("id")}
    except Exception as e:
        log.warning("X announce failed for org=%s: %r", org_id, e)
        return {"ok": False, "error": str(e)[:300]}


async def run_publish(supabase: Any, org_id: str, video_id: str) -> str:
    """Publish one approved pipeline. Returns a human summary (logged by
    callers; also written to the ledger's publish stage entry)."""
    row = claim_pipeline(supabase, org_id, video_id)
    if row is None:
        return "not claimable (already publishing/published, or no longer approved)"

    assets = list(row.get("assets") or [])
    video_title = row.get("video_title") or video_id
    published_at = _now_iso()

    approved = [(i, a) for i, a in enumerate(assets) if a.get("approved") is True]
    if not approved:
        _finish(supabase, org_id, video_id, assets, "failed",
                error="final approval given but no individual assets were approved")
        return "nothing to publish — no reviewer-approved assets"

    links: list[str] = []
    successes = 0
    for i, asset in approved:
        kind = asset.get("kind")
        if kind == "clip":
            record = await _publish_clip(supabase, org_id, asset, video_title)
            yt_rec = record.get("youtube_shorts") or {}
            ig_rec = record.get("instagram") or {}
            # A clip counts as shipped when ANY of its targets is live —
            # an Instagram-only success must not park the run at failed
            # (which would re-post the Reel on the owner's retry).
            if yt_rec.get("ok") or ig_rec.get("ok"):
                successes += 1
            if yt_rec.get("ok"):
                links.append(yt_rec["url"])
        elif kind == "podcast_episode":
            record = await _publish_episode(supabase, org_id, asset, published_at=published_at)
            if record.get("podcast_rss", {}).get("ok"):
                successes += 1
                links.append(record["podcast_rss"]["feed_url"])
        elif kind == "audio":
            record = {"at": _now_iso(), "note": "audio ships inside the podcast episode"}
        elif kind == "post_copy":
            record = {"at": _now_iso(), "note": "consumed by the X announcement"}
        else:
            record = {"at": _now_iso(), "note": f"no publish target for kind={kind!r}"}
        assets[i] = {**asset, "publish": record}

    # Announce ONLY when something actually shipped, and only ONCE across
    # retries — a total failure must not tweet about content that never
    # went out, and a retried partial failure must not tweet again.
    prior_x = ((row.get("stages") or {}).get("publish") or {}).get("x") or {}
    if prior_x.get("ok"):
        x_result = prior_x
    elif successes:
        # The drafted X post only goes out as written if the reviewer
        # approved it; otherwise the fallback announcement is generic.
        approved_post_copy = next(
            (a for _, a in approved if a.get("kind") == "post_copy"), None
        )
        x_result = await _announce_on_x(
            supabase, org_id, video_title, links, post_copy=approved_post_copy
        )
    else:
        x_result = {"ok": False, "skipped": "nothing shipped — announcement withheld"}

    if successes:
        _finish(supabase, org_id, video_id, assets, "published", x_result=x_result)
        return f"published {successes}/{len(approved)} approved asset(s)"
    _finish(
        supabase, org_id, video_id, assets, "failed",
        error="every publish target failed — see per-asset publish records",
        x_result=x_result,
    )
    return "publish failed for every approved asset"


def _finish(
    supabase: Any,
    org_id: str,
    video_id: str,
    assets: list[dict],
    status: str,
    *,
    error: str | None = None,
    x_result: dict | None = None,
) -> None:
    # MERGE publish records into the CURRENT row's assets instead of
    # writing back our claim-time snapshot wholesale: the reviewer can flip
    # asset decisions while a fan-out is mid-flight (it legitimately runs
    # for minutes), and clobbering those flips could let a just-rejected
    # asset publish on a later retry.
    write_assets = assets
    try:
        resp = (
            supabase.table("content_pipelines")
            .select("assets").eq("org_id", org_id).eq("video_id", video_id)
            .limit(1).execute()
        )
        current = (resp.data[0].get("assets") if resp.data else None) or []
        if len(current) == len(assets):
            merged = []
            for cur, ours in zip(current, assets):
                m = dict(cur)
                if "publish" in ours:
                    m["publish"] = ours["publish"]
                if ours.get("public_audio_path"):
                    m["public_audio_path"] = ours["public_audio_path"]
                merged.append(m)
            write_assets = merged
    except Exception:
        pass  # fall back to the snapshot — better stale flags than no record

    patch: dict[str, Any] = {
        "status": status,
        "assets": write_assets,
        "error": error,
        "updated_at": _now_iso(),
    }
    if status == "published":
        patch["published_at"] = _now_iso()
    try:
        supabase.table("content_pipelines").update(patch).eq("org_id", org_id).eq(
            "video_id", video_id
        ).execute()
    except Exception as e:
        log.warning("publish finish write failed for %s: %r", video_id, e)
    if x_result is not None:
        try:
            # (tools.record_stage uses the ContextVar client — direct writes here.)
            resp = (
                supabase.table("content_pipelines")
                .select("stages").eq("org_id", org_id).eq("video_id", video_id)
                .limit(1).execute()
            )
            stages = (resp.data[0].get("stages") if resp.data else None) or {}
            stages["publish"] = {
                "status": "done" if status == "published" else "failed",
                "detail": f"x: {x_result}",
                "x": x_result,  # structured — the announce-once check reads this
                "at": _now_iso(),
            }
            supabase.table("content_pipelines").update(
                {"stages": stages, "updated_at": _now_iso()}
            ).eq("org_id", org_id).eq("video_id", video_id).execute()
        except Exception as e:
            log.warning("publish stage write failed for %s: %r", video_id, e)
