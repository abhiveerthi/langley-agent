"""
Output-escaping tests for the invite delivery services.

Owner-controlled fields (org_name, inviter_name) flow into:
  - HTML email body via app.services.email._render_invite_html
  - Slack mrkdwn message via app.services.slack_invite._format_invite_message

Both surfaces are user-facing and reach recipients outside the inviting
org, so injection there becomes a phishing vector. These tests pin the
escape boundary.
"""
from __future__ import annotations

from app.services.email import _render_invite_html, _render_invite_text, _safe_link
from app.services.slack_invite import _escape_mrkdwn, _format_invite_message


# ── HTML email ──────────────────────────────────────────────────────────


class TestEmailHtmlEscape:
    def test_org_name_with_script_tag_is_escaped(self):
        html = _render_invite_html(
            magic_link="https://example.com/m",
            org_name="<script>alert(1)</script>",
            inviter_name="Alice",
        )
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_inviter_name_attribute_escape(self):
        """A break-out from a quoted attribute would look like
        `"><script>...</script>`. Make sure quotes get escaped too."""
        html = _render_invite_html(
            magic_link="https://example.com/m",
            org_name="Org",
            inviter_name='"><img src=x onerror=alert(1)>',
        )
        # Raw payload must not appear; escaped form must.
        assert '"><img src=x onerror=alert(1)>' not in html
        assert "&quot;&gt;&lt;img" in html or "&#x27;" in html or "&lt;img" in html

    def test_javascript_link_rejected(self):
        """An attacker-controlled `magic_link` (shouldn't happen since it's
        Supabase-generated, but defense in depth) must not produce a
        javascript: href."""
        html = _render_invite_html(
            magic_link="javascript:alert(1)",
            org_name="Org",
            inviter_name="Alice",
        )
        assert "javascript:" not in html
        # The href becomes empty string; the button still renders.
        assert 'href=""' in html

    def test_https_link_passes_through_with_escape(self):
        html = _render_invite_html(
            magic_link='https://example.com/m?x="bad"',
            org_name="Org",
            inviter_name="Alice",
        )
        # Quotes inside the URL must be HTML-escaped within the href attr.
        assert 'href="https://example.com/m?x="bad""' not in html
        # Properly escaped form:
        assert "&quot;bad&quot;" in html


class TestEmailTextEscape:
    def test_text_strips_newlines_from_inviter(self):
        text = _render_invite_text(
            magic_link="https://example.com/m",
            org_name="Org",
            inviter_name="Alice\nBcc: attacker@example.com",
        )
        # The header-injection payload must not carry a newline through.
        assert "\nBcc:" not in text


class TestSafeLink:
    def test_https_passes(self):
        assert _safe_link("https://example.com/x") == "https://example.com/x"

    def test_http_passes(self):
        assert _safe_link("http://example.com/x") == "http://example.com/x"

    def test_javascript_blocked(self):
        assert _safe_link("javascript:alert(1)") == ""

    def test_data_uri_blocked(self):
        assert _safe_link("data:text/html,<script>alert(1)</script>") == ""

    def test_empty_string(self):
        assert _safe_link("") == ""

    def test_query_string_quotes_escaped(self):
        assert "&quot;" in _safe_link('https://example.com/x?q="x"')


# ── Slack mrkdwn ────────────────────────────────────────────────────────


class TestSlackMrkdwnEscape:
    def test_link_syntax_escaped(self):
        """Slack interprets `<URL|label>` as a clickable link. An
        org_name like `<https://phish/|Backroom>` would otherwise
        render as a phishing link."""
        out = _escape_mrkdwn("<https://phish/|Backroom>")
        assert "<https://phish/|Backroom>" not in out
        # Both `<` and `|` must be neutralized.
        assert "&lt;" in out and "&#124;" in out

    def test_format_invite_message_escapes_org_name(self):
        msg = _format_invite_message(
            magic_link="https://example.com/m",
            invitee_email="alice@example.com",
            inviter_name="Alice",
            org_name="<https://phish|Evil>",
        )
        assert "<https://phish|Evil>" not in msg
        # The legitimate magic link MUST still be wrapped in real link syntax
        assert "<https://example.com/m|" in msg

    def test_format_invite_message_preserves_legit_magic_link(self):
        msg = _format_invite_message(
            magic_link="https://supabase.example.com/auth/v1/verify?token=abc",
            invitee_email="alice@example.com",
            inviter_name="Owner",
            org_name="My Workspace",
        )
        # The Supabase URL goes inside the link slot un-escaped.
        assert "<https://supabase.example.com/auth/v1/verify?token=abc|" in msg

    def test_non_http_magic_link_drops(self):
        """Defense in depth: if somehow a non-http URL got into the
        magic_link slot, it must not become a clickable link."""
        msg = _format_invite_message(
            magic_link="javascript:alert(1)",
            invitee_email="alice@example.com",
            inviter_name="Owner",
            org_name="My Workspace",
        )
        assert "javascript:" not in msg
        # Still produces a (broken) link with empty URL — Slack will just
        # render it as `<|...>` which is harmless.
        assert "alert" not in msg

    def test_ampersand_escaped(self):
        out = _escape_mrkdwn("AT&T")
        assert "AT&amp;T" in out
