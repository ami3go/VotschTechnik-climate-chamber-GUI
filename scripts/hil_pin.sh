#!/usr/bin/env bash
# Operator PIN lifecycle + exclusive bench lock for one physical HIL test command.
# Only setup/reset/revoke require interactive local operator confirmation.
set -Eeuo pipefail
set +x
cd "$(dirname "$(readlink -f "$0")")/.."
PYTHON="${PYTHON:-python3}"
usage() {
  echo "Usage: scripts/hil_pin.sh {setup|reset|revoke|status|verify|run -- COMMAND ...}" >&2
  exit 2
}
[[ $# -ge 1 ]] || usage
action="$1"; shift
case "$action" in
  setup|reset|revoke|status)
    [[ $# -eq 0 ]] || usage
    exec "$PYTHON" -m chamber_web.hil.pin "$action"
    ;;
  verify)
    [[ $# -eq 0 ]] || usage
    if [[ -z "${CHAMBER_HIL_PIN:-}" ]]; then
      [[ -r /dev/tty ]] || { echo "Operator terminal required" >&2; exit 2; }
      IFS= read -r -s -p "Operator HIL PIN: " CHAMBER_HIL_PIN </dev/tty
      printf '\n' >/dev/tty
      export CHAMBER_HIL_PIN
    fi
    exec "$PYTHON" -m chamber_web.hil.pin verify
    ;;
  run)
    [[ "${1:-}" == "--" ]] || usage
    shift
    [[ $# -gt 0 ]] || usage
    command -v flock >/dev/null || { echo "flock required for bench serialization" >&2; exit 2; }
    state_dir="$HOME/.local/state/votsch-climate-chamber"
    [[ -d "$state_dir" && ! -L "$state_dir" ]] || { echo "Operator must setup a PIN first" >&2; exit 2; }
    exec 9>"$state_dir/hil-bench.lock"
    chmod 600 "$state_dir/hil-bench.lock"
    flock -n 9 || { echo "HIL bench busy: another PIN-launched test holds the lock" >&2; exit 2; }
    if [[ -z "${CHAMBER_HIL_PIN:-}" ]]; then
      [[ -r /dev/tty ]] || { echo "Operator PIN required via terminal" >&2; exit 2; }
      IFS= read -r -s -p "Operator HIL PIN: " CHAMBER_HIL_PIN </dev/tty
      printf '\n' >/dev/tty
    fi
    export CHAMBER_HIL_PIN
    "$PYTHON" -m chamber_web.hil.pin verify >/dev/null || exit 2
    # Child keeps FD 9 locked for the command's lifetime. Real chamber scripts
    # must implement their own bounded STOP/restore handling before exit.
    exec "$@"
    ;;
  *) usage ;;
esac
