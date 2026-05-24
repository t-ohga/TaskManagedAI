# task-01 SP-008 Batch D Self Review

Date: 2026-05-24

## Scope

Batch D adds the append-only `repo_pr_opened` event writer and payload contract. It does not claim final automatic call-site wiring from the eventual live RepoProxy Draft PR execution path.

## Findings

| severity | finding | disposition |
|---|---|---|
| HIGH | A transport-provided PR URL could include token-like material and leak into AgentRunEvent payload. | adopt: payload ignores `DraftPRResult.pr_url` and rebuilds canonical `https://github.com/{repo}/pull/{number}` from validated server-owned fields. |
| HIGH | Denied Draft PR results could still append `repo_pr_opened`. | adopt: writer returns `PR_NOT_CREATED` for any result with `deny_reason` or missing `pr_number`; tests assert no append call. |
| MEDIUM | Event writer could bypass append-only sequencing. | adopt: writer uses `AgentRunEventRepository.append_event()` only, with `expected_previous_seq_no` passthrough and DB persistence test. |
| MEDIUM | Duplicate PR event retry could produce duplicate timeline entries. | adopt: idempotency key is fixed to `repoproxy:repo_pr_opened:{run_id}:{pr_number}`. |
| MEDIUM | Docs could overclaim complete runtime integration. | adopt: Sprint Pack and handoff docs state writer + DB path complete, final RepoProxy call-site wiring still residual. |

## Checklist

- [x] Payload includes `pr_number`, canonical `pr_url`, `repo_full_name`, `branch`, `head_sha`, `draft=true`, `created_at`, `approval_id`, and `source`.
- [x] Raw token-like URL input is not copied into payload.
- [x] Denied / incomplete / non-draft results do not append events.
- [x] Writer uses `event_type='repo_pr_opened'`.
- [x] Writer uses deterministic idempotency key.
- [x] DB integration persists append-only event through `AgentRunEventRepository`.

## Verified

- `uv run ruff check backend/app/services/repoproxy/repo_pr_event.py backend/app/services/repoproxy/repoproxy.py backend/app/services/repoproxy/github_app_adapter.py backend/app/services/repoproxy/__init__.py tests/repoproxy/test_repo_pr_opened_event.py`
- `PYTHONPATH=cli uv run mypy backend/app/services/repoproxy/repo_pr_event.py backend/app/services/repoproxy/repoproxy.py backend/app/services/repoproxy/github_app_adapter.py tests/repoproxy/test_repo_pr_opened_event.py`
- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/repoproxy/test_repo_pr_opened_event.py -q`

## Deferred

- Automatic call-site wiring from the final RepoProxy Draft PR execution path.
- Agent-runs KPI endpoint.
