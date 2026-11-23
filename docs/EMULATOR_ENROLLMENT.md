# Bench emulator enrollment (EMU-ENROLL-01)

**Status:** implemented on branch `feat/emulator-enrollment`; software tests
pass; live G04 bench check against the Leonardo/W5500 emulator **PASS**
(2026-11-22). This is **not** physical HIL, site acceptance, R01 release
approval or a substitute for a real Vötsch chamber.

## 1. Why this exists

The GUI previously had only two device classes:

* an in-process `FakeBackend` (simulation), or
* a real Vötsch chamber admitted by a physical `CHAMBER_HIL_*` authorization.

A network emulator such as the Arduino Leonardo R3 + W5500 `SIMLEO0001` board
speaks the real driver protocol over TCP/2049, but it is not a chamber. Treating
it as simulation skips the real G04/G06/G07 path; treating it as physical HIL
pretends a bench board is a chamber and pollutes physical evidence. The
Leonardo runbook therefore kept GUI-to-emulator activation blocked.

This feature adds a third, explicitly **bench-emulator** device class. It runs
the real driver, backend, controller, profile-runner and recording path, while
remaining clearly non-physical in identity, UI, audit and admission.

## 2. Trust model

An operator signs one exact enrollment with an Ed25519 key provisioned outside
the browser and repository. The server verifies it before opening a socket.

The signed record binds:

| Field | Required value / check |
| --- | --- |
| `scope` | exactly `EMULATOR_BENCH_DEVICE` |
| `backend_id` | exactly `votsch_emulator` |
| `expected_serial` | starts with `SIM`, 4–16 alphanumeric characters |
| `expected_model` | exactly `VT4011-EMULATOR` (driver-reported) |
| `address` | private, non-loopback IPv4 literal |
| temperature envelope | finite, inside −40…130 °C, span ≤ 60 °C |
| validity | explicit UTC, maximum 14 days, must include now |
| `isolated_network_ack` | must be `true` |
| `operator`, `approval_reference` | non-empty |
| `firmware_sha256` | optional 64-hex evidence binding |

The server also refuses to start if:

* any `CHAMBER_HIL_*`, `CHAMBER_LAB_MODE` or `CHAMBER_H02_*` setting is present
  (the operating policies are mutually exclusive);
* `CHAMBER_RELEASE`, `CHAMBER_W02_RELEASE` or `CHAMBER_PRODUCTION` is enabled;
* the enrollment/key file is a symlink, oversized, or group/world writable;
* the trusted key is absent, not exactly 32 bytes, or the signature fails;
* the enrollment is expired, premature or longer than 14 days.

**Residual risk:** the AVR firmware has no cryptographic device attestation.
A matching USB/Ethernet serial and the `VT4011-EMULATOR` model are strong
software-visible discriminators, not proof of the physical board. A malicious
host on the same network could spoof the protocol. This is why the enrollment
is bench-only, private-IPv4-only, mutually exclusive with physical policies,
and why the runbook still requires an isolated test LAN. Do not move this
mechanism to a production chamber.

## 3. Operator workflow

```bash
python -m scripts.emulator_enroll keygen \
  --private-key /secure/bench.key --public-key-out /secure/bench.pub

python -m scripts.emulator_enroll template \
  --out spec.json --chamber-id leo-emu \
  --address 192.168.31.146 --serial SIMLEO0001 \
  --min-c 15 --max-c 35 --valid-hours 24

# Edit spec.json: operator, approval_reference, envelope and validity are the
# operator's decision. Replace every REPLACE_ME.
python -m scripts.emulator_enroll sign \
  --spec spec.json --private-key /secure/bench.key --out enrollment.json

python -m scripts.emulator_enroll verify \
  --enrollment enrollment.json --public-key /secure/bench.pub
```

The signing tool prints the full record and requires the operator to type
`ENROLL` at an interactive terminal. It verifies the signature before writing.
Keep the private key off the server PC where practical; the server only needs
the public key and the signed enrollment.

## 4. Server configuration

Exactly one trusted-key source:

```bash
export CHAMBER_EMULATOR_ENROLLMENT_FILE=/secure/enrollment.json
export CHAMBER_EMULATOR_TRUSTED_KEY_FILE=/secure/bench.pub
# or: export CHAMBER_EMULATOR_TRUSTED_KEY=<base64 32-byte public key>
export CHAMBER_EMULATOR_ACK=ISOLATED-BENCH-EMULATOR
```

