"""Mint and verify HMAC-signed bearer tokens for the userscript API.

Token format: "abt1.<b64url(payload)>.<b64url(hmac_sha256(payload))>" where
payload is JSON {"u": user_id, "g": guild_id, "exp": unix_ts | null}.
exp == null means the token never expires; revocation happens by removing the
poster role (re-checked on every API request) or rotating WEB_SECRET.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

_PREFIX = "abt1"

# Same key-derivation pattern as web/app.py, but with a distinct domain prefix
# so web session cookies and API tokens can never be swapped for each other.
_raw_key = os.getenv("WEB_SECRET") or os.getenv("TOKEN", "fallback-key")
API_SIGNING_KEY: bytes = hashlib.sha256(f"artbot-api:{_raw_key}".encode()).digest()


class InvalidToken(Exception):
    pass


@dataclass
class Claims:
    user_id: int
    guild_id: int
    expires_at: int | None


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: bytes) -> str:
    return _b64encode(hmac.new(API_SIGNING_KEY, payload, hashlib.sha256).digest())


def mint_token(user_id: int, guild_id: int, expiry_days: int | None) -> str:
    exp = int(time.time()) + expiry_days * 86400 if expiry_days else None
    payload = json.dumps({"u": user_id, "g": guild_id, "exp": exp}).encode()
    return f"{_PREFIX}.{_b64encode(payload)}.{_sign(payload)}"


def verify_token(token: str) -> Claims:
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
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise InvalidToken("Malformed payload")

    if exp is not None and time.time() > exp:
        raise InvalidToken("Token expired")

    return Claims(user_id=user_id, guild_id=guild_id, expires_at=exp)
