# task-03 Self-Plan-Review

Date: 2026-05-22 JST

## Inputs Read

- `docs/codex-handoff/2026-05-22-3day-autonomous/tasks/task-03-sp022-1-scripts-hardening.md`
- `docs/sprints/SP-022-1_scripts_wrapper_hardening.md`
- `docs/deploy/mac-single-host-smoke-sop.md`
- `scripts/taskhub_backup_orchestrator.py`
- `scripts/taskhub_destructive_lock.py`
- `scripts/taskhub_admin.py`
- `tests/scripts/test_taskhub_backup_orchestrator.py`

## Source Drift Decision

The startup prompt references `SP-022-1_scripts_hardening.md`,
`scripts/backup_orchestrator.py`, `compose.yaml`, and `Dockerfile.eval`.
Those files do not exist in the current repo. The current canonical Sprint Pack
is `SP-022-1_scripts_wrapper_hardening.md`, with implementation targets
`scripts/taskhub_backup_orchestrator.py`, `scripts/taskhub_admin.py`,
`scripts/taskhub_destructive_lock.py`, `docker-compose.yml`, and deployment SOPs.

Decision: adopt the Sprint Pack and current repo names as source of truth; treat
the startup prompt target names as stale aliases.

## Batch Plan

| batch | scope | rationale |
|---|---|---|
| 1 | pg_dump flag cleanup + backup path allowlist helper + healthcheck timing docs/tests | Low-risk source hardening with direct unit-test coverage. |
| 2 | SOPS env missing path + stale destructive lock helper | More behavioral risk; keep separate for focused review. |
| 3 | alembic wrapper + SOP §13 grep coverage + Layer C runbook | Docs/wrapper polish; can be isolated from backup core. |
| 4 | Sprint Pack completion + task-03 completion report | Final docs once all prior PRs are merged. |

## Round 1 Findings

| id | severity | finding | decision |
|---|---|---|---|
| T03-P1-001 | HIGH | Backup orchestrator already rejects legacy 5-field claims in Phase 5; reworking claim schema now would risk ADR Gate #8 without new value. | adopt: do not rewrite claim model; add/regress only where drift remains. |
| T03-P1-002 | HIGH | `pg_dump --format=custom --single-transaction` is still present in host and compose paths and matches Sprint Pack deviation 4. | adopt in batch 1. |
| T03-P1-003 | MEDIUM | Allowlist roots are currently local variables in `BackupOptions.from_environment`, while SOP describes path policy separately. | adopt: extract helper/constants and reference them from tests/docs. |
| T03-P1-004 | MEDIUM | docker healthcheck timing in `docker-compose.yml` remains conservative retries=3/start_period=5s, while stale startup prompt asks for longer Mac-friendly values. | adopt cautiously: extend start_period/retries without changing service commands. |
| T03-P1-005 | MEDIUM | `.env.encrypted` missing with `include_sops_env` differs between legacy and Phase 5; this may affect signed claim fingerprint. | defer to batch 2 because it touches approval/runtime binding. |
| T03-P1-006 | MEDIUM | stale destructive lock auto-cleanup can race if implemented too aggressively. | defer to batch 2 with explicit PID+age tests. |
| T03-P1-007 | LOW | `Dockerfile.eval` target is stale; no such file exists. | reject for current repo; record in completion as stale handoff target. |

## Readiness Gate

- Residual CRITICAL: 0
- Residual HIGH: 0 for batch 1 after scoped plan
- Proceed with batch 1 only.
