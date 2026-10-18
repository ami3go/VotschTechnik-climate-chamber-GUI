# H02 — Process watchdog operation and physical limitations

## Bounded development/test execution

Use the standalone standard-library process supervisor:

    python scripts/h02_watchdog_command.py --timeout-s 180 --idle-timeout-s 75 --cleanup-s 5 --log-dir h02-evidence -- python -m unittest discover -s tests -p "test_h02_*.py" -v

If a legitimate task is silent, omit idle timeout or configure a trusted heartbeat file with --heartbeat-file PATH and --heartbeat-timeout-s N. Never use browser-supplied file paths or heartbeat data for trusted supervision. Keep overall CI stage/job deadlines above each command deadline. On any timeout, exit status 124 (deadline) or 125 (stalled/lost heartbeat) is NOT a PASS.

The wrapper records child PID and process-group ownership, UTC and monotonic progress, stdout.log, stderr.log, timeline.jsonl, summary.json. On timeout it kills only the owned POSIX session/process group or Windows task tree. Verify cleanup separately before retrying; it cannot guarantee termination of every exotic orphan or uninterruptible process. File-size progress is not proof of functional liveness.

## Physical watchdog — H02-C implementation (in review)

The application-side `chamber_web.hil.supervision.SupervisionHost` starts one independent watchdog OS process per physical launch via `python -m chamber_web.hil.watchdog_process` (never a `multiprocessing` spawn child: spawn re-executes the app entrypoint). They connect over an authenticated loopback socket (`multiprocessing.connection` HMAC handshake with a per-launch 32-byte secret). The child holds **no device authority**: it never opens a device connection and its only possible action is exactly one `STOP_REQUEST`.

Mutual verification: the app heartbeats bounded G04/G07 state (controller generation and ownership, recorder health, telemetry age, measured temperature envelope, step/whole monotonic budgets) at `min(process/supervisor heartbeat, telemetry gap, readback deadline)/3`; the child enforces its own parent-heartbeat deadline and the monotonic step/whole budgets, answers every heartbeat with an ACK, and confirms the config handshake. Losing the child (or its ACK deadline) latches the host fail-closed.

Fault handling: on any violation the app routes the fault through the G06 runner (`notify_supervisor_fault` → durable STOP intent, UNKNOWN, no replay), submits one G04 STOP, then verifies a fresh GOOD STOPPED readback within `stop_verification_timeout_s`. Verification failure, child loss or spawn failure writes `watchdog-latch.json` and refuses all further physical starts until an approved on-site review clears it:

    python scripts/h02_watchdog_reset.py --evidence-dir PATH --reviewed-by "NAME" --confirm-clear

Evidence: `watchdog-timeline.jsonl` (host) and `watchdog-child.jsonl` (child, includes `CHILD_START`, `CONFIG_CONFIRMED`, `FAULT`, `PARENT_LOST`; exit codes 2 connect, 3 parent lost, 4 config invalid, 5 protocol error — none are a PASS). The child's plain-launch CLI is only ever started by the host; do not run it manually against a live chamber.

The command watchdog remains an independent process but **it does NOT implement a G04 STOP path** and does not certify independent physical chamber supervision. Physical activation still requires the same reviewed implementation plus signed site method approval: authoritative chamber identity, fresh telemetry and measured temperature envelope, G04 command generation and ownership, G07 recorder heartbeat, per-step and whole-run monotonic deadlines, approved policy for exactly one prioritized G04 STOP and bounded fresh STOP verification (implemented above, pending independent review).

On physical watchdog expiry, prevent further G06 dispatch, commit abort/UNKNOWN intent if storage is still writable, request one approved STOP through G04 if possible, verify fresh authoritative stopped state, keep UNKNOWN + explicit reconciliation lockout if any uncertainty remains, alert on-site staff to the independently approved physical emergency procedure and preserve all evidence. Never blindly retry STOP or assume it restores air/dryer/digital outputs. An independent software process cannot stop a chamber after host power, OS, network or instrument failure.

## Configuration

H02WatchdogLimits v1 has finite positive values for controller command timeout, readback deadline, maximum telemetry gap, per-step and overall profile deadlines, recorder heartbeat, application/process heartbeat, supervisor heartbeat, cleanup and STOP verification. Physical values MUST be approved in the signed site permit; there are no universal default physical safety durations. P00 requires readback and telemetry <= 5 seconds and whole-run <= 14 days. G06 PAUSE never resets step/run deadlines.

**Site H02 permit: ABSENT. Physical tests: NOT RUN. Physical execution: NO-GO.**