Launch the normal server (`python main.py` or the desktop launcher). The UI
shows `BENCH EMULATOR`, the signed serial/address/envelope, and a persistent
“NOT a climate chamber” banner. Do **not** set any `CHAMBER_HIL_*`,
`CHAMBER_LAB_MODE` or H02 variable in the same process.

If the GUI server is bound to a LAN address, `CHAMBER_EMULATOR_ALLOW_LAN=1`,
TLS and a specific bind host are additionally required. The default is a
loopback server controlling a bench emulator on the isolated test LAN.

## 5. Runtime behavior

* `ChamberIdentity.is_emulator=True`, `is_simulation=False`,
  `backend_id="votsch_emulator"`.
* The adapter still owns the driver; the GUI never speaks the protocol.
* Serial and model are re-verified on every `read_status`; an endpoint swap is
  rejected.
* The signed envelope becomes the controller capability range.
* G04 operator leases, verified readback, STOP/UNKNOWN fencing and generation
  reconciliation remain unchanged.
* G06 profile admission accepts the emulator without an H02 permit or PIN, but
  the run is labelled emulator and still uses G08 authorization, the run
  journal, G06 deadlines and the G04 verified-STOP preflight.
* G07 recording remains the normal recorder; evidence must say
  `EMULATOR_BENCH_CHECK`, never physical HIL.
* Packaged/offline runtimes refuse the emulator configuration.

## 6. What this does and does not unblock

**Unblocked for development**

* Full NiceGUI → G04/G05/G06/G07 path against a network device.
* Profile execution, pause/resume/stop, recording and export UI testing.
* Capability-driven features (setpoint, start/stop, outputs, gradients) once
  the driver/firmware exposes them.
* Repeatable regression runs without a real chamber or HIL PIN.

**Still separate gates**

* Physical chamber identity, envelope, STOP performance, site acceptance and
  R01 release remain physical/site decisions.
* The emulator does not prove physical emergency-stop timing, relay behaviour,
  sensor accuracy or chamber safety.
* Digital-output/ramp writes are still capability-gated; the Leonardo driver
  reports outputs 1–8 and ramp readback, but profile gradient writes remain
  opt-in.
* Multi-chamber scheduling is still out of scope (`ChamberManager` enforces one
  configured device).

## 7. Bounded G06/G07 profile check

After the read-only and narrow write check succeeds, exercise the normal
profile runner and durable journal with the signed enrollment:

```bash
CHAMBER_EMULATOR_ENROLLMENT_FILE=/secure/enrollment.json \
CHAMBER_EMULATOR_TRUSTED_KEY_FILE=/secure/bench.pub \
CHAMBER_EMULATOR_ACK=ISOLATED-BENCH-EMULATOR \
python scripts/h02_watchdog_command.py \
  --timeout-s 180 --idle-timeout-s 60 \
  --log-dir /tmp/emulator-profile-check -- \
  python scripts/emulator_profile_check.py \
    --serial SIMLEO0001 \
    --evidence /tmp/emulator-profile-check/evidence.json
```

The script requires an uninterrupted read-only identity/STOP stability window
before its first profile mutation. It then runs two steps through G06: verified
gradients, digital output 2 ON/OFF and chamber run ON/OFF. A result is PASS only
when the runner reaches `COMPLETED`, G07 durably finalizes the run and the final
independent G04 state is `VERIFIED_STOPPED`. Any timeout, non-success terminal
state, journal failure or unverified restore is a failure. This emulator path
does not use a HIL PIN.

## 8. Verified bench evidence (2026-11-22)

Live device: `192.168.31.146:2049`, serial `SIMLEO0001`, model
`VT4011-EMULATOR`, STOPPED, 23.0 °C, USB-CDC identity matched the Ethernet
identity.

`scripts/emulator_bench_check.py` through the bounded watchdog:

* read-only: **PASS** — G04 connect, emulator identity, verified STOPPED;
* writes: **PASS** — setpoint 24.0 °C, START/running readback, reached within
  0.2 °C, STOP verified `VERIFIED_STOPPED`.

This is emulator evidence only. It does not change issue #112 or any physical
HIL/site/release result.
