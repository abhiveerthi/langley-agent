"""
Content Agent Phase D — publish fan-out. No network, no live APIs.

Covers:
  - RSS feed assembly: escaping, enclosures, chapters, episode filtering
  - run_publish flow: approved-subset selection, claim gating, partial
    success → published, total failure → failed, per-asset publish records
  - the webhook FINAL-approval → publish trigger
  - Instagram gate raises Unavailable when unconfigured
"""
from __future__ import annotations

import pytest

from packages.agents.content import publish, rss


# ── RSS assembly ───────────────────────────────────────────────────────────
class TestBuildFeed:
    def _ep(self, **over):
        return {
            "title": "Episode One",
            "description": "Notes.",
            "summary": "One line.",
            "audio_url": "https://x/storage/v1/object/public/podcast-public/org/episodes/v1.m4a",
            "audio_type": "audio/mp4",
            "audio_size_bytes": 123,
            "guid": "content-agent-org-v1",
            "published_at": "2026-07-07T12:00:00+00:00",
            "chapters": [{"start": "00:00:00", "title": "Open"}],
            **over,
        }

    def test_basic_feed_shape(self):
        xml = rss.build_feed(
            show_title="Positively American with Braden Langley",
            show_description="Daily.",
            show_link="https://x/feed.xml",
            episodes=[self._ep()],
        )
        assert xml.startswith('<?xml version="1.0"')
        assert "<title>Positively American with Braden Langley</title>" in xml
        assert '<enclosure url="https://x/storage/v1/object/public/podcast-public/org/episodes/v1.m4a" length="123" type="audio/mp4"/>' in xml
        assert "<guid isPermaLink=\"false\">content-agent-org-v1</guid>" in xml
        assert "00:00:00 — Open" in xml

    def test_llm_text_is_escaped(self):
        """Episode titles/notes come from an LLM over spoken audio — hostile
        or accidental markup must never break the feed."""
        xml = rss.build_feed(
            show_title="Show <&>",
            show_description="d",
            show_link="https://x",
            episodes=[self._ep(title="Breaking: <script>alert(1)</script> & more")],
        )
        assert "<script>" not in xml
        assert "&lt;script&gt;" in xml
        assert "<title>Show &lt;&amp;&gt;</title>" in xml

    def test_collect_published_filters_unapproved_and_unpublic(self, mock_supabase_factory):
        sb = mock_supabase_factory({
            "content_pipelines": [{
                "video_id": "v1", "published_at": "2026-07-07T12:00:00Z",
                "assets": [
                    {"kind": "podcast_episode", "approved": True,
                     "public_audio_path": "org/episodes/v1.m4a", "title": "keep"},
                    {"kind": "podcast_episode", "approved": False,
                     "public_audio_path": "org/episodes/v0.m4a", "title": "drop-unapproved"},
                    {"kind": "podcast_episode", "approved": True, "title": "drop-no-audio"},
                    {"kind": "clip", "approved": True, "title": "drop-not-episode"},
                ],
            }],
        })
        eps = rss.collect_published_episodes(sb, "org-1", "https://x")
        assert [e["title"] for e in eps] == ["keep"]


# ── run_publish flow ───────────────────────────────────────────────────────
def _pipeline_row(assets):
    return {
        "org_id": "org-1", "video_id": "v1", "video_title": "8PM Live",
        "status": "approved", "assets": assets,
    }


@pytest.fixture
def quiet_targets(monkeypatch):
    """Replace every external publish target with recorders."""
    calls = {"clip": [], "episode": [], "x": []}

    async def fake_clip(supabase, org_id, asset, video_title):
        calls["clip"].append(asset)
        return {"youtube_shorts": {"ok": True, "url": "https://youtube.com/shorts/abc"}}

    async def fake_episode(supabase, org_id, asset, *, published_at, config=None):
        calls["episode"].append(asset)
        return {"podcast_rss": {"ok": True, "feed_url": "https://x/feed.xml"}}

    async def fake_x(supabase, org_id, title, links, post_copy=None):
        calls["x"].append(links)
        return {"ok": True, "tweet_id": "t1"}

    monkeypatch.setattr(publish, "_publish_clip", fake_clip)
    monkeypatch.setattr(publish, "_publish_episode", fake_episode)
    monkeypatch.setattr(publish, "_announce_on_x", fake_x)
    return calls


