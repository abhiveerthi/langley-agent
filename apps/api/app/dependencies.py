from fastapi import Depends, HTTPException, Request
from supabase import create_client, Client
from app.config import get_settings, Settings
from dataclasses import dataclass


@dataclass
class CurrentUser:
    id: str
    org_id: str
    email: str
    role: str = "member"


def get_supabase(settings: Settings = Depends(get_settings)) -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_key)


async def get_current_user(request: Request, supabase: Client = Depends(get_supabase)) -> CurrentUser:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = auth_header.split(" ")[1]

    try:
        user_response = supabase.auth.get_user(token)
        user = user_response.user
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Get the user's org membership
    membership = (
        supabase.table("org_members")
        .select("org_id, role")
        .eq("user_id", user.id)
        .limit(1)
        .execute()
    )

    if not membership.data:
        raise HTTPException(status_code=403, detail="User is not a member of any organization")

    member = membership.data[0]

    return CurrentUser(
        id=user.id,
        org_id=member["org_id"],
        email=user.email,
        role=member["role"],
    )
