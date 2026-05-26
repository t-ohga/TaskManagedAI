---
id: "SP-034_mcp_server_gateway"
type: "heavy"
status: "draft"
sprint_no: 34
created_at: "2026-05-26"
updated_at: "2026-05-26"
target_days: 7
max_days: 10
adr_refs: []
planned_adr_refs:
  - "ADR-00026 (MCP Server Gateway、新規起票)"
related_sprints:
  - "SP-016_ui_cli_parity"
  - "SP-014_orchestrator_agent"
  - "SP-013_multi_agent_orchestration"
risks:
  - "MCP protocol version drift"
  - "AI agent が TaskManagedAI invariant を破壊する経路"
  - "raw secret が MCP tool response に漏れる経路"
---

## 目的

- TaskManagedAI を **MCP Server** として公開し、Claude Code / Codex / 他の AI agent が MCP client として接続して開発タスクを管理できるようにする
- AI agent が「チケット作成 → 計画 → 承認待ち → 実行 → Draft PR」を TaskManagedAI API 経由で一気通貫実行できる回路を確立する
- 全 AI の作業を統一された監査ログ・承認ワークフロー・品質ゲートで管理する

## 背景

- 現在 Claude Code / Codex は TaskManagedAI の API を通さず、直接 git / file で作業している
- TaskManagedAI の backend には AgentRun 16 状態 + Provider Adapter + Runner + RepoProxy が全て実装済み
- 足りないのは「AI が TaskManagedAI API を叩く入口」= MCP Server

## 対象外

- MCP Server の marketplace 公開 (P2)
- AI agent の自律 merge / deploy (P0 deny 維持)
- Provider key の MCP 経由直接取得 (SecretBroker boundary 維持)

## 設計判断

### MCP Server として公開する Tool 一覧

| Tool | 対応 API | AI が使うシーン |
|---|---|---|
| `ticket_create` | POST /api/v1/projects/{id}/tickets | タスク登録 |
| `ticket_list` | GET /api/v1/projects/{id}/tickets | 既存タスク確認 |
| `ticket_show` | GET /api/v1/projects/{id}/tickets/{id} | 詳細確認 |
| `run_create` | POST /api/v1/agent_runs | AI 実行開始 |
| `run_show` | GET /api/v1/agent_runs/{id} | 実行状態確認 |
| `run_plan_dry_run` | POST /api/v1/onboarding/dry_run_plan | 計画ドライラン |
| `approval_list` | GET /api/v1/approvals | 承認一覧 |
| `approval_show` | GET /api/v1/approvals/{id} | 承認詳細 |
| `audit_list` | GET /api/v1/audit_events | 監査ログ確認 |
| `context_show` | GET /api/v1/me/current_project | プロジェクト情報 |
| `kpi_show` | GET /api/v1/eval/kpi-rollup | KPI 確認 |

### AI agent 認証

- MCP Server 起動時に Tailscale 閉域内のみアクセス可能
- 各 AI agent は `actor_type=agent` として actors table に登録
- capability token (TTL 5-30 分) で operation ごとに認可
- raw secret は MCP tool response に含めない

### 安全境界

- AI agent が `approval_decide` を呼べない (human-only decider invariant)
- AI agent が `merge` / `deploy` を実行できない (P0 deny)
- AI agent の全操作が audit_events に記録される
- Provider Compliance Matrix による送信データ分類は維持

## 実装チケット

| BL | 内容 |
|---|---|
| BL-0300 | MCP Server skeleton (FastMCP or stdio transport) |
| BL-0301 | 11 Tool 定義 + input schema (Zod → JSON Schema) |
| BL-0302 | AI agent 登録 API + capability token 発行 |
| BL-0303 | MCP → FastAPI API 橋渡し (auth + tenant context resolve) |
| BL-0304 | response redaction (raw secret / provider key 除去) |
| BL-0305 | .claude/settings.json MCP server 登録 (Claude Code 用) |
| BL-0306 | .codex/config.toml MCP server 登録 (Codex 用) |
| BL-0307 | E2E テスト (MCP client → ticket create → run → approval) |
| BL-0308 | Sprint Pack closeout + docs |

## タスク一覧

- [ ] batch 0: ADR-00026 起票 (MCP Server Gateway) + ADR accepted
- [ ] batch 1: BL-0300 + BL-0301 (MCP Server skeleton + Tool 定義)
- [ ] batch 2: BL-0302 + BL-0303 (認証 + API 橋渡し)
- [ ] batch 3: BL-0304 + BL-0305 + BL-0306 (redaction + 設定)
- [ ] batch 4: BL-0307 + BL-0308 (E2E + closeout)

## must_ship / defer_if_over_budget

| must_ship | defer_if_over_budget |
|---|---|
| MCP Server 起動 + 11 Tool + Claude Code 接続 | Codex 接続 / 他 AI 接続 / marketplace 公開 |

## 受け入れ条件

- [ ] Claude Code から MCP 経由で ticket 作成 → agent run 開始 → 状態確認ができる
- [ ] 全操作が audit_events に記録される
- [ ] approval_decide は human-only (AI agent 不可)
- [ ] raw secret が MCP tool response に出ない
- [ ] Codex からも接続可能 (設定ファイル配布)

## 検証手順

```bash
# MCP server 起動
uv run python -m backend.app.mcp_server

# Claude Code から接続テスト
claude --mcp-config .mcp.json

# E2E
uv run pytest tests/mcp/ -q
```

## 残リスク

- MCP protocol の breaking change (version pinning で対処)
- AI agent が大量 request で rate limit (BudgetGuard で制御)
- 複数 AI agent の並行 approval request 競合 (atomic claim で制御)
