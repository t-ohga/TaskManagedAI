# Dev Commands

TaskManagedAI の開発コマンド早見表。  
未実装 script は Sprint 1 で `package.json` / `pyproject.toml` / `docker-compose.yml` と同期する。

## 1. Frontend / pnpm

| コマンド | 用途 |
|---|---|
| `pnpm install` | frontend dependencies install |
| `pnpm dev` | Next.js dev server |
| `pnpm build` | production build |
| `pnpm start` | build 後の local start |
| `pnpm typecheck` | TypeScript type check |
| `pnpm lint` | lint |
| `pnpm lint:fix` | lint auto-fix |
| `pnpm format` | format |
| `pnpm test` | Vitest |
| `pnpm test -- --coverage` | coverage |
| `pnpm test:e2e` | Playwright |
| `pnpm test:e2e:headed` | headed Playwright |
| `pnpm ci:local` | lint + typecheck + test + build |

## 2. Backend / uv

| コマンド | 用途 |
|---|---|
| `uv sync` | Python dependencies install |
| `uv run fastapi dev backend/app/main.py` | FastAPI dev server |
| `uv run uvicorn backend.app.main:app --reload` | Uvicorn dev server |
| `uv run pytest` | backend test |
| `uv run pytest backend/tests/unit` | unit test |
| `uv run pytest backend/tests/contract` | contract test |
| `uv run pytest backend/tests/integration` | integration test |
| `uv run ruff check backend tests` | lint |
| `uv run ruff format backend tests` | format |
| `uv run mypy backend` | type check |
| `uv run python -m backend.scripts.seed_dev` | dev seed 候補 |

## 3. Database / Alembic

| コマンド | 用途 |
|---|---|
| `uv run alembic current` | 現在 revision |
| `uv run alembic history` | migration history |
| `uv run alembic revision --autogenerate -m "<message>"` | migration 生成 |
| `uv run alembic upgrade head` | migrate up |
| `uv run alembic downgrade -1` | 1 revision rollback |
| `uv run alembic check` | migration drift check |
| `uv run pytest backend/tests/db` | DB contract test |

注意:

- DB schema は ADR Gate Criteria。
- destructive migration は rollback と backup 方針が必須。
- tenant / project invariant negative test を更新する。
- SecretBroker DDL 変更は atomic claim test を更新する。

## 4. Docker Compose

| コマンド | 用途 |
|---|---|
| `docker compose config` | compose validation |
| `docker compose up --build` | 全 service 起動 |
| `docker compose up postgres redis` | DB / Redis 起動 |
| `docker compose down` | 停止 |
| `docker compose down -v` | volume 削除、破壊的 |
| `docker compose logs -f backend` | backend logs |
| `docker compose logs -f worker` | worker logs |
| `docker compose exec postgres psql -U taskmanagedai` | psql |
| `docker compose exec redis redis-cli` | redis-cli |

注意:

- public bind を避け、localhost / internal network を優先する。
- `down -v` は破壊的操作。実行前に確認する。
- backup / restore drill は AC-HARD-04 と連動する。

## 5. Worker / arq

| コマンド | 用途 |
|---|---|
| `uv run arq backend.worker.WorkerSettings` | arq worker 起動 |
| `uv run python -m backend.worker.healthcheck` | worker healthcheck 候補 |
| `uv run pytest backend/tests/worker` | worker test |
| `docker compose logs -f worker` | worker logs |

確認項目:

- job timeout。
- max retries。
- cancellation boundary。
- AgentRunEvent append。
- BudgetGuard。
- runner / provider call の timeout。

## 6. Provider / Compliance

| コマンド | 用途 |
|---|---|
| `uv run pytest backend/tests/provider` | provider contract |
| `uv run pytest backend/tests/provider/test_compliance_matrix.py` | Matrix invariant |
| `uv run pytest backend/tests/provider/test_preflight.py` | `provider_request_preflight` |
| `uv run python -m backend.scripts.validate_provider_matrix config/provider_compliance.toml` | Matrix validation 候補 |

確認項目:

- `payload_data_class` 未設定 deny。
- `allowed_data_class` は Matrix 由来。
- data class ordinal。
- conditional ZDR `condition_status=verified`。
- audit payload。

## 7. SecretBroker

| コマンド | 用途 |
|---|---|
| `uv run pytest backend/tests/secrets` | SecretBroker tests |
| `uv run pytest backend/tests/secrets/test_atomic_claim.py` | atomic claim |
| `uv run pytest backend/tests/secrets/test_rotation.py` | rotation |
| `uv run python -m backend.scripts.secretbroker_dry_run` | dry-run verify 候補 |

確認項目:

- raw secret DB 保存なし。
- `secret_ref` URI。
- TTL 5-30 分。
- token hash 保存。
- one-time redeem。
- actor / run / fingerprint binding。

## 8. AgentRun / Eval

| コマンド | 用途 |
|---|---|
| `uv run pytest backend/tests/agentrun` | state machine tests |
| `uv run pytest backend/tests/agentrun/test_state_machine.py` | 16 状態 contract |
| `uv run pytest eval/tests` | eval harness tests |
| `uv run python -m eval.run --dataset public_regression` | public regression 候補 |
| `uv run python -m eval.run --dataset private_holdout` | holdout evaluation 候補 |
| `uv run python -m eval.report` | KPI report 候補 |

確認項目:

- AgentRun 16 状態。
- `blocked_reason` サブ 3。
- terminal state。
- ContextSnapshot 10 カラム。
- fixture ID / dataset version。

## 9. Tailscale / Network

| コマンド | 用途 |
|---|---|
| `tailscale status` | tailnet 状態 |
| `tailscale serve status` | serve 状態 |
| `tailscale ping <host>` | private connectivity |
| `docker compose ps` | bind 確認 |
| `lsof -iTCP -sTCP:LISTEN` | local listen 確認 |

注意:

- Funnel は P0 対象外。
- public bind は ADR Gate。
- Tailscale auth key は `secret_ref` で扱う。
- grants 変更は review と audit を残す。

## 10. Git / GitHub App

| コマンド | 用途 |
|---|---|
| `git status --short` | worktree 確認 |
| `git diff --stat` | 差分概要 |
| `git diff` | 差分確認 |
| `git log --oneline -n 20` | recent history |
| `gh pr status` | PR 状態 |
| `gh pr checks` | CI 状態 |

注意:

- commit はユーザー依頼時のみ。
- conventional commits を使う。
- main / master 直コミットを避ける。
- GitHub App permission 変更は ADR Gate。

## 11. Local Full Check

推奨順:

1. `pnpm typecheck`
2. `pnpm lint`
3. `pnpm test`
4. `uv run ruff check backend tests`
5. `uv run mypy backend`
6. `uv run pytest`
7. `uv run alembic check`
8. `pnpm build`
9. `pnpm test:e2e`
10. `docker compose up --build`

## 12. 実行できない場合の記録

```md
## Verification Gap

- command: `<command>`
- reason: <why not run>
- alternative: <manual/static check>
- residual risk: <risk>
```

