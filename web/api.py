"""Userscript-facing HTTP API.

Mounted into the admin web app (web/app.py) but with its own bearer-token auth
— it is never behind the admin session cookie. Requires the Discord bot to be
running in the same process (main.py run_combined calls set_bot); when the web
app runs standalone every route answers 503.

No CORS middleware on purpose: the userscript talks to us via GM_xmlhttpRequest,
which is exempt from CORS.
"""
from __future__ import annotations

import asyncio
import io
import json
import secrets
import time
from dataclasses import dataclass, field

import discord
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

import exception
from services import posting
from utils.api_token import (
    ACCESS_TOKEN_TTL,
    SETUP_TOKEN_TTL,
    InvalidToken,
    TokenExpired,
    mint_access_token,
    mint_refresh_token,
    verify_token,
)

router = APIRouter(prefix="/api")

DETECTION_TIMEOUT = 90          # seconds the ML long-poll may take
SUBMISSION_TTL = 1800           # seconds an unconfirmed submission is kept
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_bot = None


def set_bot(bot) -> None:
    global _bot
    _bot = bot


def get_bot():
    return _bot


# ---------------------------------------------------------------------------
# Errors — every error body is flat JSON: {"code": ..., "message": ...}
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


async def api_error_handler(_: Request, err: ApiError) -> JSONResponse:
    return JSONResponse({"code": err.code, "message": err.message, **err.extra}, status_code=err.status)


def _raise_from_pipeline(err: Exception):
    """Translate a posting-pipeline exception into an ApiError."""
    status, code, message = posting.error_payload(err)
    extra = {}
    if isinstance(err, exception.ThreadsNotFound):
        original = str(getattr(err, "original", ""))
        extra["missing"] = [line[2:] for line in original.split("\n") if line.startswith("- ")]
    if isinstance(err, exception.DuplicateImageFound):
        original = str(getattr(err, "original", ""))
        if original.startswith("Post: "):
            extra["existing_post"] = original.removeprefix("Post: ")
    raise ApiError(status, code, message, **extra) from err


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@dataclass
class Poster:
    user_id: int
    guild: discord.Guild
    name: str
    member: discord.Member


def _require_bot() -> None:
    if _bot is None or not _bot.is_ready():
        raise ApiError(503, "api_unavailable", "The bot is not running.")


async def _resolve_poster(claims) -> Poster:
    """Live guild-membership + poster-role check shared by every auth path."""
    guild = _bot.get_guild(claims.guild_id)
    if guild is None:
        raise ApiError(403, "unknown_guild", "The bot is no longer in that server.")

    member = guild.get_member(claims.user_id)
    if member is None:
        try:
            member = await guild.fetch_member(claims.user_id)
        except discord.HTTPException:
            raise ApiError(403, "not_member", "You are no longer a member of that server.")

    role_id = _bot.config.poster_role_id
    if role_id is None:
        raise ApiError(403, "not_configured", "No poster role is configured; ask an admin.")
    if role_id not in [role.id for role in member.roles]:
        raise ApiError(403, "not_poster", "You aren't allowed to post art! (Missing the poster role.)")

    return Poster(user_id=claims.user_id, guild=guild, name=member.display_name, member=member)


async def require_poster(authorization: str = Header(default="")) -> Poster:
    _require_bot()

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ApiError(401, "invalid_token", "Missing bearer token.")
    try:
        claims = verify_token(token, expected_type="access")
    except TokenExpired:
        # Distinct code so the userscript knows to refresh + retry, not re-link.
        raise ApiError(401, "token_expired", "Access token expired — refresh it.")
    except InvalidToken as err:
        raise ApiError(401, "invalid_token", str(err))

    return await _resolve_poster(claims)


