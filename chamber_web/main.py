"""NiceGUI read-only Dashboard bound to the server-owned generic service.

G02-A exposes no chamber mutations, no page-owned chamber state, and no hardware.
The legacy CSV editor remains a browser-local unpersisted draft until G03-C.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from pathlib import Path

from nicegui import app, ui

from .bootstrap import create_demo_dashboard_service
from .ui_pages import register_pages, render_navigation
from .ui_state import project_capabilities, project_telemetry, safe_view

from .model import (
    MAX_TEMP, MIN_TEMP, Step, default_steps,
    export_profile_csv, import_profile_csv,
)


@dataclass
class ProfileDraft:
    """Unpersisted per-page profile editing data, not chamber/control state."""
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
    service = get_dashboard_service()
    # Local drafts are not executable runs or chamber state.
    state = ProfileDraft()

    def warn_while_running() -> bool:
        # No runnable profile engine exists in G02-A.
        return False

    def scroll_to(section: str) -> None:
        # Section names are fixed in this module, never user-controlled.
        ui.run_javascript(
            f"document.getElementById({section!r})?.scrollIntoView("
            "{behavior:'smooth',block:'start'})"
        )

    def export_csv() -> None:
        try:
            content = export_profile_csv(state.steps)
            ui.download.content(content, "temperature_profile.csv", "text/csv")
            state.log("Profile exported")
        except ValueError as exc:
            ui.notify(str(exc), color="negative")

    async def import_csv(event) -> None:
        if warn_while_running():
            return
        try:
            content = await event.file.text()
            loaded = import_profile_csv(content)
        except (ValueError, UnicodeError, TypeError, OverflowError) as exc:
            ui.notify(f"Invalid CSV: {exc}", color="negative")
            return
        state.steps = loaded
        state.step_index = 0
        state.run_steps = []
        state.completed = False
        state.log(f"Imported {len(loaded)} profile steps")
        editor_rows.refresh()
        step_overview.refresh()
        import_dialog.close()
        ui.notify("Profile imported", color="positive")

    def new_profile() -> None:
        if warn_while_running():
            return
        state.steps = default_steps()
        state.profile_name = "New Temperature Profile"
        state.run_steps = []
        state.step_index = 0
        state.completed = False
        name_input.value = state.profile_name
        editor_rows.refresh()
        step_overview.refresh()
        state.log("Created new draft profile")

    def add_step() -> None:
        if warn_while_running():
            return
        state.steps.append(Step(25, 5, 2, 600, "New step"))
        editor_rows.refresh()
        step_overview.refresh()

    def duplicate_step() -> None:
        if warn_while_running():
            return
        step = state.steps[-1]
        state.steps.append(Step(step.target, step.ramp, step.tolerance,
                                step.dwell, step.description, step.enabled))
        editor_rows.refresh()
        step_overview.refresh()

    def delete_step(step: Step) -> None:
        if warn_while_running():
            return
        if len(state.steps) <= 1:
            ui.notify("A profile needs at least one step", color="warning")
            return
        state.steps.remove(step)
        state.step_index = min(state.step_index, len(state.steps) - 1)
        editor_rows.refresh()
        step_overview.refresh()

    def set_field(step: Step, field: str, value) -> None:
        if warn_while_running():
            return
        if value is None:
            return
        if field == "description":
            setattr(step, field, str(value))
        elif field == "enabled":
            setattr(step, field, bool(value))
        else:
            try:
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("non-finite value")
                if field == "dwell" and not number.is_integer():
                    raise ValueError("Dwell must be whole seconds")
                setattr(step, field, int(number) if field == "dwell" else number)
            except (ValueError, TypeError, OverflowError) as exc:
                ui.notify(f"Invalid {field}: {exc}", color="negative")
                return
        step_overview.refresh()

    with ui.dialog() as import_dialog:
        with ui.card().classes("w-96"):
            ui.label("Import profile CSV").classes("text-lg font-bold")
            ui.label("Required columns: target, ramp, tolerance, dwell, description, enabled").classes(
                "text-xs text-grey-7")
            ui.upload(on_upload=import_csv, auto_upload=True, max_file_size=1_000_000).props(
                "accept=.csv").classes("w-full")
            ui.button("Close", on_click=import_dialog.close).props("flat")

    with ui.row().classes("app-shell no-wrap"):
        with ui.column().classes("sidebar gap-1"):
            render_navigation("/")

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
                                capability_detail_label = ui.label("Capabilities unverified").classes("text-xs text-orange-9")
                                ramp_detail_label = ui.label("Gradient support unverified").classes("text-xs text-grey-7")


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
                    with ui.column().classes("panel editor-panel").props('id="profile-editor"'):
                        with ui.row().classes("panel-head"):
                            _panel_title("edit_note", "Profile Editor")
                            with ui.row().classes("gap-1"):
                                ui.button("New", icon="add", on_click=new_profile).props(
                                    "outline no-caps").classes("toolbar-button")
                                ui.button("Import CSV", icon="upload", on_click=import_dialog.open).props(
                                    "outline no-caps").classes("toolbar-button")
                                ui.button("Export CSV", icon="download", on_click=export_csv).props(
                                    "outline no-caps").classes("toolbar-button")
                        with ui.row().classes("items-center w-full"):
                            ui.label("Profile Name").classes("text-xs")
                            name_input = ui.input(value=state.profile_name,
                                                  on_change=lambda e: setattr(
                                                      state, "profile_name", e.value)).props(
                                                          "outlined dense").classes("flex-grow")

                        @ui.refreshable
                        def editor_rows():
                            with ui.column().classes("edit-scroll gap-0"):
                                with ui.element("div").classes("edit-row header"):
                                    for column in ("#", "Use", "Target °C", "Ramp", "Tolerance",
                                                   "Dwell (s)", "Description", "Delete"):
                                        ui.label(column)
                                for index, step in enumerate(state.steps):
                                    with ui.element("div").classes("edit-row"):
                                        ui.label(str(index + 1))
                                        ui.checkbox(value=step.enabled,
                                                    on_change=lambda e, s=step: set_field(
                                                        s, "enabled", e.value)).props("dense")
                                        for field, amount in (("target", step.target),
                                                              ("ramp", step.ramp),
                                                              ("tolerance", step.tolerance),
                                                              ("dwell", step.dwell)):
                                            ui.number(value=amount,
                                                      on_change=lambda e, s=step, f=field:
                                                      set_field(s, f, e.value)).props(
                                                          "dense borderless")
                                        ui.input(value=step.description,
                                                 on_change=lambda e, s=step:
                                                 set_field(s, "description", e.value)).props(
                                                     "dense borderless")
                                        ui.button(icon="delete_outline",
                                                  on_click=lambda s=step: delete_step(s)).props(
                                                      "flat dense round color=grey-7")
                        editor_rows()
                        with ui.row().classes("gap-2 mt-3"):
                            ui.button("Add Step", icon="add", on_click=add_step).props(
                                "outline no-caps").classes("toolbar-button")
                            ui.button("Duplicate Last", icon="content_copy", on_click=duplicate_step).props(
                                "outline no-caps").classes("toolbar-button")
                        ui.label("Local draft only: not persisted or executable. G03-C adds revision editing.").classes(
                            "text-xs text-grey-7")

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
        capability_detail_label.set_text(capability.controls_locked_reason)
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
            "status": "SIMULATED" if identity is None or identity.is_simulation else "READ ONLY",
        } for index, s in enumerate(recent)])
        log_table.update_rows(list(state.logs))

    ui.timer(1.0, refresh, immediate=False)
    refresh()


def run() -> None:
    # Fail safe: localhost-only until authentication / network controls exist.
    ui.run(title="Climate Chamber — server simulation", host="127.0.0.1",
           port=8080, reload=False, show=False)


if __name__ == "__main__":
    run()
