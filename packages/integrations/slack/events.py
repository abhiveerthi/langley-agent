"""Signing-secret verification for Slack's Events API webhook.

Slack signs every event POST with HMAC-SHA256 over the raw request body and
a unix timestamp, using the app's signing secret as the key. We verify both
the signature and that the timestamp is fresh (≤5 minutes old) so an
attacker can't replay an old captured event.

See https://api.slack.com/authentication/verifying-requests-from-slack.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Mapping

# Slack rejects requests older than this window in their own server-side
# verification; mirror it so a captured signature can't be replayed forever.
MAX_TIMESTAMP_SKEW_SECONDS = 60 * 5


def verify_signing_secret(
    headers: Mapping[str, str],
    raw_body: bytes,
    signing_secret: str,
) -> bool:
    """Return True iff the X-Slack-Signature header matches an HMAC of
    raw_body and the X-Slack-Request-Timestamp header is fresh.

    Reads headers case-insensitively (FastAPI's `request.headers` already
    handles that, but we tolerate raw dicts too for testability)."""
    if not signing_secret:
        return False

    # Case-insensitive header lookup.
    timestamp = _get_header(headers, "X-Slack-Request-Timestamp")
    signature = _get_header(headers, "X-Slack-Signature")
    if not timestamp or not signature:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > MAX_TIMESTAMP_SKEW_SECONDS:
        return False

    # Slack's basestring format: "v0:{ts}:{raw_body}"
    basestring = b"v0:" + timestamp.encode() + b":" + raw_body
    expected = (
        "v0="
        + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature)


def _get_header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return None
