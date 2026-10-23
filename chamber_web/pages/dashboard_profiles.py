"""Dashboard card for existing server-owned G06/G08 profile execution.

This is a presentation layer only: no chamber commands or browser-owned
runner. The /profiles page and dashboard use the same ProfileExecutionService.
Physical HIL profile execution remains fail-closed at the service boundary.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chamber_web.persistence.profiles import ProfileRevision
    from chamber_web.services.profile_execution import RunView


class DashboardProfileUI:
    """Saved-profile controls (Chamber Control) and run status (Active Profile).

    Both parts share one selection and one refresh timer. Call
    ``render_controls()`` and ``render_card()`` inside their dashboard cards,
    then ``begin_refresh()`` once both exist.
    """

    def __init__(self) -> None:
        self.render_controls, self.render_card, self.begin_refresh = _build()


def _build():
    # Resolve the session/authority modules at page build, never at import:
    # a module-level binding could outlive a reloaded composition root and
    # check sessions against a stale SecurityStore (redirect loop to /login).
    from chamber_web.domain.chamber import ChamberSafetyError
    from chamber_web.pages.profiles import (
        get_profile_editor_service, get_profile_execution_service,
    )
    from chamber_web.persistence.profiles import ProfileNotFoundError, ProfileSchemaError
    from chamber_web.security.auth import AuthenticationError, AuthorizationError
    from chamber_web.security.guards import Permission
    from chamber_web.security.nicegui import (
        active_tokens, require_authenticated_page, require_browser_permission,
    )

    editor = get_profile_editor_service()
    execution = get_profile_execution_service()
    selected: ProfileRevision | None = None
    shown: ProfileRevision | None = None
    shown_key: tuple[str, int] | None = None
    rendered_progress: tuple | None = None

    def selection_changed(profile_id: str | None) -> None:
        nonlocal selected
        if not require_authenticated_page(touch=False):
            return
        try:
            require_browser_permission(Permission.READ, editor.chamber_id)
            selected = (
                editor.store.get_revision(editor.chamber_id, str(profile_id))
                if profile_id else None
            )
        except (ValueError, ProfileNotFoundError, ProfileSchemaError) as exc:
            selected = None
            ui.notify(str(exc), color="negative")
        refresh_run()

    def refresh_library() -> None:
        if not require_authenticated_page(touch=False):
            return
        try:
            require_browser_permission(Permission.READ, editor.chamber_id)
            headers = editor.profiles(limit=100)
        except (AuthenticationError, AuthorizationError):
            ui.navigate.to("/login")
            return
        except (OSError, ValueError, ProfileSchemaError):
            library_info.set_text("Saved profiles unavailable; check profile storage")
            run_button.disable()
            return
        options = {
            header.profile_id: f"{header.name} · rev {header.current_revision}"
            for header in headers
        }
        if profile_select.options != options:
            profile_select.options = options
            profile_select.update()
        library_info.set_text(
            f"{len(headers)} saved profiles shown · Refresh to see new revisions"
            if headers else "No saved profiles. Create one on the Profiles page."
        )

    @ui.refreshable
    def step_overview() -> None:
        if shown is None:
            ui.label("Select a saved profile to preview its steps.").classes(
                "text-sm text-grey-7"
            )
            return
        with ui.column().classes("w-full gap-0").style(
            "max-height:280px;overflow-y:auto"
        ):
            with ui.element("div").classes("profile-row header"):
                for heading in ("#", "Step", "Target", "Dwell", "Status"):
                    ui.label(heading)
            view = current_view
            relevant = bool(
                view and view.profile_id == shown.header.profile_id
                and view.revision == shown.revision and view.state is not None
            )
            enabled = [step for step in shown.profile.steps if step.enabled]
            current_number = None
            if relevant and enabled and view.total_steps:
                current_number = enabled[(max(1, view.step) - 1) % len(enabled)].step
            for step in shown.profile.steps:
                if not step.enabled:
                    status = "Skipped"
                elif not relevant:
                    status = "Pending"
                elif view.state == "COMPLETED":
                    status = "Done"
                elif view.active and step.step == current_number:
                    status = view.state.title()
                elif view.active:
                    status = "Pending / repeat"
                elif step.step == current_number:
                    status = view.state.title()
                else:
                    status = "Not completed"
                css = "profile-row"
                if relevant and view.active and step.step == current_number:
                    css += " active-step"
                with ui.element("div").classes(css):
                    ui.label(str(step.step))
                    ui.label(step.notes or f"Step {step.step}")
                    ui.label(f"{step.target_temperature_c:g} °C")
                    ui.label(f"{step.dwell_s:g} s")
                    ui.label(status)

    async def run_action(action: str) -> None:
        if not require_authenticated_page(touch=False):
            return
        session, csrf = active_tokens()
        if action == "start":
            # Pin the revision that was explicitly previewed; no implicit edits,
            # auto-start, or selection-driven chamber writes.
            if selected is None:
                ui.notify("Select a saved profile first", color="warning")
                return
            profile_id, revision = selected.header.profile_id, selected.revision
            run_button.disable()
        try:
            if action == "start":
                await execution.start_async(session, csrf, profile_id, revision)
                started = execution.view(session)
                ui.notify(
                    f"Started saved revision {revision} " +
                    ("in simulation" if started.simulation else
                     "on the physical chamber (isolated lab mode)"
                     if started.lab else
                     "under supervised physical HIL permit"),
                    color="positive")
            else:
                method = {
                    "stop": execution.cancel,
                    "pause": execution.pause,
                    "resume": execution.resume,
                }[action]
                await asyncio.to_thread(method, session, csrf)
                ui.notify(
                    "STOP requested; awaiting verified state"
                    if action == "stop" else f"Profile {action} requested",
                    color="warning" if action == "stop" else "positive",
                )
        except (ChamberSafetyError, AuthenticationError, AuthorizationError,
                ProfileNotFoundError, ProfileSchemaError, ValueError) as exc:
            ui.notify(str(exc), color="negative", timeout=7000)
        except Exception:
            # A worker exception cannot establish the outcome of a chamber
            # command; never announce a successful STOP or start.
            ui.notify("Profile command outcome unverified; check controller status",
                      color="negative", timeout=7000)
        refresh_run()

    def refresh_run() -> None:
        nonlocal selected, shown, shown_key, rendered_progress, current_view
        if not require_authenticated_page(touch=False):
            return
        try:
            view = execution.view(active_tokens()[0])
        except (AuthenticationError, AuthorizationError):
            run_timer.deactivate()
            ui.navigate.to("/login")
            return
        except Exception:
            status_label.set_text("UNKNOWN — profile runner state unavailable")
            for button in (run_button, pause_button, resume_button):
                button.disable()
            # Do not make an authorization or STOP availability decision from
            # an unverified status. /profiles remains the fallback control UI.
            stop_button.disable()
            return
        current_view = view
        # A page navigation destroys this page's selection closure. Restore
        # only the precise immutable revision from the last server-owned run
        # when the operator hasn't made a new choice. This is read-only:
        # never start a profile from selection or passive refresh.
        if selected is None and view.profile_id and view.revision:
            try:
                previous = editor.store.get_revision(
                    editor.chamber_id, view.profile_id, revision=view.revision)
                selected = previous
                if profile_select.value != view.profile_id:
                    profile_select.value = view.profile_id
            except (ValueError, ProfileNotFoundError, ProfileSchemaError, OSError):
                pass
        for button, enabled_flag in (
            (run_button, view.can_start and selected is not None),
            (pause_button, view.can_pause),
            (resume_button, view.can_resume),
            (stop_button, view.can_stop),
        ):
            button.enable() if enabled_flag else button.disable()
        profile_select.disable() if view.active else profile_select.enable()
        reload_button.disable() if view.active else reload_button.enable()
        if view.lab:
            mode_label.set_text(
                "Physical chamber: isolated lab mode — no permit or watchdog required")
        elif not view.simulation:
            mode_label.set_text(
                "Physical HIL: signed permit, witness and live watchdog required"
                if view.supervised else
                "Physical HIL: enable isolated lab mode in Settings or configure "
                "a signed H02 permit in the server environment")
        elif view.stop_latched and view.controller_state == "VERIFIED_STOPPED":
            mode_label.set_text(
                "Verified STOP — Run Profile rechecks STOPPED before a new run")
        elif view.stop_latched:
            mode_label.set_text(
                "Unknown/faulted STOP — Admin reconciliation required")
        else:
            mode_label.set_text("Simulation · saved profiles run on the server")
        if view.state:
            status_label.set_text(
                f"{view.state} · {view.profile_name} rev {view.revision} "
                f"· step {view.step}/{view.total_steps}"
            )
            details_label.set_text(
                f"Run {view.run_id} · operator {view.operator}" +
                (f" · {view.reason}" if view.reason else "")
            )
        else:
            status_label.set_text("No profile run since server start")
            details_label.set_text("")
        if view.active:
            key = (view.profile_id, view.revision)
        elif selected is not None:
            key = (selected.header.profile_id, selected.revision)
        elif view.profile_id and view.revision:
            key = (view.profile_id, view.revision)
        else:
            key = None
        if key != shown_key:
            try:
                shown = (
                    editor.store.get_revision(editor.chamber_id, key[0],
                                              revision=key[1])
                    if key else None
                )
                shown_key = key
            except (ValueError, ProfileNotFoundError, ProfileSchemaError, OSError):
                shown = None
                shown_key = None
                ui.notify("Saved profile preview unavailable", color="negative")
        active_name.set_text(
            f"{shown.profile.name} · rev {shown.revision}"
            if shown else "Select a saved profile"
        )
        if view.state is None:
            step_label.set_text("Step —")
            progress.value = 0
            progress_label.set_text("0%")
        else:
            step_label.set_text(f"Step {view.step}/{view.total_steps}")
            count_done = (
                view.total_steps if view.state == "COMPLETED"
                else max(0, view.step - 1)
            )
            fraction = count_done / view.total_steps if view.total_steps else 0
            progress.value = fraction
            progress_label.set_text(f"{fraction:.0%}")
        changed = (shown_key, view.run_id, view.state, view.step, view.total_steps)
        if changed != rendered_progress:
            rendered_progress = changed
            step_overview.refresh()

    current_view: RunView | None = None
    profile_select = reload_button = library_info = None
    run_button = pause_button = resume_button = stop_button = None
    status_label = details_label = mode_label = None
    step_label = progress = progress_label = active_name = None
    run_timer = None

    def render_controls() -> None:
        """Chamber Control section: choose a saved profile and run it."""
        nonlocal profile_select, reload_button, library_info, run_button
        nonlocal pause_button, resume_button, stop_button, status_label
        nonlocal details_label, mode_label
        ui.label("Profile").classes("section-title")
        with ui.row().classes("control-row"):
            profile_select = ui.select(
                {}, label="Saved profile", with_input=True,
                on_change=lambda event: selection_changed(event.value),
            ).props("outlined dense").classes("control-field")
            reload_button = ui.button(
                "Reload", icon="refresh",
                on_click=lambda: (refresh_library(),
                                  selection_changed(profile_select.value)),
            ).props("outline no-caps").classes("control-button")
        library_info = ui.label("").classes("text-xs text-grey-7")
        with ui.row().classes("control-row wrap"):
            run_button = ui.button(
                "Run Profile", icon="play_arrow",
                on_click=lambda: run_action("start"),
            ).props("unelevated color=primary no-caps").classes(
                "control-button").disable()
            pause_button = ui.button(
                "Pause", icon="pause",
                on_click=lambda: run_action("pause"),
            ).props("outline no-caps").classes("control-button").disable()
            resume_button = ui.button(
                "Resume", icon="play_circle",
                on_click=lambda: run_action("resume"),
            ).props("outline no-caps").classes("control-button").disable()
            stop_button = ui.button(
                "Stop Run", icon="stop",
                on_click=lambda: run_action("stop"),
            ).props("unelevated color=deep-orange no-caps").classes(
                "control-button").disable()
        status_label = ui.label("").classes("text-sm")
        details_label = ui.label("").classes("text-xs text-grey-7")
        mode_label = ui.label("").classes("text-xs text-orange-9")

    def render_card() -> None:
        """Active Profile card: progress and read-only step preview."""
        nonlocal step_label, progress, progress_label, active_name
        with ui.row().classes("panel-head"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("description", color="blue-grey-10").classes("text-2xl")
                ui.label("Active Profile").classes("panel-heading")
            with ui.row().classes("items-center gap-2"):
                step_label = ui.label("Step —").classes("text-xs")
                progress = ui.linear_progress(value=0, color="blue",
                                              show_value=False).style("width:100px")
                progress_label = ui.label("0%").classes("text-xs")
        with ui.column().classes("w-full gap-2"):
            active_name = ui.label("Select a saved profile").classes("font-bold")
            ui.label(
                "Choose and run profiles in Chamber Control. Runs use the selected "
                "immutable revision; closing the browser does not stop the server "
                "run. STOP is not a hardware emergency stop."
            ).classes("text-xs text-grey-7")
            step_overview()

    def begin_refresh() -> None:
        nonlocal run_timer
        run_timer = ui.timer(1.0, refresh_run, immediate=False)
        refresh_library()
        refresh_run()

    return render_controls, render_card, begin_refresh
