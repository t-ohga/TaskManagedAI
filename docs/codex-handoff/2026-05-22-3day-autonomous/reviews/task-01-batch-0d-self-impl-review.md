# task-01 batch 0d Self-Impl-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0d Tool Registry network enum + tool_network_policies
- protocol: `00-codex-behavior-guide.md` §3.2 Self-Impl-Review
- implementation target:
  - `migrations/versions/0028_sp014_tool_registry_network.py`
  - `backend/app/db/models/tool_registry.py`
  - `backend/app/domain/tool_registry/network_policy.py`
  - `backend/app/services/tool_registry/network_policy.py`
  - `tests/services/tool_registry/test_network_policy.py`
  - `docs/adr/00030_tool_registry_network_enum.md`

## implemented

- Added `tool_registry` with `network_access in ('none','allowlist','internet')`.
- Added `tool_network_policies` with domain allowlist, payload data-class cap, and provider requirement.
- Seeded `web_fetch` and `docs_search` as deny-only `network_access='none'` for existing and new tenants.
- Added Tool Registry network domain constants and fail-closed service guard.
- Created accepted ADR-00030 and updated SP-014 / DD-02 / architecture docs.

## adversarial review findings

| id | severity | category | symptom | judgment | fix |
|---|---|---|---|---|---|
| SP014-B0D-IMPL-R1-F001 | HIGH | ADR collision | ADR-00021 path in prompt was already occupied. | adopt | Created ADR-00030 and did not modify ADR-00021. |
| SP014-B0D-IMPL-R1-F002 | HIGH | direct internet | `network_access='internet'` could become an implicit allow. | adopt | Service guard denies internet mode; test asserts reason code. |
| SP014-B0D-IMPL-R1-F003 | MEDIUM | seed semantics | web_fetch/docs_search registration could be mistaken for allow. | adopt | Seed `deny_only=true` and `network_access='none'`; service guard denies. |
| SP014-B0D-IMPL-R1-F004 | MEDIUM | allowlist safety | Domain/payload/provider checks could be too weak. | adopt | Exact domain, payload ordinal, provider-required tests added. |

## invariant checklist

- 5+ source enum integrity: PASS for network_access (Literal + frozenset + DB CHECK + migration + pytest + ADR/DD docs).
- deny-by-default: PASS; default seeded tools deny.
- direct internet deny: PASS; service guard rejects `internet`.
- new tenant seed: PASS; trigger creates deny-only web_fetch/docs_search.
- raw secret / token leakage: PASS; no secret values or capability tokens introduced.
- action_class separation: PASS; web_fetch/docs_search remain Tool Registry actions, not ADR-00009 action_class values.

## verification

- `uv run ruff check backend tests`: PASS
- `uv run mypy backend`: PASS (`262 source files`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/services/tool_registry/test_network_policy.py -q`: PASS (`7 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/services/tool_registry/test_network_policy.py tests/policy/test_policy_profile_seed.py -q`: PASS (`15 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/db/test_repository_layer.py tests/db/test_schema_introspection.py tests/test_seeds.py -q`: PASS (`37 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/multi_agent/ -q`: PASS (`47 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/runtime/test_agent_run_events.py tests/runtime/test_agentrun_transitions.py -q`: PASS (`51 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... uv run alembic downgrade -1`: PASS
- `TASKMANAGEDAI_DATABASE_URL=...55432... uv run alembic upgrade head`: PASS
- `TASKMANAGEDAI_DATABASE_URL=...55432... uv run alembic check`: NOT CLEAN, existing env limitation (`migrations/env.py` does not provide `target_metadata`)

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0
- deferred: `alembic check` infrastructure drift only
- verdict: READY for batch 0d PR
