---
id: "SP-034_mcp_server_gateway"
type: "heavy"
status: "partial_skeleton"
sprint_no: 34
created_at: "2026-05-26"
updated_at: "2026-06-10"
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

(2026-06-05 監査) **partial_skeleton 維持 + 実態精緻化**。MCP test suite 41 passed (10 DB-gated skip) で acceptance の core + security-critical 充足を確認:
- ✅ approval_decide human-only (`test_human_only_tools_not_exposed`) / AI が approval 作成不可 (`test_approval_request_create_forbidden`)
- ✅ raw secret 非露出 (`test_ticket_list/audit_list_returns_no_raw_secret`) / 39 tools 登録 + read/mutate 分類
- ✅ idempotency (#323 ADR-00049、`test_create_idempotency_*`) / input validation (invalid uuid/role/status/dispatch deny)

→ `partial_skeleton` は core を過小評価 (security-critical は tested)。ただし **残 acceptance**: per-actor rate limit + max concurrent (BudgetGuard pre-spend) / stdio hardening (absolute argv / no shell / max request bytes / env allowlist) / caller-supplied server-owned field reject の明示 negative test が test suite に未確認 → これら hardening 系を実装・検証してから completed 化する (over-claim 回避、台帳 honesty)。本 audit では status 不変 (security-critical 充足の証跡記録 + 残 hardening gap 明示)。

(2026-06-10 hardening 実装) **3 security hardening gap を closure** (status は `partial_skeleton` 維持、下記理由)。

- **Codex adversarial R7 HIGH (F-10) + R8 HIGH (F-12) adopt**: Discord 通知を `python -c` subprocess
  (`import httpx`) で送っていたが、token-bearing child の import-path / interpreter symlink hijack で token が
  別 process の repo コードに読まれ得た。**subprocess を全廃し in-process httpx へ移行** (`_SEND_SCRIPT` /
  `_PYTHON_EXECUTABLE` / `_hardened_subprocess_env` / `_terminate_child` 削除、`httpx.AsyncClient` bounded
  timeout best-effort)。token は親 process memory に留まり **child env / argv に一切出ない** (R5 F-8 の
  subprocess timeout cleanup も自然解消)。
  R8 F-12 / R9 F-13 の残論点 (in-process でも `python -m backend.app.mcp` 起動で project-local `httpx.py` が
  **親 process の** import を shadow し得る) には **defense-in-depth gate を追加**: `httpx.__file__` が
  `site-packages` / `dist-packages` から来ているかを検証し、shadow 疑い時は通知を **fail-closed**
  (token を resolve/使用せず no-op) にする (`_is_trusted_dependency_path` / `_HTTPX_TRUSTED`)。
  **honest 限界 (R9 F-13)**: 本 gate は post-import チェックのため shadow module の **import-time
  top-level code 実行自体は防げない** (HTTP call で token を untrusted httpx へ渡さない防御に留まる)。
  根本的に、repo の import path へ `httpx.py` を書ける攻撃者は `discord_notify.py` を含む backend 全モジュール
  を既に制御でき token は server 全体と同等露出 = **server コード完全性** (deployment / file 権限) の問題で
  **SP-034 (MCP gateway) scope 外**。よって本項は完全 closure ではなく best-effort gate + honest 限界明記。
  regression (`TestDiscordInProcessNotify`: subprocess machinery 不在 / token は Authorization header のみ /
  token 不在 no-op / HTTP error 握り潰し / untrusted httpx で fail-closed / 実 httpx は trusted)。
- **Codex adversarial R7 MEDIUM (F-11) adopt**: ingress guard 拒否を `ToolResult` で返していたため MCP client
  には `isError=false` の成功扱いになり、blocked mutation を automation が「成功」と誤認し得た。拒否を
  **`ToolError`** (FastMCP → MCP protocol で `isError=true`) に変更、payload 正本 key を `error` → **`error_code`**
  に統一。fail-open try の **外** で raise し guard bypass を防ぐ。regression (`test_ingress_rejection_is_protocol_error`:
  `_call_tool_mcp` で ToolError 伝播、`test_mutating_tool_over_rate_limit_rejected` / `test_oversized_read_tool_rejected`
  で ToolError + error_code 検証)。
- **gap #1 (per-actor rate limit + max concurrent + max input bytes)**: `backend/app/mcp/hardening.py` +
  `middleware.py` で in-process な FastMCP `MutationGuardMiddleware` (`on_call_tool` hook) を追加。
  mutating tool (19) のみ gate し read tool (20) は素通し。sliding-window rate limit + concurrency 上限 +
  per tool-call input byte 上限を **actor-keyed** で適用。現状 MCP は固定 default actor で動くため
  enforcement は実質 global だが、`resolve_actor_key` は caller 申告を無視して server-owned key を返す
  ため、SP-016 で per-actor 認証が wired されると自動的に per-actor になる (idempotency table と同じ
  forward-compat)。閾値は env-tunable (`TASKMANAGEDAI_MCP_MUTATION_RATE_LIMIT` / `_WINDOW_SEC` /
  `_MAX_CONCURRENT_MUTATIONS` / `_MAX_TOOL_INPUT_BYTES`) で単一ユーザー通常利用では発火しない generous
  既定値 (240/60s / 32 concurrent / 256 KiB)。guard 内部エラーは **fail-open** (可用性優先)。本 ingress
  guard は per-run `BudgetGuard` (token/cost gate) を **置き換えず補完** する (entry 時の rate/concurrency/size)。
- **gap #2 (stdio hardening)**: MCP-reachable な subprocess は **唯一 agent_spawner のみ** (Discord 通知は
  R7 F-10 で subprocess を全廃し in-process httpx 化済 = 子 process なし。下記 F-10/F-12 参照)。
  - **agent_spawner** (`superintendent_agent_start` MCP tool 経由、Codex R5 F-7 / R6 F-9): provider
    executable (`claude`/`codex`/`echo`) を bare name から **絶対 path 解決** (`_resolve_executable`:
    shutil.which → realpath → 絶対 assert)。**project-local binary を拒否** (解決先が project_dir 配下なら
    ValueError、poisoned PATH / project-local hijack で user 資格情報露出する command hijack を防ぐ)。
    加えて (Codex R10 F-15) **ambient PATH poisoning 拒否**: 解決先が tmp / user-writable transient
    prefix (`/tmp` / `/private/tmp` / `/var/tmp` / `/dev/shm` / `$TMPDIR`) 配下なら ValueError、子 process の
    PATH を ambient から継承させず **最小 trusted PATH** (system 標準 dir + 解決済み executable の dir) に
    **再構成** (poisoned PATH を agent へ持ち越さない)。さらに (Codex R12 F-17) **group/world-writable な
    executable / dir を stat で拒否** (他ユーザ writable = command hijack vector、user-owned 755 の
    `~/.local/bin` 等の正規 install 先は通す)。設定済み絶対パス executable allowlist (環境依存) は SP-035
    architecture へ defer。
    加えて **process lifecycle hygiene** (R6 F-9): 未使用 pipe を **DEVNULL** (stdin/stdout/stderr、prompt
    未書込 / 出力未 drain による hang を防ぐ)、`stop_agent` を **process group kill** (`os.killpg` +
    fallback、`start_new_session=True` の child の descendant 残留を防ぐ、kill_all_agents と同 semantics)。
    **honest 限界 (R10 F-15)**: 設定済み絶対パス executable allowlist 化 (環境依存、claude/codex の install
    先が `~/.local/bin` 等で固定 allowlist 不可) は SP-035 agent-supervision architecture (task #16) の範囲。
  - max request bytes は middleware の per tool-call argument byte 上限で実現 (post-parse、F-4 参照)。
  - scope 外: cli_artifact launcher / sops_resolver / runner_adapter / anti_gaming の subprocess は MCP 経由で
    呼ばれない別 subsystem (各 Sprint の hardening 範囲)。
- **gap #3 (caller-supplied server-owned field reject)**: 全 39 tool の inputSchema が `additionalProperties:False`
  (FastMCP が extra field を reject) + server-owned field (actor_id/tenant_id/policy_profile 等) を露出する tool
  ゼロ、を **明示 negative test 化**。read/mutate partition (MUTATION_TOOLS 19 / READ_TOOLS 20) は 5+ source
  drift guard (`test_partition_covers_all_registered_tools`) で全 39 と一致を固定。
  - **Codex R11 F-16 + R12 F-18 adopt (secret leak 防止)**: FastMCP/Pydantic の additionalProperties rejection は
    **raw field value を ValidationError / WARNING ログへ露出**する (例: `capability_token` の secret 値)。これを
    防ぐため `MutationGuardMiddleware` で **FastMCP validation 到達前**に `SERVER_OWNED_FORBIDDEN_FIELDS` を
    検出し、**field 名のみ**の `ToolError` (`error_code=caller_supplied_field_rejected`, `fields=[...]`) で拒否
    (raw value は log / 例外 / payload に一切出さない)。**F-18**: 検出 set を server-owned identity 9 種に加え
    repo canonical な `_PROHIBITED_PAYLOAD_KEYS` (api_key / secret_capability_token / raw_token / session_token /
    provider_key 等の alias) と **union** (drift 回避)。**F-20**: 判定を **case-insensitive** 化
    (`API_KEY` / `Raw_Token` 等の大文字 alias が guard を擦り抜け FastMCP validation で raw value 露出するのを
    防ぐ、original 名は response に保持)。regression は複数 secret-alias + **case variant** に **parametrize**
    (`capability_token` / `API_KEY` 等の canary が例外文字列・caplog・MCP payload のどこにも出ない、middleware 直 +
    `_call_tool_mcp` protocol 経由)。
  - **Codex R15 F-23 + R16 F-24 adopt (unknown-field secret leak 防止 + fail-closed)**: forbidden 名でない
    **unknown** top-level 引数 (`unexpected="sk-proj-..."`) や secret-shaped **key** (`{"sk-proj-...": x}`) は
    FastMCP の additionalProperties rejection で raw value が ValidationError / WARNING へ露出する。FastMCP
    validation 到達前に `arguments_contain_secret` で検出し、**generic** error (`caller_supplied_secret_detected`、
    field 名 / 値を一切含めない) で reject。**F-24**: scanner を **bounded iterative** (明示 stack、`RecursionError`
    で fail-open する経路を排除) + node 上限超の巨大/深い payload は **fail-closed** で secret 疑い扱い。さらに
    middleware を **security check (fail-CLOSED)** と **availability check (rate/concurrency、fail-open)** に
    **分離** (security scan の例外は素通しせず reject)。`estimate_input_bytes` も bounded iterative 化。
    **F-25**: scanner が **全 depth** の dict key を `SERVER_OWNED_FORBIDDEN_FIELDS` (prohibited 名、case-insensitive)
    と照合 (broad pattern 非該当の短い token でも nested `{"capability_token": "short"}` を止める)。regression は
    unknown-field / secret-shaped-key / nested-value / **nested-prohibited-key** + **3000-deep nesting** +
    node-cap fail-closed + scan-crash fail-closed (secret fragment が例外・caplog・payload に出ない)。**副次効果**:
    許可 field の secret-shaped 値も MCP ingress で reject (F-22 の MCP-write path closure)。
  - **Codex R12 F-19 + R14 F-21 adopt (nested secret echo 防止)**: `delegation_create` の free-form `task_spec`
    JSON は `bridge_delegation_create` が response に raw echo する。`task_spec={"capability_token": "<secret>"}`
    が DB / MCP payload へ漏れるため、bridge 冒頭で `_assert_freeform_payload_no_secret` (再帰検査) を実行し、
    hit 時は store / echo 前に generic error (`task_spec_contains_secret`、raw value 非露出) で **fail-closed
    reject**。検査対象は (a) dict **key** の prohibited 名 + **broad scanner** (F-21: `{"sk-proj-...": ...}` の
    secret-shaped key も拒否)、(b) string **値** の broad scanner、を再帰。regression (helper の prohibited-key /
    secret-shaped-key / value-pattern / clean + bridge が DB access 前に reject)。
- **Codex adversarial R1 HIGH (F-1) adopt**: `run_cost` を read 風の名前で READ 分類していたが、
  `bridge_run_cost` が `AgentRun.cost_usd` / `tokens_*` を書き込み commit する mutating path で guard を
  bypass していた (cost/KPI 汚染リスク)。`run_cost` を MUTATION_TOOLS へ移動 (18→19) + **semantic drift
  guard** (`test_committing_bridges_are_classified_mutating`: commit する bridge を呼ぶ tool が READ 分類なら
  fail、AST 解析) を追加し再発防止。set 数だけの drift guard では捕捉できなかった class を semantic に固定。
- **Codex adversarial R2 MEDIUM (F-3) adopt**: input-size cap を mutating tool のみに適用していたが、
  oversized **read** 引数 (ticket_search / context_auto 等) で memory/CPU/DB-heavy path に誘導され得る。
  input-size 判定を `input_size_exceeded` に分離し middleware の read/mutate split **前** に全 tool へ適用
  (transport-wide)。rate-limit + concurrency は mutating のみ維持。regression test
  (`test_oversized_read_tool_rejected`) 追加。
- **Codex adversarial R2 HIGH (F-2) adopt (honest scoping、shared backend は SP-016/P0.1 へ defer)**:
  rate/concurrency state は module-global = **当該 server process 内に閉じる**。stdio deployment で
  client ごとに別 server process が spawn されると process ごとに quota 独立 → cross-process な global
  per-actor quota にはならない。本 guard を「**per-process DoS 緩和** (単一 process 内の runaway loop /
  write storm 抑止)」と claim を正直化 (code docstring + 本 §)。cross-process enforcement は共有 counter
  backend (Redis / PG advisory lock) が必要で per-actor 認証 (SP-016) + multi-agent orchestration (P0.1)
  と結合するため、そこで shared-backend 化する (現状固定単一 actor では cross-process 共有の実益も限定的)。
  この scope 限定が `partial_skeleton` 維持の追加理由 (over-claim 回避)。
- **Codex adversarial R3 MEDIUM (F-5) + R4 MEDIUM (F-6) adopt**: `bridge_ticket_list` (F-5) と
  `bridge_ticket_search` (F-6) が raw `limit` を実 query (`LIMIT :limit`) へ渡していた (小 input でも
  `limit=1e9` で tenant-wide unbounded read)。両者を **clamp-before-query** へ修正 + regression
  (`test_ticket_list_clamps_query_limit_before_db` / `test_ticket_search_clamps_query_limit_before_db`:
  limit=1e9 → 実 SQL bind は `MAX_LIMIT=200`)。`LIMIT :limit` 系 read bridge 全件監査済
  (ticket_list / ticket_list_all / ticket_search / audit_list / run_list / delegation_inbox は全て
  clamp-before-query)。残: notification_list は SQL `LIMIT :raw` ではなく repo 全件 fetch → Python
  `[:limit]` slice (per-actor 件数で自然に bounded、別 pattern)。
- **Codex adversarial R3 HIGH (F-4) adopt (honest scoping)**: 引数 byte cap は FastMCP が JSON-RPC frame
  を deserialize した **後** に効く **post-parse argument cap** (defense-in-depth) であり、raw stdio frame
  の transport-level size limit ではない。`MAX_TOOL_INPUT_BYTES` の claim を正直化 (code docstring + 本 §)。
  local trusted stdio (MCP client = user 自身の Claude Code/Codex、network 露出なし) では transport-frame
  DoS は低優先 + FastMCP が transport size 設定を露出しないため、真の frame-size 制限は transport layer
  patch を要する follow-up とする (P0 は post-parse cap で defense-in-depth)。

### partial_skeleton 維持の残 acceptance (completed 化の前提、honest)

本 hardening 後も以下が未達のため `completed` にしない (over-claim 回避):
- explicit outputSchema (mutating tool の構造化出力 model) + tool annotations (readOnlyHint/idempotentHint)。
- cross-process な per-actor rate/concurrency enforcement (shared counter backend、SP-016/P0.1)。
- raw stdio transport frame-size limit (transport layer、上記 F-4)。
- read-side の rate/cost guard (DB-heavy read tool、現状は per-tool clamp + 引数 cap のみ)。
- agent_spawner の **full process supervision** (startup health timeout 強制 / bounded output capture /
  prompt 受け渡し protocol / descendant 監督 semantics、Codex R6 F-9 の architecture-level 部分) は
  SP-035 cross-process agent supervisor architecture sprint (task #16、ADR-00048) の範囲。本 PR は spawn
  hygiene (DEVNULL pipe + 絶対 argv + process-group stop) のみ closure。
- Discord 通知 path の **import-time module shadow 防止** (Codex R9 F-13): project-local `httpx.py` の
  import-time code 実行は application layer では完全に防げず、server コード完全性 (deployment / file 権限)
  の問題で SP-034 scope 外。本 PR は post-import trust gate (fail-closed) の defense-in-depth に留める。
- **MCP-wide な許可 free-form text 値の secret scanning** (Codex R14 F-22、partial closure 済 + residual defer):
  R15 F-23 の `arguments_contain_secret` により MCP ingress では **secret-shaped 値** (`description="sk-proj-..."`
  等) も reject されるようになった (MCP-write path の closure)。**残る F-22 residual** = (a) **既に DB 保存済の
  legacy 値** の read 時 redaction、(b) **web UI 等 MCP 以外の入口** からの同種入力、(c) どの field を
  reject vs redaction にするかの **app-wide design** + false-positive policy。これらは MCP ingress hardening の
  範囲外で、専用 Pack / ADR で決める **別 follow-up** (task #26、honest defer)。
- **検証**: `tests/mcp/test_mcp_hardening.py` 22 passed、full `tests/mcp/` 63 passed + 10 DB-gated skip
  (regression なし、middleware は直接 tool 呼び出しを bypass)。ruff clean / 新規 file mypy clean
  (mcp/ 残 5 mypy は pre-existing baseline)。
- **completed 化しない理由 (台帳 honesty、over-claim 回避)**: acceptance「all mutating tool に inputSchema +
  **outputSchema** + **annotations** 定義」のうち、inputSchema は充足 (additionalProperties:False) だが、
  **explicit outputSchema (構造化出力 model) と tool annotations (readOnlyHint/idempotentHint 等の advisory
  client hint) が未設定**。これらは security 制御ではなく client metadata だが acceptance に列挙されており、
  未達のまま completed 化すると over-claim になる。よって status は `partial_skeleton` 維持、残項目を本 §に
  明示する (annotations/outputSchema は FastMCP decorator への付与 + 出力 model 定義が必要な別 scope)。
- 実装 file: `backend/app/mcp/hardening.py` (新) / `middleware.py` (新) / `server.py` (+middleware 登録) /
  `discord_notify.py` (subprocess hardening) / `tests/mcp/test_mcp_hardening.py` (新、22 tests)。
  codex-adversarial-review + 採否判定済 (PR で記録)。
