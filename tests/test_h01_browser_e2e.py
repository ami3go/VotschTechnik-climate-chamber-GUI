"""H01 real Chromium integration against a running, localhost-only NiceGUI server.

Requires the optional test dependency 'playwright' and an installed Chromium
browser. Unlike nicegui.testing.User this executes real browser JS + WebSocket.
The server is the current PRODUCTION COMPOSITION ROOT with FakeBackend only.
"""
from __future__ import annotations

import os
import socket
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


def _select_port() -> int:
    """Keep 8080 when free (CI), honour the override, else auto-select.

    A developer machine may occupy 8080 (or a parallel run may hold a fixed
    port); a free ephemeral port keeps the suite self-contained instead of
    failing on port contention.
    """
    override = os.environ.get("H01_BROWSER_PORT")
    if override:
        return int(override)
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 8080))
            return 8080
        except OSError:
            pass
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


PORT = _select_port()
URL = f"http://127.0.0.1:{PORT}"


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
        # NiceGUI 3.18 helpers.is_pytest() checks PYTEST_CURRENT_TEST in the
        # environment, not whether pytest is imported in this child process.
        # Strip pytest and NiceGUI test/runtime markers: the subprocess is a
        # real localhost-only server, not an in-process NiceGUI test fixture.
        inherited_test_vars = {
            "PYTEST_CURRENT_TEST", "NICEGUI_USER_SIMULATION",
            "NICEGUI_HOST", "NICEGUI_PORT", "NICEGUI_PROTOCOL",
        }
        env = {key: value for key, value in os.environ.items()
               if key not in inherited_test_vars and
               not key.startswith("NICEGUI_SCREEN_TEST")}
        env.update({
            "CHAMBER_SECURITY_DIR": str(security_root),
            "CHAMBER_PORT": str(PORT),
            "CHAMBER_ALLOWED_ORIGINS": URL + f",http://localhost:{PORT}",
            "PYTHONUNBUFFERED": "1",
        })
        logfile = Path(temp) / "server.log"
        with logfile.open("w+", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", "main"],  # canonical project launcher
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
            # Operators may Start directly when the chamber is ready. A
            # previous uncertain restart latch can still require reconciliation.
            expect(admin.get_by_role("button", name="Stop", exact=True)).to_be_enabled()
            if "UNKNOWN" not in admin.locator("body").inner_text():
                expect(admin.get_by_role("button", name="Start", exact=True)).to_be_enabled()

            admin.goto(URL + "/profiles")
            expect(admin.locator("body")).to_contain_text("Persistent Profiles / Revisions")
            expect(admin.locator("body")).to_contain_text("Immutable Revision History")

            sign_in(viewer, "browser_viewer", "StrongViewerPassword#2")
            expect(viewer.locator("body")).to_contain_text("VIEWER")
            viewer.goto(URL + "/profiles")
            expect(viewer.locator("body")).to_contain_text("Persistent Profiles / Revisions")
            viewer.goto(URL + "/history")
            expect(viewer.locator("body")).to_contain_text("Run History")
            expect(viewer.locator("body")).to_contain_text(
                "Server-recorded runs only")
            # Return to /profiles so the session-survival reload below keeps
            # asserting the same page the original regression covered.
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


def test_browser_g05_actual_manual_start_stop_and_viewer_denial(live_app):
    # End-to-end Chromium + NiceGUI WebSocket, not just service unit calls.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            admin_context = browser.new_context()
            viewer_context = browser.new_context()
            admin = admin_context.new_page()
            viewer = viewer_context.new_page()
            sign_in(admin, "browser_admin", "StrongAdminPassword#1")
            expect(admin.get_by_role("button", name="Stop", exact=True)).to_be_enabled()
            admin.goto(URL + "/admin")
            expect(admin.locator("body")).to_contain_text("Lease state: RELEASED")
            # A restart with uncertain state is a genuine safety exception:
            # preserve signed, fresh-readback Admin recovery for that case.
            if "STOP/reconciliation required" in admin.locator("body").inner_text():
                admin.get_by_role("button", name="Admin reconcile STOP").click()
                admin.get_by_role("button", name="Confirm reconcile").click()
                expect(admin.locator("body")).to_contain_text("fence clear", timeout=15000)
            admin.goto(URL + "/")
            # Routine STOP works without a claim, and a fresh START acquires
            # the lease and re-arms a verified stop without visiting Admin.
            expect(admin.get_by_role("button", name="Start", exact=True)).to_be_enabled()
            admin.get_by_role("button", name="Stop", exact=True).click()
            expect(admin.locator("body")).to_contain_text(
                "CONFIRMED · stop", timeout=15000)
            expect(admin.get_by_role("button", name="Start", exact=True)).to_be_enabled()
            admin.get_by_label("Target °C").fill("25")
            admin.get_by_role("button", name="Set Target").click()
            expect(admin.locator("body")).to_contain_text("CONFIRMED · set_temperature", timeout=15000)
            admin.get_by_role("button", name="Start", exact=True).click()
            expect(admin.locator("body")).to_contain_text("CONFIRMED · start", timeout=15000)
            admin.goto(URL + "/admin")
            expect(admin.locator("body")).to_contain_text(
                "Lease state: CLAIMED", timeout=15000)
            admin.goto(URL + "/")
            sign_in(viewer, "browser_viewer", "StrongViewerPassword#2")
            expect(viewer.get_by_role("button", name="Start", exact=True)).to_be_disabled()
            expect(viewer.get_by_role("button", name="Stop", exact=True)).to_be_disabled()
            admin.get_by_role("button", name="Stop", exact=True).click()
            expect(admin.locator("body")).to_contain_text(
                "STOP verified; controls ready", timeout=15000)
            # Normal owner STOP automatically rearms only after independent
            # verified STOPPED readback; ownership remains unchanged.
            expect(admin.get_by_role("button", name="Start", exact=True)).to_be_enabled(
                timeout=15000)
            admin.get_by_role("button", name="Start", exact=True).click()
            expect(admin.locator("body")).to_contain_text(
                "CONFIRMED · start", timeout=15000)
            admin.get_by_role("button", name="Stop", exact=True).click()
            expect(admin.locator("body")).to_contain_text(
                "STOP verified; controls ready", timeout=15000)
            admin.goto(URL + "/admin")
            expect(admin.locator("body")).to_contain_text("fence clear", timeout=15000)
            expect(admin.locator("body")).to_contain_text(
                "Lease state: CLAIMED", timeout=15000)
            admin.get_by_role("button", name="Release", exact=True).click()
            expect(admin.locator("body")).to_contain_text(
                "Lease state: RELEASED", timeout=15000)
            viewer.reload()
            expect(viewer.get_by_role("button", name="Stop", exact=True)).to_be_disabled()
            admin_context.close()
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
