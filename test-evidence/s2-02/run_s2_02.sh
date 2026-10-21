#!/usr/bin/env bash
# S2-02 combined regression baseline — exact-main, simulation only, no hardware.
# Each group is independently bounded by scripts/h02_watchdog_command.py.
# A watchdog TIMEOUT/NO_OUTPUT kill is FAIL, never a partial pass.
set -u
cd "$(dirname "$0")/../.."
ROOT="$PWD"
EV="$ROOT/test-evidence/s2-02"
PY="$ROOT/.venv/bin/python"
WD="$PY $ROOT/scripts/h02_watchdog_command.py"
export PYTHONUNBUFFERED=1
# /tmp tmpfs is full on this host; keep every temp write on the root filesystem.
export TMPDIR=/home/codepc/github/ami3go/.tmp-space
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/home/codepc/.cache/ms-playwright}"
mkdir -p "$EV"

# Environment/identity evidence (captured once).
{
  echo "utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "git_head: $(git rev-parse HEAD)"
  echo "git_describe: $(git describe --always --dirty)"
  echo "git_status_porcelain: $(git status --porcelain | head -20)"
  echo "python: $($PY --version 2>&1)"
  echo "uname: $(uname -a)"
  $PY -m pip freeze 2>/dev/null | sort
} > "$EV/environment.txt" 2>&1

declare -A TIMEOUT IDLE
TIMEOUT[A]=1500; IDLE[A]=300
TIMEOUT[B]=1200; IDLE[B]=300
TIMEOUT[C]=1500; IDLE[C]=300
TIMEOUT[D]=600;  IDLE[D]=300
TIMEOUT[E]=240;  IDLE[E]=90   # mirrors h01-extended-ci.yml chromium job

run_group() {
  local id="$1"; shift
  local junit="$1"; shift
  echo "=== GROUP $id: $* ==="
  $WD --timeout-s "${TIMEOUT[$id]}" --idle-timeout-s "${IDLE[$id]}" \
      --cleanup-s 10 --log-dir "$EV/$id" -- \
      "$PY" -m pytest -q --junitxml="$EV/$junit" "$@"
  local code=$?
  echo "=== GROUP $id exit=$code ==="
  return $code
}

CODES=()

run_group A s2-02-a-core-control-profiles.xml \
  tests/test_chamber_controller.py tests/test_chamber_backend.py \
  tests/test_chamber_settings.py \
  tests/test_profile_runner.py tests/test_profile_storage.py \
  tests/test_profile_schema.py tests/test_profile_execution_service.py \
  tests/test_profile_editor.py tests/test_profile_runtime.py \
  tests/test_profile_security_integration.py \
  tests/test_dashboard_service.py tests/test_dashboard_profile_ui.py \
  tests/test_manual_control.py tests/test_manual_ui.py
CODES+=("A=$?")

run_group B s2-02-b-g07-recording-h02-supervision.xml \
  tests/test_run_recording.py tests/test_run_recording_integration.py \
  tests/test_h02_profile_admission.py tests/test_h02_supervised_profile.py \
  tests/test_h02_watchdog.py tests/test_h02_watchdog_supervision.py
CODES+=("B=$?")

run_group C s2-02-c-g08-security-web-infra.xml \
  tests/test_security_core.py tests/test_security_credential_reset.py \
  tests/test_security_factory_credentials.py tests/test_security_full.py \
  tests/test_security_profiles.py \
  tests/test_web_model.py tests/test_web_views.py tests/test_web_ui.py \
  tests/test_web_pages_ui.py tests/test_web_profiles_ui.py \
  tests/test_web_factory_admin_ui.py tests/test_web_chamber_discovery.py \
  tests/test_nicegui_test_isolation.py tests/test_setup_environment.py \
  tests/test_repository_layout.py tests/test_verify_driver_install.py \
  tests/test_votsch_discovery.py tests/test_w02_release.py \
  tests/test_windows_packaging.py
CODES+=("C=$?")

run_group D s2-02-d-h01-simulated.xml \
  tests/test_h01_simulation.py tests/test_h01_full_stack.py \
  tests/test_h01_web_transport.py tests/test_h01_physical_hil.py
CODES+=("D=$?")

# Real Chromium browser/server lifecycle (CI equivalent).
run_group E s2-02-e-chromium-e2e.xml \
  -v -s tests/test_h01_browser_e2e.py
CODES+=("E=$?")

{
  echo "S2-02 group exit codes:"
  printf '  %s\n' "${CODES[@]}"
} | tee "$EV/summary.txt"
