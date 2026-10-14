# W02 — Packaging, supply-chain and Windows security review

**Review type: AI-assisted implementation assessment, NOT independent security approval or Windows release certification.** Review of existing PR #30 after incorporating merged main H01 simulation and PR #33 developer setup. No physical equipment was contacted or enabled.

| Finding | Severity | Engineering disposition | Remaining gate |
| --- | --- | --- | --- |
| W02-R01: signed-inventory CI blocked at Ruff F401 | LOW, gate blocker | Unused Python imports removed; Windows lint reached actual tests | Exact final-head CI |
| W02-R02: W01 verifier rejects W02 signature sidecars | HIGH, functionality | Added explicit W02-only sidecar list to W01 verifier; legacy W01 standalone closed inventory unchanged. Regression check added | Final Windows 3.10/3.12 verification |
| W02-R03: Python 3.10 has no `hashlib.file_digest` | HIGH, compatibility | Now uses existing W01 streaming SHA-256 utility. Real Windows 3.10 regression run passes on an intermediate head | Final-head matrix |
| W02-R04: Windows path names and backup traversal | HIGH | New reserved-device/trailing-character/casefold/file-directory collision, symlink/junction checks; backup staging refuses overlapping source/candidate roots. Tests added | Reparse-point and junction testing on native clean Win10/11 |
| W02-R05: release trust key obtained from bundle | HIGH | Code rejects publisher-key path under release tree; signed canonical payload must be verified by external key. Out-of-band trust operationally required | Publisher key-escrow/trust-root provisioning not implemented/approved |
| W02-R06: rollback/downgrade bypass on first install | HIGH | Added caller-supplied `--min-version` policy to Python verifier, and reject same/downgrade in staging | **OPEN**: tamper-resistant persistent min-version policy; approved key rotation/revocation |
| W02-R07: independent Python-free on-target signature verifier absent | **BLOCKER** | PowerShell 5.1 helper intentionally refuses execution, rather than accepting unsigned SHA-256 | **OPEN**: separately distributed/verified on-target Ed25519 verifier and isolated Win10/11 test |
| W02-R08: online un-hash-locked transitive dependency resolution | **BLOCKER** | Provisional CycloneDX 1.5 build inventory, license CSV and source/provenance disclaimers added to W01 hashed files | **OPEN**: reviewed hash-locked offline wheelhouse, full frozen-runtime SBOM, licenses and provenance attestation |
| W02-R09: updater does not atomically switch binaries or migrate/restore data | **BLOCKER** | Software only validates and stages a rollback copy; no unsafe automatic upgrade introduced | **OPEN**: G03/G07/G08 snapshot/migrations/schema policies, power-fail and corrupted backup drills |
| W02-R10: single-instance/local data/logoff security not certified | **HIGH** | W01 launcher retained; G08 owns identity/sessions; app remains loopback/mock only | **OPEN**: NTFS ACL owner/DACL, logoff/reboot, Windows service supervision, protected credentials/logs |
| W02-R11: offline egress/GUI/simulated hardware compatibility unproven | **HIGH** | Existing H01 simulated web/browser checks retained from main; W01 connected-host frozen launch is separate evidence | **OPEN**: network-denied Windows 10/11 clean-VM browser HAR/DNS/firewall traces with no Python/Git |
| W02-R12: signed release provenance and operational approval absent | **BLOCKER** | No signing key is committed or CI-generated artifact promoted as a trusted release | **OPEN**: independent signer, key-management approval, signed artifact provenance, site QA and release approval |

## Trust and control invariants

1. Signed `w02-release.json` authenticates an exact file tree **only when** the verifying public key is independently trusted; mere SHA256SUMS, an embedded key, and a green CI are not proof of publisher authenticity.
2. W01 remains the sole frozen launcher/runtime packaging architecture; external driver dependency can be present but device communication remains simulation-only. `setup_environment.py` is an online developer helper and is never part of the target-side startup.
3. The W01 legacy inventory is strict by default. W02 explicitly requests the two signature sidecar exceptions only after verifying the signed W02 inventory; no arbitrary extra executable is allowlisted.
4. G04 remains the sole command authority; G05/G07/G08 drafts must integrate via accepted mainline changes. No hardware connection, live enable flag, unauthenticated STOP exception, new vendor protocol or automatic run replay may be introduced.
5. None of the findings requiring independent review, clean-VM acceptance or site signoff are closed by this document itself.

**Software merge disposition: BLOCKED pending final-head CI, required independent review, and applicable BLOCKER/HIGH software acceptance.** **Offline/operational deployment: NO-GO.** **Physical HIL: NOT AUTHORIZED.**
