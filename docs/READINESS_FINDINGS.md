# Migration readiness findings — canonical closure ledger

Review baseline: GUI main `9bbbc6d`, driver main `67978f9`, 2026-10-12. `B`/`H`/`M` are the only valid IDs for the 2026-10-12 readiness review. Older unidentified `BLOCKER-01`–`HIGH-10` tags in previous plans have been retired rather than guessed into equivalence. See [P00 contracts](P00_DECISION_CONTRACTS.md).

| ID | Severity | Finding | Work item / closure evidence | Status |
|---|---|---|---|---|
| B1 | BLOCKER (hardware) | Unbounded/ambiguous TCP exchange | D01 driver PR + fault-injection tests + H01 framing certification | IN PROGRESS; HIL PENDING |
| B2 | BLOCKER (hardware) | STOP verification and uncertainty | D01, G04 STOP fencing, site STOP matrix, H01 | IN PROGRESS; HIL PENDING |
| B3 | BLOCKER (hardware) | Unsigned model envelope and failure response | P00 signed site limits/policy and H01 | OPEN: SITE |
| B4 | BLOCKER (release) | Controller/persistence/security/HIL absent | G01–G08, H01, W01/W02, R01 | OPEN |
| H1 | HIGH | Non-finite driver numeric inputs | D01 unit/boundary tests | IN PROGRESS |
| H2 | HIGH | Null gradient inherits prior hardware state | P00 explicit baseline semantics + G06 tests/HIL | ENGINEERING CONTRACT DRAFTED; HIL PENDING |
| H3 | HIGH | Zero-stability, gaps, deadline ambiguity | P00 virtual-clock semantics + G06 tests | ENGINEERING CONTRACT DRAFTED; CODE OPEN |
| H4 | HIGH | Loopback hardware authentication gate too late | G08-min prerequisite to G05 and live HIL | SEQUENCE CORRECTED; CODE OPEN |
| H5 | HIGH | Previous finding IDs undefined | This ledger and sequence linkage | DOCUMENTED |
| H6 | HIGH | Legacy demo CSV migration ambiguous | G03 conversion/original-preservation tests | ENGINEERING CONTRACT DRAFTED; CODE OPEN |
| H7 | HIGH | SQLite/filesystem crash gap | G07 journal/recovery/fault tests | ENGINEERING CONTRACT DRAFTED; CODE OPEN |
| H8 | HIGH | CI/dependency/driver pin insufficient | Per-repo CI, G01 conformance, driver commit pin, Windows tests | OPEN |
| M1 | MEDIUM | One-device multi-vendor architecture unproven | G01 strict one-physical-device guard, 3 backend fixtures | OPEN |
| M2 | MEDIUM | Windows freezing/offline unverified | W01 scripts/Windows CI, W02 offline VM | OPEN |

**Definition of closure:** a merged PR and passing unit/static/integration checks alone close a code finding only to **software-verified** status. Safety-related findings require signed site documentation and physical HIL. Each future PR must update the row's status, exact merged commit/test run link, and owner/approver; never claim HIL from mocks. Hardware remains disabled in the current demo.
