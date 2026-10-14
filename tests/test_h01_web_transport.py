"""ASGI transport security around the real NiceGUI OriginMiddleware.

No in-memory HTTP endpoint may circumvent G08; all denied requests must be
rejected before reaching a downstream ASGI application.
"""
from __future__ import annotations

import unittest

from chamber_web.security.http import OriginMiddleware


GOOD = "http://127.0.0.1:8080"


class H01WebTransportTests(unittest.IsolatedAsyncioTestCase):
    async def probe(self, *, kind="http", method="POST", path="/_nicegui/socket.io/",
                    host="127.0.0.1:8080", origin=GOOD, site="same-origin"):
        dispatched = []
        messages = []

        async def inner(scope, receive, send):
            dispatched.append((scope["type"], scope.get("method"), scope.get("path")))
            if scope["type"] == "websocket":
                await send({"type": "websocket.accept"})
            else:
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"OK"})

        middleware = OriginMiddleware(inner, allowed_origins=frozenset({
            GOOD, "http://localhost:8080",
        }))
        headers = [(b"host", host.encode("ascii"))]
        if origin is not None:
            headers.append((b"origin", origin.encode("ascii")))
        if site is not None:
            headers.append((b"sec-fetch-site", site.encode("ascii")))
        scope = {"type": kind, "method": method, "path": path, "headers": headers}
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            messages.append(message)
        await middleware(scope, receive, send)
        return dispatched, messages

    async def test_valid_same_origin_nicegui_post_reaches_app(self):
        dispatched, messages = await self.probe()
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(messages[0]["status"], 200)

    async def test_anonymous_custom_http_mutation_blocked_even_same_origin(self):
        dispatched, messages = await self.probe(path="/api/chamber/start")
        self.assertEqual(dispatched, [])
        self.assertEqual(messages[0]["status"], 403)

    async def test_cross_site_post_never_reaches_app(self):
        for origin, host, site in [
            ("https://evil.example", "127.0.0.1:8080", "cross-site"),
            (GOOD, "evil.example", "same-origin"),
            (None, "127.0.0.1:8080", None),
            ("null", "127.0.0.1:8080", None),
            (GOOD, "127.0.0.1:8080", "cross-site"),
            ("http://127.0.0.1:9999", "127.0.0.1:8080", "same-origin"),
        ]:
            with self.subTest(origin=origin, host=host, site=site):
                dispatched, messages = await self.probe(origin=origin, host=host, site=site)
                self.assertEqual(dispatched, [])
                self.assertEqual(messages[0]["status"], 403)

    async def test_good_websocket_upgrade_is_origin_bound(self):
        dispatched, messages = await self.probe(
            kind="websocket", method="GET", path="/_nicegui_ws/socket.io/")
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(messages[0]["type"], "websocket.accept")

    async def test_foreign_and_missing_websocket_origins_refused(self):
        for origin, host, site in [
            (None, "127.0.0.1:8080", None),
            ("https://evil.example", "127.0.0.1:8080", "cross-site"),
            (GOOD, "fake-host.example", "same-origin"),
        ]:
            with self.subTest(origin=origin):
                dispatched, messages = await self.probe(
                    kind="websocket", method="GET", origin=origin, host=host, site=site)
                self.assertEqual(dispatched, [])
                self.assertEqual(messages[0]["type"], "websocket.close")
                self.assertEqual(messages[0]["code"], 1008)

    async def test_get_still_requires_application_authentication(self):
        # A read-only GET is intentionally handed to the Next layer.
        # G08's actual page-level login check is exercised by browser tests.
        dispatched, messages = await self.probe(
            method="GET", path="/", origin=None, site=None)
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(messages[0]["status"], 200)


if __name__ == "__main__":
    unittest.main()
