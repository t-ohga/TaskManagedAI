# task-05 batch B Self-Impl-Review

Date: 2026-05-22 JST

## Scope

- migration `0029_sp0045_tool_registry_core`
- `tool_registry` explicit `registry_version`, `allowed_actions`, and
  `max_outgoing_data_class` columns
- `tool_versions` history table
- ORM model updates
- DB contract test updates

## Findings

- T05-BATCH-B-F001 / HIGH / adopt:
  - finding: Adding non-null columns to `tool_registry` without replacing the
    tenant seed trigger would break future tenant creation.
  - fix: Migration replaces `seed_tool_registry_network_for_tenant()` with
    SP-0045 columns and restores the SP-014 form on downgrade.
- T05-BATCH-B-F002 / HIGH / adopt:
  - finding: Existing SP-014 seeded rows needed deterministic backfill before
    NOT NULL and CHECK constraints were added.
  - fix: Migration backfills `registry_version`, `allowed_actions`, and
    `max_outgoing_data_class` from existing `manifest` or `tool_key`.
- T05-BATCH-B-F003 / MEDIUM / adopt:
  - finding: `manifest->allowed_actions` alone cannot enforce
    cross-source enum integrity at the DB layer.
  - fix: Added explicit `allowed_actions` JSONB with DB CHECK rejecting any
    value outside the four read-only actions.
- T05-BATCH-B-F004 / MEDIUM / adopt:
  - finding: `tool_versions` could accept non-hash lock values.
  - fix: Added `tool_versions_ck_allowlist_hash_sha256_hex` and a negative
    DB contract test.
- T05-BATCH-B-F005 / MEDIUM / defer:
  - finding: Actual `alembic check` could not connect because this worktree has
    no `.env.local`; `scripts/worktree_setup.sh` ran successfully but SOPS is
    unavailable on this host, so env decryption was skipped.
  - follow-up: Keep as environment/infrastructure defer. Syntax, head chain,
    migration history, and wrapper dry-run were verified locally.

## Readiness gate

- CRITICAL: 0
- HIGH: 0
- MEDIUM open: 0 for batch B implementation
- deferred: live DB alembic execution blocked by missing local env only
- status: READY for PR

## Verification

- `uv run ruff check` on migration, ORM model, and tool registry tests
- `uv run mypy` on ORM model and loader tests
- `uv run pytest tests/services/tool_registry -q`
- `uv run python -m py_compile migrations/versions/0029_sp0045_tool_registry_core.py`
- `uv run python -m backend.app.services.tool_registry.loader --validate config/tool_registry.toml`
- `uv run alembic heads`
- `uv run alembic history -r 0028_sp014_tool_registry_network:head`
- `bash scripts/alembic_wrapper.sh --dry-run upgrade head`
- `git diff --check`
