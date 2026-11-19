# H01 — Equipment inventory (historical site acceptance checklist)

> For current agent-run physical HIL *tests*, use the local operator-issued
> PIN described in [HIL_PIN_RUNBOOK.md](HIL_PIN_RUNBOOK.md), not a site
> permit/signature/witness package. This equipment inventory still documents
> independent hardware/safety checks and the distinct certification process.

Every value below must cite approved OEM manual section, calibration and a signed local inspection. Do not infer from FakeBackend (-40…130 °C), injected Vötsch mock (-20…80 °C), screenshots, firmware assumptions or driver command codes. Project plans mention VT4011, **but site model is unverified**.

| Required site evidence | Recorded value | Status |
|---|---|---|
| Manufacturer and exact model nameplate | NOT PROVIDED | OPEN |
| Serial number / manufacture and installed options | NOT PROVIDED | OPEN |
| Firmware / controller version | NOT PROVIDED | OPEN |
| Approved OEM document title, ID and revision | NOT PROVIDED | OPEN |
| Communication interface, cable, network segregation and host | NOT VERIFIED; driver source uses TCP port 2049 but installed interface unknown | OPEN |
| Site-certified minimum/maximum temperature, fixture/sample derating | NOT PROVIDED | OPEN |
| Independent thermometer/calibration and readback tolerance | NOT PROVIDED | OPEN |
| Certified gradient up/down, units, limit, readback and baseline restoration | NOT PROVIDED; unavailable for HIL | BLOCKED |
| OEM alarm codes, faults, physical interlocks | NOT VERIFIED | OPEN |
| Actual START/manual control/STOP interpretation | NOT VERIFIED | OPEN |
| Local STOP and *separate* emergency-stop procedures | NOT PROVIDED | OPEN |
| Physical supervision, trained operator and alternate safety response | NOT PROVIDED | OPEN |
| Test operator PIN (24 h; never record value) | Not issued in repository; issued at bench | OPERATOR ACTION |
| Windows host account/ACL, local lock, TLS/firewall, offline security | NOT VERIFIED | OPEN |
| Approved power-loss hazard analysis and special permit | NOT AUTHORIZED | BLOCKED |
| Driver provenance | `9323e3701f3befedcc23b45170a851fd327f0bcc` (software pin ONLY) | PARTIAL |

Physical test: operator/UTC time: __________ ; HIL PIN validity (do not record PIN): __________ ; serial/STOP verified: __________ .

Separate product/site certification (if applicable): owner/safety officer/witness/permit: __________ .

**Physical I/O: NOT APPROVED.**
