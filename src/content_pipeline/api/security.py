from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import Request
from starlette.responses import JSONResponse, Response

from content_pipeline.api.network import peer_is_allowed
from content_pipeline.settings import Settings

SESSION_COOKIE = "ai_popline_session"
CSRF_COOKIE = "ai_popline_csrf"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_PATHS = {"/health", "/auth/login"}
PUBLIC_ASSET_PATHS = {"/", "/health"}
PUBLIC_PREFIXES = ("/static/",)


@dataclass(frozen=True)
class SessionData:
    issued_at: int
    expires_at: int
    csrf_token: str


class WebSecurity:
    """Enforce the direct-peer, browser, and application-authentication boundary."""

    def __init__(self, settings: Settings):
        self.settings = settings
        admin_token = settings.web_admin_token.get_secret_value()
        api_token = settings.web_api_token.get_secret_value()
        session_secret = settings.web_session_secret.get_secret_value()
        self._auth_configuration_valid = (
            len(admin_token) >= 32
            and len(api_token) >= 32
            and len(session_secret) >= 32
            and not secrets.compare_digest(admin_token, api_token)
        )
        self._login_failures: dict[str, list[float]] = {}
        self._failure_lock = threading.Lock()

    def enforce(self, request: Request) -> Response | None:
        peer = request.client.host if request.client else ""
        if not peer_is_allowed(peer, self.settings.allowed_networks):
            return self._error(403, "peer_not_allowed", "client address is outside the configured access boundary")

        remote = not peer_is_allowed(peer, ())
        if remote and not self.settings.web_auth_required:
            return self._error(503, "remote_access_disabled", "remote access requires application authentication")
        if remote and request.url.scheme != "https" and not self.settings.web_allow_zerotier_http:
            return self._error(426, "https_required", "remote access requires HTTPS")

        host = self._request_hostname(request)
        allowed_hosts = {item.lower().strip("[]") for item in self.settings.allowed_hosts}
        if not host or host.lower().strip("[]") not in allowed_hosts:
            return self._error(400, "host_not_allowed", "request Host is not allowed")

        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in {item.rstrip("/") for item in self.settings.allowed_origins}:
                return self._error(403, "origin_not_allowed", "request Origin is not allowed")

        if not self.settings.web_auth_required:
            request.state.auth_kind = "local"
            request.state.session = None
            return None

        if request.url.path in PUBLIC_ASSET_PATHS or request.url.path.startswith(PUBLIC_PREFIXES):
            return None

        if not self._auth_configuration_valid:
            return self._error(503, "authentication_misconfigured", "application authentication is not configured")

        if request.url.path in PUBLIC_PATHS:
            return None

        auth_kind, session = self.authenticate(request)
        if auth_kind is None:
            return self._error(401, "authentication_required", "valid session or bearer token required")
        request.state.auth_kind = auth_kind
        request.state.session = session

        if request.method in UNSAFE_METHODS and auth_kind == "session":
            csrf_header = request.headers.get("x-csrf-token", "")
            csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
            if not session or not csrf_header or not csrf_cookie:
                return self._error(403, "csrf_failed", "CSRF token required")
            if not secrets.compare_digest(csrf_header, csrf_cookie) or not secrets.compare_digest(
                csrf_header, session.csrf_token
            ):
                return self._error(403, "csrf_failed", "CSRF token mismatch")
        return None

    def authenticate(self, request: Request) -> tuple[str | None, SessionData | None]:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            supplied = authorization[7:].strip()
            expected = self.settings.web_api_token.get_secret_value()
            if expected and secrets.compare_digest(supplied, expected):
                return "bearer", None

        session_cookie = request.cookies.get(SESSION_COOKIE, "")
        session = self.decode_session(session_cookie)
        if session is not None:
            return "session", session
        return None, None

    def verify_login(self, peer: str, supplied_token: str) -> bool:
        now = time.time()
        with self._failure_lock:
            recent = [stamp for stamp in self._login_failures.get(peer, []) if now - stamp < 300]
            self._login_failures[peer] = recent
            if len(recent) >= 5:
                return False

        expected = self.settings.web_admin_token.get_secret_value()
        valid = bool(expected) and secrets.compare_digest(supplied_token, expected)
        with self._failure_lock:
            if valid:
                self._login_failures.pop(peer, None)
            else:
                self._login_failures.setdefault(peer, []).append(now)
        return valid

    def new_session(self) -> tuple[str, SessionData]:
        now = int(time.time())
        session = SessionData(
            issued_at=now,
            expires_at=now + self.settings.web_session_ttl_seconds,
            csrf_token=secrets.token_urlsafe(32),
        )
        payload = json.dumps(
            {"iat": session.issued_at, "exp": session.expires_at, "csrf": session.csrf_token},
            separators=(",", ":"),
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
        signature = self._sign(encoded)
        return f"{encoded}.{signature}", session

    def decode_session(self, value: str) -> SessionData | None:
        if not value or "." not in value:
            return None
        encoded, supplied_signature = value.rsplit(".", 1)
        expected_signature = self._sign(encoded)
        if not expected_signature or not secrets.compare_digest(supplied_signature, expected_signature):
            return None
        try:
            padding = "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
            session = SessionData(
                issued_at=int(payload["iat"]),
                expires_at=int(payload["exp"]),
                csrf_token=str(payload["csrf"]),
            )
        except (binascii.Error, KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None
        if session.expires_at <= int(time.time()) or session.issued_at > int(time.time()) + 60:
            return None
        return session

    def set_session_cookies(self, response: Response, value: str, session: SessionData, *, secure: bool) -> None:
        max_age = max(0, session.expires_at - int(time.time()))
        response.set_cookie(
            SESSION_COOKIE,
            value,
            max_age=max_age,
            httponly=True,
            secure=secure,
            samesite="strict",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            session.csrf_token,
            max_age=max_age,
            httponly=False,
            secure=secure,
            samesite="strict",
            path="/",
        )

    @staticmethod
    def clear_session_cookies(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
        response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")

    def add_security_headers(self, request: Request, response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    def session_is_recent(self, request: Request) -> bool:
        if getattr(request.state, "auth_kind", None) == "bearer":
            return True
        session = getattr(request.state, "session", None)
        if not isinstance(session, SessionData):
            return not self.settings.web_auth_required
        return int(time.time()) - session.issued_at <= self.settings.web_publish_reauth_seconds

    def _sign(self, payload: str) -> str:
        secret = self.settings.web_session_secret.get_secret_value()
        if not secret:
            return ""
        digest = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def _request_hostname(request: Request) -> str:
        host = request.headers.get("host", "")
        try:
            return urlsplit(f"//{host}").hostname or ""
        except ValueError:
            return ""

    @staticmethod
    def _error(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})
