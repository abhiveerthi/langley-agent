"""
PDF rendering + Dropbox delivery — the artifact pipeline behind Strategist
briefs, CM triage reports, and Brand Manager pitches.

Two contracts under test:
  - render_pdf produces real PDF bytes (magic header, non-empty) from a
    Markdown body, with and without the optional cover fields.
  - deliver_pdf_to_dropbox is best-effort: it no-ops gracefully (returns
    None, never raises) when there's no Supabase context and when the org
    has no Dropbox connection.

No real Dropbox / Supabase — uses the conftest MockSupabase stand-in and the
autouse contextvar reset. asyncio_mode=auto means async tests need no marker.
"""
from __future__ import annotations

from packages.agents.core.pdf_export import deliver_pdf_to_dropbox, render_pdf
from packages.integrations.context import current_supabase


# ── render_pdf ─────────────────────────────────────────────────────────────
class TestRenderPdf:
    def test_returns_pdf_bytes_with_magic_header(self):
        out = render_pdf(
            "Weekly Brief",
            "# Headline\n\nA paragraph of body text.\n\n- one\n- two\n",
        )
        assert isinstance(out, bytes)
        assert out, "expected non-empty PDF bytes"
        assert out.startswith(b"%PDF"), "missing PDF magic header"

    def test_cover_fields_are_optional(self):
        out = render_pdf("Title only", "Just a body line.")
        assert out.startswith(b"%PDF")

    def test_full_cover_block_renders(self):
        out = render_pdf(
            "Pitch to Magpul",
            "## Section\n\n**Bold** and *italic* and `code`.\n\n1. first\n2. second\n",
            subtitle="Sponsorship outreach",
            brand_name="Langley Outdoors Academy",
        )
        assert out.startswith(b"%PDF")
        # A richer document should be at least as large as a bare one.
        assert len(out) > len(render_pdf("x", "y"))

    def test_markdown_with_html_chars_does_not_crash(self):
        # User/LLM content can contain < > & — must be escaped, not injected.
        out = render_pdf("A & B", "Compare 1 < 2 & 3 > 2 in <tags>.")
        assert out.startswith(b"%PDF")


# ── deliver_pdf_to_dropbox ──────────────────────────────────────────────────
class TestDeliverPdfToDropbox:
    async def test_noop_when_no_supabase_context(self, real_uuid):
        # _reset_contextvars (autouse) leaves current_supabase = None.
        result = await deliver_pdf_to_dropbox(
            real_uuid,
            filename="brief.pdf",
            pdf_bytes=b"%PDF-1.4 fake",
            subfolder="briefs",
        )
        assert result is None

    async def test_noop_when_no_org_id(self, mock_supabase):
        current_supabase.set(mock_supabase)
        result = await deliver_pdf_to_dropbox(
            "",
            filename="brief.pdf",
            pdf_bytes=b"%PDF-1.4 fake",
            subfolder="briefs",
        )
        assert result is None

    async def test_noop_when_no_dropbox_connection(self, mock_supabase, real_uuid):
        # MockSupabase has no `integrations` rows → get_connection returns None
        # → delivery is a clean no-op, no exception.
        current_supabase.set(mock_supabase)
        result = await deliver_pdf_to_dropbox(
            real_uuid,
            filename="brief.pdf",
            pdf_bytes=b"%PDF-1.4 fake",
            subfolder="briefs",
        )
        assert result is None

    async def test_noop_when_empty_pdf_bytes(self, mock_supabase, real_uuid):
        current_supabase.set(mock_supabase)
        result = await deliver_pdf_to_dropbox(
            real_uuid,
            filename="brief.pdf",
            pdf_bytes=b"",
            subfolder="briefs",
        )
        assert result is None
