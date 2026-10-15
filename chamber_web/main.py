"""NiceGUI read-only Dashboard bound to the server-owned generic service.

G05 exposes server-authorized manual control of one FakeBackend by default, or
of ONE supervised physical Vötsch chamber when the server is launched with a
complete CHAMBER_HIL_* authorization (loopback deployment only).
G03-C provides persistent profile editing in /profiles; Dashboard preview is non-executable.
"""
from __future__ import annotations

import asyncio
import os

from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

from .security.paths import configure_nicegui_storage

configure_nicegui_storage()

from nicegui import app, ui  # noqa: E402

from .bootstrap import create_demo_control_services
from .domain.chamber import ChamberSafetyError
from .hil.physical import hil_authorization_from_env
from .security.nicegui import (active_tokens, cookie_secret, current_actor, deployment_policy,
                               get_security, logout, require_authenticated_page)
from .ui_pages import (NavigationContext, install_navigation_resolver,
                       register_pages, render_navigation)
from .ui_state import project_capabilities, project_telemetry, safe_view

from .model import (
    MAX_TEMP, MIN_TEMP, Step, default_steps,
)


@dataclass
class ProfileDraft:
    """Non-executable Dashboard preview; editing lives under G03-C."""
    profile_name: str = "Temperature Cycle – Automotive"
    steps: list[Step] = field(default_factory=default_steps)
    logs: list[dict] = field(default_factory=list)
    run_steps: list[Step] = field(default_factory=list)
    step_index: int = 0
    completed: bool = False

    @property
    def active_steps(self) -> list[Step]:
        return self.steps

    def log(self, message: str) -> None:
        self.logs.insert(0, {
            "id": str(datetime.now().timestamp()),
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": "DRAFT", "message": message,
        })
        del self.logs[40:]


# One process-level device service, independent of any client/browser lifecycle.
# Physical I/O only via an explicit, complete launch-time HIL authorization.
_HIL = hil_authorization_from_env(os.environ)
if _HIL is not None and deployment_policy.is_lan:
    raise ChamberSafetyError("Supervised physical HIL is restricted to loopback deployment")
_dashboard_service, _manual_service = create_demo_control_services(get_security(), _HIL)
_MODE = "simulation" if _HIL is None else "physical HIL"
app.on_startup(_dashboard_service.start)
app.on_shutdown(_dashboard_service.close)


def get_dashboard_service():
    return _dashboard_service


# Role-driven navigation is presentation only; all service mutations are guarded.
def _server_navigation_context() -> NavigationContext:
    actor = current_actor()
    return NavigationContext(
        authenticated=actor is not None,
        role=actor.role.value if actor else None,
        permitted_routes=frozenset({"/", "/profiles", "/history", "/logs", "/settings"})
        if actor else frozenset(),
        physical_hil=_HIL is not None,
    )


install_navigation_resolver(_server_navigation_context)

# G07 readers are injected when the recording service is implemented.
register_pages(get_dashboard_service)


CSS = (Path(__file__).parent / "assets" / "style.css").read_text(encoding="utf-8")
ui.add_css(CSS, shared=True)


def _columns(columns: list[tuple[str, str]]) -> list[dict]:
    return [{"name": field, "label": title, "field": field, "align": "left"}
            for field, title in columns]


def _panel_title(icon: str, title: str) -> None:
    with ui.row().classes("items-center gap-2"):
        ui.icon(icon, color="blue-grey-10").classes("text-2xl")
        ui.label(title).classes("panel-heading")


