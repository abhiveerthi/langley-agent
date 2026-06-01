"""
Agent artifact → PDF rendering + Dropbox delivery.

The product wants agent outputs (Strategist weekly briefs, intel/triage
reports, Brand Manager pitches) delivered as polished PDFs — both archived in
the Storage Library (so the creator sees them alongside their own uploads) and
dropped into the creator's connected Dropbox (so they live where the rest of
their files do).

Two layers here:

  render_pdf(...)               — Markdown/HTML body → PDF bytes. Pure-Python
                                  via reportlab (no wkhtmltopdf, no headless
                                  browser, no system libraries). A lightweight
                                  Markdown subset is parsed into reportlab
                                  flowables: a cover/title block, headings,
                                  body paragraphs, bullet lists, bold/italic.

  deliver_pdf_to_dropbox(...)   — uploads the PDF into the org's connected
                                  Dropbox under /Marcus/<subfolder>/. Resolves
                                  the connection exactly like the dropbox
                                  router/client (integrations row + refreshed
                                  access token).

Both follow storage_export.py's defensive contract: best-effort, never raise.
Dropbox not connected / not configured / a flaky upload → log and return None.
The agent's primary output (DB row, chat reply, Storage copy) has already
shipped; a delivery hiccup must not break the user-facing flow.
"""
from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from io import BytesIO

from packages.integrations.context import current_supabase


# ── Markdown → reportlab inline formatting ─────────────────────────────────
# reportlab Paragraphs accept a tiny HTML-ish markup (<b>, <i>, <br/>). We
# translate a Markdown subset into that, escaping everything else so user /
# LLM content can't inject stray tags.
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE = re.compile(r"`(.+?)`")


def _inline(text: str) -> str:
    """Escape text, then re-introduce the small set of inline tags reportlab
    understands. Order matters: escape first so the source can't smuggle tags,
    then apply bold/italic/code on the escaped string."""
    out = html.escape(text, quote=False)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _INLINE_CODE.sub(r"<font face='Courier'>\1</font>", out)
    out = _ITALIC.sub(r"<i>\1</i>", out)
    return out


def render_pdf(
    title: str,
    markdown_body: str,
    *,
    subtitle: str | None = None,
    brand_name: str | None = None,
) -> bytes:
    """Render a clean, professional PDF from a Markdown (or plain-text) body.

    Layout: a cover/title block (optional brand kicker, title, optional
    subtitle, generated-on date, hairline rule) followed by the body with
    `#`/`##`/`###` headings, paragraphs, and `-`/`*`/`1.` bullet lists.

    Returns the PDF as bytes (always begins with the `%PDF` magic header).
    Pure reportlab — no system binaries required.
    """
    # Imported lazily so importing this module (e.g. for deliver_pdf_to_dropbox)
    # never pays the reportlab import cost or hard-fails if it's somehow absent.
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        ListFlowable,
        ListItem,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    base = getSampleStyleSheet()
    ink = colors.HexColor("#1a1a1a")
    muted = colors.HexColor("#6b7280")
    accent = colors.HexColor("#111827")

    title_style = ParagraphStyle(
        "MarcusTitle", parent=base["Title"], fontName="Helvetica-Bold",
        fontSize=26, leading=30, textColor=accent, spaceAfter=6, alignment=TA_LEFT,
    )
    kicker_style = ParagraphStyle(
        "MarcusKicker", parent=base["Normal"], fontName="Helvetica-Bold",
        fontSize=10, leading=12, textColor=muted, spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "MarcusSubtitle", parent=base["Normal"], fontName="Helvetica",
        fontSize=13, leading=17, textColor=muted, spaceAfter=2,
    )
    meta_style = ParagraphStyle(
        "MarcusMeta", parent=base["Normal"], fontName="Helvetica",
        fontSize=9, leading=12, textColor=muted, spaceBefore=8,
    )
    h1 = ParagraphStyle(
        "MarcusH1", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=17, leading=21, textColor=accent, spaceBefore=16, spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "MarcusH2", parent=base["Heading2"], fontName="Helvetica-Bold",
        fontSize=13, leading=17, textColor=ink, spaceBefore=12, spaceAfter=4,
    )
    h3 = ParagraphStyle(
        "MarcusH3", parent=base["Heading3"], fontName="Helvetica-Bold",
        fontSize=11, leading=15, textColor=ink, spaceBefore=10, spaceAfter=3,
    )
    body = ParagraphStyle(
        "MarcusBody", parent=base["BodyText"], fontName="Helvetica",
        fontSize=10.5, leading=15, textColor=ink, spaceAfter=8,
    )

    flowables: list = []

    # ── Cover / title block ──────────────────────────────────────────────
    if brand_name:
        flowables.append(Paragraph(_inline(brand_name.upper()), kicker_style))
    flowables.append(Paragraph(_inline(title or "Untitled"), title_style))
    if subtitle:
        flowables.append(Paragraph(_inline(subtitle), subtitle_style))
    generated = datetime.now(timezone.utc).strftime("%B %d, %Y")
    flowables.append(Paragraph(f"Generated {generated}", meta_style))
    flowables.append(Spacer(1, 6))
    flowables.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb")))
    flowables.append(Spacer(1, 12))

    # ── Body ─────────────────────────────────────────────────────────────
    flowables.extend(_body_flowables(
        markdown_body or "", h1, h2, h3, body,
        Paragraph, ListFlowable, ListItem, Spacer,
    ))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        title=title or "Marcus document", author=brand_name or "Marcus",
    )
    doc.build(flowables)
    return buf.getvalue()


