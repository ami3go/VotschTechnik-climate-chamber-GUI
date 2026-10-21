# W02 — Windows offline signed-release foundation and acceptance ledger

**Status: SOFTWARE FOUNDATION MERGED / RELEASE NO-GO.** [PR #30](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/30) merged 2026-10-15 as `0e9e9cd546cc675f06734272a67c4a8ce7a9da70` after its PR-head Windows checks passed; the certification gates in this document remain OPEN.
This extends W01-A; no second launcher, no new chamber I/O owner and no enablement of physical Vötsch communication. W01's frozen PyInstaller executable remains a **simulation-only** portable prototype. A green connected Windows Actions job does not certify disconnected Windows 10/11 or release signing.

## Build and architecture

- The W01 scripts `scripts/build_windows_launcher.ps1` and `scripts/build_windows_offline.ps1` are the sole launcher/freezer path. Build natively on Windows x64 with Python **3.12** and PowerShell 5.1+; Windows 10 and 11 x64 target baselines remain **unverified**. The browser is an OS-installed browser, not bundled.
- Bundles include NiceGUI and `chamber_web` assets, the FakeBackend and alternate test stub. The pinned external Vötsch Python dependency is included by default through the dedicated `VotschBackend` import path, but G04 rejects physical I/O. `-SimulationOnly` omits the external driver and is non-release test scope.
- `setup_environment.py` from merged PR #33 is an **online developer bootstrap** (may run pip/Git/Playwright downloads). It is not, and must not be invoked as, a frozen/offline updater or on-target installation requirement.
- W01 still resolves packages using connected pip without verified full transitive wheel hashes. The W01 archive's SHA256SUMS is a corruption checksum, **not** a publisher authentication mechanism. The CI artifact is unsigned.
- The W01 manifest builder now emits `sbom.cdx.json` (CycloneDX 1.5), `THIRD_PARTY_LICENSES.csv`, and `build-provenance.json` *before* hashing files into `build-manifest.json`. These are deterministic **build-environment inventory** artifacts; every license is `REVIEW_REQUIRED`, the dependency closure is `UNVERIFIED`, and source provenance is `UNATTESTED`. **They are not a complete frozen dependency closure, an approved license report, or signed provenance.**

## Cryptographic trust and signing

`scripts/w02_release.py` creates `w02-release.json` (canonical ASCII-serialized JSON, Ed25519 signature `w02-release.sig`) and validates a complete closed inventory, Windows case-insensitive name/file-directory collisions, unsafe NTFS paths, reparse-point/symlink checks, altered/missing/extra files, invalid signatures and W01's legacy file hashes. The two W02 signature sidecars are excluded **only** in the explicitly W02-authorized W01 validation; standalone W01 continues rejecting unlisted files.

**Publisher keys MUST be distributed out of band.** Do not copy a public key out of the unverified ZIP or use a test key from CI; verification rejects an embedded public key path. Generate an Ed25519 signing key on a protected dedicated signing host, store the private key in secured escrow/HSM, and record fingerprint, issuer, approval, rotation, compromise and revocation procedure in the site release register. Protect key access with independent authorizations; never upload private keys to artifacts/repository.

On a trusted isolated signing station with approved Python and the pinned `cryptography` dependency, after producing and extracting the unsigned W01 bundle:

```powershell
python -m scripts.w02_release --sign --bundle .\ClimateChamber-Web-Windows-x64-1.0.0-offline --version 1.0.0 --source-sha <64-lowercase-hex-of-reviewed-source-provenance> --private-key C:\Protected\w02-private.pem
python -m scripts.w02_release --verify --bundle .\ClimateChamber-Web-Windows-x64-1.0.0-offline --public-key C:\SiteTrusted\w02-publisher.pem --min-version 1.0.0
```

The 64-character source SHA-256 field is a **claimed provenance reference**, not a signed builder attestation. A Git SHA-1 commit ID cannot substitute for it. Verify exact source/tree, build logs, dependency fingerprints and signing attestation *out of band*. The site must independently pin the trusted publisher key **and** the minimum accepted version before first install. A copied manifest cannot define its own trusted rollback floor. Version floors must be maintained in a separately protected site policy; no such on-target policy store is implemented yet.

**Target-side software verifier candidate:** `scripts/w02_target_verifier.py` is a no-launch, no-network, no-hardware archive verifier intended to be frozen independently using PyInstaller `--onefile` as `ClimateChamberReleaseVerifier.exe`. It pre-validates ZIP entries for traversal/NTFS aliasing, zip expansion limits and unsafe links, extracts into a fresh `.pending` quarantine, checks an out-of-band Ed25519 publisher key and externally pinned minimum version against every file, and stages via same-volume rename only after verification. `scripts/verify_w02_release.ps1` uses Windows PowerShell 5.1 `Get-FileHash` to check an **independently supplied** verifier SHA-256 before invoking the EXE. The PowerShell script, verifier binary and expected hash must themselves be distributed/attested separately by the site; a digest taken from the untrusted bundle cannot authenticate the verifier.

Example **candidate** procedure; not a production-authorized package, and do not treat a test/CI hash or key as approved:

```powershell
# On a trusted Windows x64 build/signing station, not the target:
python -m pip install pyinstaller==6.16.0 -r requirements-w02-build.txt
python -m PyInstaller --noconfirm --clean --onefile --console --name ClimateChamberReleaseVerifier --paths . scripts/w02_target_verifier.py

# On target in a trusted offline PowerShell 5.1 console, before any GUI launch:
powershell.exe -NoProfile -File C:\SiteTrusted\verify_w02_release.ps1 `
  -Archive D:\Transfer\W02-signed.zip -InstallDir C:\AppStaging\ClimateChamber-1.0.0 `
  -VerifierPath C:\SiteTrusted\ClimateChamberReleaseVerifier.exe `
  -VerifierSha256 <64-lowercase-hex-OUT-OF-BAND-approved-verifier-digest> `
  -TrustedPublicKey C:\SiteTrusted\publisher.pem -MinimumVersion 1.0.0
```

The independently provisioned verifier and PowerShell 5.1 wrapper require **exact Windows CI proof and separate clean disconnected Windows 10/11 testing**, controlled signing/Authenticode or protected digest attestation, site trust-key management, permissions review and security approval. Until then the release gate **remains fail-closed / NO-GO**. Signed production W02 artifacts have **not** been generated with a site-approved key.

## Air-gap dependency closure (S2-03 software increment)

`scripts/w02_closure.py` produces and verifies the **complete transitive dependency
closure** of the frozen Windows runtime: every wheel pinned by SHA-256, resolved
natively on the target platform, installable with no index access.

| Command | Purpose |
|---|---|
| `python -m scripts.w02_closure build` | Resolve the closure with pip, download every wheel into a wheelhouse, verify each SHA-256 and write `requirements-w02-runtime.lock` + `w02-closure-manifest.json` |
| `python -m scripts.w02_closure verify` | Fail closed unless the wheelhouse is *exactly* the locked closure: a damaged, missing or extra artifact is a refusal |
| `python -m scripts.w02_closure install` | Prove the offline installation with `pip install --no-index --find-links <wheelhouse> --require-hashes` |
| `python -m scripts.w02_closure sbom` | Emit the **runtime** CycloneDX SBOM and license inventory from the closure |

Rules the tool enforces, each of which closes a specific way a previous
release could have been wrong:

- **Resolution happens natively on the target.** `pip --platform` evaluates
  environment markers against the *build* interpreter, which silently produces
  a wrong closure on Windows (a Linux-only `uvloop` dependency). A wrong
  closure is worse than none, so a foreign-platform resolution is refused.
- **Wheels only.** An sdist would need a compiler on the target and cannot be
  hash-verified after a build.
- **Every entry is pinned and hashed.** An unhashed entry is refused; the lock
  is pip `--require-hashes` compatible so the same file proves the install.
- **The runtime SBOM comes from the closure**, not from the build environment.
  A build host contains build-only tools (PyInstaller, pip, setuptools) that
  are not shipped; the previous `sbom.cdx.json` was exactly such an inventory
  and is marked `unapproved-build-environment-not-runtime-closure`.
- **No license is self-approved.** Every row of the license inventory stays
  `REVIEW_REQUIRED`; only a qualified reviewer and the site release register
  can approve redistribution.

**This is connected-build-host software evidence, not certification.** The
Windows CI job (`airgap-closure` in `w02-release-validation.yml`) resolves,
downloads, verifies and installs the closure on a connected Windows runner.
That proves the closure is complete and hash-verified; it does **not** prove
the disconnected clean-Windows 10/11 acceptance (Stage 2 S2-04), the site
publisher key, the signed artifact or the independent supply-chain review.
The external Vötsch driver is not part of the PyPI closure and still has to be
vendored as a locally built wheel on the Windows build host with its own
recorded hash before an air-gap install can be complete.

## Updates, backups and data safety

`python -m scripts.w02_release --stage-update --bundle OLD --candidate NEW --backup PREVIOUS --public-key C:\SiteTrusted\w02-publisher.pem` verifies both software trees, refuses same-core/same-version and downgrades, rejects aliasing/overlapping staging directories and creates a verified copy of OLD using `PREVIOUS.pending` followed by rename. It does **not** replace binaries, stop processes, migrate SQLite or back up user data; do not mistake this for an installed/atomic updater.

**Required operator procedure (NOT yet certified):** stop the existing server and verify process exit; independently verify NEW and the site's version floor; preserve immutable backups of profile revisions, G07 run journals/exports and G08 security credentials, audited events and cookie-signing keys under restricted OS ACLs; inspect SQLite `quick_check` and approved schema version; stage candidate on the same volume, keep live data outside executable trees; run migrations with version checks and a pre-migration snapshot; then atomically switch a supervised executable pointer; restart in simulated mode only, validate bootstrap/login, continuity/revocation policy and run recovery; on failure, restore **verified** original binaries and matching data snapshot, never silently replay chamber commands. Retain hashes, logs, timestamps and two-person approval.

This transactional install/migration/rollback sequence is **not implemented** and must not be described as an automated update. G03-C profile SQLite, G07-A recorder and G08-full security storage are distinct owners; their changes must be integrated only after their separate PRs merge. Windows NTFS ACL validation, logoff/restart supervision, credential-safe logging, restored-session policy, corrupt backup rejection and upgrade-interruption drills are not certified.

## CI and release evidence

`W02 signed-inventory` Windows Python 3.10/3.12 runs Ruff plus adversarial tests against cryptography and W01 checks. The W01 workflow builds the frozen x64 simulator and launches it on a **connected** Windows runner. The H01 extended merged workflow exercises simulated web/GUI/browser behavior; it is **not** a physical HIL or disconnected test.

| Gate | Status as of 2026-10-14 | Acceptable closure |
| --- | --- | --- |
| Code signing and closed-file inventory | **PARTIAL SOFTWARE** | Final-head 3.10/3.12 Windows unit results, independent review |
| Connected Windows frozen x64 smoke | **EARLY W01 evidence only** | Final-head W01 job and extraction / simulator launch |
| Complete lockfile, hashes and air-gap wheel closure | **SOFTWARE TOOLING MERGED; WINDOWS CLOSURE ARTIFACT PENDING REVIEW** | Approved wheelhouse hash lock, offline pip resolution and damaged-wheel negative tests — tooling and negative tests merged ([S2-03](#air-gap-dependency-closure-s2-03-software-increment)); the generated Windows closure still has to be reviewed and committed, and the disconnected install still has to be proven on a clean target |
| SBOM and license/provenance review | **PROVISIONAL FILES ONLY** | Reviewed runtime/component inventory with licenses, signed build provenance — the runtime SBOM is now derived from the locked closure, but every license row is still `REVIEW_REQUIRED` and the provenance is still unattested |
| Independent target-side verifier with no Python | **CANDIDATE CODE / NO-GO** | Frozen tool + PowerShell 5.1 Windows CI, independently attested tool/key policy, clean offline Windows 10/11 evidence |
| Profile/G07/G08 data migration and reversible upgrade | **NO-GO** | Atomic stage/swap, snapshot, schema and interrupted-update trials |
| Windows service/portable logoff/reboot and NTFS credentials | **NO-GO** | Clean-VM functional and security observations and site-approved policy |
| H01 simulated web/GUI | **MERGED UPSTREAM; W02 compatibility pending** | Exact final-head H01 CI and frozen browser checks |
| Windows 10 clean VM with NIC disconnected | **NOT PERFORMED** | OS build, snapshot, no Python/Git, offline launcher/web traces, event logs |
| Windows 11 clean VM with NIC disconnected | **NOT PERFORMED** | Same plus ACL/Chrome/Edge WebSocket and session checks |
| Independent security/supply-chain review | **NOT OBTAINED** | Qualified independent approval on the exact accepted head |
| Production/site/physical release | **NO-GO** | W02 + G05/G07/G08 + P00 signed site policy + H01 physical HIL |

### Disconnected Windows 10/11 acceptance runbook (future site QA)

On **clean** isolated x64 VMs with Python, Git, Node and build tools absent, record OS build, browser version, VM snapshot ID, security policy/ACLs and independent publisher-verifier identity. Physically disconnect NIC or enforce a logged firewall deny-all egress policy; record network status and DNS/firewall evidence. Transfer the signed release separately from a site-pinned verifier/key/minimum-version policy; run the verifier's **quarantine extraction** and signature validation before staging or executing any app binary; hash the transfer ZIP and check every unpacked file. Confirm offline first-admin bootstrap, read-only pages, two independent browsers, viewer denial/session revocation, CSV/profile run in FakeBackend, simulated STOP and G07 crash recovery (when merged), clean shutdown, logoff/reboot, reinstall, tamper, backup/rollback and no runtime pip/CDN/outbound requests. Save event logs, browser console + HAR, signed evidence hashes and operator/QA approvals.

**Do not use an internet-connected Actions runner as replacement for this procedure.** No physical chamber is connected and Web STOP is not a physical emergency stop.

## Integration/merge decision — closed 2026-10-15 / gates re-affirmed 2026-10-18

[W02 PR #30](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/30) merged 2026-10-15 as `0e9e9cd546cc675f06734272a67c4a8ce7a9da70` after its PR-head Windows checks passed; G05 [#28](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/28), G07-A [#27](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/27) and G08-full [#29](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/29) merged the same day. This was a software-foundation integration only. Independent Windows clean-VM certification, site-approved publisher keys, signed release artifacts and operational approval remain **OPEN / NO-GO**; neither PR merge nor unit-test success grants hardware enablement or a certified W02 release.
