---
id: "task-01-sp016-kickoff-blockers-self-review"
status: "completed"
created_at: "2026-05-24"
updated_at: "2026-05-24"
---

# Self Review: SP-016 Kickoff Blockers

## Findings

| id | severity | finding | disposition |
|---|---|---|---|
| SR-001 | HIGH | ADR-00015 remained proposed while SP-016 expected implementation to start. | Adopted: ADR-00015 accepted and SP-016 `adr_refs` synchronized. |
| SR-002 | HIGH | CLI canonical remained unresolved, which would cause implementation/test naming drift. | Adopted: `tm` canonical selected after local/Homebrew conflict checks; `tmai` retained only as future fallback. |
| SR-003 | MEDIUM | `message` / `audit` / `export` / `sprint` command draft did not match the 13 capability matrix. | Adopted: non-parity policy added; `sprint` assigned to `taskhub` admin scope. |
| SR-004 | MEDIUM | `api_capability_tokens` DDL lacked exact lifecycle/audit details for implementation. | Adopted: DDL, hashes, status, deny audit, replay handling, and migration name fixed in ADR-00015/SP-016. |
| SR-005 | MEDIUM | Existing dogfooding parser test expected SP-013 to be draft although SP-013 is completed on current main. | Adopted: test expectation updated and verified. |

## Checklist

- [x] No code implementation beyond stale test expectation repair.
- [x] No raw token / raw credential storage introduced.
- [x] `tm` decision grounded in local command / Homebrew exact search checks.
- [x] Tailscale config mutation remains out of scope.
- [x] Verification commands recorded in completion report.