class TestRunPublish:
    @pytest.mark.asyncio
    async def test_publishes_only_reviewer_approved_assets(
        self, mock_supabase_factory, quiet_targets
    ):
        assets = [
            {"kind": "clip", "approved": True, "url": "https://c/1.mp4"},
            {"kind": "clip", "approved": False, "url": "https://c/2.mp4"},   # Kaydi rejected
            {"kind": "clip", "url": "https://c/3.mp4"},                      # undecided = not approved
            {"kind": "podcast_episode", "approved": True, "title": "Ep"},
            {"kind": "audio", "approved": True},
        ]
        sb = mock_supabase_factory({"content_pipelines": [_pipeline_row(assets)]})
        summary = await publish.run_publish(sb, "org-1", "v1")
        assert "published 2/3" in summary  # clip + episode succeed; audio is a rider
        assert len(quiet_targets["clip"]) == 1
        assert len(quiet_targets["episode"]) == 1
        status_writes = [
            p for t, p in sb._canned["_updates"]
            if t == "content_pipelines" and "status" in p
        ]
        final = status_writes[-1]
        assert final["status"] == "published"
        # Per-asset records: approved clip has one; rejected/undecided don't.
        assert "publish" in final["assets"][0]
        assert "publish" not in final["assets"][1]
        assert "publish" not in final["assets"][2]

    @pytest.mark.asyncio
    async def test_not_claimable_when_row_missing(self, mock_supabase_factory, quiet_targets):
        sb = mock_supabase_factory({"content_pipelines": []})
        summary = await publish.run_publish(sb, "org-1", "v1")
        assert "not claimable" in summary
        assert quiet_targets["clip"] == []

    @pytest.mark.asyncio
    async def test_no_approved_assets_fails_honestly(self, mock_supabase_factory, quiet_targets):
        sb = mock_supabase_factory({
            "content_pipelines": [_pipeline_row([{"kind": "clip", "approved": False}])],
        })
        summary = await publish.run_publish(sb, "org-1", "v1")
        assert "nothing to publish" in summary
        final = [p for t, p in sb._canned["_updates"] if t == "content_pipelines"][-1]
        assert final["status"] == "failed"
        assert "no individual assets" in final["error"]

    @pytest.mark.asyncio
    async def test_total_target_failure_parks_at_failed_and_withholds_announce(
        self, mock_supabase_factory, monkeypatch
    ):
        """Nothing shipped → no announcement tweet, ever — a live 'New drop'
        post about content that never published is a public lie."""
        announces = []

        async def failing_clip(supabase, org_id, asset, video_title):
            return {"youtube_shorts": {"ok": False, "error": "quota"}}

        async def fake_x(supabase, org_id, title, links, post_copy=None):
            announces.append(links)
            return {"ok": True}

        monkeypatch.setattr(publish, "_publish_clip", failing_clip)
        monkeypatch.setattr(publish, "_announce_on_x", fake_x)
        sb = mock_supabase_factory({
            "content_pipelines": [_pipeline_row([{"kind": "clip", "approved": True, "url": "u"}])],
        })
        summary = await publish.run_publish(sb, "org-1", "v1")
        assert "failed for every" in summary
        assert announces == []  # announcement withheld
        final = [p for t, p in sb._canned["_updates"] if t == "content_pipelines"]
        assert any(p.get("status") == "failed" for p in final)

    @pytest.mark.asyncio
    async def test_instagram_only_success_counts_as_published(
        self, mock_supabase_factory, monkeypatch
    ):
        """YouTube fails but the Reel ships → the run is published, NOT
        failed — parking it at failed would re-post the Reel on retry."""
        async def ig_only_clip(supabase, org_id, asset, video_title):
            return {
                "youtube_shorts": {"ok": False, "error": "403 missing scope"},
                "instagram": {"ok": True, "media_id": "m1"},
            }

        async def fake_x(supabase, org_id, title, links, post_copy=None):
            return {"ok": True}

        monkeypatch.setattr(publish, "_publish_clip", ig_only_clip)
        monkeypatch.setattr(publish, "_announce_on_x", fake_x)
        sb = mock_supabase_factory({
            "content_pipelines": [_pipeline_row([{"kind": "clip", "approved": True, "url": "u"}])],
        })
        summary = await publish.run_publish(sb, "org-1", "v1")
        assert "published 1/1" in summary

    @pytest.mark.asyncio
    async def test_retry_never_reposts_targets_already_live(self, monkeypatch):
        """A clip whose prior attempt shipped the Short must carry the prior
        record forward without re-uploading (the real _publish_clip path)."""
        uploads = []

        async def boom_download(url, *, cap):
            uploads.append(url)
            raise AssertionError("must not re-download an already-published clip")

        monkeypatch.setattr(publish, "_download", boom_download)
        asset = {
            "kind": "clip", "approved": True, "url": "https://c/1.mp4",
            "publish": {
                "youtube_shorts": {"ok": True, "url": "https://youtube.com/shorts/prior"},
                "instagram": {"ok": False, "skipped": "not configured"},
            },
        }
        record = await publish._publish_clip(None, "org-1", asset, "Vid")
        assert uploads == []
        assert record["youtube_shorts"]["url"] == "https://youtube.com/shorts/prior"

    @pytest.mark.asyncio
    async def test_announce_fires_only_once_across_retries(
        self, mock_supabase_factory, quiet_targets
    ):
        """A retried run whose earlier attempt already tweeted must not
        tweet again — the prior x result is carried from the ledger."""
        row = _pipeline_row([{"kind": "clip", "approved": True, "url": "u"}])
        row["stages"] = {"publish": {"status": "failed", "x": {"ok": True, "tweet_id": "t0"}}}
        sb = mock_supabase_factory({"content_pipelines": [row]})
        summary = await publish.run_publish(sb, "org-1", "v1")
        assert "published" in summary
        assert quiet_targets["x"] == []  # no second announcement


