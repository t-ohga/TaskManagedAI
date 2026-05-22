---
id: "ADR-00013"
title: "Remote Agent Integration Extension Point (Codex app-server / Claude Agent SDK)"
status: "proposed"
date: "2026-05-10"
authors:
  - "t-ohga"
related_sprints:
  - "SP-006_cli_artifact"
  - "SP-007_runner_sandbox"
requires_adr_updates:
  - "ADR-00006 (Secrets management): app-server token の SecretBroker 統合"
  - "ADR-00007 (External exposure): WebSocket listener 制約"
  - "ADR-00010 (Provider change): Codex / Claude SDK Matrix entry 追加"
acceptance_blocked_by:
  - "SP-006 (CliArtifactAdapter) accepted + Sprint Exit"
  - "SP-007 (Runner Sandbox) accepted + AC-HARD-05/06 PASS"
  - "SP-008 (RepoProxy) accepted + AC-KPI-02 trace 確立"
  - "ADR-00006/00007/00010 update draft + accepted/co-accepted"
  - "Thread/Turn/Item ↔ AgentRun 16 状態 mapping table contract fixture PASS"
supersedes: null
superseded_by: null
---

このテンプレの使い方: ADR Gate Criteria #4 (AI エージェント権限)、#5 (MCP / tool 権限)、#6 (Secrets 管理)、#7 (外部公開)、#10 (Provider 追加 / 切替) に同時該当する Remote Agent Integration の **extension point** を P0 では deny / proposed で固定し、P0.1 / P1 で accepted 化して実装するための ADR。SP-006 §「対象外」line 47 で「Codex App Server / Claude Remote Control adapter は P0.1 / P1 へ defer、この Sprint では設計 note と extension point に止める」と既に書かれているが、正式仕様化されていないため本 ADR で固定する。

最終更新: 2026-05-22 (SP-014 batch 0e で P0.1 deny-only `remote_agent_gateway` stub 例外を明記。full remote integration は proposed 維持)

## 背景

- 決定対象: TaskManagedAI に **Codex app-server (WebSocket / JSON-RPC、Thread/Turn/Item モデル)** および **Claude Agent SDK (subscription 内 remote 接続)** の richer integration を将来追加するための extension point boundary 仕様。
- 関連 Sprint: SP-006 (CliArtifactAdapter)、SP-007 (Runner Sandbox)、SP-008 以降 (RepoProxy / GitHub PR)
- 前提 / 制約:
  - Sprint 5 で ProviderAdapter (OpenAI/Anthropic/Gemini API 直叩き) は完成済。Provider Compliance Matrix v2 + 13 reason_code が runtime invariant。
  - SP-006 は CliArtifactAdapter (`codex exec` / `claude -p` subprocess + artifact) を P0 must_ship として実装する。Codex app-server / Claude Agent SDK は P0 deny。
  - AI Output Boundary §1 は AI 出力直結を絶対禁止。app-server の `item/commandExecution/requestApproval` / `item/fileChange/requestApproval` は TaskManagedAI Approval Workflow と二重承認になりうる。
  - SecretBroker は `secret_ref` URI と capability token のみ DB 保存、raw secret 非保存。app-server token も同 boundary を維持する必要がある。
  - DD-05 / ADR-00007 は Tailscale 閉域 P0 必須、Funnel / public 公開 deny。app-server の WebSocket listener も同制約。
  - ロードマップ §94 正本順序: Sprint 5 → 5.5 → 6 → 7 → 8 → ...。Remote Agent Integration は 8 完了後 (P0.1) が最速。
- 動機:
  - サブスクリプション (ChatGPT Plus / Claude Pro) 内で remote 接続して TaskManagedAI 内のタスクを AI が消化する flow を P0.1 / P1 で実現したい。
  - 雑な後付け実装は既存 5 boundary (ProviderAdapter / CliArtifactAdapter / SecretBroker / Approval / `runner_mutation_gateway`) を破壊するリスクが高いため、proposed ADR で boundary 仕様を事前固定する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: 現状維持 (ADR なし、SP-006 note のみ) | Sprint で実装時に都度判断 | 軽量、追加 docs なし | drift 発生、P0.1 着手時に再設計必要、Sprint Pack DoD 不整合 |
