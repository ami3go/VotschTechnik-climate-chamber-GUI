"""Strict Host, Origin, peer ACL and browser transport security boundary.

NiceGUI Socket.IO POSTs need Origin + Host restrictions; application callbacks
still MUST revalidate an authenticated session and its CSRF token. No Origin or
host header constitutes authentication.
"""
from __future__ import annotations

from urllib.parse import urlsplit
from .deployment import DeploymentPolicy


def _normalized_origin(value: str) -> str | None:
    if not value or value == "null" or len(value) > 256:
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.path or
                parts.query or parts.fragment):
            return None
        return (f"{parts.scheme}://{parts.hostname}:{parts.port}"
                if parts.port is not None else f"{parts.scheme}://{parts.hostname}")
    except ValueError:
        return None


def valid_origin(origin: str | None, host: str | None,
                 allowed_origins: frozenset[str]) -> bool:
    """Bind browser Origin to exact allowed scheme + Host authority."""
    normalized = _normalized_origin(origin or "")
    if normalized is None or normalized not in allowed_origins or not host:
        return False
    try:
        target = urlsplit(normalized)
        supplied = urlsplit("//" + host)
        return (not supplied.username and not supplied.password and
                not supplied.path and not supplied.query and
                not supplied.fragment and supplied.hostname == target.hostname and
                (supplied.port or (443 if target.scheme == "https" else 80)) ==
                (target.port or (443 if target.scheme == "https" else 80)))
    except ValueError:
        return False


class OriginMiddleware:
    """ASGI gate for all HTTP and WebSocket requests, including safe GETs."""

    def __init__(self, app, *, allowed_origins: frozenset[str],
                 deployment: DeploymentPolicy | None = None):
        if not allowed_origins or any(_normalized_origin(v) != v for v in allowed_origins):
            raise ValueError("Explicit canonical origins required")
        self.app = app
        self.allowed_origins = allowed_origins
        self.deployment = deployment

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        # Reject ambiguous duplicate security headers before a proxy/framework
        # can interpret a different Host, Cookie or Origin than our middleware.
        headers = {}
        for key, value in scope.get("headers", []):
            name = key.decode("latin-1").lower()
            if name in {"host", "origin", "cookie", "sec-fetch-site"} and name in headers:
                await self._deny(kind, send)
                return
            headers[name] = value.decode("latin-1")
        method = scope.get("method", "GET").upper()
        host = headers.get("host")
        origin = headers.get("origin")
        site = headers.get("sec-fetch-site")
        path = scope.get("path", "")
        mutating = method not in {"GET", "HEAD", "OPTIONS"}
        if (not host or not any(valid_origin(o, host, self.allowed_origins)
                                for o in self.allowed_origins)):
            await self._deny(kind, send)
            return
        if self.deployment is not None:
            peer = scope.get("client")
            if not self.deployment.allows_client(peer[0] if peer else None):
                await self._deny(kind, send)
                return
        if site == "cross-site":
            await self._deny(kind, send)
            return
        if (kind == "websocket" or mutating or origin is not None):
            if not valid_origin(origin, host, self.allowed_origins):
                await self._deny(kind, send)
                return
        if kind == "http" and mutating and not (
                path.startswith("/_nicegui/") or path.startswith("/_nicegui_ws/")):
            await self._deny(kind, send)
            return

        async def secure_send(event):
            if event["type"] == "http.response.start":
                event = dict(event)
                existing = {k.lower() for k, _ in event.get("headers", [])}
                safe = (
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"frame-ancestors 'none'"),
                )
                extra = [(key, val) for key, val in safe if key not in existing]
                event["headers"] = list(event.get("headers", [])) + extra
            await send(event)

        await self.app(scope, receive, secure_send)

    @staticmethod
    async def _deny(kind, send):
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"text/plain"),
                                    (b"cache-control", b"no-store"),
                                    (b"x-content-type-options", b"nosniff")]})
            await send({"type": "http.response.body", "body": b"Forbidden"})


def authorize_http_mutation(request, security, session: str | None,
                            permission, chamber_id: str | None = None):
    """For explicit custom endpoints: ASGI transport gate is not sufficient."""
    from .guards import require_permission

    token = request.headers.get("x-csrf-token")
    actor = security.authenticate(session, csrf=token, mutation=True)
    try:
        require_permission(actor, permission)
    except Exception:
        security.audit(actor, str(permission), "DENIED", chamber_id)
        raise
    return actor