# ── Webhook → publish trigger ──────────────────────────────────────────────
class TestWebhookPublishTrigger:
    @pytest.mark.asyncio
    async def test_final_approval_spawns_publish(self, mock_supabase_factory, monkeypatch):
        from app.routers import monday_webhooks as mw

        ORG = "8b7d2c31-4a5e-4f6a-9c8d-1e2f3a4b5c6d"
        sb = mock_supabase_factory({
            "content_review_boards": [{
                "org_id": ORG, "board_id": "b1", "status_column_id": "status_x",
                "webhook_id": "w1", "webhook_secret": "s3cret",
            }],
            "content_review_items": [{
                "org_id": ORG, "video_id": "v1", "monday_item_id": "111",
                "role": "final", "asset_index": None, "kind": "final_approval",
                "decision": "pending",
            }],
            "content_pipelines": [{
                "org_id": ORG, "video_id": "v1", "status": "ready_for_review", "assets": [],
            }],
        })
        monkeypatch.setattr(mw, "_service_client", lambda: sb)
        spawned = []
        monkeypatch.setattr(mw, "_spawn_publish", lambda s, o, v: spawned.append((o, v)))

        class _Req:
            headers = {}
            async def json(self):
                return {"event": {"type": "update_column_value", "pulseId": 111,
                                  "columnId": "status_x",
                                  "value": {"label": {"text": "Approved"}}}}

        await mw.monday_webhook(ORG, "s3cret", _Req())
        assert spawned == [(ORG, "v1")]

    @pytest.mark.asyncio
    async def test_asset_approval_does_not_spawn_publish(self, mock_supabase_factory, monkeypatch):
        from app.routers import monday_webhooks as mw

        ORG = "8b7d2c31-4a5e-4f6a-9c8d-1e2f3a4b5c6d"
        sb = mock_supabase_factory({
            "content_review_boards": [{
                "org_id": ORG, "board_id": "b1", "status_column_id": "status_x",
                "webhook_id": "w1", "webhook_secret": "s3cret",
            }],
            "content_review_items": [{
                "org_id": ORG, "video_id": "v1", "monday_item_id": "111",
                "role": "asset", "asset_index": 0, "kind": "clip", "decision": "pending",
            }],
            "content_pipelines": [{
                "org_id": ORG, "video_id": "v1", "status": "ready_for_review",
                "assets": [{"kind": "clip"}],
            }],
        })
        monkeypatch.setattr(mw, "_service_client", lambda: sb)
        spawned = []
        monkeypatch.setattr(mw, "_spawn_publish", lambda s, o, v: spawned.append((o, v)))

        class _Req:
            headers = {}
            async def json(self):
                return {"event": {"type": "update_column_value", "pulseId": 111,
                                  "columnId": "status_x",
                                  "value": {"label": {"text": "Approved"}}}}

        await mw.monday_webhook(ORG, "s3cret", _Req())
        assert spawned == []