| **B: 本 ADR proposed で extension point 正式仕様化 (採用)** | P0 deny、P0.1 / P1 で accepted 化して実装 | 既存 5 boundary との衝突点を事前固定、SP-006 / SP-007 / SP-008 と整合維持 | ADR 1 件追加、proposed → accepted の gate 管理コスト |
| C: P0 内に簡易 stub 実装を入れる | P0 段階で extension point の最小経路を作る | 早期に動く感じが出せる | P0 scope creep、5 boundary 同時拡張で破壊的、Hard Gates 7 への影響 |

## 採用案

- 採用: **B (本 ADR proposed で extension point 正式仕様化)**
- 理由:
  - 既存 5 boundary との衝突点を **事前に固定**することで、P0.1 / P1 着手時の再設計コストを下げる。
  - SP-006 §「対象外」line 47 / line 97 / line 163 / line 180 / line 193 で既に extension point は note 化されており、本 ADR はその正本化のみで scope creep を起こさない。
  - P0 では accepted 化しないため Sprint 5.5 / 6 / 7 / 8 の must_ship を破壊しない。
- 実装 Sprint: P0 では実装しない (SP-006 で extension point note のみ)。**accepted 化は P0.1 着手時** (Sprint 8 RepoProxy 完了後が最速)。

### P0 期間中の scope guard (R1-F-001 fix、proposed ADR 段階の deny 範囲)

**P0 で作成可能な成果物**:
- 本 ADR (ADR-00013) 本文
- SP-006 / SP-007 / SP-008 の note + planned_adr_refs に reference として ADR-00013 を追加すること
- accepted 化前提条件で明示する rollback fixture / mapping table 草案 (P0.1 着手時 review 用、ただし `tests/` 配下の実 fixture は P0 では deny)

**P0 で作成禁止 (proposed の間の物理的禁止)**:
- `backend/app/adapters/remote_agent/*.py` (codex_app_server_adapter / claude_agent_sdk_adapter / 任意 stub)
- `backend/app/services/remote_agent_gateway.py` (full gateway 実装)
- `backend/app/api/remote_agent_router.py`
- `frontend/app/remote-agent/*`
- `config/remote_agent_compliance.toml` (Provider Compliance Matrix 独立 entry の追記も含む)
- `tests/{integration,security,contract}/remote_agent/*.py`
- 既存 `provider_compliance.toml` への `codex_app_server` / `claude_agent_sdk` 行追加

これらは **本 ADR が accepted に昇格するまで** 一切作成しない。proposed のまま PR が立った場合は reject。CI lint で path allowlist enforce することを accepted 化時の追加要件にする。

**SP-014 batch 0e 例外 (accepted via ADR-00014 / SP-014)**:

- `backend/app/services/remote_agent_gateway/deny_only.py` は P0.1 deny-only stub として作成可。
- adapter、API router、external listener、remote compliance config、provider matrix entry は引き続き禁止。
- deny-only stub は dispatch を実行せず、`audit_events.event_type='remote_agent_dispatch_denied'` を書いて `decision='deny'` を返すだけに限定する。
- payload は `gateway_kind='remote_agent'`、`reason_code='p0_1_stub'`、tenant / actor / role / requested_remote_role / capability_class / run_id? / project_id? を含め、raw secret / raw token / provider raw response を含めない。
- 本例外は full remote integration の accepted 化ではない。Codex app-server / Claude Agent SDK adapter は本 ADR の `acceptance_blocked_by` 全件が satisfied になるまで引き続き prohibited。

### 実装対象ファイル (P0.1 / P1 で、accepted 化後に作成)
  - `backend/app/adapters/remote_agent/codex_app_server_adapter.py` (新規)
  - `backend/app/adapters/remote_agent/claude_agent_sdk_adapter.py` (新規)
  - `backend/app/services/remote_agent_gateway.py` (新規 gateway、`runner_mutation_gateway` / `tool_mutating_gateway_stub` と並列の第 3 gateway)
  - `config/remote_agent_compliance.toml` (Codex 内部 OpenAI モデル / Claude Agent SDK モデルの Provider Compliance Matrix 独立 entry)
  - `backend/app/api/remote_agent_router.py` (TaskManagedAI backend を Codex app-server / Claude SDK に対する **bridge** として動かす API)
  - `frontend/app/remote-agent/*` (Browser → backend → app-server の bridge UI、token は backend のみ保持)

### 実装ガイダンス (boundary 仕様)

#### Thread/Turn/Item ↔ AgentRun 16 状態 mapping (R1-F-004 fix)

