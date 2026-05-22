# task-01 batch 0e Self-Impl-Review (2026-05-22)

## scope

- task: task-01 / SP-014 batch 0e remote_agent_gateway P0.1 deny-only stub
- protocol: `00-codex-behavior-guide.md` §3.2 Self-Impl-Review
- implementation target:
  - `backend/app/services/remote_agent_gateway/deny_only.py`
  - `tests/multi_agent/test_remote_agent_gateway_p0_1_stub.py`
  - `docs/adr/00013_remote_agent_extension.md`

## implemented

- Added `RemoteAgentGateway.deny_dispatch()` service-only stub.
- Added `RemoteAgentDispatchRequest` / `RemoteAgentDispatchDecision` dataclasses.
- Every request returns deny with `reason_code='p0_1_stub'`.
- Stub writes `audit_events.event_type='remote_agent_dispatch_denied'`.
- Audit payload includes tenant / actor / project / run / role / requested_remote_role / capability_class / payload_data_class, and runs raw secret scan before insert.
- ADR-00013 now explicitly permits only this deny-only stub while keeping adapters/API/config prohibited.

## adversarial review findings

| id | severity | category | symptom | judgment | fix |
|---|---|---|---|---|---|
| SP014-B0E-IMPL-R1-F001 | HIGH | full integration creep | A remote gateway package could be mistaken for accepted remote adapter implementation. | adopt | Package contains deny-only service only; no adapter/router/config files. |
| SP014-B0E-IMPL-R1-F002 | HIGH | tenant boundary | Audit row could be written under wrong app.tenant_id. | adopt | Tenant context is set/checked before insert; mismatch test added. |
| SP014-B0E-IMPL-R1-F003 | MEDIUM | secret leakage | requested role field can contain token-like text. | adopt | `assert_no_raw_secret` catches payload before audit insert; test asserts no row is written. |
| SP014-B0E-IMPL-R1-F004 | MEDIUM | weak audit | Empty role fields reduce incident usefulness. | adopt | Empty field validation raises `RemoteAgentGatewayError`. |

## invariant checklist

- deny-only invariant: PASS; no dispatch path exists.
- audit trace: PASS; `remote_agent_dispatch_denied` row is persisted.
- raw secret / token leakage: PASS; shared scanner rejects token-like payloads.
- tenant boundary: PASS; app tenant context mismatch rejects.
- ADR-00013 scope: PASS; full integration remains proposed/prohibited.

## verification

- `uv run ruff check backend tests`: PASS
- `uv run mypy backend`: PASS (`264 source files`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/multi_agent/test_remote_agent_gateway_p0_1_stub.py -q`: PASS (`4 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/multi_agent/ -q`: PASS (`51 passed`)
- `TASKMANAGEDAI_DATABASE_URL=...55432... TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/runtime/test_agent_run_events.py tests/runtime/test_agentrun_transitions.py -q`: PASS (`51 passed`)

## readiness gate

- residual CRITICAL: 0
- residual HIGH: 0
- deferred: none for batch 0e
- verdict: READY for batch 0e PR
