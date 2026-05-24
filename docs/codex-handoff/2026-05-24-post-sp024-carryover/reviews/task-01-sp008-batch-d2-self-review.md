# task-01 SP-008 Batch D2 Self Review

Date: 2026-05-24

## Scope

Batch D2 wires the standard runtime call-site for Draft PR creation:

- `DraftPRRuntime.create_draft_pr()`
- `RepoProxy.create_draft_pr(binding)` success path
- `RepoPROpenedEventWriter.append_from_result()` append-only `repo_pr_opened` emission

It does not enable the real GitHub httpx transport. External API/worker adoption remains a follow-up after the real transport path is enabled.

## Findings

| severity | finding | disposition |
|---|---|---|
| HIGH | Denied Draft PR attempts could emit `repo_pr_opened`, corrupting KPI source-of-truth. | adopt: runtime returns without writer call when `deny_reason` exists or `pr_number` is missing; test asserts repository calls remain empty. |
| HIGH | Successful PR creation could silently fail event emission when result metadata is incomplete. | adopt: writer denial is surfaced as `event_deny_reason` in `DraftPRRuntimeResult`; caller can alert instead of assuming event persistence. |
| MEDIUM | Runtime service could bypass server-owned binding by accepting raw DraftPRRequest fields. | adopt: runtime accepts only `DraftPRBinding` and delegates request resolution to the injected `RepoProxy`. |
| MEDIUM | Runtime success path could be test-only and never prove DB append. | adopt: DB integration test uses `MockRepoProxy` + `RepoPROpenedEventWriter(session)` and verifies persisted `agent_run_events` row. |

## Checklist

- [x] Runtime accepts IDs only via `DraftPRBinding`.
- [x] Event append occurs only after successful Draft PR result.
- [x] Denied PR results do not append.
- [x] Event payload still uses the writer's canonical raw-token-free URL builder.
- [x] DB integration covers the RepoProxy → writer path.
- [x] Remaining external API/worker adoption is documented as residual.

## Verification

- `uv run ruff check backend/app/services/repoproxy/draft_pr_runtime.py backend/app/services/repoproxy/__init__.py tests/repoproxy/test_repo_pr_opened_event.py`
- `PYTHONPATH=cli uv run mypy backend/app/services/repoproxy/draft_pr_runtime.py tests/repoproxy/test_repo_pr_opened_event.py`
- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/repoproxy/test_repo_pr_opened_event.py -q`
