"""H01 real Chromium integration against a running, localhost-only NiceGUI server.

Requires the optional test dependency 'playwright' and an installed Chromium
browser. Unlike nicegui.testing.User this executes real browser JS + WebSocket.
The server is the current PRODUCTION COMPOSITION ROOT with FakeBackend only.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from chamber_web.security.auth import Role, SecurityStore


ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8080"


@pytest.fixture(scope="module")
def live_app():
    """Start exactly one isolated simulated server; no developer credentials."""
    with tempfile.TemporaryDirectory(prefix="h01-browser-") as temp:
        security_root = Path(temp) / "security"
        security = SecurityStore(security_root)
        security.bootstrap_admin("browser_admin", "StrongAdminPassword#1")
        admin = security.login("browser_admin", "StrongAdminPassword#1")
        security.create_user(
            admin.session, admin.csrf, "browser_viewer",
            "StrongViewerPassword#2", Role.VIEWER,
        )
        # pytest/nicegui.testing may set SCREEN_TEST without the paired port.
        # A separately launched production-like server must not inherit that
        # in-process test harness flag (NiceGUI ui.run would exit at startup).
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("NICEGUI_SCREEN_TEST")}
        env.update({
            "CHAMBER_SECURITY_DIR": str(security_root),
            "CHAMBER_PORT": "8080",
            "CHAMBER_ALLOWED_ORIGINS": URL + ",http://localhost:8080",
            "PYTHONUNBUFFERED": "1",
        })
        logfile = Path(temp) / "server.log"
        with logfile.open("w+", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "chamber_web.main"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(URL + "/login", timeout=1.5) as response:
                            if response.status == 200:
                                break
                    except (urllib.error.URLError, TimeoutError, ConnectionError):
                        time.sleep(0.25)
                else:
                    raise RuntimeError("NiceGUI startup timed out")
                if proc.poll() is not None:
                    raise RuntimeError("NiceGUI exited before browser tests")
                yield security
            except BaseException:
                log.flush()
                log.seek(0)
                print("H01 server diagnostics:\n" + log.read()[-10000:])
                raise
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)


def sign_in(page, username, password):
    page.goto(URL + "/login", wait_until="domcontentloaded")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    expect(page.locator("body")).to_contain_text("SIMULATION", timeout=15000)


def test_browser_authenticated_dashboard_profiles_and_independent_clients(live_app):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            admin_context = browser.new_context(viewport={"width": 1440, "height": 900})
            viewer_context = browser.new_context(viewport={"width": 1024, "height": 768})
            admin = admin_context.new_page()
            viewer = viewer_context.new_page()

            admin.goto(URL + "/")
            expect(admin.get_by_label("Username")).to_be_visible()
            sign_in(admin, "browser_admin", "StrongAdminPassword#1")
            expect(admin.locator("body")).to_contain_text("Signed in: browser_admin (ADMIN)")
            expect(admin.locator("body")).to_contain_text("Backend: fake")
            # Current main Dashboard is deliberately read-only, not G05.
            expect(admin.get_by_role("button", name="Start", exact=True)).to_be_disabled()
            expect(admin.get_by_role("button", name="Stop", exact=True)).to_be_disabled()

            admin.goto(URL + "/profiles")
            expect(admin.locator("body")).to_contain_text("Persistent Profiles / Revisions")
            expect(admin.locator("body")).to_contain_text("Immutable Revision History")

            sign_in(viewer, "browser_viewer", "StrongViewerPassword#2")
            expect(viewer.locator("body")).to_contain_text("VIEWER")
            viewer.goto(URL + "/profiles")
            expect(viewer.locator("body")).to_contain_text("Persistent Profiles / Revisions")

            admin.reload()
            expect(admin.locator("body")).to_contain_text("Persistent Profiles / Revisions")
            admin_context.close()
            # Closing the other browser MUST NOT end the viewer server session.
            viewer.reload()
            expect(viewer.locator("body")).to_contain_text("Persistent Profiles / Revisions")
            viewer_context.close()
        finally:
            browser.close()


def test_browser_revoked_session_cannot_reenter_protected_page(live_app):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            sign_in(page, "browser_viewer", "StrongViewerPassword#2")
            # Admin-authorized role change revokes existing viewer sessions.
            admin = live_app.login("browser_admin", "StrongAdminPassword#1")
            live_app.change_role(
                admin.session, admin.csrf, "browser_viewer", Role.OPERATOR)
            page.goto(URL + "/profiles")
            expect(page.get_by_label("Username")).to_be_visible(timeout=15000)
            context.close()
        finally:
            browser.close()
