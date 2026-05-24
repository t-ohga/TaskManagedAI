---
id: "task-01-api-capability-token-schema-completed"
status: "completed"
created_at: "2026-05-24"
updated_at: "2026-05-24"
---

# Completion: API Capability Token Schema

## Completed

- Added `ApiCapabilityToken` SQLAlchemy model.
- Added migration `0031_sp016_api_capability_tokens.py`.
- Added table to schema introspection tenant/FK/metadata coverage.
- Added schema constraint/index regression assertions.
- Updated SP-016 Review with batch 0a status.

## Verification

- PASS: `uv run ruff check ...`
- PASS: `uv run mypy ...`
- PASS: `uv run alembic upgrade head`
- PASS: `uv run alembic downgrade 0030_sp015_inter_agent_messages && uv run alembic upgrade head`
- PASS: `uv run pytest tests/db/test_schema_introspection.py -q` (`24 passed`)
- KNOWN FAIL: `uv run alembic check` still fails because `migrations/env.py` does not provide target metadata for autogenerate.
