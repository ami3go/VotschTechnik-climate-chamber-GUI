"""G02-A NiceGUI dashboard backed by the server-owned chamber service.

Runtime bootstrap is FakeBackend ONLY. This page can read normalized status and
capabilities but does not issue any chamber commands. Profile drafts are local
editor inputs, never a browser-owned chamber simulator or execution engine.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from nicegui import ui

from chamber_web.bootstrap import get_dashboard_service
from chamber_web.domain.chamber import OperationState, ReadingQuality
from chamber_web.model import (
    Step, default_steps, export_profile_csv, import_profile_csv,
)
from chamber_web.services.dashboard import DashboardView

CSS = (Path(__file__).parent / "assets" / "style.css").read_text(encoding="utf-8")
ui.add_css(CSS, shared=True)


def _columns(columns: list[tuple[str, str]]) -> list[dict]:
    return [{"name": field, "label": title, "field": field, "align": "left"}
            for field, title in columns]


def _panel_title(icon: str, title: str) -> None:
    with ui.row().classes("items-center gap-2"):
        ui.icon(icon, color="blue-grey-10").classes("text-2xl")
        ui.label(title).classes("panel-heading")


def _temperature(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} °C"


@ui.page("/")
async def dashboard() -> None:
    service = get_dashboard_service()
    chamber_id = service.chamber_id
    initial = await service.read_async(chamber_id)
    caps = initial.capabilities
    draft_steps = default_steps()
    draft_name = "New Temperature Profile"

    def scroll_to(section: str) -> None:
        # Fixed IDs only; no user-controlled JavaScript.
        ui.run_javascript(
            f"document.getElementById({section!r})?.scrollIntoView("
            "{behavior:'smooth',block:'start'})"
        )

    def export_csv() -> None:
        try:
            ui.download.content(
                export_profile_csv(draft_steps), "temperature_profile.csv", "text/csv"
            )
        except ValueError as exc:
            ui.notify(str(exc), color="negative")

    async def import_csv(event) -> None:
        nonlocal draft_steps
        try:
            draft_steps = import_profile_csv(await event.file.text())
        except (ValueError, UnicodeError, TypeError, OverflowError) as exc:
            ui.notify(f"Invalid CSV: {exc}", color="negative")
            return
        editor_rows.refresh()
        import_dialog.close()
        ui.notify("Draft imported (not saved or runnable)", color="positive")

    def new_profile() -> None:
        nonlocal draft_steps, draft_name
        draft_steps = default_steps()
        draft_name = "New Temperature Profile"
        name_input.value = draft_name
        editor_rows.refresh()

    def add_step() -> None:
        draft_steps.append(Step(25, 5, 2, 600, "New step"))
        editor_rows.refresh()

    def duplicate_step() -> None:
        if draft_steps:
            step = draft_steps[-1]
            draft_steps.append(Step(step.target, step.ramp, step.tolerance,
                                    step.dwell, step.description, step.enabled))
            editor_rows.refresh()

    def delete_step(step: Step) -> None:
        if len(draft_steps) <= 1:
            ui.notify("A draft needs at least one step", color="warning")
            return
        draft_steps.remove(step)
        editor_rows.refresh()

    def set_field(step: Step, field: str, value) -> None:
        if value is None:
            return
        if field == "description":
            step.description = str(value)
        elif field == "enabled":
            step.enabled = bool(value)
        else:
            try:
                number = float(value)
                if not math.isfinite(number) or (field == "dwell" and not number.is_integer()):
                    raise ValueError("non-finite or non-integral value")
                setattr(step, field, int(number) if field == "dwell" else number)
            except (ValueError, OverflowError, TypeError) as exc:
                ui.notify(f"Invalid {field}: {exc}", color="negative")

    with ui.dialog() as import_dialog:
        with ui.card().classes("w-96"):
            ui.label("Import profile CSV").classes("text-lg font-bold")
            ui.label("Draft only — not persisted or executable").classes("text-xs text-orange-9")
            ui.upload(on_upload=import_csv, auto_upload=True, max_file_size=1_000_000).props(
                "accept=.csv").classes("w-full")
            ui.button("Close", on_click=import_dialog.close).props("flat")

    with ui.dialog() as settings_dialog:
        with ui.card().classes("w-96"):
            ui.label("Chamber capabilities (read-only)").classes("text-lg font-bold")
            ui.label(
                f"Reported adapter range (not HIL-approved): {caps.temperature_min_c:g} to "
                f"{caps.temperature_max_c:g} °C"
            )
            ui.label(f"Start/Stop capability: {caps.supports_start_stop}")
            ui.label(f"Ramp-up capability: {caps.supports_ramp_up}")
            ui.label(f"Ramp-down capability: {caps.supports_ramp_down}")
            ui.label("Connections and hardware controls are disabled in G02-A.").classes(
                "text-sm text-orange-9"
            )
            ui.button("Close", on_click=settings_dialog.close).props("flat")

    with ui.dialog() as history_dialog:
        with ui.card().classes("w-96"):
            ui.label("Run History").classes("text-lg font-bold")
            ui.label("Run execution and durable recording are planned for G06/G07.")
            ui.label("Dashboard observations are not execution records.").classes(
                "text-orange-9"
            )
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
                with ui.button(on_click=callback, icon=icon).props(
                    "flat no-caps align=left"
                ) as button:
                    ui.label(title).classes("nav-text")
                if index == 0:
                    button.classes("nav-active")
            ui.label("Climate Chamber | SIMULATION\nServer-side FakeBackend only").classes(
                "side-note whitespace-pre-line")

        with ui.column().classes("main-area gap-0"):
            with ui.row().classes("topbar"):
                with ui.column().classes("gap-0"):
                    ui.label("Climate Chamber").classes("top-title")
                    ui.label("Test Control Platform").classes("top-subtitle")
                with ui.column().classes("items-end gap-0"):
                    identity_label = ui.label("").classes("demo-status")
                    chamber_label = ui.label("").classes("text-xs text-grey-4")
                    clock_label = ui.label("").classes("text-xs text-grey-4")

            with ui.column().classes("dashboard gap-0").props('id="dashboard-content"'):
                ui.label(
                    "SIMULATION ONLY — server-side backend status. "
                    "No profile execution, physical START, STOP or setpoint commands."
                ).classes("demo-banner w-full")
                with ui.element("div").classes("top-grid"):
                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("power_settings_new", "Chamber Control")
                            with ui.row().classes("gap-1"):
                                ui.button("Start", icon="play_arrow").props(
                                    "color=blue no-caps disable"
                                ).tooltip("Disabled until controller and authorization gates")
                                ui.button("Stop", icon="stop").props(
                                    "color=deep-orange no-caps disable"
                                ).tooltip("Not a certified hardware emergency STOP")
                                ui.button("Hold", icon="pause").props(
                                    "outline color=dark no-caps disable"
                                ).tooltip("Hold not implemented")
                        ui.separator()
                        with ui.element("div").classes("metric-row"):
                            with ui.column().classes("metric gap-1"):
                                ui.label("Measured temperature").classes("metric-caption")
                                current_label = ui.label("—").classes("metric-value")
                            with ui.column().classes("metric gap-1"):
                                ui.label("Backend setpoint").classes("metric-caption")
                                target_label = ui.label("—").classes("metric-value")
                            with ui.column().classes("metric gap-1"):
                                ui.label("Operation state").classes("metric-caption")
                                status_label = ui.label("UNKNOWN").classes("status-pill")
                                quality_label = ui.label("").classes("text-xs text-grey-7")
                        ui.separator()
                        with ui.element("div").classes("controls-line"):
                            with ui.column().classes("gap-1"):
                                ui.label("Set temperature (°C)").classes("text-xs")
                                ui.number(
                                    value=initial.snapshot.setpoint_temperature_c,
                                    min=caps.temperature_min_c,
                                    max=caps.temperature_max_c,
                                    step=0.5,
                                ).props("outlined dense disable").classes("w-full")
                                ui.label("Command disabled (G04/G08-min pending)").classes(
                                    "text-xs text-orange-9"
                                )
                            with ui.column().classes("gap-1"):
                                ui.label("Gradient (°C/min)").classes("text-xs")
                                ui.label(
                                    "Supported" if (caps.supports_ramp_up
                                                    or caps.supports_ramp_down)
                                    else "Not supported by adapter"
                                ).classes("text-xs text-grey-7")

                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("description", "Active Profile")
                        ui.label("No server-side profile is running").classes("font-bold")
                        ui.label("Profile execution is deferred to G06").classes(
                            "text-xs text-grey-7"
                        )
                        ui.label("The editor below produces local, non-persisted drafts.")

                with ui.column().classes("panel chart-panel"):
                    with ui.row().classes("panel-head"):
                        _panel_title("show_chart", "Temperature Graph (backend observations)")
                        ui.label("Not a durable run log").classes("text-xs text-grey-7")
                    chart = ui.echart({
                        "animation": False,
                        "grid": {"left": 58, "right": 18, "top": 18, "bottom": 34},
                        "tooltip": {"trigger": "axis"},
                        "legend": {"show": True},
                        "xAxis": {"type": "category", "boundaryGap": False, "data": []},
                        "yAxis": {"type": "value", "name": "°C",
                                  "min": caps.temperature_min_c - 10,
                                  "max": caps.temperature_max_c + 10},
                        "series": [
                            {"name": "Measured", "type": "line", "symbol": "none",
                             "data": [], "lineStyle": {"color": "#147bd3"}},
                            {"name": "Setpoint", "type": "line", "symbol": "none",
                             "data": [], "lineStyle": {"color": "#ef8429"}},
                        ],
                    }).classes("chart-box")

                with ui.element("div").classes("bottom-grid"):
                    with ui.column().classes("panel editor-panel").props('id="profile-editor"'):
                        with ui.row().classes("panel-head"):
                            _panel_title("edit_note", "Profile Editor (draft only)")
                            with ui.row().classes("gap-1"):
                                ui.button("New", icon="add", on_click=new_profile).props(
                                    "outline no-caps"
                                ).classes("toolbar-button")
                                ui.button("Import CSV", icon="upload",
                                          on_click=import_dialog.open).props(
                                              "outline no-caps").classes("toolbar-button")
                                ui.button("Export CSV", icon="download",
                                          on_click=export_csv).props(
                                              "outline no-caps").classes("toolbar-button")
                        with ui.row().classes("items-center w-full"):
                            ui.label("Profile Name").classes("text-xs")
                            name_input = ui.input(
                                value=draft_name,
                                on_change=lambda e: None,  # name persistence belongs to G03-C
                            ).props("outlined dense").classes("flex-grow")

                        @ui.refreshable
                        def editor_rows():
                            with ui.column().classes("edit-scroll gap-0"):
                                with ui.element("div").classes("edit-row header"):
                                    for header in ("#", "Use", "Target °C", "Ramp", "Tolerance",
                                                   "Dwell (s)", "Description", "Delete"):
                                        ui.label(header)
                                for index, step in enumerate(draft_steps):
                                    with ui.element("div").classes("edit-row"):
                                        ui.label(str(index + 1))
                                        ui.checkbox(
                                            value=step.enabled,
                                            on_change=lambda e, s=step:
                                            set_field(s, "enabled", e.value),
                                        ).props("dense")
                                        for field, amount in (
                                            ("target", step.target),
                                            ("ramp", step.ramp),
                                            ("tolerance", step.tolerance),
                                            ("dwell", step.dwell),
                                        ):
                                            ui.number(
                                                value=amount,
                                                on_change=lambda e, s=step, f=field:
                                                set_field(s, f, e.value),
                                            ).props("dense borderless")
                                        ui.input(
                                            value=step.description,
                                            on_change=lambda e, s=step:
                                            set_field(s, "description", e.value),
                                        ).props("dense borderless")
                                        ui.button(
                                            icon="delete_outline",
                                            on_click=lambda s=step: delete_step(s),
                                        ).props("flat dense round color=grey-7")
                        editor_rows()
                        with ui.row().classes("gap-2 mt-3"):
                            ui.button("Add Step", icon="add", on_click=add_step).props(
                                "outline no-caps"
                            ).classes("toolbar-button")
                            ui.button("Duplicate Last", icon="content_copy",
                                      on_click=duplicate_step).props(
                                          "outline no-caps").classes("toolbar-button")
                        ui.label("Drafts cannot be executed or persisted in G02-A").classes(
                            "text-xs text-orange-9"
                        )

                    with ui.column().classes("panel"):
                        with ui.row().classes("panel-head"):
                            _panel_title("storage", "Recent Observations")
                        live_table = ui.table(
                            columns=_columns([("time", "Time"), ("measured", "Measured"),
                                              ("target", "Target")]),
                            rows=[], row_key="id", pagination=0,
                        ).props("dense flat hide-bottom separator=horizontal").classes(
                            "small-table w-full"
                        )

                    with ui.column().classes("panel").props('id="event-log"'):
                        with ui.row().classes("panel-head"):
                            _panel_title("list_alt", "Status / Logs")
                        error_label = ui.label("").classes("text-sm text-orange-9")
                        sample_label = ui.label("").classes("text-xs text-grey-7")
                        ui.label("Persistent event logging is deferred to G07").classes(
                            "text-xs text-grey-7"
                        )

    def display(view: DashboardView) -> None:
        snapshot = view.snapshot
        identity = snapshot.identity
        identity_label.set_text(
            f"{'SIMULATION' if identity.is_simulation else 'DEVICE'} · "
            f"{identity.manufacturer} {identity.model}"
        )
        chamber_label.set_text(f"Chamber ID: {identity.chamber_id}")
        current_label.set_text(_temperature(snapshot.measured_temperature_c))
        target_label.set_text(_temperature(snapshot.setpoint_temperature_c))
        status_label.set_text(snapshot.operation_state.value)
        quality_label.set_text(f"Reading: {snapshot.quality.value}")
        error_label.set_text(view.error or (
            "Status UNKNOWN / FAULT — do not infer device state"
            if snapshot.operation_state in (OperationState.UNKNOWN, OperationState.FAULT)
            or snapshot.quality is not ReadingQuality.GOOD else ""
        ))
        sample_label.set_text(
            f"Last sample: {snapshot.sampled_at_utc.isoformat()}"
            if snapshot.sampled_at_utc else "No verified current sample"
        )
        clock_label.set_text(datetime.now().strftime("%b %d, %Y %H:%M"))
        samples = view.observations
        chart.options["xAxis"]["data"] = [
            obs.sampled_at_utc.astimezone().strftime("%H:%M:%S") for obs in samples
        ]
        chart.options["series"][0]["data"] = [
            obs.measured_temperature_c for obs in samples
        ]
        chart.options["series"][1]["data"] = [
            obs.setpoint_temperature_c for obs in samples
        ]
        chart.update()
        live_table.update_rows([
            {
                "id": str(i),
                "time": obs.sampled_at_utc.astimezone().strftime("%H:%M:%S"),
                "measured": _temperature(obs.measured_temperature_c),
                "target": _temperature(obs.setpoint_temperature_c),
            }
            for i, obs in enumerate(reversed(samples[-12:]))
        ])

    async def refresh() -> None:
        # The browser observes a shared service; it never owns chamber state.
        view = await service.read_async(chamber_id)
        display(view)

    display(initial)
    ui.timer(1.0, refresh, immediate=False)


def run() -> None:
    # No authentication or safety controller yet; loopback only, FakeBackend only.
    ui.run(title="Climate Chamber — SIMULATION", host="127.0.0.1",
           port=8080, reload=False, show=False)


if __name__ == "__main__":
    run()
