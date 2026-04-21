import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client

from app.config import Settings, get_settings
from app.dependencies import CurrentUser, get_current_user, get_supabase
from packages.integrations.youtube import client as yt_client
from packages.integrations.youtube import oauth as yt_oauth

router = APIRouter(tags=["integrations"])


class AuthUrlResponse(BaseModel):
    auth_url: str


class CallbackRequest(BaseModel):
    code: str
    state: str


@router.post("/integrations/youtube/auth-url", response_model=AuthUrlResponse)
async def youtube_auth_url(
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(500, "Google OAuth is not configured")
    if not settings.jwt_secret:
        raise HTTPException(500, "JWT secret is not configured")

    state = yt_oauth.sign_state(
        {"org_id": user.org_id, "user_id": user.id},
        settings.jwt_secret,
    )
    url = yt_oauth.build_auth_url(
        client_id=settings.google_client_id,
        redirect_uri=settings.youtube_oauth_redirect_uri,
        state=state,
    )
    return AuthUrlResponse(auth_url=url)


@router.post("/integrations/youtube/callback")
async def youtube_callback(
    body: CallbackRequest,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    try:
        payload = yt_oauth.verify_state(body.state, settings.jwt_secret)
    except ValueError as e:
        raise HTTPException(400, f"Invalid state: {e}")

    if payload.get("org_id") != user.org_id:
        raise HTTPException(403, "State does not match current org")

    try:
        tokens = await yt_oauth.exchange_code(
            code=body.code,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.youtube_oauth_redirect_uri,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    try:
        channel = await yt_oauth.fetch_channel_info(tokens.access_token)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    saved = yt_client.save_connection(supabase, user.org_id, tokens, channel)
    return {
        "status": "ok",
        "channel": channel,
        "scopes": saved.get("scopes", []),
    }


@router.get("/integrations/youtube/status")
async def youtube_status(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    conn = yt_client.get_connection(supabase, user.org_id)
    if not conn:
        return {"connected": False}
    return {
        "connected": True,
        "status": conn.get("status", "active"),
        "channel": conn.get("metadata") or {},
        "scopes": conn.get("scopes") or [],
        "token_expires_at": conn.get("token_expires_at"),
    }


@router.delete("/integrations/youtube")
async def youtube_disconnect(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    yt_client.delete_connection(supabase, user.org_id)
    return {"status": "disconnected"}


@router.get("/integrations/youtube/uploads")
async def youtube_uploads(
    limit: int = 12,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    conn = yt_client.get_connection(supabase, user.org_id)
    if not conn:
        raise HTTPException(400, "YouTube is not connected")
    uploads_playlist = (conn.get("metadata") or {}).get("uploads_playlist_id")
    if not uploads_playlist:
        raise HTTPException(400, "No uploads playlist on file — reconnect YouTube")

    try:
        token = await yt_client.get_fresh_access_token(
            supabase,
            user.org_id,
            settings.google_client_id,
            settings.google_client_secret,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    limit = min(max(limit, 1), 50)
    async with httpx.AsyncClient(timeout=20) as client:
        pl = await client.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={
                "part": "snippet,contentDetails",
                "playlistId": uploads_playlist,
                "maxResults": limit,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if pl.status_code >= 400:
            raise HTTPException(502, f"YouTube: {pl.status_code} {pl.text[:200]}")

        items = pl.json().get("items", [])
        ids = [i["contentDetails"]["videoId"] for i in items]
        privacy_by_id: dict[str, str] = {}
        duration_by_id: dict[str, str] = {}
        if ids:
            vids = await client.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "status,contentDetails", "id": ",".join(ids)},
                headers={"Authorization": f"Bearer {token}"},
            )
            if vids.status_code < 400:
                for v in vids.json().get("items", []):
                    privacy_by_id[v["id"]] = v.get("status", {}).get("privacyStatus", "unknown")
                    duration_by_id[v["id"]] = v.get("contentDetails", {}).get("duration", "")

    return [
        {
            "video_id": i["contentDetails"]["videoId"],
            "title": i["snippet"]["title"],
            "description_preview": (i["snippet"].get("description") or "")[:200],
            "thumbnail": (i["snippet"].get("thumbnails") or {}).get("medium", {}).get("url"),
            "published_at": i["snippet"]["publishedAt"],
            "privacy_status": privacy_by_id.get(i["contentDetails"]["videoId"]),
            "duration": duration_by_id.get(i["contentDetails"]["videoId"]),
        }
        for i in items
    ]
