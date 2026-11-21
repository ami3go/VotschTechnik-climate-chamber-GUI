# Automotive temperature-test templates — NiceGUI integration

**Status:** Research/catalogue feature, **not** qualified test software.  
**Dataset snapshot:** 2026-11-21.  
**Sources:** [86-standard catalogue](AUTOMOTIVE_TEMPERATURE_TEST_STANDARDS.md), [60-method extraction](AUTOMOTIVE_TEMPERATURE_PROFILE_EXTRACTION.md), and the [standard-to-method index](data/automotive_temperature_profile_index_2026.csv).

## Scope

The **Profiles → Automotive Temperature Standards Library** panel exposes 86 catalogued ISO/IEC/SAE, OEM, AEC/JEDEC and battery standards. Where a public or secondary test method was extracted, selecting the standard shows its referenced method(s), numerical information, sequence, duty state, equipment requirement, evidence class, source URL and known missing parameters.

The application bundles exact research-source CSV snapshots at:

- `chamber_web/assets/automotive_temperature_profile_index_2026.csv`
- `chamber_web/assets/automotive_temperature_profile_methods_2026.csv`

The CSV data is **read-only catalogue content**, never dispatched to the chamber. Values labelled `public_vendor_example` are not an authorized substitute for the controlled OEM test plan.

## Actual G03 candidate generation

The current G03 schema represents a temperature setpoint followed by stabilization and a dwell. It does **not** represent timed ramp segments, humidity setpoints, hot/cold chamber transfers, water spray, condensation, DUT electrical switching, bath immersion or independent DUT temperature sensors.

Only the following research methods can currently become **unsaved editor drafts**:

| Method ID | Target | Dwell | Additional inputs |
|---|---:|---:|---|
| ISO-COLD-STORAGE | −40 °C | 24 h | Positive tolerance, DUT stabilization, reach watchdog |
| ISO-HOT-STORAGE | +85 °C | 48 h | Positive tolerance, DUT stabilization, reach watchdog |
| ISO-COLD-OP | user-selected `Tmin` | 24 h | Tmin and mandatory review inputs |
| ISO-HOT-OP | user-selected `Tmax` | 96 h | Tmax and mandatory review inputs |
| IEC-COLD-METHOD | customer-selected cold severity | customer-selected | Target, duration and mandatory review inputs |
| IEC-DRY-HEAT-METHOD | customer-selected dry-heat severity | customer-selected | Target, duration and mandatory review inputs |

All generated G03 steps use **null ramps** and leave auxiliary outputs unchanged. `chamber_run=ON` means **chamber control only**, not DUT power. The output step notes and metadata retain an explicit **unapproved** marker. Operator input is necessary; no values for tolerance, stabilization or reach-timeout are invented. Generating a candidate never writes SQLite, creates a hardware lease or starts a run.

The remaining **54 methods** are **research-only previews** for now. This includes IEC humidity methods, LV124 OEM vendor examples, JEDEC cycling and shock, battery approval sequences, thermal stress beyond the 14-day runtime limit, methods requiring external DUT operations or any profile without a verified sequence that the current runner can represent. Standards with no extracted method remain visible and explain the missing evidence.

## Execution safety / provenance

- Candidate generation produces a G03 `EditorDraft` with `profile_id=None` and `dirty=True`. A separate manual **Save Revision** action is required to archive the unapproved candidate for review.
- The candidate is **never automatically approved**. The original methodology, clause revision, test severity, DUT power/functional checks, soak start criterion, ambient recovery, sensor placement and actual equipment limits remain open for review.
- The persisted `ParsedProfile.migration_warning` starts with `AUTOMOTIVE_RESEARCH_TEMPLATE_UNAPPROVED:`; the same marker is embedded in the first step's notes to survive lossy canonical CSV export/import.
- **Both** `ProfileExecutionService.start()` and `ProfileRunner.start()` reject profiles carrying either marker, **before releasing manual control or acquiring the controller lease**. This includes simulation, lab and supervised modes.
- A deliberate, separately reviewed production-profile design/approval workflow is required to execute a standards-based method. **This PR does not implement approval**, and it does not certify a programmed chamber test as compliant with any OEM requirement.
- Generic existing profiles are not affected. Editing/clearing the source marker is not an approval process; operational controls, revision approval and user authorization must be enforced by a future explicit lifecycle feature.

## Watchdogs and acceptance boundaries

User-supplied reach timeout is mandatory even for research drafts, and must cover the selected DUT stabilization interval. No generated gradient is sent to G04; the normal runner continues to impose step deadlines and an absolute 14-day run watchdog on independent future approved profiles. Software-only test work should be bounded by `scripts/h02_watchdog_command.py` or the CI job's `timeout-minutes`. **Process timeout does not mean physical STOP**; hardware access continues to require the current PIN and verified STOP procedure, and no energized HIL run was carried out here.

The NiceGUI application has no new instrument-communication path: all production chamber I/O remains delegated to the Vötsch Python driver via existing G04 services.

## Software verification

- `python -m pytest -q tests/test_automotive_profile_templates.py`
- `python -m unittest discover -s tests -p "test_profile_*.py" -v`
- `python -m pytest -q tests/test_web_profiles_ui.py`
- `python -m ruff check chamber_web tests/test_automotive_profile_templates.py --select E4,E7,E9,F`

The 86-to-60 mapping, duplicate IDs, HTTPS source fields and `execution_approved=false` flags are checked when the catalogue is loaded. Tests verify the six candidate conversions, required/invalid inputs, canonical ZIP/CSV provenance, SQLite non-mutation before manual save and execution denial on the simulated backend. Physical HIL acceptance remains **not performed**.
