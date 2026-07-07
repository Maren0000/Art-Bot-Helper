"""Mint and verify HMAC-signed bearer tokens for the userscript API.

Token format: "abt1.<b64url(payload)>.<b64url(hmac_sha256(payload))>" where
payload is JSON {"u": user_id, "g": guild_id, "t": type, "exp": unix_ts | null,
"jti": id (setup tokens only)}.

Three token types:
- "setup"   — DM'd by /token, valid for SETUP_TOKEN_TTL seconds and single-use
              (the API tracks spent jti values); only good for the exchange
              endpoint, where it is traded for a refresh + access token pair.
- "refresh" — long-lived (config token_expiry_days; 0 = never expires), stored
              by the userscript, only good for minting fresh access tokens.
- "access"  — short-lived (ACCESS_TOKEN_TTL), the actual Bearer credential on
              API requests.

Revocation happens by removing the poster role (re-checked on every API request
and every refresh) or rotating WEB_SECRET (invalidates every token at once).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

_PREFIX = "abt1"

SETUP_TOKEN_TTL = 300      # 5 minutes to paste the DM'd token into the userscript
ACCESS_TOKEN_TTL = 3600    # access tokens auto-refresh, so keep them short

# Same key-derivation pattern as web/app.py, but with a distinct domain prefix
# so web session cookies and API tokens can never be swapped for each other.
_raw_key = os.getenv("WEB_SECRET") or os.getenv("TOKEN", "fallback-key")
API_SIGNING_KEY: bytes = hashlib.sha256(f"artbot-api:{_raw_key}".encode()).digest()


class InvalidToken(Exception):
    pass


class TokenExpired(InvalidToken):
    pass


@dataclass
class Claims:
    user_id: int
    guild_id: int
    token_type: str
    expires_at: int | None
    jti: str | None = None


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: bytes) -> str:
    return _b64encode(hmac.new(API_SIGNING_KEY, payload, hashlib.sha256).digest())


def _mint(user_id: int, guild_id: int, token_type: str, exp: int | None, jti: str | None = None) -> str:
    claims: dict = {"u": user_id, "g": guild_id, "t": token_type, "exp": exp}
    if jti is not None:
        claims["jti"] = jti
    payload = json.dumps(claims).encode()
    return f"{_PREFIX}.{_b64encode(payload)}.{_sign(payload)}"


def mint_setup_token(user_id: int, guild_id: int) -> str:
    return _mint(user_id, guild_id, "setup", int(time.time()) + SETUP_TOKEN_TTL, jti=secrets.token_urlsafe(9))


def mint_refresh_token(user_id: int, guild_id: int, expiry_days: int | None) -> str:
    exp = int(time.time()) + expiry_days * 86400 if expiry_days else None
    return _mint(user_id, guild_id, "refresh", exp)


def mint_access_token(user_id: int, guild_id: int) -> str:
    return _mint(user_id, guild_id, "access", int(time.time()) + ACCESS_TOKEN_TTL)


def verify_token(token: str, expected_type: str) -> Claims:
    try:
        prefix, payload_b64, sig = token.strip().split(".")
    except ValueError:
        raise InvalidToken("Malformed token")
    if prefix != _PREFIX:
        raise InvalidToken("Unknown token version")

    try:
        payload = _b64decode(payload_b64)
    except (ValueError, TypeError):  # binascii.Error subclasses ValueError
        raise InvalidToken("Malformed token")
    if not hmac.compare_digest(sig, _sign(payload)):
        raise InvalidToken("Bad signature")

    try:
        claims = json.loads(payload)
        user_id, guild_id, exp = int(claims["u"]), int(claims["g"]), claims["exp"]
        token_type = str(claims["t"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise InvalidToken("Malformed payload")

    if token_type != expected_type:
        raise InvalidToken(f"Wrong token type (expected a {expected_type} token)")
    if exp is not None and time.time() > exp:
        raise TokenExpired("Token expired")

    return Claims(
        user_id=user_id,
        guild_id=guild_id,
        token_type=token_type,
        expires_at=exp,
        jti=claims.get("jti"),
    )
