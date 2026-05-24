# task-03 batch 0d Self-Impl-Review

## verdict

- task: SP-015 batch 0d trusted_instruction defense
- status: READY for batch 0e
- unresolved CRITICAL: 0
- unresolved HIGH: 0
- unresolved MEDIUM: 0

## implementation reviewed

- `backend/app/services/inter_agent/publisher.py`
- `backend/app/services/inter_agent/__init__.py`
- `tests/inter_agent/test_trusted_instruction.py`
- `docs/sprints/SP-015_inter_agent_communication.md`

## adversarial findings

| id | severity | category | decision | result |
|---|---|---|---|---|
| T03-0D-R1-001 | HIGH | caller-supplied trust promotion | adopt | `InterAgentPublishRequest` still rejects `trust_level`, `approval_request_id`, and `action_class`; trusted publish uses internal `TrustedInstructionGrant`. |
| T03-0D-R1-002 | HIGH | stale / mismatched approval reuse | adopt | Service verifies approved status plus artifact_hash / policy_version / provider_request_fingerprint / action_class equality before writing trusted refs. |
| T03-0D-R1-003 | HIGH | non-human approval decider | adopt | Service requires `ApprovalRequest.decided_by_actor_id` to resolve to a human actor. |
| T03-0D-R1-004 | HIGH | source artifact boundary | adopt | Service loads `source_artifact_id` under the same tenant/project and verifies `content_hash` equals the approval-bound artifact hash. |
| T03-0D-R1-005 | MEDIUM | forbidden action class | adopt | `merge` / `deploy` are excluded from the trusted inter-agent action subset. |

## invariant checklist

- [x] trusted_instruction cannot be requested through caller-facing schema.
- [x] approval must exist and be `approved`.
- [x] approval decider must be human.
- [x] artifact_hash binding is exact.
- [x] policy_version binding is exact.
- [x] provider_request_fingerprint binding is exact.
- [x] action_class binding is exact and limited to trusted inter-agent subset.
- [x] source Artifact belongs to the same tenant/project and matches content_hash.
- [x] DB CHECK still enforces trusted_instruction server-owned refs at persistence layer.

## verification

```bash
TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/inter_agent/test_trusted_instruction.py -q
# 10 passed, 18 warnings

TASKMANAGEDAI_ENVIRONMENT=test \
TASKMANAGEDAI_DATABASE_URL=<local test db> \
TASKMANAGEDAI_REDIS_URL=<local redis> \
TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET=<dummy> \
TASKMANAGEDAI_RUN_DB_TESTS=1 \
uv run pytest tests/inter_agent/ tests/db/test_schema_introspection.py -q
# 53 passed, 82 warnings

uv run ruff check backend tests migrations
# All checks passed

uv run mypy backend/app/db/models/inter_agent_message.py \
  backend/app/schemas/inter_agent.py \
  backend/app/services/inter_agent \
  tests/inter_agent \
  tests/db/test_schema_introspection.py
# Success: no issues found in 11 source files
```

## readiness gate

- CRITICAL = 0
- HIGH = 0 after adopted fixes
- Batch 0e may start.