| Codex / Claude SDK 概念 | TaskManagedAI 概念 | mapping note |
|---|---|---|
| `thread` 開始 (`thread/started`) | `agent_run.status='queued' → 'gathering_context'` | run_queued / context_gathered event |
| `turn` 開始 (`turn/started`) | `context_snapshot` (snapshot_kind=`pre_tool`) + `agent_run.status='running'` | provider_requested event |
| `item/agentMessage/delta` | `agent_run_event` (kind=`provider_responded`、payload は redacted summary) | streaming は accumulate して `artifact_generated` で一括 |
| `item/commandExecution` | **deny by default** (capability class deny、後述 F-002 fix) → `agent_run_event` (kind=`runtime_blocked`) | `runner_mutation_gateway` 経由のみ許可 |
| `item/fileChange` | `agent_run_event` (kind=`artifact_generated`) → schema validation → `policy_linted` → `diff_ready` | canonical pipeline 通過必須 (R1-F-017 fix) |
| `turn/diff/updated` | `agent_run_event` (kind=`diff_ready`) | `artifact → schema_validated → policy_linted` 後のみ |
| `item/*/requestApproval` | `agent_run.status='waiting_approval'` + `approval_requests` row (4 整合 binding) | F-006 fix で 4 整合適用 |
| `turn/completed` (status=`success`) | `context_snapshot` (snapshot_kind=`post_tool`) → `agent_run.status='completed'` | run_completed event |
| `turn/completed` (status=`failed`) | `agent_run.status='failed'` または `provider_refused` / `provider_incomplete` | provider failure mapping は ADR-00010 と整合 |
| `turn/interrupted` / cancel | `agent_run.status='cancelled'` | run_cancelled event |
| schema invalid / validation failure | `agent_run.status='validation_failed'` → repair retry → `repair_exhausted` | Sprint 5.5 (Output Validator) の pipeline 利用 |
| budget / policy deny | `agent_run.status='blocked'` + `blocked_reason` ∈ {policy_blocked, budget_blocked, runtime_blocked} | 16 状態の blocked サブ 3 維持 |

accepted 化前提条件として **本 mapping table の contract fixture PASS** を要求 (acceptance_blocked_by に明記済)。

#### Canonical pipeline mapping (R1-F-017 fix)

remote-agent から来る raw `item` は AI Output Boundary §1 の canonical sequence を**必ず通過**:

```
remote agent raw item (item/agentMessage/delta / item/fileChange 等)
  → artifact (immutable、content hash + payload_data_class)
  → schema_validated (JSON Schema / Pydantic)
  → policy_linted (forbidden path / dangerous command / secret canary)
  → diff_ready (patch path allowlist / diff size / repo_state binding)
  → approval_required → waiting_approval (4 整合)
  → runner_or_repo_action (runner_mutation_gateway / RepoProxy 経由)
```

**raw item を直接 `diff_ready` に mapping することは禁止**。schema_validated / policy_linted を skip する経路は AI Output Boundary §1 違反。

#### Capability class deny (R1-F-002 fix、`thread/shellCommand` 単独禁止から拡張)

`remote_agent_gateway` は protocol method 名ではなく **capability class** で deny-by-default にする。以下の class が remote agent から要求された場合は **無条件 deny** (run_id / actor / tenant に関係なく):

| Capability class | 例 (Codex / Claude SDK protocol) | 代替経路 |
|---|---|---|
| `os_command_execution` | `thread/shellCommand`、`item/commandExecution` (任意 alias)、MCP tool で shell 起動を含むもの | `runner_mutation_gateway` 経由のみ |
| `file_mutation` | `item/fileChange` で workspace 書き込み | `runner_mutation_gateway` 経由のみ |
| `repo_mutation` | git push / commit / branch 作成 | `RepoProxy` 経由のみ (Sprint 8) |
| `external_network_mutation` | curl / fetch で外部 API への mutating call | `tool_mutating_gateway_stub` (P0 deny-only) または P1 `mcp_mutating_gateway` |
| `secret_resolution` | 任意 token / key の plaintext 取得 | `SecretBroker` redeem 経由のみ (raw 値は memory-only) |
| `workspace_write` | `cd` 範囲外の write、temp file 残置 | runner sandbox 内のみ |

deny rule は **method 名ではなく intent / effect** で判定する。alias / 新 protocol 名 / MCP tool / approval request 経由でも capability class が一致すれば deny。AC-HARD-05 fixture も alias / bypass 名を含む negative test を要求する。

#### Secret redaction invariant (R1-F-003 fix、SecretBroker 統合の境界拡張)