# ── Episode delivery modes (Podbean pivot: manual is the default) ──────────
class TestEpisodeDeliveryModes:
    EP = {
        "kind": "podcast_episode", "approved": True, "title": "Ep 9",
        "summary": "One line.", "description": "Notes.",
        "brand": "Positively American with Braden Langley",
        "chapters": [{"start": "00:00:00", "title": "Open"}],
        "audio_storage_path": "org/audio/v1.m4a", "audio_content_type": "audio/mp4",
        "video_id": "v1",
    }

    @pytest.mark.asyncio
    async def test_default_mode_is_manual_package(self, monkeypatch):
        async def fake_manual(supabase, org_id, asset):
            return {"podcast_manual": {"ok": True, "delivered": "dropbox"}}

        async def boom_rss(*a, **k):
            raise AssertionError("rss path must not run in default (manual) mode")

        monkeypatch.setattr(publish, "_deliver_episode_package", fake_manual)
        monkeypatch.setattr(publish, "_publish_episode_rss", boom_rss)
        record = await publish._publish_episode(
            None, "org-1", dict(self.EP), published_at="now", config={}
        )
        assert record["podcast_manual"]["ok"] is True

    @pytest.mark.asyncio
    async def test_rss_mode_opt_in(self, monkeypatch):
        async def fake_rss(supabase, org_id, asset, *, published_at):
            return {"podcast_rss": {"ok": True, "feed_url": "https://x/feed.xml"}}

        async def boom_manual(*a, **k):
            raise AssertionError("manual path must not run in rss mode")

        monkeypatch.setattr(publish, "_publish_episode_rss", fake_rss)
        monkeypatch.setattr(publish, "_deliver_episode_package", boom_manual)
        record = await publish._publish_episode(
            None, "org-1", dict(self.EP), published_at="now",
            config={"podcast_publish_mode": "rss"},
        )
        assert record["podcast_rss"]["feed_url"]

    @pytest.mark.asyncio
    async def test_prior_manual_success_carried_forward(self, monkeypatch):
        async def boom(*a, **k):
            raise AssertionError("no re-delivery of an already-delivered episode")

        monkeypatch.setattr(publish, "_deliver_episode_package", boom)
        asset = dict(self.EP)
        asset["publish"] = {"podcast_manual": {"ok": True, "delivered": "dropbox"}}
        record = await publish._publish_episode(
            None, "org-1", asset, published_at="now", config={}
        )
        assert record["podcast_manual"]["delivered"] == "dropbox"

    def test_show_notes_markdown(self):
        md = publish.episode_show_notes_md(self.EP)
        assert md.startswith("# Ep 9")
        assert "**Show:** Positively American" in md
        assert "- 00:00:00 — Open" in md

    @pytest.mark.asyncio
    async def test_dropbox_failure_degrades_to_storage_only_success(self, monkeypatch, mock_supabase_factory):
        """The requirement is CREATION — a Dropbox hiccup must not park the
        pipeline at failed when the episode exists in the Storage library."""
        import packages.integrations.dropbox.client as dbx

        async def no_token(*a, **k):
            raise RuntimeError("dropbox not connected")

        monkeypatch.setattr(dbx, "get_fresh_access_token", no_token)

        class _Storage:
            def from_(self, bucket):
                return self
            def download(self, path):
                return b"audio-bytes"

        sb = mock_supabase_factory({})
        sb.storage = _Storage()
        record = await publish._deliver_episode_package(sb, "org-1", dict(self.EP))
        assert record["podcast_manual"]["ok"] is True
        assert record["podcast_manual"]["delivered"] == "storage-only"


# ── Stale-publishing rescue + SSRF guard ───────────────────────────────────
class TestStalePublishingRescue:
    @pytest.mark.asyncio
    async def test_rescues_wedged_rows_to_failed(self, mock_supabase_factory):
        from app.services import scheduler

        sb = mock_supabase_factory({
            "content_pipelines": [
                {"org_id": "org-1", "video_id": "v1", "status": "publishing",
                 "updated_at": "2020-01-01T00:00:00+00:00"},
            ],
        })
        await scheduler._rescue_stale_publishing(sb)
        updates = [p for t, p in sb._canned.get("_updates", []) if t == "content_pipelines"]
        assert updates and updates[0]["status"] == "failed"
        assert "re-approve" in updates[0]["error"]


class TestSsrfGuard:
    @pytest.mark.parametrize("url", [
        "http://plain-http.example/x.mp4",
        "https://127.0.0.1/x.mp4",
        "https://10.0.0.5/x.mp4",
        "https://localhost/x.mp4",
        "ftp://x/x.mp4",
        "",
    ])
    def test_rejects_unsafe_urls(self, url):
        with pytest.raises(RuntimeError):
            publish._assert_safe_url(url)

    def test_allows_public_https(self):
        publish._assert_safe_url("https://cdn.opus.pro/clips/abc.mp4")  # no raise


# ── Instagram gate ─────────────────────────────────────────────────────────
class TestInstagramGate:
    def test_unconfigured(self):
        from packages.integrations import instagram

        assert instagram.is_configured() is False

    @pytest.mark.asyncio
    async def test_publish_reel_raises_unavailable(self):
        from packages.integrations import instagram

        with pytest.raises(instagram.InstagramUnavailable):
            await instagram.publish_reel("https://c/1.mp4", caption="x")
