from fastapi import Depends, HTTPException, Request
from supabase import create_client, Client
from app.config import get_settings, Settings
from app.auth_cache import TtlCache
from dataclasses import dataclass


@dataclass
class CurrentUser:
    id: str
    org_id: str
    email: str
    role: str = "member"


@dataclass
class AuthenticatedUser:
    """Just-the-JWT-decode user, no org membership context.

    Used by endpoints like POST /api/invites/{id}/complete where the
    invitee is authenticated via Supabase Auth but doesn't yet have an
    org_members row (and the auto-provisioner gate would 409 them via
    get_current_user). The /complete endpoint inserts that row itself."""
    id: str
    email: str


# Cached service-role client(s), keyed on the (url, key) tuple.
# Constructing a Supabase Client builds GoTrueClient + PostgrestClient +
# RealtimeClient + StorageClient under the hood, each with their own
# httpx Client. Doing that per request burns measurable CPU + GC pressure
# for no value — the configuration never changes within a process. The
# Client is thread-safe (the underlying httpx Clients are designed for
# sharing), so a process-wide singleton is safe to share across requests.
#
# Keying on (url, key) instead of a bare global so:
#   1. Tests that swap settings get a fresh client.
#   2. If we ever need a multi-tenant Supabase config (different region per
#      cohort etc.), the cache shape already supports it.
_supabase_clients: dict[tuple[str, str], Client] = {}

# Auth-token cache singletons (from the auth-cache PR). One per kind of
# resolver because a `CurrentUser` and an `AuthenticatedUser` aren't
# interchangeable — `get_authenticated_user` must NOT silently return the
# org-bound shape even if a same-token entry exists in the org-bound cache.
#
# Tests reset these via clear() between cases; production code never
# touches them directly.
_current_user_cache: TtlCache[CurrentUser] = TtlCache()
_authenticated_user_cache: TtlCache[AuthenticatedUser] = TtlCache()


def get_supabase(settings: Settings = Depends(get_settings)) -> Client:
    """Return a cached service-role Supabase client.

    First call for a given (url, key) tuple builds the Client; every
    subsequent call returns the same instance. The Client is intended
    to be shared across requests — it pools its own HTTP connections
    via httpx, and the auth/db sub-clients are stateless wrt the
    caller's identity (we always pass the user JWT explicitly via the
    `auth.get_user(token)` API, never via Client state).
    """
    cache_key = (settings.supabase_url, settings.supabase_service_key)
    cached = _supabase_clients.get(cache_key)
    if cached is not None:
        return cached
    client = create_client(*cache_key)
    _supabase_clients[cache_key] = client
    return client


async def get_authenticated_user(
    request: Request,
    supabase: Client = Depends(get_supabase),
) -> AuthenticatedUser:
    """Decode the Bearer token and return the auth.users identity.

    Does NOT look up org_members or trigger the auto-provisioner gate.
    Use this when the caller is authenticated but org context isn't
    relevant yet (e.g. invite acceptance — the org_members row gets
    inserted by the endpoint handler after this dependency runs)."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = auth_header.split(" ")[1]

    cached = _authenticated_user_cache.get(token)
    if cached is not None:
        return cached

    try:
        user_response = supabase.auth.get_user(token)
        user = user_response.user
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    resolved = AuthenticatedUser(id=user.id, email=user.email or "")
    _authenticated_user_cache.set(token, resolved)
    return resolved


async def get_current_user(request: Request, supabase: Client = Depends(get_supabase)) -> CurrentUser:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = auth_header.split(" ")[1]

    # Cache hit short-circuits both the JWT verify and the org_members
    # SELECT. This is the hot path during normal page loads — every
    # other call from a user within ~60s lands here.
    cached = _current_user_cache.get(token)
    if cached is not None:
        return cached

    try:
        user_response = supabase.auth.get_user(token)
        user = user_response.user
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    membership = (
        supabase.table("org_members")
        .select("org_id, role")
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )

    if membership.data:
        member = membership.data[0]
        resolved = CurrentUser(
            id=user.id,
            org_id=member["org_id"],
            email=user.email,
            role=member["role"],
        )
        _current_user_cache.set(token, resolved)
        return resolved

    # No membership yet. Before auto-provisioning a personal workspace,
    # check whether the user's email has a pending invite waiting. If so,
    # block the auto-provision — the invitee must accept the invite to
    # land in the inviting org, not be quietly handed a separate personal
    # workspace they'd then be locked out of (single-org-per-user in v1).
    #
    # Note: the 409 below is deliberately NOT cached. The user might be
    # about to click their invite link, after which the next request
    # should resolve fresh — not be told 409 again until the TTL expires.
    email_norm = (user.email or "").strip().lower()
    if email_norm:
        pending = (
            supabase.table("org_invites")
            .select("id")
            .eq("email", email_norm)
            .is_("accepted_at", "null")
            .is_("revoked_at", "null")
            .limit(1)
            .execute()
        )
        if pending.data:
            raise HTTPException(
                status_code=409,
                detail="You have a pending invite. Click the link in your invite email to join the workspace.",
            )

    # First sign-in with no pending invite: provision a personal workspace.
    member = _provision_personal_workspace(supabase, user)
    resolved = CurrentUser(
        id=user.id,
        org_id=member["org_id"],
        email=user.email,
        role=member["role"],
    )
    _current_user_cache.set(token, resolved)
    return resolved


def _provision_personal_workspace(supabase: Client, user) -> dict:
    # Ensure users row
    meta = getattr(user, "user_metadata", {}) or {}
    full_name = meta.get("full_name") or meta.get("name") or (user.email.split("@")[0] if user.email else None)
    (
        supabase.table("users")
        .upsert(
            {"id": user.id, "email": user.email, "full_name": full_name},
            on_conflict="id",
        )
        .execute()
    )

    # Create or recover a personal org
    org_name = f"{full_name}'s workspace" if full_name else "My workspace"
    slug = f"u-{user.id.replace('-', '')[:10]}"

    try:
        org_row = (
            supabase.table("orgs")
            .insert({"name": org_name, "slug": slug})
            .execute()
            .data[0]
        )
    except Exception:
        # Slug collision — recover existing row
        org_row = (
            supabase.table("orgs")
            .select("id")
            .eq("slug", slug)
            .limit(1)
            .execute()
            .data[0]
        )

    # Idempotent membership (unique on org_id+user_id)
    (
        supabase.table("org_members")
        .upsert(
            {"org_id": org_row["id"], "user_id": user.id, "role": "owner"},
            on_conflict="org_id,user_id",
        )
        .execute()
    )

    return {"org_id": org_row["id"], "role": "owner"}
