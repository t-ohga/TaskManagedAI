# TaskManagedAI クイックスタート

## 概要

TaskManagedAI は AI-native な開発タスク管理ツールです。
チケット管理、AI agent への作業振り分け、承認ワークフロー、監査ログを統合管理します。

## セットアップ

### 1. Docker 起動

```bash
cd ~/repo/TaskManagedAI
set -a && source .env.local && set +a
docker compose up -d
```

5 つのサービスが起動します:
- **frontend** (localhost:3900) — Next.js UI
- **api** (localhost:8000) — FastAPI バックエンド
- **worker** — arq ワーカー
- **postgres** (localhost:5432) — PostgreSQL
- **redis** (localhost:6379) — Redis

### 2. DB 初期化 (初回のみ)

```bash
TASKMANAGEDAI_DATABASE_URL="postgresql+asyncpg://taskmanagedai:taskmanagedai_local_smoke_pwd@127.0.0.1:5432/taskmanagedai" \
  uv run alembic upgrade head
```

### 3. MCP Server 設定 (各プロジェクト)

```bash
bash ~/repo/TaskManagedAI/scripts/setup-mcp-client.sh /path/to/your-project
```

Claude Code セッションを再起動すると `mcp__taskmanagedai__*` tools が使えます。

### 4. UI にログイン

- URL: http://127.0.0.1:3900
- Dev token: .env.local の `TASKMANAGEDAI_DEV_LOGIN_TOKEN`

## 基本操作

### チケット管理

| 操作 | MCP tool | UI |
|------|----------|-----|
| プロジェクト一覧 | `project_list` | ダッシュボード |
| チケット作成 | `ticket_create(project_id, title)` | — |
| チケット一覧 | `ticket_list(project_id)` | チケット (看板ボード) |
| 横断検索 | `ticket_search(query)` | — |
| ステータス更新 | `ticket_update(project_id, ticket_id, status)` | — |
| コメント追記 | `ticket_comment(project_id, ticket_id, message)` | — |

### AI agent 管理

| 操作 | MCP tool |
|------|----------|
| agent 登録 | `superintendent_agent_register(role_id, project_id, provider)` |
| タスク割り当て | `superintendent_dispatch(agent_id, ticket_id)` |
| 実行一覧 | `run_list(project_id)` |
| 実行詳細 | `run_show(run_id)` |
| コスト記録 | `run_cost(run_id, cost_usd, tokens_input, tokens_output)` |

### Multi-Agent Delegation

| 操作 | MCP tool |
|------|----------|
| タスク委譲 | `delegation_create(project_id, parent_run_id, ticket_id, purpose, role_id, task_spec)` |
| 受信確認 | `delegation_inbox(run_id)` |
| 受諾 | `delegation_accept(run_id, message_id)` |
| 結果提出 | `delegation_submit(run_id, parent_run_id, project_id, result_status)` |
| レビュー | `delegation_review(run_id, reviewer_run_id, decision, quality_score)` |
| ツリー表示 | `delegation_tree(run_id)` |
| 全体進捗 | `workflow_status()` |

## 安全制約

- `approval_decide` は human-only (MCP 非公開)
- `merge` / `deploy` / `secret_access` は delegation policy で常に deny
- 監査ログに raw secret は含まれない
- self-review 禁止 (reviewer ≠ implementer)

## 登録済みプロジェクト

`project_list` で最新一覧を取得できます。

## トラブルシューティング

### Docker が起動しない
```bash
docker compose down && docker compose up -d
```

### MCP tools が見つからない
Claude Code セッションを再起動してください。

### DB 接続エラー
PostgreSQL が起動しているか確認:
```bash
docker ps | grep postgres
```
