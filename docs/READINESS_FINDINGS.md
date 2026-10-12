# Migration readiness findings — canonical closure ledger

Original review baseline: GUI `9bbbc6d`, driver `67978f9` (2026-10-12). Status rechecked against GUI `ef473e1` and driver `9323e37`. **Original review SHAs are historical, not the current implementation.** `B`/`H`/`M` are the only valid IDs for the 2026-10-12 readiness review. Older unidentified `BLOCKER-01`–`HIGH-10` tags in previous plans have been retired rather than guessed into equivalence. See [P00 contracts](P00_DECISION_CONTRACTS.md).

| ID | Severity | Finding | Work item / closure evidence | Status |
|---|---|---|---|---|
| B1 | BLOCKER (hardware) | Unbounded/ambiguous TCP exchange | Driver PR #2 merged as `9323e37` with 3.9/3.12 CI; H01 framing certification | SOFTWARE FIX MERGED; HIL OPEN |
| B2 | BLOCKER (hardware) | STOP verification and uncertainty | Driver PR #2 `9323e37` implements attempted STOP + readback; G04 fencing/HIL still outstanding | DRIVER FIX MERGED; G04/HIL OPEN |
| B3 | BLOCKER (hardware) | Unsigned model envelope and failure response | P00 signed site limits/policy and H01 | OPEN: SITE |
| B4 | BLOCKER (release) | Controller/persistence/security/HIL absent | G01–G08, H01, W01/W02, R01 | OPEN |
| H1 | HIGH | Non-finite driver numeric inputs | Driver PR #2 `9323e37` and unit tests | SOFTWARE FIX MERGED |
| H2 | HIGH | Null gradient inherits prior hardware state | P00 explicit baseline semantics + G06 tests/HIL | ENGINEERING CONTRACT DRAFTED; HIL PENDING |
| H3 | HIGH | Zero-stability, gaps, deadline ambiguity | P00 virtual-clock semantics + G06 tests | ENGINEERING CONTRACT DRAFTED; CODE OPEN |
| H4 | HIGH | Loopback hardware authentication gate too late | G08-min prerequisite to G05 and live HIL | SEQUENCE CORRECTED; CODE OPEN |
| H5 | HIGH | Previous finding IDs undefined | This ledger and sequence linkage, P00 PR #6 | CLOSED (documentation) |
| H6 | HIGH | Legacy demo CSV migration ambiguous | GUI PR #8 `2ef81b6` adds strict parser and legacy-source-preserving ZIP; [GUI PR #12](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/12) adds transactional SQLite revisions with strict schema checks. G03-C UI/editor still pending | CORE VERIFIED; STORAGE IN PR #12; UI OPEN |
| H7 | HIGH | SQLite/filesystem crash gap | G07 journal/recovery/fault tests | ENGINEERING CONTRACT DRAFTED; CODE OPEN |
| H8 | HIGH | CI/dependency/driver pin insufficient | [GUI #10](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/10) `ef473e1` pins direct dependencies and driver revision; [Windows CI green](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/actions/runs/38261039285). Hash-locked transitive freeze, typing and offline VM gates pending | PARTIAL — release gate OPEN |
| M1 | MEDIUM | One-device multi-vendor architecture unproven | GUI PR #7 `c978ef9` and follow-up #9 `e8519ad`, Windows 3.10/3.12 CI | G01 FOUNDATION MERGED; G04 CONTROL OPEN |
| M2 | MEDIUM | Windows freezing/offline unverified | W01 scripts/Windows CI, W02 offline VM | OPEN |

**Definition of closure:** a merged PR and passing unit/static/integration checks alone close a code finding only to **software-verified** status. Safety-related findings require signed site documentation and physical HIL. Each future PR must update the row's status, exact merged commit/test run link, and owner/approver; never claim HIL from mocks. Hardware remains disabled in the current demo.

## Implemented PR audit trail

- Driver [PR #2](https://github.com/ami3go/VotschTechnik-climate-chamber-Python/pull/2): `9323e3701f3befedcc23b45170a851fd327f0bcc`, mocked transport/STOP tests green, no HIL.
- GUI [PR #6](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/6): P00 requirements/traceability contracts, `635c453`.
- GUI [PR #7](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/7): vendor-neutral G01 foundation, `c978ef9`.
- GUI [PR #9](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/9): vendor-specific branch isolation correction, `e8519ad`.
- GUI [PR #8](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/8): G03 profile migration core, `2ef81b6`.
- GUI [PR #10](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/10): pins CI-tested direct dependencies and hardened driver revision, `ef473e1`.

All release, HIL, Windows offline and operational security gates remain mandatory.

## Active status/next-PR source of truth

See [DEVELOPMENT_SEQUENCE.md](DEVELOPMENT_SEQUENCE.md) for per-delivery-unit progress, proposed G02-A/G03-B/W01-A/G04-A/G08-min-A PR order, acceptance and review/merge loops. **No site approval or HIL is recorded.** Hardware remains disabled. Status updates must distinguish phase-complete evidence from a merged foundation or demo.
