"""NiceGUI read-only Dashboard bound to the server-owned generic service.

G02-A exposes no chamber mutations, no page-owned chamber state, and no hardware.
G03-C provides the persistent editor at /profiles. The Dashboard draft profile\npreview is non-executable G02-A/G02-B demonstration state.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

from nicegui import app, ui

from .bootstrap import create_demo_dashboard_service

from .model import (
    MAX_TEMP, MIN_TEMP, Step, default_steps,
)


@dataclass
class ProfileDraft:
    """Non-executable Dashboard preview data; G03-C editing is separate."""
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


# One process-level Fake service, independent of any client/browser lifecycle.
_dashboard_service = create_demo_dashboard_service()
app.on_startup(_dashboard_service.start)
app.on_shutdown(_dashboard_service.close)


def get_dashboard_service():
    return _dashboard_service


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
    service = get_dashboard_service()
    # Local drafts are not executable runs or chamber state.
    state = ProfileDraft()

    def scroll_to(section: str) -> None:
        # Section names are fixed in this module, never user-controlled.
        ui.run_javascript(
            f"document.getElementById({section!r})?.scrollIntoView("
            "{behavior:'smooth',block:'start'})"
        )

    with ui.dialog() as settings_dialog:
        with ui.card().classes("w-96"):
            ui.label("Backend Settings (read-only)").classes("text-lg font-bold")
            ui.label("Server telemetry is provided by the single configured Fake backend.")
            ui.label("Live configuration, controller and permissions are not implemented.").classes(
                "text-sm text-orange-9")
            ui.button("Close", on_click=settings_dialog.close).props("flat")

    with ui.dialog() as history_dialog:
        with ui.card().classes("w-96"):
            ui.label("Run History").classes("text-lg font-bold")
            ui.label("Persistent run history will be implemented with the server-side runner.")
            ui.label("Current page demo is not recorded to disk.").classes("text-orange-9")
            ui.button("Close", on_click=history_dialog.close).props("flat")

    with ui.row().classes("app-shell no-wrap"):
        with ui.column().classes("sidebar gap-1"):
            ui.label("Visteon").classes("brand")
            for index, (icon, title, callback) in enumerate([
                ("dashboard", "Dashboard", lambda: scroll_to("dashboard-content")),
                ("description", "Profiles", lambda: ui.navigate.to("/profiles")),
                ("history", "Run History", history_dialog.open),
                ("list_alt", "Logs", lambda: scroll_to("event-log")),
                ("settings", "Settings", settings_dialog.open),
            ]):
                with ui.button(on_click=callback, icon=icon).props("flat no-caps align=left") as button:
                    ui.label(title).classes("nav-text")
                if index == 0:
                    button.classes("nav-active")
            ui.label("Climate Chamber | G02-A\nServer-side simulation only").classes(
                "side-note whitespace-pre-line")

        with ui.column().classes("main-area gap-0"):
            with ui.row().classes("topbar"):
                with ui.column().classes("gap-0"):
                    ui.label("Climate Chamber").classes("top-title")
                    ui.label("Test Control Platform").classes("top-subtitle")
                with ui.column().classes("items-end gap-0"):
                    backend_label = ui.label("● SIMULATION · UNKNOWN").classes("demo-status")
                    backend_id_label = ui.label("Backend: fake · demo-chamber").classes("text-xs text-grey-4")
                    clock_label = ui.label("").classes("text-xs text-grey-4")

            with ui.column().classes("dashboard gap-0").props('id="dashboard-content"'):
                ui.label(
                    "SIMULATION — server-owned Fake backend telemetry. Hardware controls are unavailable."
                ).classes("demo-banner w-full")
                with ui.element("div").classes("top-grid"):
                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("power_settings_new", "Chamber Control")
                            with ui.row().classes("gap-1"):
                                ui.button("Start", icon="play_arrow").props(
                                    "color=blue no-caps disable").classes("toolbar-button")
                                ui.button("Stop", icon="stop").props(
                                    "color=deep-orange no-caps disable").classes("toolbar-button")
                                ui.button("Hold", icon="pause").props(
                                    "outline color=dark no-caps disable").classes("toolbar-button")
                        ui.separator()
                        with ui.element("div").classes("metric-row"):
                            with ui.column().classes("metric gap-1"):
                                ui.label("Backend measured (simulation)").classes("metric-caption")
                                current_label = ui.label("—").classes("metric-value")
                            with ui.column().classes("metric gap-1"):
                                ui.label("Backend setpoint (simulation)").classes("metric-caption")
                                manual_target_label = ui.label("—").classes("metric-value")
                            with ui.column().classes("metric gap-1"):
                                ui.label("Backend reported state").classes("metric-caption")
                                status_label = ui.label("UNKNOWN").classes("status-pill")
                                quality_label = ui.label("Awaiting telemetry").classes("text-xs text-grey-7")
                        ui.separator()
                        with ui.element("div").classes("controls-line"):
                            with ui.column().classes("gap-1"):
                                ui.label("Verified capability range (view only)").classes("text-xs")
                                limits_label = ui.label("Waiting for backend capabilities")
                                ui.label("Start / Stop / Hold / setpoint locked until G04/G08-min")


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
                        _panel_title("show_chart", "Temperature Graph (Simulation)")
                        with ui.row().classes("items-center gap-2"):
                            range_toggle = ui.toggle(["1h", "6h", "12h", "24h"], value="6h").props(
                                "dense no-caps")
                            measured_cb = ui.checkbox("Measured", value=True).props("dense color=blue")
                            target_cb = ui.checkbox("Target", value=True).props("dense color=orange")
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
                        series = [sample for sample in service.recent_samples()
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
                    # G03-C owns editing; no competing browser-local editor.
                    # G02-B owns later full Dashboard cleanup.
                    with ui.column().classes("panel editor-panel").props('id="profile-editor"'):
                        with ui.row().classes("panel-head"):
                            _panel_title("edit_note", "Profile Editor")
                        ui.label(
                            "Profiles are stored in server-owned SQLite revisions. "
                            "Open Profiles to create, edit, import, export or review history."
                        ).classes("text-sm text-grey-7")
                        with ui.row().classes("gap-2 flex-wrap"):
                            ui.button("Open Profiles", icon="description",
                                      on_click=lambda: ui.navigate.to("/profiles")).props(
                                          "no-caps")
                            ui.button("Import CSV", icon="upload",
                                      on_click=lambda: ui.navigate.to("/profiles")).props(
                                          "outline no-caps")
                            ui.button("Export CSV", icon="download",
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
        view = service.view()
        identity = view.identity
        backend_label.set_text(
            f"● SIMULATION · {view.quality.value}" if identity is None or identity.is_simulation
            else f"● READ ONLY · {view.quality.value}"
        )
        backend_id_label.set_text(
            f"Backend: {identity.backend_id} · {view.chamber_id}" if identity
            else f"Backend: awaiting status · {view.chamber_id}"
        )
        current_label.set_text(
            f"{view.measured_temperature_c:.1f} °C"
            if view.measured_temperature_c is not None else "— (unverified)"
        )
        manual_target_label.set_text(
            f"{view.setpoint_temperature_c:.1f} °C"
            if view.setpoint_temperature_c is not None else "— (unverified)"
        )
        status_label.set_text(view.operation_state.value)
        quality_label.set_text(
            view.error or f"Quality: {view.quality.value} · {view.sampled_at_utc}"
        )
        limits_label.set_text(
            f"{view.capabilities.temperature_min_c:g} to "
            f"{view.capabilities.temperature_max_c:g} °C"
            if view.capabilities else "Capability data unavailable"
        )
        if view.capabilities:
            chart.options["yAxis"]["min"] = view.capabilities.temperature_min_c - 10
            chart.options["yAxis"]["max"] = view.capabilities.temperature_max_c + 10
        step_indicator.set_text("Draft")
        progress.value = 0
        progress_label.set_text("0%")
        active_name.set_text("Draft: " + state.profile_name)
        clock_label.set_text(datetime.now().strftime("%b %d, %Y %H:%M"))
        update_chart()
        recent = service.recent_samples()[-12:]
        live_table.update_rows([{
            "id": str(index), "time": s.time_utc.astimezone().strftime("%H:%M:%S"),
            "measured": f"{s.measured_c:.1f}",
            "target": f"{s.target_c:.1f}" if s.target_c is not None else "—",
            "status": "SIMULATED" if identity is None or identity.is_simulation else "READ ONLY",
        } for index, s in enumerate(recent)])
        log_table.update_rows(list(state.logs))

    ui.timer(1.0, refresh, immediate=False)
    refresh()



# G03-C Profiles route, independently owned by the persistent editor workstream.
from .pages import profiles as _profile_editor_page  # noqa: E402,F401

def run() -> None:
    # Fail safe: localhost-only until authentication / network controls exist.
    ui.run(title="Climate Chamber — server simulation", host="127.0.0.1",
           port=8080, reload=False, show=False)


if __name__ == "__main__":
    run()
