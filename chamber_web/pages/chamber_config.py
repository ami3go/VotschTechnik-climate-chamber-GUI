"""Settings-tab chamber configuration: type, connection and HIL envelope.

Saving writes server-side settings only. They are validated with the same
rules as ``CHAMBER_HIL_*`` and take effect at the NEXT server start; the
running process never switches between simulation and hardware.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

from nicegui import ui

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.hil.chamber_settings import (
    CHAMBER_TYPES, ChamberSettings, load_settings, save_settings, settings_path,
)
from chamber_web.hil.physical import HARD_MAX_C, HARD_MIN_C, MAX_ENVELOPE_SPAN_C
from chamber_web.security.auth import AuthenticationError, AuthorizationError, Role
from chamber_web.security.guards import Permission
from chamber_web.security.nicegui import (active_tokens, current_actor, get_security,
                                          require_authenticated_page, require_browser_permission)


_LOG = logging.getLogger(__name__)


def _describe(settings: ChamberSettings | None) -> str:
    if settings is None or settings.chamber_type == "simulator":
        return "Simulator (no hardware)"
    return (f"{CHAMBER_TYPES[settings.chamber_type]} · {settings.chamber_id} · "
            f"{settings.address} · serial {settings.expected_serial} · "
            f"{settings.temperature_min_c:g}…{settings.temperature_max_c:g} °C")


def render_chamber_config_panel(discover_chambers: Callable | None = None) -> None:
    """Settings-tab panel; the form is shown to administrators only."""
    actor = current_actor()
    from chamber_web.main import active_chamber_authorization

    hil, source = active_chamber_authorization()
    try:
        saved = load_settings()
        saved_error = ""
    except ChamberSafetyError as exc:
        saved, saved_error = None, str(exc)
    initial = saved or ChamberSettings()

    def update_visibility() -> None:
        physical_fields.set_visibility(type_select.value != "simulator")

    async def save() -> None:
        if not require_authenticated_page(touch=False):
            return
        try:
            settings = ChamberSettings(
                chamber_type=type_select.value,
                chamber_id=(chamber_id.value or "").strip(),
                address=(address.value or "").strip(),
                expected_serial=(serial.value or "").strip(),
                temperature_min_c=float(temp_min.value),
                temperature_max_c=float(temp_max.value),
                person_present_acknowledged=bool(acknowledge.value),
            )
        except (TypeError, ValueError):
            ui.notify("Temperature limits must be numbers.", color="negative")
            return
        session, csrf = active_tokens()
        try:
            stored = await asyncio.to_thread(
                save_settings, get_security(), session, csrf, password.value, settings)
        except (AuthenticationError, AuthorizationError):
            ui.notify("Save denied. Verify the administrator password.", color="negative")
            return
        except ChamberSafetyError as exc:
            ui.notify(f"Not saved: {exc}", color="negative", multi_line=True)
            return
        password.value = ""
        saved_label.set_text("Saved (applies after restart): " + _describe(stored))
        ui.notify("Chamber settings saved. Restart the server to apply them.",
                  color="positive")

    scanning = False

    def select_discovered(device) -> None:
        # Re-check G08 permission on every WebSocket click, not only page load.
        try:
            require_browser_permission(Permission.SETTINGS)
        except (AuthenticationError, AuthorizationError):
            ui.notify("Administrator session expired or access denied", color="negative")
            return
        type_select.value = "votsch"
        update_visibility()
        address.value = device.address
        serial.value = device.serial_number
        # Chamber ID, site-approved temperature envelope and acknowledgement are
        # deliberately NOT manufactured from network-discovered data.
        ui.notify("Address and serial filled. Review safety limits, acknowledge "
                  "supervision and save using the administrator password. "
                  "Restart required.", color="info", multi_line=True)

    async def scan_network(*, local_only: bool = False, ip_only: bool = False) -> None:
        nonlocal scanning
        if scanning:
            return
        try:
            actor = require_browser_permission(Permission.SETTINGS)
        except (AuthenticationError, AuthorizationError):
            ui.notify("Administrator session expired or access denied", color="negative")
            return
        scanning = True
        scan_button.disable()
        results.clear()
        # An IP in the existing configuration field must not be ignored.
        # Explicit scope wins. Scan-local bypasses both input fields.
        if local_only:
            scope = None
        elif ip_only:
            scope = (address.value or "").strip() or None
        else:
            scope = ((discovery_subnet.value or "").strip()
                     or (address.value or "").strip() or None)
        if ip_only and not scope:
            scan_status.set_text("Enter a private IPv4 address before verification.")
            ui.notify("Enter the chamber IP address first", color="negative")
            return
        scan_status.set_text(
            f"Checking {scope} on TCP 2049 using read-only identity queries…"
            if scope else "Scanning server-side private IPv4 networks using "
            "read-only GET CHAMBER INFO queries (12s watchdog)…")
        try:
            if discover_chambers is None:
                raise RuntimeError("Discovery service unavailable in this server")
            devices = await asyncio.wait_for(
                asyncio.to_thread(discover_chambers, scope),
                timeout=15.0)
            # Revoked sessions cannot receive results or select a chamber.
            require_browser_permission(Permission.SETTINGS)
            get_security().audit(actor, "chamber.discovery", "SUCCESS",
                                 detail=f"Found {len(devices)} chambers")
        except (AuthenticationError, AuthorizationError):
            results.clear()
            scan_status.set_text("Administrator authorization expired; results discarded.")
            return
        except (ValueError, RuntimeError, asyncio.TimeoutError) as exc:
            if isinstance(exc, asyncio.TimeoutError):
                reason = "Discovery watchdog expired. Check the server-side network or try one IP."
            else:
                reason = str(exc) or "Discovery rejected the request."
            scan_status.set_text(f"Discovery failed: {reason}")
            ui.notify(reason, color="negative", multi_line=True)
            return
        except Exception:
            _LOG.exception("Unexpected read-only chamber discovery failure")
            scan_status.set_text(
                "Discovery failed due to an internal error. Review the server logs "
                "and confirm the pinned external driver was installed.")
            ui.notify("Discovery internal error; check server logs", color="negative")
            return
        finally:
            scanning = False
            scan_button.enable()
        scan_status.set_text(
            f"Found {len(devices)} compatible chamber(s). "
            "Discovery does not certify hardware safety or connect a controller."
            if devices else "No compatible Vötsch/Weiss chambers responded on TCP 2049. "
            "Check the server subnet, network connection and chamber IP settings.")
        with results:
            for device in devices:
                with ui.row().classes("items-center w-full gap-3 flex-wrap"):
                    ui.label(
                        f"{device.address} · {device.model} · S/N {device.serial_number}"
                    ).classes("flex-grow")
                    ui.button("Select", icon="add", on_click=lambda d=device: (
                        select_discovered(d))).props("outline no-caps")

    with ui.column().classes("panel gap-2"):
        ui.label("Chamber Connection").classes("panel-heading")
        if hil is None:
            ui.label("Running: Simulator (no hardware)").classes("font-bold")
        else:
            ui.label(
                f"Running: SUPERVISED PHYSICAL HIL · {hil.chamber_id} · {hil.address} · "
                f"serial {hil.expected_serial} · "
                f"{hil.temperature_min_c:g}…{hil.temperature_max_c:g} °C").classes(
                    "font-bold text-negative")
        ui.label(f"Configuration source: {source}").classes("text-xs text-grey-8")
        if source == "environment":
            ui.label("CHAMBER_HIL_* environment variables are set for this server "
                     "and override the saved settings below.").classes(
                         "text-xs text-orange-9")
        saved_label = ui.label(
            "Saved (applies after restart): " + _describe(saved)).classes("text-sm")
        if saved_error:
            ui.label(saved_error).classes("text-negative")

    if actor is None or actor.role is not Role.ADMIN:
        ui.label("Only an administrator can change the chamber configuration.").classes(
            "text-xs text-grey-7")
        return

    with ui.column().classes("panel gap-3"):
        ui.label("Chamber configuration").classes("panel-heading")
        ui.label(
            "Changes take effect only after the server is restarted. The software "
            "envelope is a secondary guard: the chamber's own limits and emergency "
            "stop remain the primary safety layer. Physical profile runs additionally "
            "require the signed H02 site permit."
        ).classes("demo-banner w-full")
        type_select = ui.select(CHAMBER_TYPES, value=initial.chamber_type,
                                label="Chamber type",
                                on_change=lambda _: update_visibility()).classes("w-full")
        with ui.column().classes("w-full gap-2"):
            ui.label("Auto-detect Vötsch / Weiss chambers").classes("text-subtitle2")
            ui.label(
                "Scans from this server, not the browser. By default scans the "
                "server's detected private local /24 subnets. Enter a "
                "single private chamber IP or a /24-or-narrower subnet; "
                "if left blank, the IP in the configuration form is checked "
                "first. Use 'Scan local networks' to ignore saved addresses. "
                "Read-only GET CHAMBER INFO only; no control commands."
            ).classes("text-xs text-grey-7")
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                discovery_subnet = ui.input(
                    "Chamber IP or private subnet (e.g. 192.168.1.10 or 192.168.1.0/24)"
                ).props("outlined dense").classes("min-w-64 flex-grow")
                scan_button = ui.button(
                    "Auto-detect chambers", icon="travel_explore",
                    on_click=lambda: scan_network()
                ).props("outline no-caps")
                ui.button("Scan local networks", icon="lan",
                          on_click=lambda: scan_network(local_only=True)).props(
                              "flat no-caps")
            scan_status = ui.label("Discovery is manual and read-only.").classes(
                "text-xs text-grey-7")
            results = ui.column().classes("w-full gap-2")
        with ui.column().classes("w-full gap-2") as physical_fields:
            chamber_id = ui.input("Chamber ID", value=initial.chamber_id).classes("w-full")
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                address = ui.input("IP address (private IPv4)",
                                   value=initial.address).classes("flex-grow min-w-64")
                ui.button("Verify this IP", icon="wifi_find",
                          on_click=lambda: scan_network(ip_only=True)).props("outline no-caps")
            serial = ui.input("Expected serial number",
                              value=initial.expected_serial).classes("w-full")
            with ui.row().classes("w-full gap-3"):
                temp_min = ui.number("Minimum temperature (°C)",
                                     value=initial.temperature_min_c,
                                     min=HARD_MIN_C, max=HARD_MAX_C)
                temp_max = ui.number("Maximum temperature (°C)",
                                     value=initial.temperature_max_c,
                                     min=HARD_MIN_C, max=HARD_MAX_C)
            ui.label(f"Envelope must lie within {HARD_MIN_C:g}…{HARD_MAX_C:g} °C and "
                     f"span at most {MAX_ENVELOPE_SPAN_C:g} °C. The connected chamber's "
                     "serial number must match.").classes("text-xs")
            acknowledge = ui.checkbox(
                "A trained person will be present at the chamber whenever the server "
                "runs with this configuration",
                value=initial.person_present_acknowledged)
        password = ui.input("Current administrator password (required to save)",
                            password=True).props(
                                "autocomplete=current-password").classes("w-full")
        ui.button("Save chamber settings", icon="save", on_click=save).props(
            "unelevated no-caps")
        ui.label(f"Stored on the server in {settings_path()}").classes(
            "text-xs text-grey-7")
        update_visibility()
