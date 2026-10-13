# W02 — offline Windows packaging and certification evidence

Status: **IMPLEMENTATION IN PROGRESS / RELEASE NO-GO**. This work extends W01-A; it does not authorize live chamber communications. Server startup and application data remain owned by the existing W01 launcher and G08/G07 components.

## Release trust model

W01 build-manifest.json and SHA256SUMS.txt detect accidental changes only. W02 introduces w02-release.json and an Ed25519 signature over canonical JSON and its complete closed file inventory. **Hashing alone cannot establish publisher authenticity.** The site must independently pin the approved Ed25519 public key (not trust a key copied from the same unverified ZIP). The private key must be provided only on a protected signing host/CI secret, never embedded in source control, an artifact, or on target machines. Neither the unsigned GitHub CI artifact nor example signing keys constitute a trusted release.

Sign the extracted completed bundle on a trusted signing host (Python 3.12 + pinned cryptography), with the exact Git commit SHA:

```powershell
python -m scripts.w02_release --sign --bundle .\ClimateChamber-Web-Windows-x64-1.0.0-offline --version 1.0.0 --source-sha <40-or-64-character-hex-sha256-value> --private-key C:\Protected\release-private.pem
python -m scripts.w02_release --verify --bundle .\ClimateChamber-Web-Windows-x64-1.0.0-offline --public-key C:\SiteTrusted\release-public.pem
```

The current CLI requires 64 hex characters for source_sha (SHA-256 provenance identifier); a Git SHA-1 commit must instead be recorded in an independently archived provenance record. Do not claim the provided manifest alone proves source/build reproducibility. Verification requires a trusted *external* Python verifier; it is **not yet a Python-free target verifier**. Execution before trusted verification remains prohibited by deployment policy, not yet hard-enforced by the launcher.

For upgrade staging: `python -m scripts.w02_release --stage-update --bundle OLD --candidate NEW --backup PREVIOUS --public-key C:\SiteTrusted\release-public.pem`. This only validates and stages a verified rollback copy; it intentionally does **not** swap running binaries or migrate G07/G08 databases. Same-version replacement and downgrade are refused. Operators must stop the app and use a controlled deployment runbook. Failed or interrupted staging is fail-closed.

## Integration boundaries

- W01 owns the single-instance launcher/server, loopback binding and shortcut helper.
- G08-min provides interactive `server\ClimateChamberServer.exe --bootstrap-admin` with no default credential. G08-full PR #29 remains draft; backup/access controls and dedicated diagnostics must be integrated only after merge.
- G07-A PR #27 remains draft; do not invent a recorder backup or schema migration until its storage contract merges.
- G05 PR #28 remains draft; the bundle is simulator-only, and UI STOP is not an emergency stop.
- The build host uses online `pip install` with currently **unlocked transitive dependencies**. This cannot yet be described as reproducible or supply-chain-certified. Establish a hash-locked wheelhouse with offline `pip --no-index --require-hashes`, complete SPDX/CycloneDX SBOM and redistribution/license approval.

## Required independent acceptance matrix (all pending)

| Evidence ID | Environment / procedure | Required evidence | Current status |
| --- | --- | --- | --- |
| W02-VM10 | Fresh Windows 10 x64, user without admin, Python/Git/Node absent, NIC physically disconnected | OS build, VM snapshot ID, SHA-256 ZIP, Windows Event Viewer, browser console/network HAR, startup/read pages | **NO-GO: not performed** |
| W02-VM11 | Fresh Windows 11 x64 with no connectivity, software prereqs absent | Same, per-user NTFS ACL checks and browser/WebSocket tests | **NO-GO: not performed** |
| W02-AUTH | G08 merged final code with separate browser operator/viewer and session revocation | Login/bootstrap + refresh, expiry, CSRF/origin denial and multi-client test log | **NO-GO** |
| W02-DATA | G07 merged final recorder and G03 persistent profile migrations | Encrypted off-host backup, corrupted backups, crash/restart and rollback; evidence hashes | **NO-GO** |
| W02-PKG | Source-locked wheel closure, signed approved key, complete license inventory and SBOM | Wheel digests, provenance, verified signature on disconnected host | **NO-GO** |
| W02-OPS | Planned/unplanned shutdown, logoff/reboot, PID lock, restore, diagnostic redaction | Process-tree observations, no live I/O and site acceptance | **NO-GO** |
| W02-EGRESS | Browser assets and packaged server in isolated VM | Windows firewall outbound deny + DNS audit/DevTools HAR; no CDN, external URLs or pip execution | **NO-GO** |

**Do not merge as production release or claim Windows offline certification** before these gates close with exact accepted SHA, job URLs, signed operator/QA results, and independently verified threat model. W01 simulated CI on connected Windows is not an air-gap test.
