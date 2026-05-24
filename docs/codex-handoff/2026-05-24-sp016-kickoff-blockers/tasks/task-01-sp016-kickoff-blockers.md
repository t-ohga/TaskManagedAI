---
id: "task-01-sp016-kickoff-blockers"
status: "completed"
priority: "P0"
created_at: "2026-05-24"
updated_at: "2026-05-24"
---

# Task 01: SP-016 Kickoff Blockers

## Objective

Close SP-016 pre-implementation blockers as doc-only work before starting CLI/API/migration implementation.

## Required Decisions

- ADR-00015 must move from proposed to accepted.
- CLI canonical `tm` vs `tmai` must be resolved.
- 13 capability matrix drift with `message` / `audit` / `export` / `sprint` command draft must be resolved.
- `api_capability_tokens` DDL, deny audit, and replay handling must be fixed in the plan.
- Tailscale `tag:taskhub-cli` config changes must remain gated as external-exposure changes.

## Non-Goals

- No CLI code.
- No backend endpoint.
- No migration file.
- No Tailscale config mutation.
