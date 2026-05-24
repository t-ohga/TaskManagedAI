---
id: "sp016-api-capability-tokens-completion-report"
status: "completed"
created_at: "2026-05-24"
updated_at: "2026-05-24"
---

# SP-016 API Capability Tokens Completion Report

## Summary

SP016-T01 is complete. The database now has a principal-bound `api_capability_tokens` schema for CLI operation tokens, with hash-only token storage, composite tenant FKs, TTL bounds, scope structure checks, revocation consistency, and metadata raw-secret denial.

## Changed Files

- `backend/app/db/models/api_capability_token.py`
- `backend/app/db/models/__init__.py`
- `migrations/versions/0031_sp016_api_capability_tokens.py`
- `tests/db/test_schema_introspection.py`
- `docs/sprints/SP-016_ui_cli_parity.md`
- `docs/codex-handoff/2026-05-24-sp016-api-capability-tokens/*`

## Verification

- PASS: `uv run ruff check backend/app/db/models/api_capability_token.py backend/app/db/models/__init__.py migrations/versions/0031_sp016_api_capability_tokens.py tests/db/test_schema_introspection.py`
- PASS: `uv run mypy backend/app/db/models/api_capability_token.py tests/db/test_schema_introspection.py`
- PASS: `uv run alembic upgrade head`
- PASS: `uv run alembic downgrade 0030_sp015_inter_agent_messages && uv run alembic upgrade head`
- PASS: `uv run pytest tests/db/test_schema_introspection.py -q` (`24 passed`)
- KNOWN FAIL: `uv run alembic check` still fails because `migrations/env.py` does not provide target metadata for autogenerate. This is existing repository infrastructure debt, not introduced by this batch.

## Deferred

- SP016-T02 auth endpoints and token issue/revoke service.
- SP016-T03-T06 CLI implementation.
- SP016-T07 parity contract tests.
- SP016-T08 CLI token misuse negative tests.
