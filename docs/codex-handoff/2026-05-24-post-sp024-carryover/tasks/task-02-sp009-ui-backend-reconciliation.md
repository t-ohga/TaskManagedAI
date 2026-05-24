# task-02: SP-009 UI / Backend Reconciliation

## Purpose

Reconcile SP-009 after later UI, API, i18n, settings, and CLI work. SP-009 currently says `skeleton_pending_backend`, but SP-012 / SP-016 / SP-024 may have closed part of the original gap.

## Required Reads

1. `docs/sprints/SP-009_p0_ui_pack.md`
2. `docs/sprints/SP-012_p0_acceptance.md`
3. `docs/sprints/SP-016_ui_cli_parity.md`
4. frontend routes under `frontend/app/(admin)/`
5. frontend API client under `frontend/lib/api/`
6. backend routes under `backend/app/api/`
7. tests covering settings, tickets, approvals, agent runs, audit, and session API

## Output

Produce a reconciliation update that answers:

- which SP-009 UI surfaces are already real,
- which backend endpoints are still absent,
- which old UI requirements are now superseded,
- which SP-009 items should become SP-009-5 or P0.1,
- which next implementation PR is smallest and safest.

## Scope Rules

- Prefer read-only list/detail wiring before mutations.
- Do not add approval `request_revision` unless a separate accepted plan exists.
- Do not expose raw provider response, raw tool args, or raw realtime payload.
- Do not make frontend KPI values source-of-truth; backend ledger remains authoritative.

## Verification Seed

```bash
corepack pnpm@10.18.0 --dir frontend exec tsc --noEmit
corepack pnpm@10.18.0 --dir frontend exec eslint <touched-files> --max-warnings=0
corepack pnpm@10.18.0 --dir frontend exec vitest run <targeted-tests>
uv run ruff check backend/app/api tests/api
PYTHONPATH=cli uv run mypy backend/app/api tests/api
uv run pytest tests/api -q
git diff --check
```