async def _poster(request: Request) -> Poster:
    return await require_poster(request.headers.get("authorization", ""))


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise ApiError(400, "bad_request", "Body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "Body must be a JSON object.")
    return body


# Spent setup-token ids (jti -> token expiry). Setup tokens live 5 minutes, so
# this stays tiny; in-memory is fine — after a restart old setup tokens can be
# replayed only within their remaining TTL.
USED_SETUP_JTIS: dict[str, float] = {}


def _verify_auth_token(token: str, expected_type: str, expired_code: str, expired_message: str):
    try:
        return verify_token(token, expected_type=expected_type)
    except TokenExpired:
        raise ApiError(401, expired_code, expired_message)
    except InvalidToken as err:
        raise ApiError(401, "invalid_token", str(err))


@router.post("/auth/exchange")
async def api_auth_exchange(request: Request):
    """Trade a single-use /token setup token for a refresh + access token pair."""
    _require_bot()
    body = await _json_body(request)
    claims = _verify_auth_token(
        str(body.get("setup_token") or ""), "setup",
        "setup_expired", "Setup token expired — run /token in Discord for a fresh one.",
    )

    now = time.time()
    for jti in [j for j, exp in USED_SETUP_JTIS.items() if exp < now]:
        del USED_SETUP_JTIS[jti]
    if claims.jti is None or claims.jti in USED_SETUP_JTIS:
        raise ApiError(401, "setup_used", "That setup token was already used — run /token again.")

    poster = await _resolve_poster(claims)
    # Only burn the jti once the role check passed, so a user who gets the
    # poster role seconds later can retry with the same DM'd token.
    USED_SETUP_JTIS[claims.jti] = claims.expires_at or now + SETUP_TOKEN_TTL

    return {
        "refresh_token": mint_refresh_token(claims.user_id, claims.guild_id, _bot.config.token_expiry_days),
        "access_token": mint_access_token(claims.user_id, claims.guild_id),
        "access_expires_in": ACCESS_TOKEN_TTL,
        "guild_name": poster.guild.name,
        "user_name": poster.name,
    }


@router.post("/auth/refresh")
async def api_auth_refresh(request: Request):
    """Mint a fresh access token from a stored refresh token."""
    _require_bot()
    body = await _json_body(request)
    claims = _verify_auth_token(
        str(body.get("refresh_token") or ""), "refresh",
        "refresh_expired", "Your link expired — run /token in Discord and re-link.",
    )

    poster = await _resolve_poster(claims)
    return {
        "access_token": mint_access_token(claims.user_id, claims.guild_id),
        "access_expires_in": ACCESS_TOKEN_TTL,
        "guild_name": poster.guild.name,
        "user_name": poster.name,
    }


# ---------------------------------------------------------------------------
# Submission store (in-memory; lost on restart — the userscript re-submits and
# the phash duplicate check is the backstop against double posts)
# ---------------------------------------------------------------------------


@dataclass
class Submission:
    id: str
    user_id: int
    guild_id: int
    platform: str
    link: str
    image_num: int | None
    post_data: dict
    hq_image: io.BytesIO
    image_name: str
    hashes: dict
    embed_fallback: bool
    detected: dict
    created_at: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    result: dict | None = None


SUBMISSIONS: dict[str, Submission] = {}
# (user_id, idempotency_key) -> {"sid": ..., "response": ..., "result": ..., "ts": ...}
IDEMPOTENCY: dict[tuple[int, str], dict] = {}


def _sweep() -> None:
    now = time.time()
    for sid in [s.id for s in SUBMISSIONS.values() if now - s.created_at > SUBMISSION_TTL]:
        del SUBMISSIONS[sid]
    for key in [k for k, v in IDEMPOTENCY.items() if now - v["ts"] > SUBMISSION_TTL]:
        del IDEMPOTENCY[key]


def _get_submission(sid: str, poster: Poster) -> Submission:
    sub = SUBMISSIONS.get(sid)
    if sub is None or sub.user_id != poster.user_id:
        raise ApiError(404, "submission_not_found", "Unknown or expired submission — submit again.")
    return sub


def _submission_response(sub: Submission) -> dict:
    return {
        "submission_id": sub.id,
        "expires_at": int(sub.created_at + SUBMISSION_TTL),
        "detected": sub.detected,
        "result": sub.result,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/meta")
async def api_meta(request: Request):
    poster = await _poster(request)
    safety_levels = sorted(set(_bot.config.safety_map.values()))
    # Only list forums the member can actually see — the userscript dropdown
    # must not leak channels hidden from them.
    forums = [
        {"id": str(channel.id), "name": channel.name}
        for channel in poster.guild.channels
        if isinstance(channel, discord.ForumChannel)
        and any(channel.name.endswith(f"-{safety}") for safety in safety_levels)
        and channel.permissions_for(poster.member).view_channel
    ]
    forums.sort(key=lambda f: f["name"])
    return {
        "guild_id": str(poster.guild.id),
        "guild_name": poster.guild.name,
        "forums": forums,
        "safety_levels": safety_levels,
    }


async def _parse_submission_request(request: Request) -> tuple[dict, bytes | None, str | None]:
    """Returns (payload_dict, image_bytes | None, image_filename | None)."""
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("image")
        raw_payload = form.get("payload")
        if upload is None or raw_payload is None:
            raise ApiError(400, "bad_request", "Multipart submissions need 'image' and 'payload' fields.")
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            raise ApiError(400, "bad_request", "'payload' field is not valid JSON.")
        image_bytes = await upload.read()
        if len(image_bytes) > MAX_UPLOAD_BYTES:
            raise ApiError(413, "too_large", "Image exceeds the 50MB upload limit.")
        if not image_bytes:
            raise ApiError(400, "bad_request", "Uploaded image is empty.")
        return payload, image_bytes, upload.filename or "upload.jpg"

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise ApiError(400, "bad_request", "Body is not valid JSON.")
    return payload, None, None


@router.post("/submissions")
async def api_submit(request: Request):
    poster = await _poster(request)
    _sweep()

    payload, image_bytes, image_filename = await _parse_submission_request(request)
    platform = payload.get("platform", "")
    link = (payload.get("url") or "").strip()
    idem_key = payload.get("idempotency_key")
    if not link:
        raise ApiError(400, "bad_request", "Missing 'url'.")

    # Idempotent replay: a retry of an already-processed submit returns the
    # original outcome instead of re-running detection (or worse, re-posting).
    if idem_key:
        entry = IDEMPOTENCY.get((poster.user_id, idem_key))
        if entry is not None:
            if entry.get("result") is not None:
                return entry["result"]
            if entry.get("sid") in SUBMISSIONS:
                return _submission_response(SUBMISSIONS[entry["sid"]])

    try:
        if platform == "pixiv":
            image_num = payload.get("image_num")
            image_num = int(image_num) if image_num else None
            post_data, hq_image, image_name, hashes, embed_fallback, _ = await posting.fetch_and_validate_image(
                _bot, link, poster.guild, image_num,
            )
        elif platform == "twitter":
            if image_bytes is None:
                raise ApiError(400, "bad_request", "Twitter submissions must be multipart with an 'image' file.")
            image_num = None
            post_data = {
                "url": link,
                "author_handle": payload.get("author_handle", "unknown"),
                "author_name": payload.get("author_name", ""),
                "text": payload.get("text", ""),
            }
            image_name = image_filename
            hq_image, hashes, embed_fallback = await posting.validate_uploaded_image(
                _bot, image_bytes, image_name, poster.guild,
            )
        else:
            raise ApiError(400, "bad_request", f"Unsupported platform: {platform!r}")

        try:
            charas_model, series, safety = await asyncio.wait_for(
                posting.tags_model_pass(_bot, hq_image, image_name),
                timeout=DETECTION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise ApiError(504, "detection_timeout", "Character detection took too long — try again.")

        if platform == "pixiv":
            charas_extra, series_extra = posting.tags_pixiv_pass(_bot.config, post_data)
        else:
            charas_extra, series_extra = posting.tags_text_pass(_bot.config, post_data.get("text", ""))
        characters = sorted(charas_model | charas_extra)
        if series_extra:
            series = series_extra
    except ApiError:
        raise
    except Exception as err:
        _raise_from_pipeline(err)

    forum = posting.find_forum_by_name(poster.guild, series, safety)
    if forum is not None and not forum.permissions_for(poster.member).view_channel:
        forum = None  # never suggest a forum the member can't see

    sub = Submission(
        id=secrets.token_urlsafe(16),
        user_id=poster.user_id,
        guild_id=poster.guild.id,
        platform=platform,
        link=link,
        image_num=image_num,
        post_data=post_data,
        hq_image=hq_image,
        image_name=image_name,
        hashes=hashes,
        embed_fallback=embed_fallback,
        detected={
            "characters": characters,
            "series": series,
            "safety": safety,
            "forum": {"id": str(forum.id), "name": forum.name} if forum else None,
        },
        created_at=time.time(),
    )
    SUBMISSIONS[sub.id] = sub
    if idem_key:
        IDEMPOTENCY[(poster.user_id, idem_key)] = {"sid": sub.id, "result": None, "ts": time.time()}
    return _submission_response(sub)


@router.post("/submissions/{sid}/confirm")
async def api_confirm(sid: str, request: Request):
    poster = await _poster(request)
    _sweep()
    sub = _get_submission(sid, poster)

    body = await _json_body(request)

    characters = (body.get("characters") or "").strip()
    if not characters:
        raise ApiError(400, "bad_request", "Missing 'characters'.")
    try:
        forum_id = int(body.get("forum_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "forum_not_found", "Missing or invalid 'forum_id'.")
    forum = poster.guild.get_channel(forum_id)
    # Same error for "doesn't exist" and "hidden from you" so hidden channel
    # ids can't be probed.
    if not isinstance(forum, discord.ForumChannel) or not forum.permissions_for(poster.member).view_channel:
        raise ApiError(400, "forum_not_found", "That forum channel does not exist.")

    async with sub.lock:
        if sub.result is not None:
            # Double click / retried confirm after success — never post twice.
            return sub.result

        try:
            threads, _, _ = await posting.find_character_threads(forum, characters)
            sub.hq_image.seek(0)
            img = sub.hq_image.read()
            links_text, post_id = await posting.create_embed_and_send(
                _bot, sub.link, sub.post_data, threads, poster.name, poster.guild.id, forum.name,
                sub.embed_fallback, img, sub.image_name, sub.hashes, sub.image_num, sub.platform,
            )
        except Exception as err:
            # Submission is kept so the userscript can adjust fields and retry.
            _raise_from_pipeline(err)

        sub.result = {
            "thread_links": [line[2:] for line in links_text.split("\n") if line.startswith("- ")],
            "note": next((line for line in links_text.split("\n") if line.startswith("**NOTE:")), None),
            "post_id": post_id,
            "forum_url": forum.jump_url,
        }

    # Keep the outcome under the idempotency key, then drop the (large) submission.
    for entry in IDEMPOTENCY.values():
        if entry.get("sid") == sid:
            entry["result"] = sub.result
    result = sub.result
    SUBMISSIONS.pop(sid, None)
    return result


@router.get("/submissions/{sid}")
async def api_submission_status(sid: str, request: Request):
    poster = await _poster(request)
    return _submission_response(_get_submission(sid, poster))


@router.delete("/submissions/{sid}")
async def api_submission_discard(sid: str, request: Request):
    poster = await _poster(request)
    sub = _get_submission(sid, poster)
    SUBMISSIONS.pop(sub.id, None)
    return {"discarded": True}