remote-agent secret (Codex token / Claude SDK key / app-server capability token) は SecretBroker redeem 後も **以下を invariant として禁止**:

- **memory-only**: redeem 後の plaintext は backend bridge process memory にのみ存在、それ以外の永続化は禁止
- **no artifact**: artifact body / metadata に plaintext を含めない (sha256 prefix / pattern hit 種別のみ可)
- **no log**: structured log / stderr / stdout / debug log に plaintext を出さない
- **no snapshot**: ContextSnapshot の任意カラム (`provider_continuation_ref` 含む、`exportable=false` でも) に plaintext を入れない
- **no provider payload**: Provider Compliance Gate `provider_request_preflight` で plaintext / token pattern を scan、検出時 deny
- **no approval body**: Approval Workflow の `artifact_hash` / 表示 body に plaintext を入れない
- **no audit body**: AuditEvent payload は redaction 済み (raw 値は別 path、retention 限定)

AC-HARD-02 fixture は browser 非露出だけでなく artifact / log / snapshot / provider payload / approval / audit の **6 経路すべて** の secret_canary_no_leak を verify する。

#### SecretBroker 統合 (簡略)

app-server capability token / Claude SDK key は `secret_ref` URI で管理。`secret://sops/p0/codex-app-server-token#vN`。`runner_injectable=false` 強制。redeem は SecretBroker atomic claim + OperationContext fingerprint。raw token は browser に渡さない、backend bridge のみが保持。

#### Provider Compliance Matrix (簡略)

Codex 内部 OpenAI gpt-5.x / Claude Agent SDK モデルは **独立 entry** として登録 (`provider=codex_app_server`、`api_or_feature=thread_turn` / `provider=claude_agent_sdk`、`api_or_feature=agent_message`)。`payload_data_class` は turn 単位で算出、`allowed_data_class` は entry から resolve。詳細 update checklist は §関連 ADR (ADR-00010 update) を参照。

#### Approval Workflow 4 整合適用 (R1-F-006 fix)

remote-agent approval request も TaskManagedAI Approval Workflow の **4 整合 binding を満たさない限り Approval Inbox に載せない**:

1. `artifact_hash`: remote agent の `item` を artifact 化した sha256
2. `policy_version`: 当該 turn 時点の policy pack version
3. `provider_request_fingerprint`: turn の OperationContext canonical fingerprint (`thread_id` / `turn_id` / model_resolved / payload_hash 含む)
4. `action_class`: `task_write` / `repo_write` / `pr_open` / `secret_access` のいずれか

4 整合の **いずれか 1 つでも mismatch なら invalidated**、Approval Inbox に載せず deny。app-server 側の `item/commandExecution/requestApproval` を backend bridge が中継する際に 4 整合の計算と verify を行う。**race / replay / payload 差し替え攻撃**は 4 整合 mismatch で防ぐ。

test 指針 (P0.1): `tests/integration/remote_agent/test_approval_unification.py` に **4 整合 mismatch negative cases** (artifact_hash 差し替え / policy_version stale / provider_request_fingerprint 改変 / action_class 違反) を必須含める。

#### 第 3 gateway `remote_agent_gateway` precedence (R1-F-009 fix)

既存 2 gateway との責務境界と precedence を明示:

```
[remote_agent_gateway]
  - Codex app-server / Claude SDK protocol → artifact 化 (immutable)
  - capability class deny (上記 F-002 fix)
  - mutation intent は必ず下位 gateway に **委譲**

[tool_mutating_gateway_stub] (Sprint 4.5、P0 deny-only)
  - MCP / external tool 書込系
  - remote agent から MCP tool 経由の mutation も deny

[runner_mutation_gateway] (Sprint 7)
  - runner sandbox 内 patch 適用
  - remote agent → file_mutation / os_command_execution capability は本 gateway 経由のみ
  - policy / approval / forbidden path / command gate を通過後のみ apply
```

**Deny precedence**: いずれかの gateway が deny を出した時点で全体 deny。`remote_agent_gateway` deny → 下位 gateway 到達せず。`tool_mutating_gateway_stub` deny → `runner_mutation_gateway` 到達せず。AuditEvent payload は `gateway_kind=remote_agent|tool|runner` を分けて記録。

#### Network boundary (R1-F-008 fix、auth/origin/CSRF 拡張)

WebSocket listener は **127.0.0.1 / Tailscale 内のみ** bind (DD-05 / ADR-00007 と整合)。加えて backend bridge layer で以下を **必須 contract** として要求:

