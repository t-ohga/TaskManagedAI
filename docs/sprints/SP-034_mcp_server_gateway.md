---
id: "SP-034_mcp_server_gateway"
type: "heavy"
status: "partial_skeleton"
sprint_no: 34
created_at: "2026-05-26"
updated_at: "2026-05-26"
target_days: 7
max_days: 10
adr_refs:
  - "[ADR-00026](../adr/00026_mcp_server_gateway.md) # accepted 2026-05-26"
planned_adr_refs: []
related_sprints:
  - "SP-016_ui_cli_parity"
  - "SP-014_orchestrator_agent"
  - "SP-013_multi_agent_orchestration"
risks:
  - "MCP protocol version drift"
  - "AI agent self-registration / token mint 経路"
  - "raw secret が MCP tool response に漏れる経路"
  - "caller-supplied server-owned field bypass"
---

## 目的

- TaskManagedAI を **MCP Server (stdio transport)** として公開し、Claude Code / Codex / 他の AI agent が MCP client として接続して開発タスクを管理できるようにする
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
- HTTP transport (P2、stdio transport で P1 は十分)

## 設計判断

### Transport: stdio-only local (R1-F1 fix)

- **stdio transport を採用** (HTTP transport は P2 defer)
- Claude Code: `.claude/settings.json` の `mcpServers` に stdio command 登録
- Codex: `.codex/config.toml` の `[mcp_servers]` に登録
- 他 AI: stdio protocol 準拠の任意 MCP client から接続可能
- Tailscale 閉域内で動作 (ネットワーク認可は不要、プロセス認可で十分)

### AI Agent 認証 (R1-F2 fix)

- **agent 登録は human/admin 限定** (agent 自身が自己登録不可)
- admin が `taskhub agent register` CLI で agent actor を作成 → bootstrap token 発行
- bootstrap token は TTL 30 分、one-time、human 発行のみ
- agent は bootstrap token で初回認証 → session-scoped capability token 取得
- capability token は TTL 5-30 分、operation bound、actor/run/fingerprint binding
- **self-grant 禁止**: agent が自身の scope を escalation する経路なし
- SP-016 `api_capability_tokens` 契約を流用 (project/audience/request_binding/jti/scope_constraint)

### MCP Tool 一覧 (R1-F3/F6/F8 fix)

| Tool | Method | API | read/mutate | annotations |
|---|---|---|---|---|
| `ticket_create` | POST | /api/v1/projects/{id}/tickets | mutate | `readOnlyHint=false`, `idempotentHint=false` |
| `ticket_list` | GET | /api/v1/projects/{id}/tickets | read | `readOnlyHint=true` |
| `ticket_show` | GET | /api/v1/projects/{id}/tickets/{id} | read | `readOnlyHint=true` |
| `ticket_update` | PATCH | /api/v1/projects/{id}/tickets/{id} | mutate | `readOnlyHint=false`, `idempotentHint=true` |
| `run_create` | POST | /api/v1/agent_runs | mutate | `readOnlyHint=false`, `idempotentHint=false` |
| `run_show` | GET | /api/v1/agent_runs/{id} | read | `readOnlyHint=true` |
| `run_cancel` | POST | /api/v1/agent_runs/{id}/cancel | mutate | `readOnlyHint=false` |
| `run_plan_dry_run` | POST | /api/v1/onboarding/dry_run_plan | read | `readOnlyHint=true` (response-only) |
| `approval_list` | GET | /api/v1/approvals | read | `readOnlyHint=true` |
| `approval_show` | GET | /api/v1/approvals/{id} | read | `readOnlyHint=true` |
| `audit_list` | GET | /api/v1/audit_events | read | `readOnlyHint=true` |
| `context_show` | GET | /api/v1/me/current_project | read | `readOnlyHint=true` |
| `kpi_show` | GET | /api/v1/eval/kpi-rollup | read | `readOnlyHint=true` |
| `notification_list` | GET | /api/v1/notifications | read | `readOnlyHint=true` |
| `notification_resolve` | POST | /api/v1/notifications/{id}/resolve | mutate | `readOnlyHint=false` |

**Intentionally excluded**:
- `approval_decide`: **human-only** (agent は approval requester のみ)
- `repo_push` / `pr_open`: AgentRun pipeline 内部で実行 (MCP tool として直接公開しない)
- `merge` / `deploy`: P0 deny

