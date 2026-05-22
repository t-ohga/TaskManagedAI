# task-03 batch 3 Self-Impl-Review

Date: 2026-05-22 JST

## Scope Implemented

- Added `scripts/alembic_wrapper.sh` to run Alembic inside the `api`
  container while stripping host/container `TASKMANAGEDAI_DATABASE_URL` and
  `DATABASE_URL` overrides from the Alembic process.
- Updated `docs/deploy/mac-single-host-smoke-sop.md` §4 to use the wrapper for
  `current` and `upgrade head`.
- Expanded `docs/deploy/mac-single-host-smoke-sop.md` §13 into §13.1-§13.6
  with DATABASE_URL extraction, verify command, failure grep, pass marker grep,
  SSH diagnostic grep, and evidence capture.
- Added `docs/deploy/layer-c-operator-runbook.md` with operator sections §1-§9.
- Added regression tests for wrapper dry-run behavior, SOP references, §13 grep
  coverage, and Layer C runbook section coverage.

## Adversarial Review Findings

- T03-B3-R1-001 HIGH:
  Alembic wrapper must strip host env before Docker Compose interpolation and
  strip container env before `uv run alembic`; doing only one side leaves the
  Phase 7a drift path. Decision: adopt. The wrapper prefixes host command with
  `env -u ...` and container command with `env -u ...`.
- T03-B3-R1-002 HIGH:
  A wrapper without dry-run would make verification require a live Docker stack.
  Decision: adopt. `--dry-run` prints the exact sanitized command and is covered
  by tests.
- T03-B3-R1-003 MEDIUM:
  Ruff should not be pointed at shell scripts as Python files. Decision: adopt.
  Verify shell syntax with `bash -n`, and run ruff only on Python regression
  tests.
- T03-B3-R1-004 MEDIUM:
  SOP §13 grep patterns could miss SSH/network diagnostics if only
  signed-journal reason codes are scanned. Decision: adopt. Add
  `VERIFY_SSH_PATTERN` and explicit §13.5 expected output.

## Local Verification

- PASS: `uv run ruff check tests/scripts/test_alembic_wrapper.py`
- PASS: `uv run mypy tests/scripts/test_alembic_wrapper.py`
- PASS: `uv run pytest tests/scripts/test_alembic_wrapper.py -q` (5 passed)
- PASS: related scripts pytest suite (74 passed)
- PASS: `bash -n scripts/alembic_wrapper.sh`
- PASS: `bash scripts/alembic_wrapper.sh --dry-run upgrade head`
- PASS: markdownlint on new Layer C runbook and batch 3 review artifact
- PASS: `git diff --check`
- KNOWN DEBT: `uv run ruff check scripts tests/scripts` still fails on
  pre-existing files outside this batch (`scripts/ci/_drill_timer_scanner.py`,
  `scripts/ci/_extract_changed_deps.py`, `scripts/ci/_intake_scanner.py`,
  `scripts/ci/_phase_e_trace_verifier.py`,
  `scripts/taskhub_signed_journal_offline.py`).
- KNOWN DEBT: `uv run mypy scripts` still fails on pre-existing files outside
  this batch (`scripts/taskhub_keyring.py`,
  `scripts/taskhub_approval_issuance.py`, `scripts/wal_archiving_check.py`,
  `scripts/kpi_rollup_run.py`).
- KNOWN DEBT: `markdownlint docs/deploy/mac-single-host-smoke-sop.md` still
  fails on pre-existing line-length/table/single-H1/list-spacing issues across
  the file. This batch updated targeted §4/§13 content and regression-tested the
  required markers instead of repo-wide doc reformatting.

## Checklist

- CRITICAL findings: 0
- HIGH findings after fixes: 0
- DB migration side effect: none; wrapper dry-run only used for local verification.
- Secret leakage risk: none; tests assert injected DSN secrets do not appear in
  dry-run output.
- Rollback: revert this batch commit; no schema, data migration, or external
  state change.