- **authenticated TaskManagedAI session**: bridge 接続前に TaskManagedAI 内の actor / principal binding を要求 (anonymous 接続 deny)
- **origin allowlist**: WS handshake の `Origin` header を allowlist で verify (browser 内 compromised script からの接続 deny)
- **CSRF / WS hijack 対策**: per-AgentRun short-lived capability token を WS connection establishment 時に提示、reuse / replay 不可
- **per-connection rate limit**: 1 actor あたり同時 N 接続 (P0.1 で N=2 目安)、それ以上は queue / reject
- **audit event**: connection establish / close / capability token redeem を AuditEvent に記録

ADR-00007 (External exposure) update が必要 (本 ADR `requires_adr_updates` で明示済)。

#### ContextSnapshot 10 必須カラム mapping (R1-F-005 fix)

remote-agent turn ごとに以下 10 カラムを **null 不可** (DD-02 / DD-03 invariant):

| ContextSnapshot column | Codex / Claude SDK 由来 | exportable / redaction |
|---|---|---|
| `prompt_pack_version` | bridge が turn 開始時に inject | exportable=true |
| `prompt_pack_lock` | bridge inject (lock hash) | exportable=true |
| `policy_version` | bridge inject (turn 時点の policy pack version) | exportable=true |
| `policy_pack_lock` | bridge inject | exportable=true |
| `repo_state` | turn 時点の commit SHA / branch / dirty flag / diff hash | exportable=true |
| `tool_manifest` | bridge inject (registered tool list version + allowlist hash) | exportable=true |
| `evidence_set_hash` | turn 内 item 群の sha256 (NFC UTF-8 + JCS canonical JSON) | exportable=true |
| `provider_continuation_ref` | `{provider: codex_app_server, kind: thread_turn, artifact_ref: <thread_id>:<turn_id>, sha256: ..., expires_at: ..., exportable: false}` | **exportable=false** (本体は短期 artifact、監査 export から除外) |
| `provider_request_fingerprint` | `model_resolved` / `api_version` / `sdk_version` / `codex_cli_version` / `temperature` / `safety_settings` 等 (canonical JSON sha256) | exportable=true (fingerprint は redacted) |
| `snapshot_kind` | `pre_tool` (turn/started 時) / `post_tool` (turn/completed 時) / `resume` (retry 時) / `final` (run terminal 時) | exportable=true |

**actor / principal / trust level / exportability** は ContextSnapshot 自体の row metadata として記録 (10 カラムとは別)。

raw secret / app-server token plaintext は **どのカラムにも入らない** (上記 secret redaction invariant §「no snapshot」と整合)。

### テスト指針 (P0.1 / P1 着手時)

- `tests/integration/remote_agent/test_codex_app_server_adapter.py` (thread/turn/item → AgentRunEvent mapping contract、16 状態すべての代表ケース)
- `tests/integration/remote_agent/test_approval_unification.py` (app-server 承認が TaskManagedAI Approval Workflow に統一される + 4 整合 mismatch negative test 4 種)
- `tests/security/remote_agent/test_token_isolation.py` (browser に Codex token が渡らない negative test)
- `tests/security/remote_agent/test_thread_shell_command_deny.py` (capability class `os_command_execution` の alias / bypass / MCP tool 経由を含む全 deny test、R1-F-002 fix)
- `tests/security/remote_agent/test_secret_redaction_six_paths.py` (artifact / log / snapshot / provider payload / approval / audit の 6 経路すべての secret 漏洩 negative test、R1-F-003 fix)
- `tests/contract/remote_agent/test_provider_compliance_matrix_entry.py` (Codex / Claude SDK が Matrix 独立 entry として登録されている test)
- `tests/security/remote_agent/test_network_boundary.py` (WebSocket listener が 127.0.0.1 / Tailscale のみ bind + auth / origin / CSRF / per-AgentRun token verify、R1-F-008 fix)
- `tests/security/remote_agent/test_mcp_prompt_injection_resist.py` (Discord / GitHub / 任意 MCP message から approval bypass / shellCommand 許可 / secret reveal / public bind 等の指示が来ても artifact pipeline で deny される、AC-HARD-07 trace、R1-F-012 fix)
- `tests/contract/remote_agent/test_canonical_pipeline_mapping.py` (raw item → artifact → schema_validated → policy_linted → diff_ready の canonical sequence、R1-F-017 fix)
- `tests/contract/remote_agent/test_thread_turn_item_to_agentrun_mapping.py` (Thread/Turn/Item ↔ AgentRun 16 状態 mapping table の全行、R1-F-004 fix)
- `tests/contract/remote_agent/test_context_snapshot_10_columns.py` (ContextSnapshot 10 必須カラム全マッピング、R1-F-005 fix)
- `tests/security/remote_agent/test_rollback_fail_closed.py` (Provider Compliance entry 削除 / SecretBroker secret_ref 無効化 / remote_agent_gateway deny-only stub 化後に remote-agent 経路が fail-closed する、R1-F-018 fix)