### Input Schema: server-owned field 拒否 (R1-F3 fix)

全 mutating tool の inputSchema で以下を `extra=forbid` 相当で拒否:
- `actor_id`, `principal_id`, `tenant_id` (server-resolved from session)
- `policy_profile`, `autonomy_level` (server-owned)
- `approval_request_id`, `decided_by_actor_id` (approval boundary)
- `capability_token`, `provider_payload` (SecretBroker boundary)

violation 時は MCP tool result `isError: true` + error_code `caller_supplied_field_rejected`。

### Response Redaction (R1-F4 fix)

全 tool response で以下を除外 (allowlist DTO):
- raw secret / provider key / capability token 生値
- provider raw response body
- internal error stack trace
- canary values
- audit の field-level redaction: `payload_keys` のみ返し `payload_values` は返さない
- pagination: `limit` / `offset` で制御、unbounded query 禁止
- project/actor scope: tenant_id + actor_id で filter

outputSchema を各 tool に定義し、allowlist 外の field は structuredContent に含めない。

### Idempotency + Multi-Agent (R1-F5 fix)

- `ticket_create`: client が `idempotency_key` を送信可能。同一 key の再送は既存 ticket を返す
- `run_create`: `(tenant_id, run_id, idempotency_key)` で重複防止
- `run_cancel`: cancel は idempotent (既に cancelled なら 200)
- multi-agent concurrency: lease ownership で排他制御 (SP-014 lease_manager 流用)
- duplicate-safe conflict response: 409 Conflict + existing resource ref

### Error Mapping (R1-F7 fix)

| エラー種別 | MCP response |
|---|---|
| validation error (inputSchema) | `isError: true`, error_code |
| auth failure | MCP protocol error (stdio transport では process exit) |
| policy deny | `isError: true`, `policy_blocked` |
| budget exceeded | `isError: true`, `budget_blocked` |
| not found | `isError: true`, `not_found` |
| server error | `isError: true`, `internal_error` (stack trace 除外) |

### Long-Running run_create (R1-F7 fix)

- `run_create` は run_id を即時返却 (AgentRun `queued` 状態)
- 実行進捗は `run_show` で polling
- MCP task support は P2 defer (stdio transport では不要)

## 実装チケット

| BL | 内容 |
|---|---|
| BL-0300 | MCP Server skeleton (FastMCP stdio transport) |
| BL-0301 | 15 Tool 定義 + inputSchema + outputSchema + annotations |
| BL-0302 | admin agent 登録 CLI + bootstrap token 発行 (human-only) |
| BL-0303 | MCP → FastAPI API 橋渡し (session resolve + server-owned field reject) |
| BL-0304 | response redaction (allowlist DTO + field-level audit redaction) |
| BL-0305 | idempotency key + multi-agent conflict response |
| BL-0306 | .claude/settings.json + .codex/config.toml MCP server 登録 |
| BL-0307 | error mapping (isError + error_code + stack trace 除外) |
| BL-0308 | E2E テスト (MCP client → ticket create → run → approval → audit) |
| BL-0309 | negative test (self-registration deny + caller-supplied field reject + approval decide deny) |
| BL-0310 | Sprint Pack closeout + docs |

## タスク一覧

- [ ] batch 0: ADR-00026 起票 (MCP Server Gateway、stdio transport 固定) + ADR accepted
- [ ] batch 1: BL-0300 + BL-0301 (MCP Server skeleton + Tool 定義)
- [ ] batch 2: BL-0302 + BL-0303 + BL-0305 (認証 + API 橋渡し + idempotency)
- [ ] batch 3: BL-0304 + BL-0307 (redaction + error mapping)
- [ ] batch 4: BL-0306 (Claude Code / Codex 設定)
- [ ] batch 5: BL-0308 + BL-0309 + BL-0310 (E2E + negative test + closeout)

## must_ship / defer_if_over_budget

| must_ship | defer_if_over_budget |
|---|---|
| MCP Server (stdio) + 15 Tool + Claude Code 接続 + admin agent 登録 + E2E | Codex 接続 (設定ファイルのみ提供、smoke test は defer) / HTTP transport / marketplace / task support |

## 受け入れ条件

