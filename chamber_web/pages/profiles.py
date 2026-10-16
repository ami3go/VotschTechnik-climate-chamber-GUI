"""G03-C NiceGUI profile editor; persistent data belongs only to ProfileStore.

Only profile metadata/step drafts live in page closures. Saved revisions may
be run only in simulation through the server-owned ProfileExecutionService;
there are no browser-local authoritative copies or automatic profile starts.
"""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from pathlib import Path

from nicegui import ui

from chamber_web.domain.chamber import ChamberSafetyError
from chamber_web.security.auth import AuthenticationError, AuthorizationError, Role
from chamber_web.security.guards import Permission
from chamber_web.security.nicegui import (active_tokens, current_actor, get_security,
                                          require_authenticated_page,
                                          require_browser_permission)
from chamber_web.domain.profile import MAX_BYTES, format_digital_outputs
from chamber_web.persistence.profiles import (
    ProfileConflictError, ProfileNotFoundError, ProfileStore,
)
from chamber_web.services.profile_editor import (
    DuplicateProfileError, EditorDraft, ProfileEditorService,
    compatibility_warnings,
)
from chamber_web.services.profile_execution import ProfileExecutionService, RunView


def default_database_path() -> Path:
    """Trusted process-owned storage, never a user/browser-selected pathname."""
    configured = os.environ.get("CHAMBER_PROFILE_DB")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        from chamber_web.windows_runtime import state_dir
        return state_dir() / "profiles.sqlite3"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / (
        "climate-chamber/profiles.sqlite3"
    )


@lru_cache(maxsize=1)
def get_profile_editor_service() -> ProfileEditorService:
    # Single application composition root: no browser input chooses chamber_id.
    from chamber_web.main import get_dashboard_service
    chamber_id = get_dashboard_service().view().chamber_id
    return ProfileEditorService(ProfileStore(default_database_path()), chamber_id)


_execution_service: ProfileExecutionService | None = None


def get_profile_execution_service() -> ProfileExecutionService:
    """One server-owned runner host; simulation mode comes from launch config only."""
    global _execution_service
    if _execution_service is None:
        from chamber_web.main import get_dashboard_service, profile_execution_is_simulation
        editor = get_profile_editor_service()
        _execution_service = ProfileExecutionService(
            get_dashboard_service().manager, editor.store, get_security(),
            editor.chamber_id, simulation=profile_execution_is_simulation(),
        )
    return _execution_service


async def shutdown_profile_execution() -> None:
    """Server shutdown hook: STOP any active run before the backend disconnects."""
    global _execution_service
    service, _execution_service = _execution_service, None
    if service is not None:
        await service.shutdown()


_RUN_ERRORS = (ChamberSafetyError, AuthenticationError, AuthorizationError,
               ValueError, ProfileNotFoundError)


def _grid_columns() -> list[dict]:
    return [
        {"field": "step", "headerName": "#", "editable": False, "width": 65,
         "pinned": "left"},
        {"field": "enabled", "headerName": "Use", "editable": True,
         "cellEditor": "agCheckboxCellEditor", "cellRenderer": "agCheckboxCellRenderer",
         "width": 90},
        {"field": "target_temperature_c", "headerName": "Target °C", "editable": True,
         "width": 120},
        {"field": "ramp_up_c_per_min", "headerName": "Ramp up °C/min", "editable": True,
         "width": 145},
        {"field": "ramp_down_c_per_min", "headerName": "Ramp down °C/min",
         "editable": True, "width": 150},
        {"field": "tolerance_c", "headerName": "Tolerance °C", "editable": True,
         "width": 135},
        {"field": "stabilize_s", "headerName": "Stabilize s", "editable": True,
         "width": 130},
        {"field": "dwell_s", "headerName": "Dwell s", "editable": True, "width": 110},
        {"field": "reach_timeout_s", "headerName": "Reach timeout s",
         "editable": True, "width": 160},
        {"field": "chamber_run", "headerName": "Chamber run", "editable": True,
         "cellEditor": "agSelectCellEditor",
         "cellEditorParams": {"values": ["UNCHANGED", "ON", "OFF"]}, "width": 145},
        {"field": "compressed_air", "headerName": "Compressed air", "editable": True,
         "cellEditor": "agSelectCellEditor",
         "cellEditorParams": {"values": ["UNCHANGED", "ON", "OFF"]}, "width": 155},
        {"field": "dryer", "headerName": "Dryer", "editable": True,
         "cellEditor": "agSelectCellEditor",
         "cellEditorParams": {"values": ["UNCHANGED", "ON", "OFF"]}, "width": 125},
        {"field": "digital_outputs", "headerName": "Other outputs", "editable": True,
         "headerTooltip": "Use number=ON;number=OFF (outputs 1, 7 and 8 have named columns)",
         "width": 180},
        {"field": "notes", "headerName": "Description / notes", "editable": True,
         "minWidth": 200, "flex": 1},
    ]


