# H01 — Physical Chamber HIL Verification (PREPARATION ONLY)

**Status: PHYSICAL NO-GO.** This file is a future site test plan, **not** authority to connect/operate hardware. GUI main baseline 64c3d8c2d41bd40173428aaec4ca5125af60dd95; pinned external driver 9323e3701f3befedcc23b45170a851fd327f0bcc. G05 #28, G07-A #27, G08-full #29 are open draft PRs; refresh the baseline and review all three before execution.

The G04 ChamberManager / ChamberController is the *only* owner of all device commands; the only physically communicative Vötsch implementation is the maintained external Python driver, imported solely by VotschBackend. The GUI must not implement device protocol. G04 rejects non-simulation before connect. **Do not add any hardware-activation flag, GUI switch, credential, environment variable or bypass in H01**. The future physical execution path requires an independently reviewed implementation and separately signed site permit.

All tests: document verified manufacturer/model/serial/firmware, signed manual revision, calibrated independent reference, approved thermal envelope, specimen hazards, emergency shutdown, two-person supervision, immutable GUI and driver SHAs and permitted maximum exposure. Capture UTC timestamps, controller and front-panel readbacks, physical instrumentation, audit/run logs and STOP/fault response. Abort under the site emergency response plan at any UNKNOWN/FAULT, unverified STOP, timeout, stale reading or abnormal alarm; never replay an ambiguous command or auto-resume/reconcile. Web STOP is **not** emergency stop, and an acknowledgment is **not** physical STOP evidence. Physical power interruption needs a separate signed permit.

| ID | Future site-supervised procedure | Minimum evidence and fail criterion |
|---|---|---|
| H01-01 | Read device nameplate, model/serial and firmware via approved OEM method | OEM/site identity and independent readback agree; missing firmware blocks |
| H01-02 | Connect/disconnect only from verified safe idle | Local observations and no unexpected command |
| H01-03 | Compare temperature telemetry with calibrated reference | Site-signed tolerance, GOOD quality and timestamp freshness |
| H01-04 | Confirm certified envelope and fixture derating | Signed exact limits, no simulated defaults |
| H01-05 | Read back an approved bounded setpoint | Fresh independent target observation; acknowledgement insufficient |
| H01-06 | Site-authorized START, web STOP, local STOP/E-stop separately | Running/stopped physical evidence and latencies; never equate web STOP with E-stop |
| H01-07 | STOP while ordinary writes are queued | Queued writes fenced; note unavoidable already executing I/O |
| H01-08 | Two operators contest lease | Single owner, STOP not lease-dependent |
| H01-09 | Anonymous, VIEWER, revoked, forged CSRF/origin attempted writes | Reject/audit with zero device dispatch |
| H01-10 | Approved network cut/timeout | UNKNOWN/FAULT, no replay/false success |
| H01-11 | Restart after ambiguous command | Persistent latch; fresh explicit approved reconciliation only |
| H01-12 | Invalid, nonfinite and out-of-envelope targets | Rejection prior to write |
| H01-13 | Manufacturer-approved alarm/fault stimuli | Site-approved alarm code, response and inhibit evidence |
| H01-14 | Gradient up/down units, certified range, readback and restoration | **BLOCKED** until all four independent OEM/site approvals |
| H01-15 | Short supervised profile and cancellation | One owner, monotonic steps and verified cancellation STOP |
| H01-16 | Durable event/sample recording and export integrity | G07 manifests, timestamps, intended target != observed setpoint |
| H01-17 | Controlled process crash and reconciliation | No automatic resume, run UNKNOWN, physical observer ready |
| H01-18 | Physical power loss | **NOT AUTHORIZED IN THIS TASK**; separate high-risk permit |
| H01-19 | Windows app/service shutdown and restart | No false stopped state or command replay |
| H01-20 | Offline frozen Win10/11 x64 install, rollback and update | Package digest, driver pin, no runtime download, site NTFS/firewall proof |

Simulation-only tests in `tests/test_h01_simulation.py` exercise a *subset* of these behaviors against `FakeBackend` and injected failures, **not** hardware/firmware/transport validity. Unimplemented site tests are NOT RUN, never PASS. G05 manual/control authorization, G07 durable journaling, G08 security, W02 signed/offline packaging, P00 site decisions, H01 actual equipment and R01 cutover remain separate mandatory gates.

Source contracts: `docs/P00_DECISION_CONTRACTS.md`, `docs/G04_A_CONTROLLER_CONTRACT.md`, `docs/G06_A_PROFILE_RUNNER_CONTRACT.md`, `docs/G08_MIN_SECURITY.md`, and branch contracts in G05 #28 / G07-A #27 / G08-full #29.

**NO-GO to real connections, control and certification until signed authorization and independent witnessed HIL.**


## H02 scope separation (2026-10-15) — historical; H02 archived 2026-10-26

H01 supervised manual HIL, including its opt-in over LAN and any manual soak,
is NOT authorization for G06 physical profile execution. The separately
permitted H02 engineering profile test subsequently passed on 2026-10-20; its
authorization applied only to that exact revision/profile/run. See the
[H02 verification plan](../archive/h02/docs/H02_PROFILE_VERIFICATION_PLAN.md). That permit
path is retired; current physical profiles use isolated lab mode and the G06/G07/G04/G08 controls.