def _body_flowables(
    md: str, h1, h2, h3, body, Paragraph, ListFlowable, ListItem, Spacer,
) -> list:
    """Translate a Markdown subset into a flat list of reportlab flowables.

    Supported: ATX headings (#/##/###), `-`/`*` and `1.` lists (consecutive
    lines coalesce into one list), blank-line-separated paragraphs, and the
    inline bold/italic/code from `_inline`. Anything else is body text.
    """
    flowables: list = []
    pending_list: list = []

    def flush_list():
        nonlocal pending_list
        if pending_list:
            items = [ListItem(Paragraph(_inline(t), body), leftIndent=12) for t in pending_list]
            flowables.append(ListFlowable(items, bulletType="bullet", start="•", leftIndent=14))
            flowables.append(Spacer(1, 4))
            pending_list = []

    for raw in md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_list()
            continue

        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        ordered = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if bullet or ordered:
            pending_list.append((bullet or ordered).group(1).strip())
            continue

        flush_list()

        if stripped.startswith("### "):
            flowables.append(Paragraph(_inline(stripped[4:].strip()), h3))
        elif stripped.startswith("## "):
            flowables.append(Paragraph(_inline(stripped[3:].strip()), h2))
        elif stripped.startswith("# "):
            flowables.append(Paragraph(_inline(stripped[2:].strip()), h1))
        elif stripped in ("---", "***", "___"):
            flowables.append(Spacer(1, 6))
        else:
            flowables.append(Paragraph(_inline(stripped), body))

    flush_list()
    return flowables


# ── Dropbox delivery ───────────────────────────────────────────────────────
_DROPBOX_ROOT = "/Marcus"
# Same filename hygiene as storage_export — agent-supplied names can never
# escape their folder or carry path separators into the Dropbox path.
_DROPBOX_SAFE = re.compile(r"[^a-zA-Z0-9._-]")


def _safe_segment(name: str, fallback: str) -> str:
    cleaned = _DROPBOX_SAFE.sub("_", (name or "").strip())
    return cleaned or fallback


async def deliver_pdf_to_dropbox(
    org_id: str,
    *,
    filename: str,
    pdf_bytes: bytes,
    subfolder: str,
) -> str | None:
    """Upload `pdf_bytes` to the org's connected Dropbox under
    `/Marcus/<subfolder>/<filename>`.

    Resolves the connection the same way the dropbox router does: read the
    `integrations` row for (org_id, provider='dropbox'), then mint a fresh
    access token (refreshing if expired) using the server's Dropbox OAuth
    credentials. Returns the Dropbox path on success.

    Best-effort by design — returns None (never raises) when:
      - there's no Supabase in context or no org_id,
      - Dropbox isn't connected for this org,
      - the server has no Dropbox OAuth credentials configured,
      - the token refresh or upload fails.

    Mirrors storage_export.py: this is a side-channel, not the agent's
    primary output, so the caller should not branch on success.
    """
    supabase = current_supabase.get()
    if supabase is None or not org_id or not pdf_bytes:
        return None

    # Late imports keep agent-core import-time free of integration deps and
    # avoid load-order cycles.
    from packages.integrations.dropbox.client import (
        get_connection,
        get_fresh_access_token,
        upload_file,
    )

    try:
        conn = get_connection(supabase, org_id)
    except Exception as e:
        print(f"[pdf_export] dropbox connection lookup failed for {org_id}: {e!r}", flush=True)
        return None
    if not conn:
        # Dropbox simply isn't connected — the common no-op path.
        return None

    client_id = os.environ.get("DROPBOX_CLIENT_ID", "")
    client_secret = os.environ.get("DROPBOX_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("[pdf_export] dropbox OAuth not configured on server; skipping delivery", flush=True)
        return None

    try:
        token = await get_fresh_access_token(supabase, org_id, client_id, client_secret)
    except Exception as e:
        print(f"[pdf_export] dropbox token resolution failed for {org_id}: {e!r}", flush=True)
        return None

    sub = _safe_segment(subfolder, "misc")
    name = _safe_segment(filename, "document.pdf")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    dropbox_path = f"{_DROPBOX_ROOT}/{sub}/{name}"

    try:
        await upload_file(token, dropbox_path, pdf_bytes, mode="overwrite")
    except Exception as e:
        print(f"[pdf_export] dropbox upload failed for {dropbox_path}: {e!r}", flush=True)
        return None

    return dropbox_path