def _rows(draft: EditorDraft) -> list[dict]:
    rows = []
    for step in draft.profile.steps:
        row = {}
        for key, value in vars(step).items():
            if key == "digital_outputs":
                row[key] = format_digital_outputs(value)
            elif value is not None and key not in (
                "enabled", "step", "notes", "chamber_run", "compressed_air", "dryer"
            ):
                row[key] = str(value)
            else:
                row[key] = value if value is not None else ""
        rows.append(row)
    return rows


@ui.page("/profiles")
def profiles_page() -> None:
    if not require_authenticated_page():
        return
    service = get_profile_editor_service()
    execution = get_profile_execution_service()
    can_mutate = current_actor().role in (Role.ADMIN, Role.OPERATOR)

    def require_read() -> None:
        # Session, role, CSRF and revocation are rechecked at event dispatch.
        require_browser_permission(Permission.READ, service.chamber_id)

    def require_edit() -> None:
        require_browser_permission(Permission.PROFILE_EDIT, service.chamber_id)
    draft = service.new_draft()
    selected_step = 0
    offset = 0
    columns = _grid_columns()

    def notice_error(exc: Exception) -> None:
        ui.notify(str(exc), color="negative", timeout=7000)

    def show_warnings() -> None:
        try:
            from chamber_web.main import get_dashboard_service
            caps = get_dashboard_service().view().capabilities
        except (RuntimeError, AttributeError, ValueError, OSError):
            caps = None
        warnings = compatibility_warnings(draft.profile, caps)
        compatibility_label.set_text(
            "Capability preview: " + ("; ".join(warnings[:6]) if warnings
                                      else "no reported capability mismatches") +
            (" (more issues omitted)" if len(warnings) > 6 else "")
        )

    def populate() -> None:
        nonlocal selected_step
        selected_step = min(selected_step, len(draft.profile.steps) - 1)
        grid.options["rowData"] = _rows(draft)
        for col in columns:
            if col["field"] != "step":
                col["editable"] = not draft.read_only and can_mutate
        grid.update()
        name_input.value = draft.profile.name
        description_input.value = draft.profile.description
        repeat_input.value = draft.profile.repeat_count
        for widget in (name_input, description_input, repeat_input):
            if draft.read_only or not can_mutate:
                widget.disable()
            else:
                widget.enable()
        for button in mutation_buttons:
            if draft.read_only or not can_mutate:
                button.disable()
            else:
                button.enable()
        status_label.set_text(
            ("New / unsaved" if draft.profile_id is None else
             f"ID {draft.profile_id} · loaded revision {draft.viewed_revision} "
             f"/ head at open {draft.expected_revision}") +
            (" · READ ONLY HISTORY" if draft.read_only else "") +
            (" · UNSAVED CHANGES" if draft.dirty else "")
        )
        provenance_label.set_text(
            draft.profile.migration_warning or
            "Canonical v2 · null gradients and UNCHANGED outputs issue no request"
        )
        version_input.value = draft.viewed_revision or 1
        show_warnings()

    def refresh_library() -> None:
        require_read()
        profiles = service.profiles(limit=100, offset=offset)
        choices = {
            p.profile_id: f"{p.name} · rev {p.current_revision} · {p.updated_at_utc[:19]}"
            for p in profiles
        }
        profile_select.options = choices
        profile_select.update()
        count_label.set_text(f"Saved profiles: {len(profiles)} on page · offset {offset}")

    def can_discard() -> bool:
        if draft.dirty:
            ui.notify("Unsaved changes. Save or click Discard Edits before switching.",
                      color="warning")
            return False
        return True

    def load_profile() -> None:
        require_read()
        nonlocal draft, selected_step
        if not can_discard() or not profile_select.value:
            return
        try:
            draft = service.open(str(profile_select.value))
            selected_step = 0
            populate()
            ui.notify("Loaded latest persisted revision", color="positive")
        except (ValueError, ProfileNotFoundError) as exc:
            notice_error(exc)

    def new_profile() -> None:
        require_edit()
        nonlocal draft, selected_step
        if not can_discard():
            return
        draft = service.new_draft()
        selected_step = 0
        populate()

    def discard() -> None:
        require_edit()
        nonlocal draft, selected_step
        try:
            draft = (service.open(draft.profile_id) if draft.profile_id
                     else service.new_draft())
            selected_step = 0
            populate()
            ui.notify("Unsaved edits discarded", color="info")
        except (ValueError, ProfileNotFoundError) as exc:
            notice_error(exc)

    def meta(field: str, value: object) -> None:
        nonlocal draft
        # NiceGUI emits on_change during server-side display synchronization;
        # identical values are not mutation requests.
        if value == getattr(draft.profile, field, object()):
            return
        try:
            require_edit()
        except (AuthenticationError, AuthorizationError):
            # Permission denial is already durably audited by G08.
            return
        try:
            draft = service.set_metadata(draft, field, value)
            status_label.set_text("UNSAVED CHANGES · Save to create an immutable revision")
        except ValueError as exc:
            notice_error(exc)

    def grid_select(event) -> None:
        require_read()
        nonlocal selected_step
        data = event.args.get("data", {}) if isinstance(event.args, dict) else {}
        number = data.get("step") if isinstance(data, dict) else None
        if type(number) is int and 1 <= number <= len(draft.profile.steps):
            selected_step = number - 1

    def grid_edit(event) -> None:
        require_edit()
        nonlocal draft, selected_step
        args = event.args if isinstance(event.args, dict) else {}
        data = args.get("data", {})
        number = data.get("step") if isinstance(data, dict) else None
        field = args.get("colId")
        try:
            if type(number) is not int or field not in columns_fields:
                raise ValueError("Invalid grid edit")
            selected_step = number - 1
            draft = service.edit_step(draft, selected_step, field, args.get("newValue"))
        except (ValueError, TypeError) as exc:
            notice_error(exc)
        finally:
            # Server canonical state always replaces untrusted client cell value.
            populate()

    def change_step(operation: str) -> None:
        require_edit()
        nonlocal draft
        try:
            draft = service.change_step(draft, operation,
                                        None if operation == "add" else selected_step)
            populate()
        except ValueError as exc:
            notice_error(exc)

    def save() -> None:
        require_edit()
        nonlocal draft
        try:
            draft = service.save(draft)
            populate()
            refresh_library()
            profile_select.value = draft.profile_id
            ui.notify("Saved immutable revision " + str(draft.viewed_revision), color="positive")
        except ProfileConflictError:
            conflict_label.set_text(
                "CONFLICT: another browser saved a newer revision. Your draft is preserved. "
                "Export/copy your changes externally or explicitly discard and reload latest; "
                "this editor will not overwrite the new head."
            )
            ui.notify("Stale revision: changes NOT saved", color="negative", timeout=9000)
        except (ValueError, ProfileNotFoundError) as exc:
            notice_error(exc)

    def duplicate() -> None:
        require_edit()
        nonlocal draft
        try:
            draft = service.duplicate(draft)
            populate()
            refresh_library()
            profile_select.value = draft.profile_id
            ui.notify("Saved a distinct profile identity", color="positive")
        except (ValueError, ProfileNotFoundError) as exc:
            notice_error(exc)

    def browse_revision() -> None:
        require_read()
        nonlocal draft
        if not can_discard() or not draft.profile_id:
            return
        raw = version_input.value
        try:
            if type(raw) is bool or raw is None or int(raw) != raw:
                raise ValueError("Revision must be a whole number")
            draft = service.open(draft.profile_id, int(raw))
            populate()
        except (ValueError, ProfileNotFoundError) as exc:
            notice_error(exc)

    def restore() -> None:
        require_edit()
        nonlocal draft
        try:
            draft = service.use_historical_as_draft(draft)
            populate()
            ui.notify("Historical copy ready to save as a NEW revision", color="warning")
        except ValueError as exc:
            notice_error(exc)

    def export_file(format: str) -> None:
        require_read()
        try:
            data, filename, content_type = service.export(draft, format=format)
            ui.download.content(data, filename, media_type=content_type)
        except (ValueError, ProfileNotFoundError) as exc:
            notice_error(exc)

    async def import_file(event) -> None:
        require_edit()
        nonlocal draft, selected_step
        if not can_discard():
            return
        try:
            data = await event.file.read()
            filename = event.file.name
            require_edit()  # Revalidate after await: session may be revoked mid-upload.
            draft = service.import_file(
                data, filename=filename, legacy_reach_timeout_s=legacy_timeout.value
            )
            selected_step = 0
            populate()
            refresh_library()
            profile_select.value = draft.profile_id
            import_dialog.close()
            ui.notify("Imported and saved revision 1", color="positive")
        except DuplicateProfileError as exc:
            ui.notify("Duplicate skipped: " + exc.header.profile_id, color="warning")
        except (ValueError, TypeError, UnicodeError, OSError) as exc:
            notice_error(exc)

    def paginate(delta: int) -> None:
        require_read()
        nonlocal offset
        offset = max(0, offset + 100 * delta)
        refresh_library()

    def render_run(view: RunView) -> None:
        if not view.simulation:
            run_mode_label.set_text("Profile execution is disabled in Physical HIL mode")
        elif view.stop_latched:
            run_mode_label.set_text("STOP latch active · request STOP reconciliation in Admin → Operator Lease")
        else:
            run_mode_label.set_text(f"Simulation · controller {view.controller_state}")
        if view.state is None:
            run_state_label.set_text("No profile run since server start")
            run_detail_label.set_text("")
        else:
            elapsed = ("" if view.elapsed_s is None else
                       f" · elapsed {int(view.elapsed_s // 60)}:{int(view.elapsed_s % 60):02d}")
            run_state_label.set_text(
                f"{view.state} · {view.profile_name} rev {view.revision} · "
                f"step {view.step}/{view.total_steps}" +
                ("" if view.target_c is None else f" · target {view.target_c:g} °C") +
                elapsed
            )
            run_detail_label.set_text(
                f"Operator {view.operator} · run {view.run_id}" +
                (f" · {view.reason}" if view.reason else "")
            )
        for button, allowed in ((run_button, view.can_start), (stop_run_button, view.can_stop),
                                (pause_button, view.can_pause),
                                (resume_button, view.can_resume)):
            if allowed:
                button.enable()
            else:
                button.disable()
        run_events.rows = [
            {"sequence": e.sequence, "kind": e.kind, "state": e.state, "step": e.step,
             "detail": e.detail,
             "temperature": "" if e.temperature_c is None else f"{e.temperature_c:.2f}"}
            for e in reversed(view.events)
        ]
        run_events.update()

    def refresh_run() -> None:
        session, _ = active_tokens()
        try:
            view = execution.view(session)
        except (AuthenticationError, AuthorizationError):
            run_timer.deactivate()
            ui.navigate.to("/login")
            return
        render_run(view)

    async def run_action(name: str, call) -> None:
        session, csrf = active_tokens()
        try:
            await call(session, csrf)
            ui.notify(name, color="positive")
        except _RUN_ERRORS as exc:
            notice_error(exc)
        refresh_run()

    async def start_run() -> None:
        if draft.profile_id is None or draft.dirty or not draft.viewed_revision:
            ui.notify("Load a saved revision without unsaved edits to run it",
                      color="warning")
            return
        profile_id, revision = draft.profile_id, draft.viewed_revision
        await run_action(
            f"Started revision {revision} in simulation",
            lambda session, csrf: execution.start_async(session, csrf, profile_id, revision),
        )

    def threaded(method):
        return lambda session, csrf: asyncio.to_thread(method, session, csrf)

    # Dynamic imports are not used: everything needed for Windows/offline
    # packaging is in the installed NiceGUI/Python dependency closure.
    columns_fields = {column["field"] for column in columns if column["field"] != "step"}
    with ui.dialog() as import_dialog:
        with ui.card().classes("w-full").style("max-width:520px"):
            ui.label("Import canonical CSV / ZIP or legacy six-column CSV").classes(
                "panel-heading")
            ui.label("Legacy CSV needs an explicit reach timeout. Its demo ramp is NOT a "
                     "physical gradient. ZIP keeps legacy originals and provenance.").classes(
                         "text-sm text-orange-9")
            legacy_timeout = ui.number("Legacy reach timeout (seconds)",
                                       min=1, max=2592000).props("outlined")
            ui.upload(on_upload=import_file, auto_upload=True,
                      max_file_size=2 * MAX_BYTES).props("accept=.csv,.zip").classes("w-full")
            ui.button("Close", on_click=import_dialog.close).props("flat")
    from chamber_web.main import get_dashboard_service
    from chamber_web.ui_pages import page_frame
    with page_frame("/profiles", get_dashboard_service(), title="Profiles"):
        ui.label("Persistent Profiles / Revisions").classes("panel-heading")
        ui.label("SIMULATION · Saved revisions run only against the simulated chamber"
                 ).classes("text-xs text-orange-9")
        ui.label("Profiles are saved on the server. Editing never starts or controls "
                 "the physical chamber.").classes("demo-banner w-full")
        with ui.column().classes("panel gap-3"):
            ui.label("Profile Library").classes("panel-heading")
            with ui.row().classes("items-center w-full gap-2"):
                profile_select = ui.select({}, label="Saved profiles", with_input=True).props(
                    "outlined dense").classes("flex-grow")
                ui.button("Load", icon="folder_open", on_click=load_profile).props(
                    "outline no-caps")
                new_button = ui.button("New", icon="add", on_click=new_profile).props(
                    "outline no-caps")
                discard_button = ui.button("Discard Edits", icon="undo", on_click=discard).props(
                    "outline no-caps")
            with ui.row().classes("items-center gap-2"):
                ui.button("Previous 100", on_click=lambda: paginate(-1)).props(
                    "flat no-caps")
                ui.button("Next 100", on_click=lambda: paginate(1)).props(
                    "flat no-caps")
                count_label = ui.label("").classes("text-xs text-grey-7")
        with ui.column().classes("panel gap-3"):
            with ui.row().classes("panel-head"):
                ui.label("Profile Editor").classes("panel-heading")
                with ui.row().classes("gap-2"):
                    save_button = ui.button("Save Revision", icon="save",
                                            on_click=save).props("no-caps")
                    duplicate_button = ui.button("Duplicate Profile", icon="content_copy",
                              on_click=duplicate).props("outline no-caps")
            status_label = ui.label("").classes("text-xs text-grey-7")
            conflict_label = ui.label("").classes("text-sm text-negative")
            with ui.row().classes("items-center gap-3 w-full"):
                name_input = ui.input("Profile name",
                                      on_change=lambda e: meta("name", e.value)).props(
                                          "outlined dense").classes("flex-grow")
                repeat_input = ui.number("Repeats", min=1, max=100, step=1,
                                         on_change=lambda e: meta(
                                             "repeat_count", e.value)).props(
                                                 "outlined dense").style("width:135px")
            description_input = ui.textarea(
                "Profile description",
                on_change=lambda e: meta("description", e.value)
            ).props("outlined dense").classes("w-full")
            ui.label("Choose a row, then edit grid cells or reorder with the buttons. "
                     "Outputs use ON / OFF / UNCHANGED; other outputs use, for example, "
                     "2=ON;3=OFF. Gradients may be blank (null).").classes(
                         "text-xs text-grey-7")
            grid = ui.aggrid({
                "columnDefs": columns,
                "rowData": [],
                "defaultColDef": {"resizable": True, "sortable": False},
                "singleClickEdit": True,
                "stopEditingWhenCellsLoseFocus": True,
            }).classes("w-full").style("height:355px")
            grid.on("cellClicked", grid_select)
            grid.on("cellValueChanged", grid_edit)
            with ui.row().classes("gap-2 flex-wrap"):
                mutation_buttons = [
                    ui.button("Add Step", on_click=lambda: change_step("add")),
                    ui.button("Duplicate Step", on_click=lambda: change_step("duplicate")),
                    ui.button("Move Up", on_click=lambda: change_step("up")),
                    ui.button("Move Down", on_click=lambda: change_step("down")),
                    ui.button("Delete Step", on_click=lambda: change_step("delete")),
                    save_button,
                ]
                for button in mutation_buttons:
                    button.props("outline no-caps")
            provenance_label = ui.label("").classes("text-xs text-orange-9")
            compatibility_label = ui.label("").classes("text-xs text-orange-9")
        with ui.column().classes("panel gap-2"):
            with ui.row().classes("panel-head"):
                ui.label("Profile Run").classes("panel-heading")
                with ui.row().classes("gap-2"):
                    run_button = ui.button("Run Loaded Revision", icon="play_arrow",
                                           on_click=start_run).props("no-caps")
                    pause_button = ui.button(
                        "Pause", icon="pause",
                        on_click=lambda: run_action(
                            "Run paused", threaded(execution.pause)),
                    ).props("outline no-caps")
                    resume_button = ui.button(
                        "Resume", icon="play_circle",
                        on_click=lambda: run_action(
                            "Run resumed", threaded(execution.resume)),
                    ).props("outline no-caps")
                    stop_run_button = ui.button(
                        "Stop Run", icon="stop",
                        on_click=lambda: run_action(
                            "STOP requested", threaded(execution.cancel)),
                    ).props("no-caps color=negative")
            run_mode_label = ui.label("").classes("text-xs text-orange-9")
            run_state_label = ui.label("").classes("text-sm")
            run_detail_label = ui.label("").classes("text-xs text-grey-7")
            ui.label("The run belongs to the server: closing this page does not stop it. "
                     "Pause only suspends qualification; the chamber keeps its setpoint. "
                     "Stop Run ends the run with a verified STOP. Web STOP is not an "
                     "emergency stop.").classes("text-xs text-grey-7")
            run_events = ui.table(
                columns=[{"name": key, "label": label, "field": key, "align": "left"}
                         for key, label in (("sequence", "#"), ("kind", "Event"),
                                            ("state", "State"), ("step", "Step"),
                                            ("temperature", "°C"), ("detail", "Detail"))],
                rows=[], row_key="sequence",
            ).props("dense flat").classes("w-full").style("max-height:260px")
        with ui.column().classes("panel gap-2"):
            ui.label("Immutable Revision History").classes("panel-heading")
            with ui.row().classes("items-center gap-2"):
                version_input = ui.number("Revision #", min=1, step=1,
                                          value=1).props("outlined dense").style(
                                              "width:135px")
                ui.button("View Revision", on_click=browse_revision).props(
                    "outline no-caps")
                ui.button("Restore Historical as Draft", on_click=restore).props(
                    "outline no-caps")
            ui.label("Historical revisions cannot be edited or replaced. Restoring "
                     "creates a new head only after Save and optimistic revision check."
                     ).classes("text-xs text-grey-7")
        with ui.column().classes("panel gap-2"):
            ui.label("Import / Export").classes("panel-heading")
            with ui.row().classes("gap-2 flex-wrap"):
                import_button = ui.button("Import CSV / ZIP", icon="upload",
                          on_click=import_dialog.open).props("outline no-caps")
                ui.button("Download ZIP (lossless)", icon="archive",
                          on_click=lambda: export_file("zip")).props("outline no-caps")
                ui.button("Canonical CSV", icon="download",
                          on_click=lambda: export_file("csv")).props("outline no-caps")
                ui.button("Spreadsheet-safe CSV", icon="table_view",
                          on_click=lambda: export_file("spreadsheet_csv")).props(
                              "outline no-caps")
            ui.label("CSV loses legacy original and legacy ramp provenance. "
                     "Spreadsheet-safe CSV escapes formula-like notes and is not "
                     "byte-identical to machine CSV. ZIP is archival.").classes(
                         "text-xs text-grey-7")
    if not can_mutate:
        for button in (new_button, discard_button, duplicate_button, import_button):
            button.disable()
    refresh_library()
    populate()
    run_timer = ui.timer(1.0, refresh_run)
    refresh_run()