- [ ] Claude Code から MCP 経由で ticket 作成 → agent run 開始 → 状態確認ができる
- [ ] 全操作が audit_events に記録される
- [ ] approval_decide は human-only (AI agent は MCP tool として呼べない)
- [ ] raw secret / provider key / capability token が MCP tool response に出ない
- [ ] agent 自己登録不可 (human/admin CLI 限定)
- [ ] caller-supplied server-owned field (actor_id/policy_profile 等) が reject される
- [ ] ticket_create / run_create に idempotency_key が使える
- [ ] multi-agent concurrent access で data corruption がない
- [ ] all mutating tool に inputSchema + outputSchema + annotations 定義
- [ ] error は isError: true + error_code (stack trace 除外)
- [ ] **CRITICAL: ApprovalDecisionService で Actor.actor_type=="human" を必須化** (agent/service/provider/github_app decider negative test)
- [ ] **API capability issue で non-human actor への approval_decide を deny**
- [ ] audit_list / run_show は session actor/project scope で filter (cross-actor deny negative test)
- [ ] notification_list は keys-only DTO (raw payload 返さない + raw secret scan)
- [ ] idempotency key は `(tenant_id, actor_id, tool_name, key)` で bind (cross-actor replay deny)
- [ ] MCP ingress に per-actor rate limit + max concurrent (BudgetGuard pre-spend gate)
- [ ] auth failure は sanitized MCP error (process exit は fatal-only、stderr はログのみ)
- [ ] stdio hardening: absolute argv, no shell, max request bytes, env allowlist

## 検証手順

```bash
# MCP server 起動
uv run python -m backend.app.mcp_server

# Claude Code から接続テスト
claude --mcp-config .mcp.json

# テスト
uv run pytest tests/mcp/ -q
uv run ruff check backend/app/mcp_server.py tests/mcp/
uv run mypy backend/app/mcp_server.py
```

## 残リスク

- MCP protocol の breaking change (version pinning + CI drift test で対処)
- AI agent が大量 request で rate limit (BudgetGuard で制御)
- stdio transport の process lifecycle 管理 (claude code が管理)
- 複数 AI agent の並行 approval request 競合 (atomic claim + lease ownership で制御)

## Review

(2026-06-04 台帳監査) **partial_skeleton (core 実装済だが idempotency acceptance 未達)**。MCP Server Gateway core (`backend/app/mcp/server.py` / api_bridge.py / context.py、15+ tools) は実装済 (ADR-00026 accepted、docs #265、MCP 21 tools full DB wiring #279) で backend pytest 4404 pass。**ただし受け入れ条件の idempotency (`ticket_create` / `run_create` の `idempotency_key` 再送重複防止、行 113/114/175/183) が未達**: `server.py:307` の `ticket_create` (および `run_create`) は `idempotency_key` 引数を受けるが docstring「idempotency_key で重複防止」に反し `bridge_ticket_create` / `bridge_run_create` へ渡しておらず (dead param)、bridge 側にも idempotency 引数が無いため MCP client retry で duplicate ticket / run が作れる (Codex CLI F-L4、実コード確認済)。よって当初の completed 維持判断を撤回し `partial_skeleton` へ訂正。idempotency 配線 (`(tenant_id, actor_id, tool_name, key)` bind) + retry duplicate 防止 test は別 scope で要実装。

(2026-06-05 追記) idempotency acceptance を **[ADR-00049](../adr/00049_mcp_create_idempotency.md) (accepted)** で実装。共有 `mcp_idempotency_keys` table (migration 0043) + reservation-first 算法 (INSERT ON CONFLICT DO NOTHING RETURNING → winner / loser FOR UPDATE) を `bridge_ticket_create` / `bridge_run_create` の chokepoint に配線、`server.py` の dead param を解消。codex-plan-review R1-R4 (F-N1〜N4、R4 approve) で reservation-first / actor 解決依存 / nullable+CHECK / completed_at を設計確定。検証: ruff + mypy clean (新規コード) / no-DB unit 7 passed (fingerprint + enum 整合) / DB-gated test 7 (winner-replay / conflict / cross-actor / null-key / race / run-replay / commit=False reject、`TASKMANAGEDAI_RUN_DB_TESTS` で CI 実行)。delegation の commit=False 経路は不変。残: per-actor cross-actor deny は SP-016 per-actor MCP 認証 wired 時に自動有効化 (現状は固定 default actor、F-N2 で forward-compatible に schema 化済)。本配線後も他 acceptance criterion の網羅監査は未実施のため status は `partial_skeleton` のまま (idempotency gap のみ closure)。
