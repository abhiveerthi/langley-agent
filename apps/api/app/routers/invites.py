"""
Org invites API.

  POST   /api/invites               owner creates an invite + dispatches it
  GET    /api/invites               list pending invites for the current org
  POST   /api/invites/{id}/complete invitee finalizes after Supabase callback
  DELETE /api/invites/{id}          owner revokes a pending invite
  GET    /api/members               list active members of the current org

Delivery model: we generate the magic link via Supabase Auth's admin
`generate_link(type='invite')` and ferry it through the channel(s) the
owner picked — Resend for email, the org's existing Slack bot for Slack.
This way the invitee's signup flow goes through Supabase Auth (which
handles tokenization, single-use, expiry), and we keep full control of
the email template + Slack post.

The /complete endpoint runs after the invitee has been signed in by
Supabase Auth (via the Next.js /auth/callback route exchanging the
code for a session). It uses get_authenticated_user — a JWT-only
dependency that bypasses the org_members lookup, since the invitee
doesn't have a row yet at that moment.

The 'limited' role gates SELECT on brand_deals + org_profiles per
migration 010_org_invites.sql; everything else stays flat-access.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
import re

from pydantic import BaseModel, Field, field_validator, model_validator
from supabase import Client

from app.config import Settings, get_settings
from app.dependencies import (
    AuthenticatedUser,
    CurrentUser,
    get_authenticated_user,
    get_current_user,
    get_supabase,
)
from app.services.email import EmailDeliveryError, send_invite_email
from app.services.slack_invite import SlackDeliveryError, post_invite_to_slack

router = APIRouter(tags=["invites"])


# ── Models ─────────────────────────────────────────────────────────────────


# Loose-but-correct email pattern. Pydantic's EmailStr would do better
# RFC-5321 validation but pulls in `email-validator` as a runtime dep —
# overkill for a B2B invite form. Anything that has user@host and a TLD
# passes; the real validation happens when Resend/Supabase Auth actually
# sends it.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InviteCreate(BaseModel):
    email: str
    delivery_method: str = Field(pattern="^(email|slack|both)$")
    slack_channel_id: str | None = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip()
        if not _EMAIL_RE.match(v):
            raise ValueError(f"Invalid email address: {v!r}")
        return v

    @model_validator(mode="after")
    def _channel_required_when_slack(self):
        # field_validators are skipped when a defaulted None survives, so
        # this constraint lives at the model level — fires unconditionally.
        if self.delivery_method in ("slack", "both") and not self.slack_channel_id:
            raise ValueError(
                "slack_channel_id is required when delivery_method includes 'slack'"
            )
        return self


class InviteResponse(BaseModel):
    """Default invite shape returned by list / revoke / complete endpoints.

    NOTE: `magic_link` is NOT exposed here — it's a Supabase Auth
    single-use sign-in token bound to the invitee's email. Returning
    it on a list endpoint would let any authenticated org member
    impersonate any pending invitee. To copy a link manually, the
    team UI calls `GET /api/invites/{id}/link`, a dedicated endpoint
    gated to owner/member that returns only the link for one specific
    invite. See `LinkResponse` below."""
    id: str
    email: str
    invited_by: str
    delivery_method: str
    slack_channel_id: str | None = None
    last_delivery_attempt_at: str | None = None
    last_delivery_error: str | None = None
    accepted_at: str | None = None
    revoked_at: str | None = None
    created_at: str


class LinkResponse(BaseModel):
    """Returned by `GET /api/invites/{id}/link`. Isolated from
    `InviteResponse` so the magic link can never leak via a list
    endpoint."""
    magic_link: str


class InviteCreateResponse(BaseModel):
    invite: InviteResponse
    delivery_warnings: list[str] = []


class CompleteResponse(BaseModel):
    org_id: str
    org_slug: str


class MemberResponse(BaseModel):
    user_id: str
    email: str
    full_name: str | None = None
    role: str
    joined_at: str


# ── Helpers ────────────────────────────────────────────────────────────────


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _row_to_invite(row: dict) -> InviteResponse:
    """Maps a DB row to the public invite shape. Intentionally OMITS
    `magic_link` — see security note on InviteResponse."""
    return InviteResponse(
        id=row["id"],
        email=row["email"],
        invited_by=row["invited_by"],
        delivery_method=row["delivery_method"],
        slack_channel_id=row.get("slack_channel_id"),
        last_delivery_attempt_at=row.get("last_delivery_attempt_at"),
        last_delivery_error=row.get("last_delivery_error"),
        accepted_at=row.get("accepted_at"),
        revoked_at=row.get("revoked_at"),
        created_at=row["created_at"],
    )


def _fetch_org(supabase: Client, org_id: str) -> dict:
    resp = supabase.table("orgs").select("id, name, slug").eq("id", org_id).limit(1).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Org not found")
    return resp.data[0]


def _fetch_user_full_name(supabase: Client, user_id: str) -> str:
    resp = (
        supabase.table("users")
        .select("full_name, email")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0].get("full_name") or resp.data[0].get("email") or "Someone"
    return "Someone"


def _generate_magic_link(
    *, supabase: Client, settings: Settings, email: str, invite_id: str
) -> str:
    """Generate a Supabase Auth invite link. Doesn't send an email — we
    deliver via our own channels. Returns the magic-link URL.

    Note: gotrue-py's generate_link expects a dict with type, email, and
    optional options (data, redirect_to). The redirect_to carries the
    invite_id back to /auth/callback as a query param so Next.js can
    finalize via POST /api/invites/{id}/complete."""
    redirect_to = f"{settings.app_url}/auth/callback?org_invite_id={invite_id}"
    try:
        resp = supabase.auth.admin.generate_link(
            {
                "type": "invite",
                "email": email,
                "options": {
                    "data": {"org_invite_id": invite_id},
                    "redirect_to": redirect_to,
                },
            }
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not generate invite link: {e}")

    # The Python SDK shape: response.properties.action_link
    properties = getattr(resp, "properties", None)
    action_link = getattr(properties, "action_link", None) if properties else None
    if not action_link:
        # Some SDK versions return a dict-like response
        if isinstance(resp, dict):
            action_link = (resp.get("properties") or {}).get("action_link")
    if not action_link:
        raise HTTPException(status_code=502, detail="Supabase did not return an action_link")
    return action_link


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/invites", status_code=201, response_model=InviteCreateResponse)
async def create_invite(
    body: InviteCreate,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    # Role gate. v1 roles: 'owner' (auto-provisioned creators) and
    # 'member' (legacy schema default) can invite. 'limited' invitees
    # explicitly cannot — the whole point of the role is read-restriction;
    # letting them invite further accounts would be privilege expansion
    # within the org. v2 roles like 'admin'/'editor' will be added to
    # the allowlist as they're introduced.
    if user.role not in ("owner", "member"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to invite teammates to this workspace.",
        )

    email = _normalize_email(body.email)

    # 1. Reject if invitee is already a member of any org (single-org-per-user, v1).
    existing_member = (
        supabase.table("users")
        .select("id, org_members!inner(org_id)")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    if existing_member.data:
        raise HTTPException(
            status_code=409,
            detail="This email is already a member of a Backroom workspace. Multi-workspace membership is coming in a future release.",
        )

    # 2. Insert org_invites row. Partial-unique catches duplicate outstanding invites.
    insert_payload = {
        "org_id": user.org_id,
        "email": email,
        "invited_by": user.id,
        "delivery_method": body.delivery_method,
        "slack_channel_id": body.slack_channel_id,
    }
    try:
        insert_resp = supabase.table("org_invites").insert(insert_payload).execute()
    except Exception as e:
        msg = str(e).lower()
        if "unique" in msg or "duplicate" in msg or "23505" in msg:
            raise HTTPException(
                status_code=409,
                detail=f"An outstanding invite for {email} already exists. Revoke it first or use the resend control.",
            )
        raise HTTPException(status_code=500, detail=f"Could not create invite: {e}")

    invite_row = insert_resp.data[0]
    invite_id = invite_row["id"]

    # 3. Generate the magic link via Supabase Auth admin.
    magic_link = _generate_magic_link(
        supabase=supabase, settings=settings, email=email, invite_id=invite_id
    )

    # 4. Dispatch delivery. Track failures per-channel; stamp on the row.
    org = _fetch_org(supabase, user.org_id)
    inviter_name = _fetch_user_full_name(supabase, user.id)
    warnings: list[str] = []
    delivery_error: str | None = None

    if body.delivery_method in ("email", "both"):
        try:
            await send_invite_email(
                to=email,
                magic_link=magic_link,
                org_name=org["name"],
                inviter_name=inviter_name,
                settings=settings,
            )
        except EmailDeliveryError as e:
            warnings.append(f"email: {e}")
            delivery_error = (delivery_error + " | " if delivery_error else "") + f"email: {e}"

    if body.delivery_method in ("slack", "both"):
        if not body.slack_channel_id:
            warnings.append("slack: channel_id not provided")
            delivery_error = (delivery_error + " | " if delivery_error else "") + "slack: channel_id missing"
        else:
            try:
                await post_invite_to_slack(
                    supabase=supabase,
                    org_id=user.org_id,
                    channel_id=body.slack_channel_id,
                    magic_link=magic_link,
                    invitee_email=email,
                    inviter_name=inviter_name,
                    org_name=org["name"],
                )
            except SlackDeliveryError as e:
                warnings.append(f"slack: {e}")
                delivery_error = (delivery_error + " | " if delivery_error else "") + f"slack: {e}"

    # 5. Stamp magic_link + delivery state on the row. magic_link is
    #    persisted so the team page can show a "Copy link" button later
    #    (manual sharing fallback while a sending domain is being verified,
    #    or whenever an owner wants to send via Slack DM / iMessage / etc).
    now_iso = datetime.now(timezone.utc).isoformat()
    update_payload: dict[str, Any] = {
        "magic_link": magic_link,
        "last_delivery_attempt_at": now_iso,
        "last_delivery_error": delivery_error,
    }
    update_resp = (
        supabase.table("org_invites")
        .update(update_payload)
        .eq("id", invite_id)
        .execute()
    )
    final_row = update_resp.data[0] if update_resp.data else {**invite_row, **update_payload}

    return InviteCreateResponse(invite=_row_to_invite(final_row), delivery_warnings=warnings)


@router.get("/invites", response_model=list[InviteResponse])
async def list_invites(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Returns outstanding (unaccepted, unrevoked) invites for the current org."""
    resp = (
        supabase.table("org_invites")
        .select("*")
        .eq("org_id", user.org_id)
        .is_("accepted_at", "null")
        .is_("revoked_at", "null")
        .order("created_at", desc=True)
        .execute()
    )
    return [_row_to_invite(r) for r in (resp.data or [])]


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Soft-revoke a pending invite. Magic link returns 410 on use after this."""
    # Same role gate as create_invite — limited members must not be able
    # to revoke their org's outstanding invites.
    if user.role not in ("owner", "member"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to revoke invites for this workspace.",
        )

    # Fetch first to give specific error codes.
    fetch = (
        supabase.table("org_invites")
        .select("id, org_id, accepted_at, revoked_at")
        .eq("id", invite_id)
        .limit(1)
        .execute()
    )
    if not fetch.data:
        raise HTTPException(status_code=404, detail="Invite not found")
    row = fetch.data[0]
    if row["org_id"] != user.org_id:
        # RLS would also block this, but be explicit.
        raise HTTPException(status_code=404, detail="Invite not found")
    if row.get("accepted_at"):
        raise HTTPException(status_code=400, detail="Invite already accepted; cannot revoke")
    if row.get("revoked_at"):
        return  # Idempotent revoke.

    supabase.table("org_invites").update(
        {"revoked_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", invite_id).execute()


@router.get("/invites/{invite_id}/link", response_model=LinkResponse)
async def get_invite_link(
    invite_id: str,
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Return the Supabase magic link for a single pending invite so
    the team UI can copy it for manual sharing.

    Security boundary:
      - Same role gate as create/revoke: limited members must NOT have
        access — handing them this URL would let them impersonate the
        intended invitee via Supabase's implicit sign-in flow.
      - Org-scoped: the invite must belong to the caller's org.
      - Refuses revoked / accepted invites — those links are dead or
        already consumed; serving them invites confusion.
    """
    if user.role not in ("owner", "member"):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to copy invite links for this workspace.",
        )

    fetch = (
        supabase.table("org_invites")
        .select("id, org_id, magic_link, accepted_at, revoked_at")
        .eq("id", invite_id)
        .limit(1)
        .execute()
    )
    if not fetch.data:
        raise HTTPException(status_code=404, detail="Invite not found")
    row = fetch.data[0]
    if row["org_id"] != user.org_id:
        # 404, not 403 — don't confirm existence of cross-tenant invites.
        raise HTTPException(status_code=404, detail="Invite not found")
    if row.get("accepted_at"):
        raise HTTPException(status_code=410, detail="Invite has already been accepted")
    if row.get("revoked_at"):
        raise HTTPException(status_code=410, detail="Invite has been revoked")
    link = row.get("magic_link")
    if not link:
        # Legacy row from before migration 011 — no link stored.
        raise HTTPException(status_code=404, detail="No link stored for this invite")
    return LinkResponse(magic_link=link)


