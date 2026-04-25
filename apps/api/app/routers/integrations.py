import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client

from app.config import Settings, get_settings
from app.dependencies import CurrentUser, get_current_user, get_supabase
from packages.integrations.dropbox import client as dropbox_client
from packages.integrations.dropbox import oauth as dropbox_oauth
from packages.integrations.monday import client as monday_client
from packages.integrations.monday import oauth as monday_oauth
from packages.integrations.slack import client as slack_client
from packages.integrations.slack import oauth as slack_oauth
from packages.integrations.x import client as x_client
from packages.integrations.x import oauth as x_oauth
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


# ── X (Twitter) ──────────────────────────────────────────────────────────────

@router.post("/integrations/twitter/auth-url", response_model=AuthUrlResponse)
async def twitter_auth_url(
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if not settings.twitter_client_id:
        raise HTTPException(500, "X (Twitter) OAuth is not configured")
    if not settings.jwt_secret:
        raise HTTPException(500, "JWT secret is not configured")

    verifier, challenge = x_oauth.generate_pkce_pair()
    state = x_oauth.sign_state(
        {"org_id": user.org_id, "user_id": user.id, "code_verifier": verifier},
        settings.jwt_secret,
    )
    url = x_oauth.build_auth_url(
        client_id=settings.twitter_client_id,
        redirect_uri=settings.twitter_oauth_redirect_uri,
        state=state,
        code_challenge=challenge,
    )
    return AuthUrlResponse(auth_url=url)


@router.post("/integrations/twitter/callback")
async def twitter_callback(
    body: CallbackRequest,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    try:
        payload = x_oauth.verify_state(body.state, settings.jwt_secret)
    except ValueError as e:
        raise HTTPException(400, f"Invalid state: {e}")

    if payload.get("org_id") != user.org_id:
        raise HTTPException(403, "State does not match current org")

    code_verifier = payload.get("code_verifier")
    if not code_verifier:
        raise HTTPException(400, "State is missing PKCE verifier")

    try:
        tokens = await x_oauth.exchange_code(
            code=body.code,
            client_id=settings.twitter_client_id,
            redirect_uri=settings.twitter_oauth_redirect_uri,
            code_verifier=code_verifier,
            client_secret=settings.twitter_client_secret or None,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    try:
        user_info = await x_oauth.fetch_user_info(tokens.access_token)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    saved = x_client.save_connection(supabase, user.org_id, tokens, user_info)
    return {
        "status": "ok",
        "user": user_info,
        "scopes": saved.get("scopes", []),
    }


@router.get("/integrations/twitter/status")
async def twitter_status(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    conn = x_client.get_connection(supabase, user.org_id)
    if not conn:
        return {"connected": False}
    return {
        "connected": True,
        "status": conn.get("status", "active"),
        "user": conn.get("metadata") or {},
        "scopes": conn.get("scopes") or [],
        "token_expires_at": conn.get("token_expires_at"),
    }


@router.delete("/integrations/twitter")
async def twitter_disconnect(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    x_client.delete_connection(supabase, user.org_id)
    return {"status": "disconnected"}


# ── Slack ────────────────────────────────────────────────────────────────────

@router.post("/integrations/slack/auth-url", response_model=AuthUrlResponse)
async def slack_auth_url(
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if not settings.slack_client_id or not settings.slack_client_secret:
        raise HTTPException(500, "Slack OAuth is not configured")
    if not settings.jwt_secret:
        raise HTTPException(500, "JWT secret is not configured")

    state = slack_oauth.sign_state(
        {"org_id": user.org_id, "user_id": user.id},
        settings.jwt_secret,
    )
    url = slack_oauth.build_auth_url(
        client_id=settings.slack_client_id,
        redirect_uri=settings.slack_oauth_redirect_uri,
        state=state,
    )
    return AuthUrlResponse(auth_url=url)


@router.post("/integrations/slack/callback")
async def slack_callback(
    body: CallbackRequest,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    try:
        payload = slack_oauth.verify_state(body.state, settings.jwt_secret)
    except ValueError as e:
        raise HTTPException(400, f"Invalid state: {e}")

    if payload.get("org_id") != user.org_id:
        raise HTTPException(403, "State does not match current org")

    try:
        install = await slack_oauth.exchange_code(
            code=body.code,
            client_id=settings.slack_client_id,
            client_secret=settings.slack_client_secret,
            redirect_uri=settings.slack_oauth_redirect_uri,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    # auth.test gives us a verified team url for the UI to deep-link to.
    extra: dict = {}
    try:
        info = await slack_oauth.auth_test(install.access_token)
        extra["team_url"] = info.get("url")
    except RuntimeError:
        # Token works for installs but auth.test failed — non-fatal; metadata
        # can be re-fetched later.
        pass

    saved = slack_client.save_connection(supabase, user.org_id, install, extra)
    return {
        "status": "ok",
        "team": {
            "id": install.team_id,
            "name": install.team_name,
            "url": extra.get("team_url"),
        },
        "scopes": saved.get("scopes", []),
    }


@router.get("/integrations/slack/status")
async def slack_status(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    conn = slack_client.get_connection(supabase, user.org_id)
    if not conn:
        return {"connected": False}
    metadata = conn.get("metadata") or {}
    return {
        "connected": True,
        "status": conn.get("status", "active"),
        "team": {
            "id": metadata.get("team_id"),
            "name": metadata.get("team_name"),
            "url": metadata.get("team_url"),
        },
        "scopes": conn.get("scopes") or [],
    }


@router.delete("/integrations/slack")
async def slack_disconnect(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    slack_client.delete_connection(supabase, user.org_id)
    return {"status": "disconnected"}


# ── Dropbox ──────────────────────────────────────────────────────────────────

@router.post("/integrations/dropbox/auth-url", response_model=AuthUrlResponse)
async def dropbox_auth_url(
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if not settings.dropbox_client_id or not settings.dropbox_client_secret:
        raise HTTPException(500, "Dropbox OAuth is not configured")
    if not settings.jwt_secret:
        raise HTTPException(500, "JWT secret is not configured")

    state = dropbox_oauth.sign_state(
        {"org_id": user.org_id, "user_id": user.id},
        settings.jwt_secret,
    )
    url = dropbox_oauth.build_auth_url(
        client_id=settings.dropbox_client_id,
        redirect_uri=settings.dropbox_oauth_redirect_uri,
        state=state,
    )
    return AuthUrlResponse(auth_url=url)


@router.post("/integrations/dropbox/callback")
async def dropbox_callback(
    body: CallbackRequest,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    try:
        payload = dropbox_oauth.verify_state(body.state, settings.jwt_secret)
    except ValueError as e:
        raise HTTPException(400, f"Invalid state: {e}")

    if payload.get("org_id") != user.org_id:
        raise HTTPException(403, "State does not match current org")

    try:
        tokens = await dropbox_oauth.exchange_code(
            code=body.code,
            client_id=settings.dropbox_client_id,
            client_secret=settings.dropbox_client_secret,
            redirect_uri=settings.dropbox_oauth_redirect_uri,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    try:
        account = await dropbox_oauth.fetch_account_info(tokens.access_token)
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    saved = dropbox_client.save_connection(supabase, user.org_id, tokens, account)
    return {"status": "ok", "account": account, "scopes": saved.get("scopes", [])}


@router.get("/integrations/dropbox/status")
async def dropbox_status(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    conn = dropbox_client.get_connection(supabase, user.org_id)
    if not conn:
        return {"connected": False}
    return {
        "connected": True,
        "status": conn.get("status", "active"),
        "account": conn.get("metadata") or {},
        "scopes": conn.get("scopes") or [],
        "token_expires_at": conn.get("token_expires_at"),
    }


@router.delete("/integrations/dropbox")
async def dropbox_disconnect(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    dropbox_client.delete_connection(supabase, user.org_id)
    return {"status": "disconnected"}


# ── monday.com ───────────────────────────────────────────────────────────────

@router.post("/integrations/monday/auth-url", response_model=AuthUrlResponse)
async def monday_auth_url(
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    if not settings.monday_client_id or not settings.monday_client_secret:
        raise HTTPException(500, "monday.com OAuth is not configured")
    if not settings.jwt_secret:
        raise HTTPException(500, "JWT secret is not configured")

    state = monday_oauth.sign_state(
        {"org_id": user.org_id, "user_id": user.id},
        settings.jwt_secret,
    )
    url = monday_oauth.build_auth_url(
        client_id=settings.monday_client_id,
        redirect_uri=settings.monday_oauth_redirect_uri,
        state=state,
    )
    return AuthUrlResponse(auth_url=url)


@router.post("/integrations/monday/callback")
async def monday_callback(
    body: CallbackRequest,
    user: CurrentUser = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    supabase: Client = Depends(get_supabase),
):
    try:
        payload = monday_oauth.verify_state(body.state, settings.jwt_secret)
    except ValueError as e:
        raise HTTPException(400, f"Invalid state: {e}")

    if payload.get("org_id") != user.org_id:
        raise HTTPException(403, "State does not match current org")

    try:
        tokens = await monday_oauth.exchange_code(
            code=body.code,
            client_id=settings.monday_client_id,
            client_secret=settings.monday_client_secret,
            redirect_uri=settings.monday_oauth_redirect_uri,
        )
    except RuntimeError as e:
        raise HTTPException(400, str(e))

    try:
        account = await monday_oauth.fetch_account_info(tokens.access_token)
    except RuntimeError as e:
        # Auth succeeded but the me-query failed — still save the token; the
        # UI can re-fetch metadata later.
        account = {"warning": f"me-query failed: {e}"}

    saved = monday_client.save_connection(supabase, user.org_id, tokens, account)
    return {"status": "ok", "account": account, "scopes": saved.get("scopes", [])}


@router.get("/integrations/monday/status")
async def monday_status(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    conn = monday_client.get_connection(supabase, user.org_id)
    if not conn:
        return {"connected": False}
    return {
        "connected": True,
        "status": conn.get("status", "active"),
        "account": conn.get("metadata") or {},
        "scopes": conn.get("scopes") or [],
    }


@router.delete("/integrations/monday")
async def monday_disconnect(
    user: CurrentUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    monday_client.delete_connection(supabase, user.org_id)
    return {"status": "disconnected"}
