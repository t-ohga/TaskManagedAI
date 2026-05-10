# MCP DB Tools (TaskManagedAI)

DB 操作系 MCP server の使い分け reference。Claude Code / Codex 両方から user-scope で利用可能。  
2026-05-10 起票 (PostgreSQL MCP user-scope 採用 + Prisma MCP plugin install を機に整理)。

## 1. PostgreSQL MCP (`postgres-taskmanagedai`)

### 採用状況

- ✅ **user-scope で採用済** (Claude scope `~/.claude.json` + Codex scope `~/.codex/config.toml`)
- 共有 wrapper: `~/.claude/local/bin/pg-mcp-taskmanagedai.sh`
- env: `PG_TASKMANAGEDAI_URL` (`~/.zshenv` で export)
- 詳細: `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/reference_postgres_mcp_user_scope.md`
- ハーネスポリシー整合: `.mcp.json` Phase 1 skeleton (project-scoped MCP は空、個別 MCP は user-global で個別解決) に準拠

### MCP server 仕様 (`@modelcontextprotocol/server-postgres`)

- **read-only by design**: `query` tool のみ expose、SELECT 文のみ実行
- AI Output Boundary §1 「AI 出力 SQL を DB に直接適用しない」を MCP server レベルで担保
- caller が SELECT 以外を投げても server が deny

### 適切な使用タイミング

| 用途 | 具体例 | Sprint 文脈 |
|---|---|---|
| Migration 後の schema 確認 | `\d agent_runs` で 16 状態 CHECK 制約 verify | Sprint 2 / 4 / 5.5 |
| Seed data 検証 | `SELECT count(*) FROM tickets GROUP BY status` | Sprint 1 / 2 / 12 |
| Test failure 調査 | E2E test 失敗時の DB state を SELECT で確認 | 任意 (failure 調査時) |
| ad-hoc data exploration | dev DB の数値分布、関係確認 | 任意 |
| ContextSnapshot 内容確認 | `SELECT * FROM context_snapshots WHERE run_id=...` | Sprint 4 以降 |
| AgentRunEvent 履歴 | `SELECT event_type, seq_no FROM agent_run_events WHERE run_id=...` | Sprint 4 以降 |

### 使わない場面

- ❌ **production / staging DB**: wrapper の localhost guard で **fail-closed** (host が `localhost` / `127.0.0.1` / `host.docker.internal` 以外を弾く)
- ❌ **書込 operation** (INSERT / UPDATE / DELETE / DDL): MCP server が SELECT only で物理的に不可
- ❌ **AI 出力 SQL を直接実行**: Claude が SQL を生成 → MCP query は read-only でも、生成 SQL は **人間 review 後に手動で psql 経由** (`.claude/rules/ai-output-boundary.md` §1 invariant)
- ❌ **secret / capability_token 値の取得**: `secret_capability_tokens` table から `token_hash` のみ表示 (生 token 値は DB に存在しない、SecretBroker invariant 維持)

### Codex / Claude 共通 wrapper の利点

両 AI agent から同じ wrapper 経由で起動 → behavior の一貫性。env / localhost guard / read-only contract が共通適用される。

## 2. Prisma MCP (`Prisma-Local` + `Prisma-Remote`)

### TaskManagedAI では **使わない**

| 理由 | 詳細 |
|---|---|
| ORM 不一致 | TaskManagedAI は **SQLAlchemy 2.x + Alembic** 採用 (ADR-00002)、Prisma 製品は不在 |
| schema 形式 | Prisma MCP の `migrate-dev / migrate-reset / migrate-status / Prisma-Studio` は `schema.prisma` 前提、TaskManagedAI には存在しない |
| 認証境界 | `Prisma-Remote` の `authenticate` / `complete_authentication` は Prisma cloud 用、TaskManagedAI と無関係 |

### 使う場面 (TaskManagedAI **外**、user-scope 全般)

- 他 project (Prisma 採用 project) で migrate / studio を起動するとき
- TaskManagedAI 作業中に accidentally 起動しないよう、本 reference で明示

### TaskManagedAI workflow での扱い

- TaskManagedAI 内では `migrate-dev` 等の Prisma tool 起動を **禁止** (Alembic と二重管理になり drift する)
- AI agent が project context (TaskManagedAI 内 cwd) で誤起動しないよう、本 reference を必読資料として参照

## 3. 適切なタイミング判断 flowchart

```text
DB 操作したい
  │
  ├─ TaskManagedAI 内 (cwd が /Users/tohga/repo/TaskManagedAI)
  │    │
  │    ├─ read 専用 (SELECT / schema 確認 / data verification)
  │    │     → ✅ postgres-taskmanagedai MCP (read-only by design)
  │    │
  │    ├─ migration / DDL / schema 変更
  │    │     → ❌ MCP 不可。`uv run alembic revision --autogenerate` で migration file 作成
  │    │       → 人間 review → `uv run alembic upgrade head` で apply
  │    │
  │    ├─ INSERT / UPDATE / DELETE
  │    │     → ❌ MCP 不可。production code (FastAPI endpoint / repository) 経由
  │    │       で必ず audit event を残しつつ実施
  │    │
  │    └─ secret / capability token 値の取得
  │          → ❌ 不可。SecretBroker mediated operation のみ。raw secret は DB に存在しない
  │
  └─ TaskManagedAI 外 (他 project)
       │
       ├─ Prisma project: ✅ Prisma MCP (migrate-dev / studio 等)
       └─ PostgreSQL project: ✅ postgres-taskmanagedai 流用 (env を別 project 用に切替) or 別 wrapper
```

## 4. Codex / Claude 起動時の確認手順

### 新 Claude session 起動時

```bash
claude mcp list | grep -E "postgres|prisma"
# 期待:
#   plugin:prisma:Prisma-Local: npx -y prisma mcp - ✓ Connected
#   plugin:prisma:Prisma-Remote: https://mcp.prisma.io/mcp (HTTP) - ! Needs authentication
#   postgres-taskmanagedai: /Users/tohga/.claude/local/bin/pg-mcp-taskmanagedai.sh - ✓ Connected
#   (postgres は要 docker compose up postgres)
```

### Codex session 起動時

```bash
# Codex CLI で MCP 一覧を確認 (Codex は startup 時に [mcp_servers.<name>] を読む)
grep "^\[mcp_servers" ~/.codex/config.toml
# 期待: chrome-devtools / codex / discord / next-devtools / playwright / postgres-taskmanagedai
```

### 動作確認 (Claude 内で)

```text
> postgres-taskmanagedai で actors テーブルの schema を見せて
> tenant_id=1 の tickets を最新 5 件 SELECT して
```

## 5. 関連

- `reference_postgres_mcp_user_scope.md` (memory): wrapper / env / localhost guard の詳細
- `.mcp.json`: Phase 1 skeleton ポリシー (project-scoped MCP 空)
- `.claude/CLAUDE.md` §2 deny-by-default + §5 重要パス参照
- `.claude/rules/ai-output-boundary.md` §1: AI 出力 SQL を DB に直接適用しない invariant
- `.claude/rules/codex-output-contract.md`: Codex 出力 truncation 防止
- ADR-00002 (DB schema foundation, accepted): SQLAlchemy + Alembic 採用、Prisma 不採用
