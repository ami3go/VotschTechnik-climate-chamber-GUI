"""ASGI Origin + CSRF boundary for NiceGUI browser transports.

NiceGUI's Socket.IO event POSTs are framework-owned; they do not support a
custom per-request CSRF header. For those paths require an exact trusted Origin
and disallow cross-site Fetch Metadata. Any OTHER HTTP mutation must use the
explicit server-side CSRF guard (no custom mutation routes exist in G08-min).
WebSocket Origin is checked during upgrade, not just when creating the page.
"""
from __future__ import annotations

from urllib.parse import urlsplit


def _normalized_origin(value: str) -> str | None:
    if not value or value == "null" or len(value) > 256:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or (
                parts.username or parts.password or parts.path or
                parts.query or parts.fragment):
            return None
        if parts.port is None:
            return f"{parts.scheme}://{parts.hostname}"
        return f"{parts.scheme}://{parts.hostname}:{parts.port}"
    except ValueError:
        return None


def valid_origin(origin: str | None, host: str | None,
                 allowed_origins: frozenset[str]) -> bool:
    """Bind Origin AND Host; do not trust arbitrary DNS-rebound Host headers."""
    normalized = _normalized_origin(origin or "")
    if normalized is None or normalized not in allowed_origins or not host:
        return False
    try:
        target = urlsplit(normalized)
        supplied = urlsplit("//" + host)
        return (supplied.hostname == target.hostname and
                (supplied.port or (443 if target.scheme == "https" else 80)) ==
                (target.port or (443 if target.scheme == "https" else 80)))
    except ValueError:
        return False


class OriginMiddleware:
    """ASGI transport gate; no browser can supply server-side role authority."""

    def __init__(self, app, *, allowed_origins: frozenset[str]):
        if not allowed_origins or any(_normalized_origin(v) != v for v in allowed_origins):
            raise ValueError("Explicit well-formed allowed origins required")
        self.app = app
        self.allowed_origins = allowed_origins

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        method = scope.get("method", "GET").upper()
        origin = headers.get("origin")
        host = headers.get("host")
        site = headers.get("sec-fetch-site")
        path = scope.get("path", "")
        mutating = method not in {"GET", "HEAD", "OPTIONS"}
        # Block cross-origin transports, even when browser credentials exist.
        if (kind == "websocket" or mutating or (
                origin is not None and path.startswith("/_nicegui_ws"))):
            if site == "cross-site" or not valid_origin(origin, host, self.allowed_origins):
                await self._deny(kind, send)
                return
            # Unknown HTTP write endpoints are always denied. NiceGUI emits
            # Socket.IO transport POSTs below these built-in prefixes only.
            if kind == "http" and mutating and not (
                path.startswith("/_nicegui/") or path.startswith("/_nicegui_ws/")
            ):
                await self._deny(kind, send)
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(kind, send):
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"text/plain"),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": b"Forbidden"})


def authorize_http_mutation(request, security, session: str | None,
                            permission, chamber_id: str | None = None):
    """For future explicitly reviewed HTTP endpoints; nothing uses this yet.

    The endpoint must first verify Origin/Host via the ASGI gate, then the
    per-session anti-CSRF header before calling a sensitive service.
    """
    from .guards import require_permission

    token = request.headers.get("x-csrf-token")
    actor = security.authenticate(session, csrf=token, mutation=True)
    try:
        require_permission(actor, permission)
    except Exception:
        security.audit(actor, str(permission), "DENIED", chamber_id)
        raise
    return actor
