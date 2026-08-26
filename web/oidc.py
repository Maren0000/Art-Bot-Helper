"""OIDC Authorization Code login for the admin UI.

Scope: the admin UI's session cookie only. web/api.py keeps its own bearer-token
auth for the userscript and is deliberately untouched — userscripts cannot do an
interactive browser redirect.

Design notes:

* Authorization Code + PKCE (S256). PKCE is not strictly required for a
  confidential client, but it costs nothing and closes code-interception.
* Claims come from the userinfo endpoint. That means we never have to verify an
  ID token signature, so there is no JWKS fetching, no key rotation handling and
  no new dependency — httpx is already required by services/tagger.py.
* If the provider advertises no userinfo endpoint we fall back to reading the ID
  token's claims WITHOUT signature verification. That is explicitly allowed by
  OIDC Core 3.1.3.7: the token came straight from the token endpoint over a
  TLS-validated channel, so TLS already authenticates the issuer. iss/aud/exp
  are still checked. We never accept an ID token that arrived via the browser.
* All cross-request state (PKCE verifier, CSRF state, nonce, post-login target)
  lives in a short-lived signed cookie. No server-side session store, so this
  survives a restart and works if the container is ever scaled out.

Everything is configured by environment variable; see OIDCSettings.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field

import httpx

LOGGER = logging.getLogger("web.oidc")

TX_COOKIE = "abadmin_oidc_tx"
TX_TTL = 600  # seconds a login attempt may sit at the IdP before it expires
HTTP_TIMEOUT = 10.0


def _env_list(name: str) -> set[str]:
    """Comma-separated allow-list, case-folded. Empty string -> empty set."""
    return {v.strip().casefold() for v in os.getenv(name, "").split(",") if v.strip()}


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class OIDCSettings:
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_url: str = ""
    scopes: str = "openid profile email"
    provider_name: str = "SSO"
    username_claim: str = "preferred_username"
    groups_claim: str = "groups"
    allowed_subs: set[str] = field(default_factory=set)
    allowed_emails: set[str] = field(default_factory=set)
    allowed_groups: set[str] = field(default_factory=set)
    disable_password_login: bool = False

    @classmethod
    def from_env(cls) -> "OIDCSettings":
        return cls(
            issuer=os.getenv("OIDC_ISSUER", "").strip().rstrip("/"),
            client_id=os.getenv("OIDC_CLIENT_ID", "").strip(),
            client_secret=os.getenv("OIDC_CLIENT_SECRET", "").strip(),
            redirect_url=os.getenv("OIDC_REDIRECT_URL", "").strip(),
            scopes=os.getenv("OIDC_SCOPES", "openid profile email").strip(),
            provider_name=os.getenv("OIDC_PROVIDER_NAME", "SSO").strip() or "SSO",
            username_claim=os.getenv("OIDC_USERNAME_CLAIM", "preferred_username").strip(),
            groups_claim=os.getenv("OIDC_GROUPS_CLAIM", "groups").strip(),
            allowed_subs=_env_list("OIDC_ALLOWED_SUBS"),
            allowed_emails=_env_list("OIDC_ALLOWED_EMAILS"),
            allowed_groups=_env_list("OIDC_ALLOWED_GROUPS"),
            disable_password_login=os.getenv("OIDC_DISABLE_PASSWORD_LOGIN", "").strip().lower()
            in ("1", "true", "yes", "on"),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.issuer and self.client_id and self.client_secret)

    @property
    def has_allow_list(self) -> bool:
        return bool(self.allowed_subs or self.allowed_emails or self.allowed_groups)

    def log_startup_state(self) -> None:
        if not self.enabled:
            if any((self.issuer, self.client_id, self.client_secret)):
                LOGGER.warning(
                    "OIDC is partially configured and therefore DISABLED. "
                    "OIDC_ISSUER, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET are all required."
                )
            return
        LOGGER.info("OIDC login enabled (issuer=%s, client_id=%s)", self.issuer, self.client_id)
        if not self.has_allow_list:
            # Loud on purpose. With no allow-list, anyone your IdP will
            # authenticate becomes a full admin of this panel.
            LOGGER.warning(
                "OIDC has NO allow-list configured: ANY user your identity provider "
                "authenticates can administer this panel. Set OIDC_ALLOWED_SUBS, "
                "OIDC_ALLOWED_EMAILS or OIDC_ALLOWED_GROUPS, or restrict who may use "
                "this application at the provider."
            )
        if self.disable_password_login:
            LOGGER.info("Password login is disabled; OIDC is the only way in.")


class OIDCError(Exception):
    """Login could not be completed. The message is shown on the login page."""


class OIDCClient:
    def __init__(self, settings: OIDCSettings, signing_key: bytes) -> None:
        self.s = settings
        self._key = signing_key
        self._meta: dict | None = None

    # -- discovery ---------------------------------------------------------

    async def metadata(self) -> dict:
        """Fetch and cache the discovery document.

        Cached for the process lifetime. Endpoints effectively never move, and a
        restart re-fetches; not worth a TTL.
        """
        if self._meta is None:
            url = f"{self.s.issuer}/.well-known/openid-configuration"
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    r = await client.get(url)
                    r.raise_for_status()
                    self._meta = r.json()
            except Exception as e:
                raise OIDCError(f"Could not reach the identity provider ({e}).") from e
            for required in ("authorization_endpoint", "token_endpoint"):
                if not self._meta.get(required):
                    raise OIDCError(f"Provider discovery document has no {required}.")
        return self._meta

    # -- signed transaction cookie ----------------------------------------

    def _sign(self, payload: str) -> str:
        return hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()

    def seal_tx(self, data: dict) -> str:
        raw = _b64u(json.dumps(data, separators=(",", ":")).encode())
        return f"{raw}.{self._sign(raw)}"

    def open_tx(self, cookie: str | None) -> dict:
        if not cookie or "." not in cookie:
            raise OIDCError("Login session expired. Please try again.")
        raw, _, sig = cookie.rpartition(".")
        if not secrets.compare_digest(sig, self._sign(raw)):
            raise OIDCError("Login session could not be verified. Please try again.")
        try:
            data = json.loads(_b64u_decode(raw))
        except Exception as e:
            raise OIDCError("Login session was malformed. Please try again.") from e
        if time.time() > data.get("exp", 0):
            raise OIDCError("Login attempt timed out. Please try again.")
        return data

    # -- step 1: redirect to the provider ---------------------------------

    async def begin(self, redirect_uri: str, next_url: str) -> tuple[str, str]:
        """Return (authorize_url, tx_cookie_value)."""
        meta = await self.metadata()
        verifier = _b64u(secrets.token_bytes(32))
        challenge = _b64u(hashlib.sha256(verifier.encode()).digest())
        state = _b64u(secrets.token_bytes(16))
        nonce = _b64u(secrets.token_bytes(16))

        params = {
            "response_type": "code",
            "client_id": self.s.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.s.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = f"{meta['authorization_endpoint']}?{urllib.parse.urlencode(params)}"
        tx = self.seal_tx({
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "next": next_url,
            "redirect_uri": redirect_uri,
            "exp": int(time.time()) + TX_TTL,
        })
        return url, tx

    # -- step 2: handle the callback --------------------------------------

    async def complete(self, code: str, state: str, tx_cookie: str | None) -> dict:
        """Validate the callback and return the user's claims."""
        tx = self.open_tx(tx_cookie)
        if not secrets.compare_digest(state, tx.get("state", "")):
            raise OIDCError("Login state did not match. Please try again.")

        meta = await self.metadata()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": tx["redirect_uri"],
            "client_id": self.s.client_id,
            "client_secret": self.s.client_secret,
            "code_verifier": tx["verifier"],
        }
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                r = await client.post(meta["token_endpoint"], data=data)
                if r.status_code >= 400:
                    # Provider error bodies name the actual problem
                    # (redirect_uri_mismatch, invalid_client, ...). Log it;
                    # the browser gets something generic.
                    LOGGER.error("OIDC token exchange failed: %s %s", r.status_code, r.text[:500])
                    raise OIDCError("The identity provider rejected the login.")
                tokens = r.json()
        except OIDCError:
            raise
        except Exception as e:
            raise OIDCError(f"Could not complete login ({e}).") from e

        claims = await self._claims(meta, tokens, tx.get("nonce", ""))
        return {"claims": claims, "next": tx.get("next", "/")}

    async def _claims(self, meta: dict, tokens: dict, nonce: str) -> dict:
        userinfo_endpoint = meta.get("userinfo_endpoint")
        if userinfo_endpoint and tokens.get("access_token"):
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    r = await client.get(
                        userinfo_endpoint,
                        headers={"Authorization": f"Bearer {tokens['access_token']}"},
                    )
                    r.raise_for_status()
                    return r.json()
            except Exception as e:
                LOGGER.warning("userinfo request failed, falling back to id_token: %s", e)

        id_token = tokens.get("id_token")
        if not id_token:
            raise OIDCError("Provider returned neither userinfo nor an ID token.")
        return self._read_id_token(id_token, nonce)

    def _read_id_token(self, id_token: str, nonce: str) -> dict:
        """Read ID token claims without verifying the signature.

        Safe only because this token came directly from the token endpoint over
        TLS (OIDC Core 3.1.3.7). Never call this on a token that arrived through
        the browser.
        """
        try:
            payload = json.loads(_b64u_decode(id_token.split(".")[1]))
        except Exception as e:
            raise OIDCError("ID token could not be decoded.") from e

        iss = str(payload.get("iss", "")).rstrip("/")
        if iss != self.s.issuer:
            raise OIDCError("ID token issuer did not match the configured issuer.")

        aud = payload.get("aud")
        aud_ok = self.s.client_id == aud or (isinstance(aud, list) and self.s.client_id in aud)
        if not aud_ok:
            raise OIDCError("ID token was not issued for this client.")

        if payload.get("exp", 0) < time.time():
            raise OIDCError("ID token has expired.")

        if nonce and payload.get("nonce") and payload["nonce"] != nonce:
            raise OIDCError("ID token nonce did not match.")

        return payload

    # -- authorization -----------------------------------------------------

    def authorize(self, claims: dict) -> str:
        """Apply the allow-lists. Returns the display username, or raises."""
        sub = str(claims.get("sub", ""))
        email = str(claims.get("email", ""))
        groups_raw = claims.get(self.s.groups_claim) or []
        if isinstance(groups_raw, str):
            groups_raw = [groups_raw]
        groups = {str(g).casefold() for g in groups_raw}

        if self.s.has_allow_list:
            allowed = (
                sub.casefold() in self.s.allowed_subs
                or (email and email.casefold() in self.s.allowed_emails)
                or bool(groups & self.s.allowed_groups)
            )
            if not allowed:
                LOGGER.warning(
                    "Denied OIDC login for sub=%s email=%s groups=%s (not in any allow-list)",
                    sub or "?", email or "?", sorted(groups) or "[]",
                )
                raise OIDCError("Your account is not permitted to access this panel.")

        name = claims.get(self.s.username_claim) or claims.get("email") or sub
        if not name:
            raise OIDCError("Provider returned no usable identity claim.")
        return str(name)
