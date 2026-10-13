"""G02-B read-only NiceGUI routes. No vendor imports, command calls, or local logs."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timezone
from typing import Callable


from nicegui import ui

from chamber_web.security.nicegui import require_authenticated_page

from chamber_web.services.web_read_models import (
    EventReader, HistoryReader, RecordPage, UnavailableEventReader,
    UnavailableHistoryReader, bounded_search,
)
from chamber_web.ui_state import project_capabilities, project_telemetry, safe_view

# These are public navigation destinations, NOT permissions for control.
NAV_ITEMS = (
    ("dashboard", "Dashboard", "/"),
    ("description", "Profiles", "/profiles"),
    ("history", "Run History", "/history"),
    ("list_alt", "Logs", "/logs"),
    ("settings", "Settings", "/settings"),
)


@dataclass(frozen=True)
class NavigationContext:
    """G08-min integration point; only a trusted server session resolver may set it."""
    authenticated: bool = False
    role: str | None = None
    permitted_routes: frozenset[str] = frozenset(
        {"/", "/profiles", "/history", "/logs", "/settings"}
    )

    @property
    def label(self) -> str:
        if not self.authenticated:
            return "Access: unauthenticated · read-only"
        return f"Role: {self.role or 'unverified'} · controls locked"


# Only Python composition/bootstrap can set this resolver; no UI handler may modify it.
_navigation_resolver: Callable[[], NavigationContext] | None = None


def install_navigation_resolver(resolver: Callable[[], NavigationContext]) -> None:
    """G08-min integration seam; the resolver must verify the current server session."""
    if not callable(resolver):
        raise TypeError("Navigation resolver must be callable")
    global _navigation_resolver
    _navigation_resolver = resolver


def navigation_context() -> NavigationContext:
    if _navigation_resolver is None:
        return NavigationContext()
    try:
        resolved = _navigation_resolver()
    except Exception:
        return NavigationContext(permitted_routes=frozenset())
    return resolved if isinstance(resolved, NavigationContext) else NavigationContext(
        permitted_routes=frozenset())


def visible_navigation_routes(context: NavigationContext) -> tuple[str, ...]:
    """Cosmetic filter only — server-side G08 guards remain mandatory."""
    return tuple(url for _, _, url in NAV_ITEMS if url in context.permitted_routes)


def render_navigation(active: str, *, context: NavigationContext | None = None) -> None:
    context = context or navigation_context()
    ui.label("Visteon").classes("brand")
    allowed = visible_navigation_routes(context)
    for icon, title, destination in NAV_ITEMS:
        if destination not in allowed:
            continue
        with ui.button(icon=icon, on_click=lambda url=destination: ui.navigate.to(url)).props(
            f'flat no-caps align=left aria-label="{title}" title="{title}"'
        ).classes("nav-active" if destination == active else ""):
            ui.label(title).classes("nav-text")
    ui.label("Climate Chamber | G02-B\nServer-side simulation only").classes(
        "side-note whitespace-pre-line"
    ).props('aria-label="Simulated chamber status"')
    ui.label(context.label).classes("side-note access-label")


def render_header(service, *, title: str = "Climate Chamber"):
    with ui.row().classes("topbar"):
        with ui.column().classes("gap-0"):
            ui.label(title).classes("top-title")
            ui.label("Test Control Platform").classes("top-subtitle")
        with ui.column().classes("items-end gap-0"):
            mode_label = ui.label("SIMULATION · ERROR").classes("demo-status")
            identity_label = ui.label("Identity unavailable").classes("text-xs text-grey-4")
            timestamp_label = ui.label("Sample: unavailable").classes("text-xs text-grey-4")

    def update_header() -> None:
        view = project_telemetry(safe_view(service))
        mode_label.set_text(f"● {view.mode} · {view.quality} · {view.operation}")
        identity_label.set_text(view.identity)
        timestamp_label.set_text(f"Sample: {view.sampled_utc}")

    update_header()
    return update_header


@contextmanager
def page_frame(active: str, service, *, title: str):
    with ui.row().classes("app-shell no-wrap"):
        with ui.column().classes("sidebar gap-1"):
            render_navigation(active)
        with ui.column().classes("main-area gap-0"):
            refresh_header = render_header(service, title=title)
            with ui.column().classes("dashboard gap-3"):
                banner = ui.label("Equipment state unverified — read only").classes(
                    "demo-banner w-full")
                yield
    def update_shell():
        if not require_authenticated_page(touch=False):
            return
        refresh_header()
        display = project_telemetry(safe_view(service))
        banner.set_text(f"{display.mode} / READ-ONLY — {display.quality} · "
                        "control commands locked; records come from server services.")
    update_shell()
    ui.timer(2.0, update_shell)


def _status_panel(page, *, empty_text: str):
    if not page.available:
        ui.icon("cloud_off", size="2em", color="orange-9")
        ui.label(page.detail or empty_text).classes("text-orange-9")
        ui.label("No run or event records have been fabricated.").classes("text-xs text-grey-7")
    elif not page.records:
        ui.icon("inbox", size="2em", color="blue-grey-6")
        ui.label(empty_text).classes("text-grey-7")


def register_pages(
    get_dashboard_service: Callable,
    *, history_reader: HistoryReader | None = None,
    event_reader: EventReader | None = None,
) -> None:
    """Composition root may inject G07 readers later, without vendor logic."""
    history = history_reader or UnavailableHistoryReader()
    events = event_reader or UnavailableEventReader()

    @ui.page("/profiles")
    def profiles_placeholder():
        if not require_authenticated_page():
            return
        service = get_dashboard_service()
        with page_frame("/profiles", service, title="Profiles"):
            with ui.column().classes("panel gap-2"):
                ui.label("Profiles editor — G03-C").classes("panel-heading")
                ui.label("The persisted Profiles editor is owned by G03-C and is not part of G02-B.")
                ui.label("The pre-existing local-only CSV draft remains on the Dashboard until migration.")
                ui.button("Open Dashboard draft", icon="arrow_back",
                          on_click=lambda: ui.navigate.to("/")).props("outline no-caps")

    @ui.page("/history")
    def history_page():
        if not require_authenticated_page():
            return
        service = get_dashboard_service()
        with page_frame("/history", service, title="Run History"):
            with ui.column().classes("panel gap-3"):
                ui.label("Run History").classes("panel-heading")
                ui.label("Server-recorded runs only · no data from the live chart cache").classes(
                    "text-xs text-grey-7")
                search = ui.input(label="Search recorded run ID or profile",
                                  placeholder="Search (up to 120 characters)").props(
                                      "outlined dense clearable").classes("w-full max-w-lg")
                status = ui.column().classes("gap-1")
                table = ui.table(columns=[
                    {"name": name, "label": label, "field": name, "align": "left"}
                    for name, label in (
                        ("run_id", "Run ID"), ("profile", "Profile · revision"),
                        ("operator", "Operator"), ("started", "Started (UTC)"),
                        ("ended", "Ended (UTC)"), ("outcome", "Outcome"))
                ], rows=[], row_key="run_id", pagination=15).props("flat bordered").classes(
                    "w-full small-table")

                def reload():
                    if not require_authenticated_page():
                        return
                    try:
                        page = history.list_runs(
                            service.chamber_id, search=bounded_search(search.value), limit=50)
                        rows = [{
                            "run_id": row.run_id,
                            "profile": f"{row.profile_name} · r{row.profile_revision}",
                            "operator": row.operator or "—",
                            "started": row.started_at_utc.astimezone(timezone.utc).isoformat(),
                            "ended": (row.ended_at_utc.astimezone(timezone.utc).isoformat()
                                      if row.ended_at_utc else "—"),
                            "outcome": row.outcome,
                        } for row in page.records if row.chamber_id == service.chamber_id][:50]
                    except Exception:
                        page = RecordPage(False, detail="Run history service failed; retry later.")
                        rows = []
                    status.clear()
                    with status:
                        _status_panel(page, empty_text="No recorded runs match this search.")
                    table.update_rows(rows)
                ui.button("Search", icon="search", on_click=reload).props("outline no-caps")
                reload()

    @ui.page("/logs")
    def logs_page():
        if not require_authenticated_page():
            return
        service = get_dashboard_service()
        with page_frame("/logs", service, title="Logs"):
            with ui.column().classes("panel gap-3"):
                ui.label("Persistent Event Logs").classes("panel-heading")
                ui.label("G07 event records and G08-min security audit integration pending").classes(
                    "text-xs text-grey-7")
                with ui.row().classes("items-center gap-3 w-full flex-wrap"):
                    severity = ui.select(["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                                         value="ALL", label="Severity").props("outlined dense")
                    search = ui.input(label="Filter recorded messages").props(
                        "outlined dense clearable").classes("min-w-48")
                    ui.button("Apply filters", icon="filter_list",
                              on_click=lambda: reload()).props("outline no-caps")
                status = ui.column().classes("gap-1")
                table = ui.table(columns=[
                    {"name": name, "label": label, "field": name, "align": "left"}
                    for name, label in (
                        ("timestamp", "Time (UTC)"), ("severity", "Severity"),
                        ("chamber", "Chamber"), ("operator", "Operator"),
                        ("run", "Run"), ("step", "Step"), ("message", "Message"))
                ], rows=[], row_key="id", pagination=15).props(
                    "flat bordered wrap-cells").classes("w-full small-table")

                def reload():
                    if not require_authenticated_page():
                        return
                    try:
                        page = events.list_events(
                            service.chamber_id, severity=severity.value,
                            search=bounded_search(search.value), limit=50)
                        rows = [{
                            "id": row.event_id,
                            "timestamp": row.timestamp_utc.astimezone(timezone.utc).isoformat(),
                            "severity": row.severity,
                            "chamber": row.chamber_id,
                            "operator": row.operator or "—",
                            "run": row.run_id or "—",
                            "step": row.step if row.step is not None else "—",
                            "message": row.message,
                        } for row in page.records if row.chamber_id == service.chamber_id][:50]
                    except Exception:
                        page = RecordPage(False, detail="Event log service failed; retry later.")
                        rows = []
                    status.clear()
                    with status:
                        _status_panel(page, empty_text="No recorded events match the filters.")
                    table.update_rows(rows)
                reload()

    @ui.page("/settings")
    def settings_page():
        if not require_authenticated_page():
            return
        service = get_dashboard_service()
        with page_frame("/settings", service, title="Settings"):
            with ui.column().classes("panel gap-3"):
                ui.label("Server Configuration (read-only)").classes("panel-heading")
                ui.label("G08-min must authorize changes. G05 and site approval must certify "
                         "physical limits; no settings mutation is exposed.").classes(
                             "text-orange-9")
                with ui.column().classes("gap-2") as details:
                    pass

                def update_details():
                    if not require_authenticated_page(touch=False):
                        return
                    view = safe_view(service)
                    cap = project_capabilities(view)
                    display = project_telemetry(view)
                    details.clear()
                    with details:
                        for title, value in (
                            ("Chamber ID", view.chamber_id),
                            ("Backend identity", display.identity),
                            ("Mode", display.mode),
                            ("Reading quality", display.quality),
                            ("Last sample (UTC)", display.sampled_utc),
                            ("Adapter-reported range (not site certified)", cap.temperature_range),
                            ("Start/STOP", cap.start_stop),
                            ("Setpoint readback", cap.setpoint_readback),
                            ("Running readback", cap.running_readback),
                            ("Ramp up", cap.ramp_up), ("Ramp down", cap.ramp_down),
                            ("Control availability", cap.controls_locked_reason),
                        ):
                            with ui.row().classes("settings-row items-start gap-3"):
                                ui.label(title).classes("text-weight-medium settings-key")
                                ui.label(value).classes("settings-value")
                update_details()
                ui.timer(2.0, update_details)
