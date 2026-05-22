# task-05 batch A Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- ADR-00027 accepted
- ADR-00012 accepted
- SP-0045 status `draft` to `ready`
- Tool Registry canonical enums
- `config/tool_registry.toml`
- Pydantic TOML loader and manifest lock hash
- frontend enum source
- loader regression tests

## Findings

- T05-BATCH-A-F001 / HIGH / adopt:
  - finding: Importing `loader` from `backend.app.services.tool_registry.__init__`
    caused a `python -m backend.app.services.tool_registry.loader` runtime
    warning because the package imported the target module before execution.
  - fix: Removed loader re-export from package `__init__`; direct submodule
    import remains supported and CLI validate now emits clean output.
- T05-BATCH-A-F002 / HIGH / adopt:
  - finding: Raw TOML hashing would create false lockfile drift when tool rows
    are reordered.
  - fix: `compute_allowlist_hash` hashes a canonical sorted projection and
    regression coverage verifies row-order independence.
- T05-BATCH-A-F003 / MEDIUM / adopt:
  - finding: Duplicate `tool_key` rows could overwrite each other in a dict.
  - fix: `LoadedToolRegistry` rejects duplicates before exposing the mapping.
- T05-BATCH-A-F004 / MEDIUM / adopt:
  - finding: `experimental` provenance plus non-public data class could weaken
    ADR-00027 without an ADR update.
  - fix: Pydantic model rejects `experimental` tools above `public`.
- T05-BATCH-A-F005 / MEDIUM / defer:
  - finding: Existing ADR/Sprint Pack markdownlint has broad pre-existing
    style debt unrelated to batch A.
  - follow-up: Keep new task-05 review artifact markdownlint clean; full docs
    style cleanup belongs to task-08 docs drift.

## Readiness gate

- CRITICAL: 0
- HIGH: 0
- MEDIUM open: 0 for batch A implementation
- deferred: existing docs style debt only
- status: READY for PR

## Verification

- `uv run pytest tests/services/tool_registry -q`
- `uv run python -m backend.app.services.tool_registry.loader --validate config/tool_registry.toml`
- targeted ruff:
  - `tests/services/tool_registry`
  - `backend/app/domain/tool_registry`
  - `backend/app/services/tool_registry`
- targeted mypy:
  - `backend/app/domain/tool_registry`
  - `backend/app/services/tool_registry`
  - `tests/services/tool_registry/test_registry_loader.py`
- `pnpm -C frontend typecheck`
- `pnpm -C frontend lint`
- `markdownlint docs/codex-handoff/2026-05-22-3day-autonomous/reviews/task-05-self-plan-review.md`
- `git diff --check`