## 却下案

- A (現状維持): SP-006 note のみでは boundary 仕様が固定されず、P0.1 着手時に再設計が必要。AI agent 権限 / Secrets / 外部公開 / Provider 5 件同時該当の変更を ADR なしで進めると ADR Gate Criteria 違反。Sprint Pack DoD §3 「heavy で adr_refs が空ではない」を満たさない。
- C (P0 内に stub): P0 must_ship (Sprint 5.5 → 6 → 7 → 8 → ... → 12) に含まれない feature を P0 に追加すると scope creep。Hard Gates 7 (特に AC-HARD-02 secret_canary_no_leak / AC-HARD-05 forbidden_path_block) の検証範囲が増え、Sprint 11 の P0 Acceptance fixture 整備が間に合わない。

## リスク

- **app-server protocol version drift**: Codex CLI が version 上げで Thread/Turn/Item schema 変更する可能性。`codex app-server generate-ts` で生成した型を versioned artifact として保存し、検出は CI で行う。proposed → accepted 昇格時の最初の実装で必ず schema lock を入れる。
- **thread/turn/item と AgentRun 16 状態 mapping drift**: turn 内の複数 item が AgentRun の単一 status に対応しないケースがある。例: `provider_incomplete` 中に `item/fileChange` が来た場合の event 順序。implementation guide で 16 状態 + AgentRunEvent への mapping を unit test で固定する。
- **Codex token 二重存在**: app-server token と TaskManagedAI capability token が同時に存在する。SecretBroker boundary で app-server token も `secret_ref` 化することで一元化するが、redeem flow が capability token と app-server token で 2 系統になる複雑性は残る。Sprint 4 SecretBroker と統合する場合は ADR-00006 update が必要 (本 ADR accepted 化時に同時 review)。
- **Approval flow の race condition**: TaskManagedAI Approval Inbox から承認するまで app-server の WebSocket は待機する。長時間待機による app-server side timeout / WebSocket disconnect の handling が必要。`item/commandExecution/requestApproval` への response timeout は app-server 側で 5-10 分が目安、TaskManagedAI Approval Workflow の SLA (KPI median 4h) と乖離する。実装時は async approval queue + reconnect 経路を設計。
- **subscription rate limit 連動**: Codex app-server / Claude Agent SDK は ChatGPT Plus / Claude Pro の subscription rate limit に従う。Provider Compliance Matrix とは別次元の budget 管理が必要。BudgetGuard 拡張または別 metric として `subscription_quota` を追加検討。
- **MCP server 経由の指示**: app-server は MCP server を読み込み可能。その経路で外部から悪意ある指示が混入するリスク (`mcp__plugin_discord_discord` で受けた message を AI が解釈する等)。`tool_mutating_gateway_stub` deny-only を MCP 経由でも維持する必要がある。

## Rollback 手順

- P0.1 着手前: 本 ADR を **superseded** に変更、SP-006 から extension point note を削除、`config/remote_agent_compliance.toml` 等の planned ファイルは作成前なので影響なし。
- P0.1 accepted 化後: implementation 削除 + Provider Compliance Matrix entry 削除 + SecretBroker `secret_ref` 削除 + `remote_agent_gateway` deny-only stub 化。最低 1 sprint の rollback Sprint が必要 (broad refactor 該当)。
- accepted 化後の rollback リスクが高いため、**proposed → accepted 昇格時に rollback 検証 fixture を必須**にする (本 ADR accepted 化時の追加要件として明記)。

## 関連 ADR (R1-F-007 / R1-F-011 fix、update checklist 詳細化)