@router.post("/invites/{invite_id}/complete", response_model=CompleteResponse)
async def complete_invite(
    invite_id: str,
    auth_user: AuthenticatedUser = Depends(get_authenticated_user),
    supabase: Client = Depends(get_supabase),
):
    """Finalize invite acceptance. Called by the Next.js /auth/callback
    route after Supabase Auth has signed the invitee in.

    Idempotent: same token + same email re-runs cleanly on retries.
    """
    # 1. Look up the invite row.
    fetch = (
        supabase.table("org_invites")
        .select("*")
        .eq("id", invite_id)
        .limit(1)
        .execute()
    )
    if not fetch.data:
        raise HTTPException(status_code=404, detail="Invite not found")
    invite = fetch.data[0]

    if invite.get("revoked_at"):
        raise HTTPException(status_code=410, detail="This invite has been revoked")
    # accepted_at being set is fine on retry (idempotent), but only for the same user.

    # 2. Verify the authenticated user's email matches the invite (case-insensitive).
    invited_email = (invite.get("email") or "").strip().lower()
    auth_email = (auth_user.email or "").strip().lower()
    if not invited_email or invited_email != auth_email:
        raise HTTPException(
            status_code=403,
            detail="This invite was issued to a different email address. Sign in with the invited email or contact the org owner.",
        )

    # 3. Single-org-per-user check. If the invitee already has any
    #    org_members row for a DIFFERENT org, reject.
    existing = (
        supabase.table("org_members")
        .select("id, org_id")
        .eq("user_id", auth_user.id)
        .execute()
    )
    other_orgs = [r for r in (existing.data or []) if r["org_id"] != invite["org_id"]]
    if other_orgs:
        # Look up the existing org name for a friendly message.
        first_other = other_orgs[0]
        org_resp = (
            supabase.table("orgs")
            .select("name")
            .eq("id", first_other["org_id"])
            .limit(1)
            .execute()
        )
        existing_name = org_resp.data[0]["name"] if org_resp.data else "another workspace"
        raise HTTPException(
            status_code=409,
            detail=(
                f"This email is already part of {existing_name}. Multi-workspace "
                f"membership is coming in a future release. To join this workspace, "
                f"please contact the owner to use a different email."
            ),
        )

    # 4. Upsert users row (idempotent, matches _provision_personal_workspace pattern).
    supabase.table("users").upsert(
        {"id": auth_user.id, "email": auth_email},
        on_conflict="id",
    ).execute()

    # 5. Upsert org_members with role='limited' (idempotent on (org_id, user_id)).
    supabase.table("org_members").upsert(
        {"org_id": invite["org_id"], "user_id": auth_user.id, "role": "limited"},
        on_conflict="org_id,user_id",
    ).execute()

    # 6. Mark accepted_at if not already set (idempotent — `WHERE accepted_at IS NULL`).
    if not invite.get("accepted_at"):
        supabase.table("org_invites").update(
            {"accepted_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", invite_id).is_("accepted_at", "null").execute()

    # 7. Return the org info so Next.js can redirect into the workspace.
    org = _fetch_org(supabase, invite["org_id"])
    return CompleteResponse(org_id=org["id"], org_slug=org["slug"])


@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Active members of the current org. Joins users for display fields."""
    resp = (
        supabase.table("org_members")
        .select("user_id, role, created_at, users!inner(email, full_name)")
        .eq("org_id", user.org_id)
        .order("created_at")
        .execute()
    )
    out: list[MemberResponse] = []
    for row in resp.data or []:
        u = row.get("users") or {}
        out.append(
            MemberResponse(
                user_id=row["user_id"],
                email=u.get("email", ""),
                full_name=u.get("full_name"),
                role=row.get("role", "member"),
                joined_at=row["created_at"],
            )
        )
    return out
