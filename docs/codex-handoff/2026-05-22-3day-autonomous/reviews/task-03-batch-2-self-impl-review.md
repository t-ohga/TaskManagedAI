# task-03 batch 2 Self-Impl-Review

Date: 2026-05-22 JST

## Scope Implemented

- Added explicit optional `.env.encrypted` skip behavior for backup SOPS env
  inclusion when the file is absent.
- Kept non-missing SOPS read errors fail-closed with
  `backup_payload_source_unreadable`.
- Added `sops_env_missing_at_lock` so Phase 5 redeem/archive can distinguish
  expected optional absence from an unbound verified copy bug.
- Added stale destructive lock cleanup helper that removes a lock only when:
  file age exceeds the threshold, payload has a pid, that pid is absent, the
  lock file is regular, and a non-blocking flock can be acquired.
- Added targeted regression tests for SOPS skip fingerprinting/redeem and stale
  lock cleanup keep/remove cases.

## Adversarial Review Findings

| id | severity | finding | decision |
|---|---|---|---|
| T03-B2-R1-001 | HIGH | Treating all missing verified SOPS copies as skip would hide Phase 5 binding bugs. | adopt: skip is allowed only when admin marked `sops_env_missing_at_lock=True`; otherwise existing fail-closed error remains. |
| T03-B2-R1-002 | HIGH | Stale lock cleanup could remove an active lock if it checks only mtime and pid. | adopt: cleanup must also acquire `LOCK_EX | LOCK_NB`; active flock-held files are not removed. |
| T03-B2-R1-003 | MEDIUM | Optional SOPS skip could still call `resolve(strict=True)` in fingerprint context and fail before skip. | adopt: fingerprint context resolves SOPS realpath only when an actual SOPS hash is present. |
| T03-B2-R1-004 | MEDIUM | PID existence checks are ambiguous under permission errors or invalid pids. | adopt: permission-denied and non-positive/invalid pid payloads are treated as not safe to remove. |
| T03-B2-R1-005 | MEDIUM | Tests covered direct fingerprint but not full-helper issue/redeem paths, leaving a regression gap around skip vs fail-closed behavior. | adopt: add issue full-helper skip test and redeem unbound-without-marker reject test. |

## Local Verification

- PASS: `uv run ruff check scripts/taskhub_backup_orchestrator.py scripts/taskhub_admin.py scripts/taskhub_destructive_lock.py tests/scripts/test_taskhub_backup_orchestrator.py tests/scripts/test_taskhub_destructive_lock.py`
- PASS: `uv run mypy scripts/taskhub_backup_orchestrator.py scripts/taskhub_admin.py scripts/taskhub_destructive_lock.py`
- PASS: `uv run pytest tests/scripts/test_taskhub_backup_orchestrator.py tests/scripts/test_taskhub_destructive_lock.py -q` (69 passed)
- PASS: `git diff --check`
- KNOWN DEBT: `uv run ruff check scripts tests/scripts` still fails on pre-existing files outside this batch (`scripts/ci/_drill_timer_scanner.py`, `scripts/ci/_extract_changed_deps.py`, `scripts/ci/_intake_scanner.py`, `scripts/ci/_phase_e_trace_verifier.py`, `scripts/taskhub_signed_journal_offline.py`).
- KNOWN DEBT: `uv run mypy scripts` still fails on pre-existing files outside this batch (`scripts/taskhub_keyring.py`, `scripts/taskhub_approval_issuance.py`, `scripts/wal_archiving_check.py`, `scripts/kpi_rollup_run.py`).

## Checklist

- CRITICAL findings: 0
- HIGH findings after fixes: 0
- Secret/plaintext leakage risk: none; absent `.env.encrypted` produces a warning, not file content logging.
- Active destructive operation boundary preserved: yes; cleanup requires non-blocking flock acquisition.
- Rollback: revert this batch commit; no schema, data migration, or external state change.
