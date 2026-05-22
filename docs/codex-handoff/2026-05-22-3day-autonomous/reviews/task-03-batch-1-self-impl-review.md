# task-03 batch 1 Self-Impl-Review

Date: 2026-05-22 JST

## Scope Implemented

- Removed `--single-transaction` from both host `pg_dump --format=custom` and
  docker compose exec `pg_dump --format=custom` argv builders.
- Extracted backup source binding allowlist into
  `backup_path_allowed_roots()` and `validate_backup_source_path_allowed()`.
- Reused the helper for compose file and env file path validation.
- Extended docker compose healthcheck retry timing for Mac/local startup
  stability without changing service commands.
- Added regression tests for pg_dump argv and source path allowlist behavior.
- Added a local type annotation for existing cleanup-failure state so targeted
  mypy on the touched backup orchestrator file passes.

## Adversarial Review Findings

| id | severity | finding | decision |
|---|---|---|---|
| T03-B1-R1-001 | HIGH | Removing `--single-transaction` must cover both direct host pg_dump and compose exec pg_dump, otherwise Phase 5 remains inconsistent. | adopt: both argv builders changed and tested separately. |
| T03-B1-R1-002 | MEDIUM | Extracting allowlist helper could silently change accepted roots if repo root resolution differs from existing code. | adopt: helper resolves repo root with `expanduser().resolve(strict=False)`, matching previous local variable behavior; tests assert the exact root tuple. |
| T03-B1-R1-003 | MEDIUM | Healthcheck retry changes could mask real unhealthy services if timeout is also expanded. | reject: timeout remains 5s and only interval/retries/start_period are adjusted. |
| T03-B1-R1-004 | LOW | Startup prompt names `compose.yaml`, but repo uses `docker-compose.yml`. | adopt as source-drift note in plan review; implementation targets the actual repo file. |

## Checklist

- CRITICAL findings: 0
- HIGH findings after fixes: 0
- Server-owned path boundary preserved: yes
- Weak assertions avoided: yes; tests assert concrete argv absence and exact allowlist roots.
- Secret/token exposure risk: none; no logging or env value output added.
- Migration/API/DB contract touched: no
- Rollback: revert this batch commit; no schema or runtime data migration.

## Local Verification

- PASS: `uv run ruff check scripts/taskhub_backup_orchestrator.py tests/scripts/test_taskhub_backup_orchestrator.py`
- PASS: `uv run mypy scripts/taskhub_backup_orchestrator.py`
- PASS: `uv run pytest tests/scripts/test_taskhub_backup_orchestrator.py -q` (56 passed)
- PASS: `docker compose -f docker-compose.yml config --quiet` with a temporary local `.env.local` containing dummy values, removed after the check.
- PASS: `git diff --check`
- KNOWN DEBT: `uv run ruff check scripts tests/scripts` still fails on pre-existing files outside this batch (`scripts/ci/_drill_timer_scanner.py`, `scripts/ci/_extract_changed_deps.py`, `scripts/ci/_intake_scanner.py`, `scripts/ci/_phase_e_trace_verifier.py`, `scripts/taskhub_signed_journal_offline.py`).
- KNOWN DEBT: `uv run mypy scripts` still fails on pre-existing files outside this batch (`scripts/taskhub_keyring.py`, `scripts/taskhub_approval_issuance.py`, `scripts/wal_archiving_check.py`, `scripts/kpi_rollup_run.py`).