### ADR-00006 (Secrets management) update checklist
- app-server capability token / Claude SDK key を `secret_ref` URI 体系に追加 (`secret://sops/p0/codex-app-server-token#vN` / `secret://sops/p0/claude-agent-sdk-key#vN`)
- `runner_injectable=false` 強制が remote-agent secret にも適用されることを明記
- redeem 経路: `SecretBroker` atomic claim + OperationContext fingerprint (turn 単位、`thread_id` / `turn_id` 含む)
- secret_capability_token の actor binding に `remote_agent_session_id` を追加 (per-AgentRun token と区別)
- redaction 6 経路 (artifact / log / snapshot / provider payload / approval / audit) を invariant section に追記

### ADR-00007 (External exposure) update checklist
- WebSocket listener (Codex app-server / 任意 remote agent) の network boundary を「127.0.0.1 + Tailscale 内」に固定
- backend bridge layer の auth / origin allowlist / CSRF / per-AgentRun short-lived capability token / per-connection rate limit を **必須 contract** として追記
- Funnel / public WebSocket 公開禁止を deny-by-default として明記
- ADR-00007 既存の Tailscale grants 表に `tag:taskhub-remote-agent` 候補 entry を追加 (P0.1 で具体化、P0 では deny-only)

### ADR-00010 (Provider change) update checklist (R1-F-007 fix)
- Provider Compliance Matrix (`config/provider_compliance.toml`) に追加すべき entry:
  - `provider="codex_app_server"`, `api_or_feature="thread_turn"`, `allowed_data_class=internal` (default、ADR で個別解禁条件明記)
  - `provider="claude_agent_sdk"`, `api_or_feature="agent_message"`, `allowed_data_class=internal` (default)
- `payload_data_class` resolver: turn 単位で artifact metadata から事前算出 (caller 入力ではない、Sprint 5 invariant 維持)
- 13 reason_code に **新規追加なし** (既存 reason_code で表現可能、`subscription_quota_exceeded` は budget_exceeded で吸収)
- retention / ZDR 条件: ChatGPT Plus / Claude Pro subscription の各公式 docs から事前確認、`condition_status=verified` まで持っていく
- subscription rate limit は別 metric `subscription_quota` として BudgetGuard に追加検討 (`provider_request_preflight` 後に check)

### ADR-00012 (Hook trust boundary) 連動 (新規予定)
- app-server から TaskManagedAI hook を呼ぶ経路がある場合 (`mcp__plugin_*` 等)、hook trust tier の検証が必要
- Wave 14 で確立した hook trust tier 3 段階 (system / project / external_mirror) と整合

## P0.1 / P1 accepted 化の前提条件 (R1-F-010 / R1-F-011 fix、evidence path 明示)

本 ADR を proposed → accepted に昇格させる前提と **gate evidence**:

1. **SP-006 (CliArtifactAdapter) accepted + Sprint Exit 完了**
   - evidence: `docs/sprints/SP-006_cli_artifact.md` の `status: accepted` + `## Review` 章記載
   - pass condition: must_ship (CLI artifact subprocess + stdout 追跡) すべて達成、AC-HARD-05/06 fixture skeleton PASS

2. **SP-007 (Runner Sandbox) accepted + AC-HARD-05 / AC-HARD-06 PASS**
   - evidence: `docs/sprints/SP-007_runner_sandbox.md` の `status: accepted` + Sprint Exit Review
   - pass condition: AC-HARD-05 (forbidden_path_block) recall=1.0、AC-HARD-06 (dangerous_command_block) recall=1.0、`runner_mutation_gateway` 完成

3. **SP-008 (RepoProxy / GitHub PR) accepted + AC-KPI-02 trace 確立**
   - evidence: `docs/sprints/SP-008_*.md` の `status: accepted` + Draft PR flow E2E PASS
   - pass condition: AC-KPI-02 (time_to_merge median ≤ 2.0h) の計測 source 確立

4. **ADR-00006 / ADR-00007 / ADR-00010 の update draft + accepted/co-accepted** (R1-F-011 fix、review だけでは不十分)
   - evidence: 各 ADR の diff merged + `status: accepted` (or `co-accepted` if 本 ADR と同時昇格)
   - pass condition: blocking finding 0、各 update checklist (上記 §関連 ADR) すべて反映、rollback fixture PASS

5. **Thread/Turn/Item ↔ AgentRun 16 状態 mapping table contract fixture PASS** (R1-F-004 fix)
   - evidence: `tests/contract/remote_agent/test_thread_turn_item_to_agentrun_mapping.py` PASS
   - pass condition: 16 状態すべての代表 case + transition table 全カバレッジ + blocked サブ 3 種 verify