@ui.page("/")
def dashboard() -> None:
    if not require_authenticated_page():
        return
    service = get_dashboard_service()
    # Local drafts are not executable runs or chamber state.
    state = ProfileDraft()

    def scroll_to(section: str) -> None:
        # Section names are fixed in this module, never user-controlled.
        ui.run_javascript(
            f"document.getElementById({section!r})?.scrollIntoView("
            "{behavior:'smooth',block:'start'})"
        )

    async def execute_manual(action: str) -> None:
        """Page event handler: pass only server-side G08 session tokens to G05."""
        if not require_authenticated_page(touch=False):
            return
        session, csrf = active_tokens()
        if action == "set_temperature":
            kw = {"target_c": target_input.value}
        else:
            kw = {}
        outcome_label.set_text(
            "STOP_REQUESTED — attempting STOP and checking readback"
            if action == "stop" else f"PENDING — {action}")
        try:
            result = await asyncio.to_thread(
                _manual_service.command, session, csrf, service.chamber_id,
                action, **kw)
        except Exception as exc:
            # Mutation-time G08 checks deny forged/revoked sessions. Other
            # unexpected service failures must NOT be classified as verified
            # rejections or successful physical/device outcomes.
            from .security.auth import AuthenticationError, AuthorizationError
            denied = isinstance(exc, (AuthenticationError, AuthorizationError))
            state = "REJECTED" if denied else "UNKNOWN"
            outcome_label.set_text(
                f"{state} — {'permission denied' if denied else 'server result unverified'} "
                f"({type(exc).__name__})")
            ui.notify(
                "Control denied" if denied else "Control effect unverified",
                color="negative")
            return
        outcome_label.set_text(
            f"{result.state.value} · {result.action} · {result.message}")
        if result.state.value != "CONFIRMED":
            ui.notify(result.message, color="warning")
        refresh_manual()

    async def confirm_handover() -> None:
        takeover_dialog.close()
        await execute_manual("handover")

    async def confirm_reconciliation() -> None:
        reconcile_dialog.close()
        await execute_manual("reconcile")

    def use_suggestion() -> None:
        # Cosmetic text-field helper: never dispatch a preset automatically.
        if preset_select.value is not None:
            target_input.value = preset_select.value

    def refresh_manual() -> None:
        if not require_authenticated_page(touch=False):
            return
        try:
            data = _manual_service.view(active_tokens()[0], service.chamber_id)
        except Exception:
            outcome_label.set_text("UNKNOWN — manual status unavailable")
            for b in (start_button, set_button, claim_button, release_button,
                      handover_button, reconcile_button):
                b.disable()
            # Keep STOP available despite telemetry failure *only* for an
            # independently reauthenticated G08 ADMIN/OPERATOR. A revoked or
            # VIEWER browser must never be shown an enabled mutation control.
            from .security.auth import Role
            try:
                actor = current_actor(touch=False)
                may_stop = actor is not None and actor.role in (Role.ADMIN, Role.OPERATOR)
            except Exception:
                may_stop = False
            stop_button.enable() if may_stop else stop_button.disable()
            return
        lease_label.set_text(
            f"Owner: {data.owner or 'unclaimed'} · "
            f"{'you hold control' if data.owned_by_actor else 'read only'}")
        control_health_label.set_text(
            f"Controller: {data.controller_state} · "
            f"{'connected' if data.connected else 'disconnected'} · "
            f"generation {data.controller_generation} · "
            f"{'STOP/reconciliation required' if data.stop_latched else 'fence clear'}")
        for button, available in (
            (start_button, data.can_start),
            (set_button, data.can_set_target),
            (stop_button, data.can_stop),
            (claim_button, data.can_stop and data.owner is None and
             data.connected and not data.stop_latched and
             data.controller_state in ("VERIFIED_STOPPED", "RUNNING") and
             data.dashboard.quality.value == "GOOD"),
            (release_button, data.can_stop and data.owned_by_actor),
            (handover_button, data.can_handover),
            (reconcile_button, data.can_reconcile),
        ):
            button.enable() if available else button.disable()
        choices = {n: f"{n:g} °C · suggestion only"
                   for n in data.presets_c}
        if choices != preset_select.options:
            preset_select.options = choices
            if preset_select.value not in choices:
                preset_select.value = None
            preset_select.update()
        if data.last_command:
            outcome_label.set_text(
                f"{data.last_command.state.value} · {data.last_command.action} · "
                f"{data.last_command.message}")

    with ui.row().classes("app-shell no-wrap"):
        with ui.column().classes("sidebar gap-1"):
            render_navigation("/")

        with ui.column().classes("main-area gap-0"):
            with ui.row().classes("topbar"):
                with ui.column().classes("gap-0"):
                    ui.label("Climate Chamber").classes("top-title")
                    ui.label(f"Signed in: {current_actor().username} ({current_actor().role.value})")
                    ui.label("Test Control Platform").classes("top-subtitle")
                with ui.column().classes("items-end gap-0"):
                    backend_label = ui.label(
                        "● SIMULATION · UNKNOWN" if _HIL is None else "● PHYSICAL HIL · UNKNOWN"
                    ).classes("demo-status")
                    backend_id_label = ui.label(
                        f"Backend: {'fake' if _HIL is None else 'votsch'} · {service.chamber_id}"
                    ).classes("text-xs text-grey-4")
                    clock_label = ui.label("").classes("text-xs text-grey-4")
                    ui.button("Sign out", icon="logout", on_click=logout).props("flat")

            with ui.column().classes("dashboard gap-0").props('id="dashboard-content"'):
                ui.label(
                    "SIMULATION ONLY — G04/G08-min authorized manual control. Physical hardware I/O is disabled."
                    if _HIL is None else
                    f"SUPERVISED PHYSICAL HIL — Vötsch SN {_HIL.expected_serial} at {_HIL.address}, "
                    f"software envelope {_HIL.temperature_min_c:g}–{_HIL.temperature_max_c:g} °C. "
                    "A person must be at the chamber; its own controls and emergency stop remain primary."
                ).classes("demo-banner w-full")
                with ui.element("div").classes("top-grid"):
                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("power_settings_new", "Chamber Control")
                            with ui.row().classes("gap-1"):
                                start_button = ui.button(
                                    "Start", icon="play_arrow",
                                    on_click=lambda: execute_manual("start")).props(
                                        "color=blue no-caps").disable().classes("toolbar-button")
                                stop_button = ui.button(
                                    "Stop", icon="stop",
                                    on_click=lambda: execute_manual("stop")).props(
                                        "color=deep-orange no-caps").disable().classes("toolbar-button")
                                ui.button("Hold", icon="pause").props(
                                    "outline color=dark no-caps disable").classes("toolbar-button")
                        ui.separator()
                        with ui.element("div").classes("metric-row"):
                            with ui.column().classes("metric gap-1"):
                                ui.label(f"Backend measured ({_MODE})").classes("metric-caption")
                                current_label = ui.label("—").classes("metric-value")
                            with ui.column().classes("metric gap-1"):
                                ui.label(f"Backend setpoint ({_MODE})").classes("metric-caption")
                                manual_target_label = ui.label("—").classes("metric-value")
                            with ui.column().classes("metric gap-1"):
                                ui.label("Backend reported state").classes("metric-caption")
                                status_label = ui.label("UNKNOWN").classes("status-pill")
                                quality_label = ui.label("Awaiting telemetry").classes("text-xs text-grey-7")
                        with ui.dialog() as takeover_dialog:
                            with ui.card():
                                ui.label("Transfer operator ownership to this administrator?").classes(
                                    "font-bold")
                                ui.label("This fences queued commands from the prior operator. "
                                         "It does not STOP the chamber or make it safe.")
                                with ui.row():
                                    ui.button("Cancel", on_click=takeover_dialog.close)
                                    ui.button("Confirm takeover",
                                              on_click=confirm_handover).props(
                                                  "color=deep-orange")
                        with ui.dialog() as reconcile_dialog:
                            with ui.card():
                                ui.label("Confirm STOP reconciliation").classes("font-bold")
                                ui.label("Only reconcile after independently checking the "
                                         "device is stopped. This is not hardware certification.")
                                with ui.row():
                                    ui.button("Cancel", on_click=reconcile_dialog.close)
                                    ui.button("Confirm reconcile",
                                              on_click=confirm_reconciliation).props(
                                                  "color=deep-orange")
                        with ui.element("div").classes("control-grid"):
                            # Target: what the chamber should do.
                            with ui.column().classes("control-section gap-2"):
                                ui.label("Target").classes("section-title")
                                with ui.row().classes("control-row"):
                                    target_input = ui.number(
                                        "Target °C", value=23.0, step=0.5).props(
                                            "outlined dense").classes("control-field")
                                    set_button = ui.button(
                                        "Set Target", icon="thermostat",
                                        on_click=lambda: execute_manual("set_temperature")).props(
                                            "unelevated color=primary no-caps").disable().classes(
                                                "control-button")
                                with ui.row().classes("control-row"):
                                    preset_select = ui.select(
                                        options={}, label="Suggested targets only").props(
                                            "outlined dense").classes("control-field")
                                    ui.button("Fill target", icon="edit",
                                              on_click=use_suggestion).props(
                                                  "outline no-caps").classes("control-button")
                                with ui.column().classes("gap-0"):
                                    ui.label("Simulated capability range (not site-certified)" if _HIL is None
                                             else "HIL software envelope (not site-certified)").classes(
                                                 "metric-caption")
                                    limits_label = ui.label("Waiting for backend capabilities").classes(
                                        "font-medium")
                                    ramp_detail_label = ui.label(
                                        "Gradients/modes unavailable; no ramp writes").classes(
                                            "text-xs text-grey-7")
                            # Operator lease: who may command the chamber.
                            with ui.column().classes("control-section gap-2"):
                                ui.label("Operator lease").classes("section-title")
                                lease_label = ui.label("Operator lease: unverified").classes("font-medium")
                                with ui.row().classes("control-row"):
                                    claim_button = ui.button(
                                        "Claim", icon="lock",
                                        on_click=lambda: execute_manual("claim")).props(
                                            "unelevated color=primary no-caps").disable().classes(
                                                "control-button")
                                    release_button = ui.button(
                                        "Release", icon="lock_open",
                                        on_click=lambda: execute_manual("release")).props(
                                            "outline no-caps").disable().classes("control-button")
                                with ui.row().classes("control-row wrap"):
                                    handover_button = ui.button(
                                        "Admin takeover", icon="swap_horiz",
                                        on_click=takeover_dialog.open).props(
                                            "outline no-caps").disable().classes("control-button")
                                    reconcile_button = ui.button(
                                        "Admin reconcile STOP", icon="verified_user",
                                        on_click=reconcile_dialog.open).props(
                                            "outline no-caps").disable().classes("control-button")
                                control_health_label = ui.label("Controller: UNKNOWN").classes(
                                    "text-xs text-grey-8")
                        # Status footer: last outcome and standing safety notes.
                        with ui.column().classes("control-status gap-1"):
                            outcome_label = ui.label("IDLE — no manual command").classes("outcome-line")
                            capability_detail_label = ui.label("Capabilities unverified").classes(
                                "text-xs text-orange-9")
                            ui.label(
                                "Web STOP is a best-effort control command, not an emergency stop."
                            ).classes("text-xs text-orange-9")


                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("description", "Active Profile")
                            with ui.row().classes("items-center gap-2"):
                                step_indicator = ui.label("Step —").classes("text-xs")
                                progress = ui.linear_progress(value=0, color="blue",
                                                              show_value=False).style("width:100px")
                                progress_label = ui.label("0%").classes("text-xs")
                        with ui.column().classes("profile-intro gap-1"):
                            active_name = ui.label("Profile: " + state.profile_name).classes("font-bold")
                            elapsed_label = ui.label("Execution unavailable (G06)")
                            ui.label("Draft preview only · no server-side profile runner").classes("text-xs")

                        @ui.refreshable
                        def step_overview():
                            with ui.column().classes("w-full gap-0"):
                                with ui.element("div").classes("profile-row header"):
                                    for heading in ("#", "Step", "Target", "Dwell", "Status"):
                                        ui.label(heading)
                                for index, step in enumerate(state.active_steps):
                                    css = "profile-row"
                                    if state.run_steps and index == state.step_index:
                                        css += " active-step"
                                    with ui.element("div").classes(css):
                                        ui.label(str(index + 1))
                                        ui.label(step.description)
                                        ui.label(f"{step.target:g} °C")
                                        ui.label(f"{step.dwell // 60} min")
                                        if not step.enabled:
                                            message = "Skipped"
                                        elif state.run_steps and index < state.step_index:
                                            message = "✓ Done"
                                        elif state.run_steps and index == state.step_index:
                                            message = state.status
                                        else:
                                            message = "○ Pending"
                                        ui.label(message)
                        step_overview()

                with ui.column().classes("panel chart-panel"):
                    with ui.row().classes("panel-head"):
                        _panel_title("show_chart", f"Temperature Graph ({_MODE.title()})")
                        with ui.row().classes("items-center gap-2"):
                            range_toggle = ui.toggle(["1h", "6h", "12h", "24h"], value="6h").props(
                                "dense no-caps")
                            measured_cb = ui.checkbox("Measured", value=True).props("dense color=blue")
                            target_cb = ui.checkbox("Target", value=True).props("dense color=orange")
                    ui.label("In-memory telemetry cache — NOT a G07 recorded run. Samples may predate disconnection.").classes("text-xs text-grey-7")
                    chart = ui.echart({
                        "animation": False,
                        "grid": {"left": 58, "right": 18, "top": 18, "bottom": 34},
                        "tooltip": {"trigger": "axis"},
                        "legend": {"show": False},
                        "xAxis": {"type": "category", "boundaryGap": False, "data": [],
                                  "axisLabel": {"fontSize": 10}},
                        "yAxis": {"type": "value", "name": "°C",
                                  "min": MIN_TEMP - 10, "max": MAX_TEMP + 10,
                                  "splitLine": {"lineStyle": {"color": "#e8edf2"}}},
                        "series": [
                            {"name": "Measured", "type": "line", "symbol": "none", "data": [],
                             "lineStyle": {"width": 2, "color": "#147bd3"}},
                            {"name": "Target", "type": "line", "step": "end",
                             "symbol": "none", "data": [],
                             "lineStyle": {"type": "dashed", "width": 2, "color": "#ef8429"}},
                        ],
                    }).classes("chart-box")

                    def update_chart() -> None:
                        # Server-owned history is independent of page refresh/close.
                        hours = {"1h": 1, "6h": 6, "12h": 12, "24h": 24}[range_toggle.value]
                        threshold = datetime.now().astimezone() - timedelta(hours=hours)
                        try:
                            recent_samples = service.recent_samples()
                        except Exception:
                            recent_samples = ()
                        series = [sample for sample in recent_samples
                                  if sample.time_utc.astimezone() >= threshold]
                        chart.options["xAxis"]["data"] = [
                            sample.time_utc.astimezone().strftime("%H:%M:%S")
                            for sample in series
                        ]
                        chart.options["series"][0]["data"] = [
                            sample.measured_c for sample in series] if measured_cb.value else []
                        chart.options["series"][1]["data"] = [
                            sample.target_c for sample in series] if target_cb.value else []
                        chart.update()

                    for widget in (range_toggle, measured_cb, target_cb):
                        widget.on("update:model-value", lambda: update_chart())

                with ui.element("div").classes("bottom-grid"):
                    # G03-C editor replaces the former nonpersistent browser draft.
                    with ui.column().classes("panel editor-panel").props('id="profile-editor"'):
                        with ui.row().classes("panel-head"):
                            _panel_title("edit_note", "Profile Editor")
                        ui.label("Profiles are saved in server-owned SQLite revisions.").classes(
                            "text-sm text-grey-7")
                        with ui.row().classes("gap-2 flex-wrap"):
                            for title, icon in (("Open Profiles", "description"),
                                                ("Import CSV", "upload"),
                                                ("Export CSV", "download")):
                                ui.button(title, icon=icon,
                                          on_click=lambda: ui.navigate.to("/profiles")).props(
                                              "outline no-caps")

                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("storage", "Live Data")
                        live_table = ui.table(
                            columns=_columns([("time", "Time"), ("measured", "Measured"),
                                              ("target", "Target"), ("status", "Quality")]),
                            rows=[], row_key="id", pagination=0).props(
                                "dense flat hide-bottom separator=horizontal").classes(
                                    "small-table w-full")

                    with ui.column().classes("panel").props('id="event-log"'):
                        with ui.row().classes("panel-head"):
                            _panel_title("list_alt", "Draft Events (not device log)")
                            def clear_log() -> None:
                                state.logs.clear()
                                log_table.update_rows([])
                            ui.button("Clear", icon="delete_outline", on_click=clear_log).props(
                                "outline no-caps").classes("toolbar-button")
                        log_table = ui.table(
                            columns=_columns([("time", "Time"), ("level", "Level"),
                                              ("message", "Message")]),
                            rows=list(state.logs), row_key="id", pagination=0).props(
                                "dense flat hide-bottom separator=horizontal").classes(
                                    "small-table w-full")

    def refresh() -> None:
        if not require_authenticated_page(touch=False):
            return
        view = safe_view(service)
        display = project_telemetry(view)
        capability = project_capabilities(view)
        identity = view.identity
        backend_label.set_text(f"● {display.mode} · {display.quality} · {display.operation}")
        backend_id_label.set_text(
            f"Backend: {identity.backend_id} · {view.chamber_id}" if identity
            else f"Backend: awaiting status · {view.chamber_id}"
        )
        current_label.set_text(display.measured)
        manual_target_label.set_text(display.setpoint)
        status_label.set_text(display.operation)
        quality_label.set_text(f"Quality: {display.quality} · {display.message} · "
                               f"sample: {display.sampled_utc}")
        limits_label.set_text(capability.temperature_range)
        capability_detail_label.set_text(
            "SIMULATED manual control — requires operator lease and fresh readback; "
            "physical device writes disabled"
            if identity and identity.is_simulation and view.capabilities
            else "PHYSICAL HIL manual control — requires operator lease and fresh device readback"
            if identity and _HIL is not None and view.capabilities
            else capability.controls_locked_reason)
        ramp_detail_label.set_text(f"Ramp up: {capability.ramp_up} · "
                                   f"ramp down: {capability.ramp_down}")
        if view.capabilities:
            chart.options["yAxis"]["min"] = view.capabilities.temperature_min_c - 10
            chart.options["yAxis"]["max"] = view.capabilities.temperature_max_c + 10
        step_indicator.set_text("Draft")
        progress.value = 0
        progress_label.set_text("0%")
        active_name.set_text("Draft: " + state.profile_name)
        clock_label.set_text(f"Sample: {display.sampled_utc}")
        update_chart()
        try:
            recent = service.recent_samples()[-12:]
        except Exception:
            recent = ()
        live_table.update_rows([{
            "id": str(index), "time": s.time_utc.astimezone().strftime("%H:%M:%S"),
            "measured": f"{s.measured_c:.1f}",
            "target": f"{s.target_c:.1f}" if s.target_c is not None else "—",
            "status": "SIMULATED" if identity is None or identity.is_simulation else "PHYSICAL",
        } for index, s in enumerate(recent)])
        log_table.update_rows(list(state.logs))

    ui.timer(1.0, refresh, immediate=False)
    ui.timer(1.0, refresh_manual, immediate=False)
    refresh()
    refresh_manual()


# G03-C profile route is registered during module import for all Windows entrypoints.
from .pages import profiles as _profile_editor_page  # noqa: E402,F401

def run() -> None:
    # TLS, peer ACL and exact Origin are mandatory for explicit LAN mode.
    # Physical Vötsch I/O requires a CHAMBER_HIL_* authorization and loopback mode.
    from .security.nicegui import deployment_policy
    options = {}
    if deployment_policy.is_lan:
        options = {"ssl_certfile": str(deployment_policy.certfile),
                   "ssl_keyfile": str(deployment_policy.keyfile)}
    ui.run(title="Climate Chamber — server simulation" if _HIL is None
           else "Climate Chamber — SUPERVISED PHYSICAL HIL",
           host=deployment_policy.bind_host, port=deployment_policy.port,
           reload=False, show=False, storage_secret=cookie_secret(),
           session_middleware_kwargs={
               "same_site": "strict", "max_age": 28800,
               "https_only": deployment_policy.is_lan,
           }, **options)


if __name__ == "__main__":
    run()
