"""Settings-tab chamber configuration: type, connection and HIL envelope.

Saving writes server-side settings only. They are validated with the same
rules as ``CHAMBER_HIL_*`` and take effect at the NEXT server start; the
running process never switches between simulation and hardware.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.hil.chamber_settings import (
    CHAMBER_TYPES, ChamberSettings, load_settings, save_settings, settings_path,
)
from chamber_web.hil.physical import HARD_MAX_C, HARD_MIN_C, MAX_ENVELOPE_SPAN_C
from chamber_web.security.auth import AuthenticationError, AuthorizationError, Role
from chamber_web.security.nicegui import (active_tokens, current_actor, get_security,
                                          require_authenticated_page)


def _describe(settings: ChamberSettings | None) -> str:
    if settings is None or settings.chamber_type == "simulator":
        return "Simulator (no hardware)"
    return (f"{CHAMBER_TYPES[settings.chamber_type]} · {settings.chamber_id} · "
            f"{settings.address} · serial {settings.expected_serial} · "
            f"{settings.temperature_min_c:g}…{settings.temperature_max_c:g} °C")


def render_chamber_config_panel() -> None:
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
        with ui.column().classes("w-full gap-2") as physical_fields:
            chamber_id = ui.input("Chamber ID", value=initial.chamber_id).classes("w-full")
            address = ui.input("IP address (private IPv4)",
                               value=initial.address).classes("w-full")
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
