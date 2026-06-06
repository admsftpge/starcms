"""Single-admin authentication for the admin app.

v0.1 scope: one admin identity from environment variables, a signed session
cookie, and CSRF protection on every POST. Multi-user auth, roles, and
password hashing are deliberately deferred.

Configuration (environment):
    STARCMS_ADMIN_USER / STARCMS_ADMIN_PASSWORD — the one admin login.
        With either unset, every login attempt fails (locked, not open).
        Read per request, so they can be set or changed at any time.
    STARCMS_SECRET — key signing the session cookie. Generated per process
        when unset, which logs everyone out on restart — fine for dev,
        set it in production. Read when the admin app is BUILT: set it
        before cms.mount(), not after.
"""

import os
import secrets

from starlette import exceptions, requests, responses
from starlette.middleware import base

from starcms import forms

_FALLBACK_SECRET = secrets.token_hex(32)


def session_secret() -> str:
    return os.environ.get("STARCMS_SECRET", _FALLBACK_SECRET)


def verify(username: str, password: str) -> bool:
    """Timing-safe credential check; always False when env vars are unset."""
    expected_user = os.environ.get("STARCMS_ADMIN_USER")
    expected_password = os.environ.get("STARCMS_ADMIN_PASSWORD")
    if not expected_user or not expected_password:
        return False
    # Bitwise & so both comparisons always run: short-circuiting would let
    # response timing reveal whether the username alone was correct.
    return secrets.compare_digest(username, expected_user) & secrets.compare_digest(
        password, expected_password
    )


async def require_csrf(request: requests.Request) -> None:
    """Reject a POST whose csrf_token doesn't match the session's.

    Cookie-session auth only: CSRF exists because browsers attach cookies
    automatically — token-authed API endpoints have no cookie to forge
    and must not use this.

    Called at the top of every POST view, NOT in middleware: a middleware
    body read starves the downstream view's request.form() (verified
    empirically — BaseHTTPMiddleware does not replay the body here).
    """
    form = await request.form()
    expected = request.session.get("csrf", "")
    given = str(form.get("csrf_token", ""))
    if not expected or not secrets.compare_digest(given, expected):
        raise exceptions.HTTPException(status_code=403, detail="CSRF token mismatch")


class AuthGate(base.BaseHTTPMiddleware):
    """Redirects anonymous requests to the login page, and supplies the
    session's CSRF token to form rendering via the forms.csrf_token
    contextvar (the ambient transport decided in forms.post_form)."""

    async def dispatch(self, request, call_next):  # type: ignore[override]
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(32)
        # The path within the mounted app: scope["path"] stays the full
        # external path under mounting, with the prefix in root_path.
        path = request.scope["path"].removeprefix(
            request.scope.get("root_path", "")
        )
        if path != "/login" and "user" not in request.session:
            return responses.RedirectResponse(
                request.url_for("login"), status_code=303
            )
        # No reset needed: each request runs in its own context copy.
        forms.csrf_token.set(request.session["csrf"])
        return await call_next(request)
