---
id: "ADR-00026"
title: "MCP Server Gateway (stdio transport、AI agent 接続)"
status: "accepted"
date: "2026-05-26"
accepted_at: "2026-05-26"
deciders:
  - "TaskManagedAI core"
adr_gate_criteria:
  - "5: MCP / tool 権限"
  - "6: Secrets 管理方式"
---

## 背景

TaskManagedAI の全機能 (チケット管理、AgentRun、承認、監査) は backend API として実装済みだが、AI agent (Claude Code / Codex / 他) が API を直接叩く入口がない。MCP (Model Context Protocol) Server として公開することで、標準プロトコルで任意の AI client から接続可能にする。

## 決定対象

- MCP transport 方式
- AI agent の認証・認可
- 公開 tool の範囲と安全境界

## 採用案: stdio transport + human-only agent 登録

### Transport

**stdio transport を採用**。理由:
- Claude Code / Codex は MCP stdio client をネイティブサポート
- Tailscale 閉域内のローカル実行で十分 (HTTP transport は P2)
- プロセス認可で完結 (OAuth / PKCE 不要)

### 認証

- **agent 登録は human/admin CLI 限定** (agent 自己登録不可)
- `taskhub agent register` → bootstrap token (TTL 30 分、one-time)
- agent は bootstrap token で session capability token を取得
- capability token: TTL 5-30 分、operation bound、actor/run/fingerprint binding
- SP-016 `api_capability_tokens` 契約を流用

### 公開 tool (15)

Read-only (10): ticket_list, ticket_show, run_show, run_plan_dry_run, approval_list, approval_show, audit_list, context_show, kpi_show, notification_list
Mutating (5): ticket_create, ticket_update, run_create, run_cancel, notification_resolve

### 除外 (human-only)

- `approval_decide`: **ApprovalDecisionService で Actor.actor_type=="human" を必須化**
- `repo_push` / `pr_open`: AgentRun pipeline 内部で実行
- `merge` / `deploy`: P0 deny

### 安全境界

- server-owned field (actor_id / tenant_id / policy_profile) は inputSchema で `extra=forbid`
- response は allowlist DTO (raw secret / provider key / stack trace 除外)
- idempotency key は `(tenant_id, actor_id, tool_name, key)` で bind
- MCP ingress に per-actor rate limit

## 却下案

1. **HTTP transport**: OAuth / Protected Resource Metadata が必要で scope 大。P2 defer。
2. **REST SDK 配布**: AI ごとに client 実装が必要。MCP は標準プロトコルで汎用的。
3. **agent 自己登録**: self-grant / scope escalation リスク。human gate 必須。

## リスク

- MCP protocol breaking change → version pinning + CI drift test
- stdio process lifecycle → Claude Code / Codex が管理
- 複数 agent 並行 → lease ownership + atomic claim で排他制御

## Rollback

- MCP Server module を disable (settings.json から mcpServers 削除)
- agent actor を revoke (admin CLI)
- 既存 API / CLI は影響なし
