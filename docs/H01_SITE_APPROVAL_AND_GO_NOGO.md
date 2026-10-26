> **HISTORICAL APPROVAL RECORD — H02 SECTION ARCHIVED (2026-10-26).** The H02 physical-profile approval path no longer exists; the signed H02 evidence is preserved under `../archive/h02/`.

# H01 — Site permit checklist and GO / NO-GO decisions

**Default decision for every real physical action: NO-GO.**

Site authority must verify and sign all items **outside the GUI**:
- [ ] Exact nameplate model, serial, installed options, firmware and approved OEM manual revision.
- [ ] Site-approved operating limits, gradient units/limits/readback/restoration or permanent gradient disable.
- [ ] Approved physical STOP and independent emergency-stop procedures, training and immediate local supervision.
- [ ] Thermal/electrical/fire/specimen risk assessment and manufacturer alarm/fault procedure.
- [ ] Driver pinned SHA and certified firmware readbacks/communications/STOP semantics.
- [ ] G05/G06/G07/G08 software integration, authentication/authorization and independent safety/security review.
- [ ] G04 exclusive process/device ownership, STOP fencing and no unsafe automatic retries/resume.
- [ ] Windows host/service offline deployment, PKI/firewall/ACL/backup and W02 approved configuration.
- [ ] Individually signed test method, authority, physical operator, second witness and separate crash/network/power permits.
- [ ] H01 reports with raw independent physical evidence, deviation closure, and R01 signoff.

| Gate | Decision now | Permitted transition |
|---|---|---|
| H01 documentation and simulated harness merge | PENDING CI + independent review | Merge code/docs only; NEVER enable real I/O |
| Physical connection | NO-GO | Signed site authorization + separate reviewed executable live test architecture |
| START/setpoint/profile | NO-GO | Certified limits, operator and physical STOP readiness, independently verified HIL |
| Web STOP as emergency stop | PERMANENT NO-GO | Not an emergency-stop system |
| Gradient mutation | NO-GO | Certified units/range/readback and approved baseline/restoration |
| Power-loss test | NO-GO | Explicit separate high-risk authorization |
| Unattended/LAN/release | NO-GO | Full G08/W02/H01/R01 signoff and approved site safety case |

**Outstanding findings:** B1 transport HIL, B2 physical STOP, B3 signed envelope, B4 integration and HIL, H2 gradient baseline, H4 security integration, H7 durability/crash, H8 supply-chain/offline Windows evidence. A commit hash, CI run or simulated STOP cannot close any physical blocker.

Independent review must inspect: module import isolation (Vötsch protocol only in external driver), G04 queue and admitted-call STOP limitations, G05/G08 authenticated mutation and lease-independent STOP, G07 intent-before-write/UNKNOWN recovery, G08 host/LAN threats, W02 service shutdown and physical on-site safety. Document actual reviewer identity and signoff; AI-assisted review alone does not constitute independent safety approval.


## H02 physical profile authorization — historical; H02 archived 2026-10-26

Any earlier H01 manual-control authorization is insufficient for automated
profile execution. A separately permitted, witnessed H02 engineering run passed
on 2026-10-20 with the independent watchdog and G04/G06/G07/G08 integration.
The H02 stack is archived; current physical profiles use isolated lab mode.
That result authorizes no later run and does not itself provide independent/site
acceptance. Future runs need their own signed permit, approved STOP procedure
and named in-person operator/witness; intrusive fault injection needs additional
permission. Software CI/PR merge cannot authorize physical profiles.
