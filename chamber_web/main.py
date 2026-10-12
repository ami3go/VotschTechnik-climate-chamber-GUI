"""NiceGUI dashboard scaffold based on the supplied Visteon mockup.

DEMO ONLY. Physical chamber integration must use VotschTechnikClimateChamber
in a separate server-side controller and is deliberately not present here.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

from nicegui import ui

from .model import (
    MAX_TEMP, MIN_TEMP, DemoChamber, Step, default_steps,
    export_profile_csv, import_profile_csv,
)

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
    # Per-browser simulation is deliberate. No shared physical controller
    # or server-side autonomous run is claimed by this initial UI scaffold.
    state = DemoChamber()

    def warn_while_running() -> bool:
        if state.running:
            ui.notify("Stop the demo before editing profile steps", color="warning")
            return True
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

    def start_demo() -> None:
        try:
            state.start()
            editor_rows.refresh()
            step_overview.refresh()
            ui.notify("Simulation started (NO chamber connected)", color="warning")
        except ValueError as exc:
            ui.notify(f"Cannot start: {exc}", color="negative")

    def stop_demo() -> None:
        state.stop()
        editor_rows.refresh()
        step_overview.refresh()

    def hold_demo() -> None:
        state.hold()

    def set_manual_target(value) -> None:
        if value is None:
            return
        if state.running:
            ui.notify("Manual temperature disabled during demo profile", color="warning")
            return
        value = float(value)
        if not math.isfinite(value) or not MIN_TEMP <= value <= MAX_TEMP:
            ui.notify("Temperature is outside configured limits", color="negative")
            return
        state.manual_target = value
        manual_target_label.set_text(f"{value:.1f} °C")

    with ui.dialog() as import_dialog:
        with ui.card().classes("w-96"):
            ui.label("Import profile CSV").classes("text-lg font-bold")
            ui.label("Required columns: target, ramp, tolerance, dwell, description, enabled").classes(
                "text-xs text-grey-7")
            ui.upload(on_upload=import_csv, auto_upload=True, max_file_size=1_000_000).props(
                "accept=.csv").classes("w-full")
            ui.button("Close", on_click=import_dialog.close).props("flat")

    with ui.dialog() as settings_dialog:
        with ui.card().classes("w-96"):
            ui.label("Simulation Settings").classes("text-lg font-bold")
            ui.label("Simulated seconds per real second")
            ui.select([1, 5, 10, 20, 60], value=state.speed,
                      on_change=lambda e: setattr(state, "speed", int(e.value))).classes("w-full")
            ui.label("DEMO ONLY: no chamber IP or device connection is available in this phase.").classes(
                "text-sm text-orange-9")
            ui.label(f"Demo temperature limits: {MIN_TEMP:g} to {MAX_TEMP:g} °C")
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
                ("description", "Profiles", lambda: scroll_to("profile-editor")),
                ("history", "Run History", history_dialog.open),
                ("list_alt", "Logs", lambda: scroll_to("event-log")),
                ("settings", "Settings", settings_dialog.open),
            ]):
                with ui.button(on_click=callback, icon=icon).props("flat no-caps align=left") as button:
                    ui.label(title).classes("nav-text")
                if index == 0:
                    button.classes("nav-active")
            ui.label("Climate Chamber | DEMO\nNo physical device connected").classes(
                "side-note whitespace-pre-line")

        with ui.column().classes("main-area gap-0"):
            with ui.row().classes("topbar"):
                with ui.column().classes("gap-0"):
                    ui.label("Climate Chamber").classes("top-title")
                    ui.label("Test Control Platform").classes("top-subtitle")
                with ui.column().classes("items-end gap-0"):
                    ui.label("● SIMULATION · DISCONNECTED").classes("demo-status")
                    ui.label("No chamber IP configured").classes("text-xs text-grey-4")
                    clock_label = ui.label("").classes("text-xs text-grey-4")

            with ui.column().classes("dashboard gap-0").props('id="dashboard-content"'):
                ui.label(
                    "DEMO MODE — simulated temperatures only. Start, Stop and Hold do not control real hardware."
                ).classes("demo-banner w-full")
                with ui.element("div").classes("top-grid"):
                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("power_settings_new", "Chamber Control")
                            with ui.row().classes("gap-1"):
                                ui.button("Start", icon="play_arrow", on_click=start_demo).props(
                                    "color=blue no-caps").classes("toolbar-button")
                                ui.button("Stop", icon="stop", on_click=stop_demo).props(
                                    "color=deep-orange no-caps").classes("toolbar-button")
                                ui.button("Hold", icon="pause", on_click=hold_demo).props(
                                    "outline color=dark no-caps").classes("toolbar-button")
                        ui.separator()
                        with ui.element("div").classes("metric-row"):
                            with ui.column().classes("metric gap-1"):
                                ui.label("Simulated temperature").classes("metric-caption")
                                current_label = ui.label("23.4 °C").classes("metric-value")
                            with ui.column().classes("metric gap-1"):
                                ui.label("Manual target (demo)").classes("metric-caption")
                                manual_target_label = ui.label("25.0 °C").classes("metric-value")
                            with ui.column().classes("metric gap-1"):
                                ui.label("Simulation status").classes("metric-caption")
                                status_label = ui.label("Stopped").classes("status-pill")
                                ui.label("Hardware: disconnected").classes("text-xs text-grey-7")
                        ui.separator()
                        with ui.element("div").classes("controls-line"):
                            with ui.column().classes("gap-1"):
                                ui.label("Set Temperature (°C)").classes("text-xs")
                                temp_number = ui.number(value=25, min=MIN_TEMP, max=MAX_TEMP,
                                                        step=0.5,
                                                        on_change=lambda e: set_manual_target(e.value)).props(
                                                            "outlined dense").classes("w-full")
                            ui.slider(min=MIN_TEMP, max=MAX_TEMP, value=25,
                                      on_change=lambda e: set_manual_target(e.value)).props("color=blue")
                            with ui.column().classes("gap-1"):
                                ui.label("Demo ramp (°C/min)").classes("text-xs")
                                ui.label("Set in profile table").classes("text-xs text-grey-7")

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
                            elapsed_label = ui.label("Elapsed: 0:00:00")
                            ui.label("Cycle: 1 / 1 • Simulation").classes("text-xs")

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
                        # Demo samples use real timestamps. The control affects
                        # the visible time window but not simulation speed.
                        hours = {"1h": 1, "6h": 6, "12h": 12, "24h": 24}[range_toggle.value]
                        threshold = datetime.now().astimezone() - timedelta(hours=hours)
                        series = [row for row in state.samples
                                  if datetime.fromisoformat(row["time"]) >= threshold]
                        chart.options["xAxis"]["data"] = [
                            datetime.fromisoformat(row["time"]).astimezone().strftime("%H:%M:%S")
                            for row in series
                        ]
                        chart.options["series"][0]["data"] = [
                            row["measured"] for row in series] if measured_cb.value else []
                        chart.options["series"][1]["data"] = [
                            row["target"] for row in series] if target_cb.value else []
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
                        ui.label("Editor values are only drafts; this demo has no hardware connection.").classes(
                            "text-xs text-grey-7")

                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("storage", "Live Data")
                        live_table = ui.table(
                            columns=_columns([("time", "Time"), ("measured", "Measured"),
                                              ("target", "Target"), ("status", "Phase")]),
                            rows=[], row_key="id", pagination=0).props(
                                "dense flat hide-bottom separator=horizontal").classes(
                                    "small-table w-full")

                    with ui.column().classes("panel").props('id="event-log"'):
                        with ui.row().classes("panel-head"):
                            _panel_title("list_alt", "Event Log")
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

    previous_running = [state.running, state.step_index]

    def refresh() -> None:
        state.tick()
        current_label.set_text(f"{state.current:.1f} °C")
        status_label.set_text(state.status)
        step_indicator.set_text(
            f"Step {state.step_index + 1} of {len(state.active_steps)}"
            if state.run_steps else "Draft")
        progress.value = state.progress
        progress_label.set_text(f"{state.progress:.0%}")
        active_name.set_text("Profile: " + state.profile_name)
        elapsed_label.set_text("Elapsed: " + str(timedelta(seconds=int(state.elapsed))))
        clock_label.set_text(datetime.now().strftime("%b %d, %Y %H:%M"))
        update_chart()
        if previous_running != [state.running, state.step_index]:
            step_overview.refresh()
            editor_rows.refresh()
            previous_running[:] = [state.running, state.step_index]
        live_table.update_rows(list(state.readings))
        log_table.update_rows(list(state.logs))

    ui.timer(1.0, refresh, immediate=False)
    refresh()


def run() -> None:
    # Fail safe: localhost-only until authentication / network controls exist.
    ui.run(title="Climate Chamber — DEMO", host="127.0.0.1",
           port=8080, reload=False, show=False)


if __name__ == "__main__":
    run()