6. **Rollback 検証 fixture PASS** (R1-F-018 fix)
   - evidence: `tests/security/remote_agent/test_rollback_fail_closed.py` PASS
   - pass condition: Provider Compliance entry 削除 / SecretBroker secret_ref 無効化 / `remote_agent_gateway` deny-only stub 化の 3 段階すべてで fail-closed verify

7. **CI lint で proposed 期間中の path allowlist enforce** (R1-F-001 fix)
   - evidence: `.github/workflows/*` または `scripts/lint/check_remote_agent_path_allowlist.sh`
   - pass condition: P0 で禁止 path (上記 §「P0 期間中の scope guard」list) への新規 PR を CI で reject

### proposed 化時の即時タスク (accepted 化前提ではなく immediate side task)

- SP-006 frontmatter `downstream_sprints: SP-005-5_output_validator` の drift 修正 (`upstream_sprints` に移動済 / Step A-4 完了)
- SP-006 line 27 「最終更新: 2026-05-08 → 2026-05-10」更新 (R1-F-015 fix)
- SP-006 frontmatter ADR-00013 行に `reference_only_for_p0: true` 相当の語追加 (R1-F-016 fix)

---

## Phase D R1-R4 + Phase E Multi-Agent vision update (2026-05-10、proposed 追記)

ADR-00014/15/16/17/18/19/20 (Multi-Agent vision) accepted 化に伴う本 ADR の update (Phase D PD-F-008/PD-R2-F-010 + Phase E PE-F-013 反映).

### orchestrator integration boundary (PD-F-008 / PD-R2-F-010 / PE-F-013)

ADR-00014 で導入する orchestrator agent (TaskManagedAI 内、actor_type='agent' + role_id='orchestrator') が `orchestrator_dispatched` event で **remote child** (Codex app-server / Claude Agent SDK) を作成する場合、本 ADR の `remote_agent_gateway` 経由必須:

| 期間 | remote_agent_gateway 状態 | TaskManagedAI 動作 |
|---|---|---|
| **P0 (Sprint 1-12)** | 実装 path 完全になし (P0 sealed CI guard で禁止) | Phase C/ADR-00014 spec で「remote child は本期間 deny」と宣言、orchestrator 自体が P0 期間中は単一 actor 想定 |
| **P0.1 開始時 (SP-014)** | `backend/app/services/remote_agent_gateway.py` deny-only stub 作成 | orchestrator_dispatched で remote child 試行 → 全件 deny + `remote_agent_dispatch_denied` audit_event |
| **P0.1〜P1 (SP-014 / SP-018+)** | ADR-00013 の段階承認 (本 ADR `acceptance_blocked_by` 7 件すべて満たす) で Codex app-server / Claude SDK を allowlist 拡張 | Thread/Turn/Item ↔ AgentRun mapping table で child AgentRun に変換 |

### P0 sealed CI guard 拡張 (PE-F-013)

Phase C draft §1.6 P0 sealed guard の forbidden glob に以下を追加 (本 ADR の P0 期間禁止 path):

- `backend/app/services/remote_agent_gateway.py`
- `backend/app/adapters/remote_agent/**`
- `backend/app/api/remote_agent_router.py`
- `frontend/app/remote-agent/**`
- `config/remote_agent_compliance.toml`
- `tests/**/remote_agent/**`
- `provider_compliance` の Codex / Claude SDK entry

P0.1 着手時 (TASKHUB_P0_1_OPENED=1) に解除.

### remote_agent_dispatch_denied audit_event payload schema (PE-F-013)

```yaml
event_type: remote_agent_dispatch_denied
required_payload:
  - tenant_id: bigint
  - project_id: uuid
  - parent_run_id: uuid (orchestrator run)
  - attempted_remote_provider: text (e.g. 'codex_app_server', 'claude_agent_sdk')
  - attempted_action: text (e.g. 'thread_create', 'turn_send')
  - denial_reason: text (`p0_period`, `p0_1_stub_deny_all`, `acceptance_blocked`)
  - attempted_actor_id: uuid (orchestrator agent actor)
prohibited_payload:
  - raw remote API request body
  - remote provider auth token
  - SecretBroker capability token raw value
```

5+ source 整合: audit_events.event_type CHECK + ORM + Pydantic + pytest + frontend (SP-017).

### 関連 ADR

- ADR-00014 (Multi-Agent Orchestration Foundation) — orchestrator が remote_agent_gateway 経由で child 作成
- ADR-00018 (Inter-Agent Communication Protocol) — 関連
- Phase C draft §3.5 / §11.3 PE-F-013
