---
id: "ADR-00048"
title: "Superintendent emergency stop (human-only kill switch 配線、SP-035 gap)"
status: "proposed"
date: "2026-06-05"
accepted_at: null
deciders: ["t-ohga"]
adr_gate_criteria: [1, 3, 4]
related_adr:
  - "ADR-00027 (Superintendent Agent / SP-035 の正本、本 ADR はその kill switch acceptance gap を塞ぐ)"
  - "ADR-00014 (Multi-Agent Orchestration / orchestrator lease・kill switch boundary)"
  - "ADR-00036 (DB から actor_type を resolve する owner/human gate の先例)"
related_dd:
  - "DD-03 (AI オーケストレーション / AgentRun state machine、runtime_blocked)"
  - "DD-04 (セキュリティ・権限・監査 / human-only decision boundary、audit)"
related_sprints:
  - "SP-035_superintendent_agent (partial_skeleton、本 ADR で kill switch acceptance を充足)"
supersedes: null
superseded_by: null
---

# ADR-00048: Superintendent emergency stop (human-only kill switch 配線、SP-035 gap)

最終更新: 2026-06-05

## 背景

2026-06-04 の Sprint Pack 台帳監査 (PR #321) で、**SP-035 Superintendent Agent の受け入れ条件
「human がいつでも Superintendent + 全 agent を即停止 (kill switch)」(SP-035 Pack 行 120) が未配線**
であることが Codex CLI adversarial review (F-L5) + 実コード検証で確定した:

- `backend/app/services/superintendent/agent_spawner.py:111` の `kill_all_agents()` は実装済
  (spawned agent の process group を SIGKILL) だが、**grep 上 caller がゼロ**で MCP / API / CLI の
  どの human 経路にも配線されていない。
- 同様に `backend/app/services/orchestrator/kill_switch.py` の `OrchestratorKillSwitch.engage()`
  (human-only enforce + `orchestrator_kill_engaged` audit 済) も **caller ゼロ**で未配線。
- 結果、**暴走した Superintendent / agent を停止する human 操作手段が存在しない**。これは
  「安全な AI 実行」を premise とする本プロダクトにおける具体的な safety hole であり、SP-035 の
  明示リスク「Superintendent 自身の暴走 (kill switch 不能)」が現実に残存している。

MCP server (`backend/app/mcp/server.py`) は **AI agent surface** であり、human-only 操作
(`approval_decide` 等) は MCP に**非露出**にすることで human-only を実現している (server.py 冒頭
「approval_decide is human-only (not exposed)」)。したがって kill switch は MCP tool ではなく
**human surface (FastAPI endpoint)** に配置するのがアーキテクチャ整合的である。

## 決定対象

Superintendent が spawn した全 agent を human が即時停止する **emergency stop 経路** を、human-only
enforce + audit 付きで FastAPI endpoint として配線する。

## 前提 / 制約

- P0/P0.1 invariant 不変: AgentRun 16 status / blocked_reason 3 種 / ContextSnapshot 10 列を変えない。
- 破壊的 migration なし (本変更は DB schema 変更を伴わない、`agent_runs` の既存 `runtime_blocked` を使う)。
- raw secret / token を response / audit に出さない。
- AI 権限を拡大しない (kill は権限の**剥奪**方向であり、AI に新たな mutating 権限を与えない)。
- self-approval 禁止等の既存 approval invariant に干渉しない (kill は approval 経路を通らない緊急停止)。

## 選択肢

1. **MCP tool として `superintendent_kill_all` を追加** — ❌ 却下。MCP は AI agent surface であり、
   human-only を MCP layer で enforce する自然な仕組みがない (MCP context は `DEFAULT_SUPERINTENDENT_ACTOR_ID`
   を使い real human actor を解決しない)。`approval_decide` 非露出の既存方針と矛盾する。
2. **FastAPI endpoint `POST /api/v1/superintendent/emergency-stop` を追加し human-only enforce** —
   ✅ 採用。`get_current_actor_id` で authenticated session を解決し、DB から `actor_type == "human"` を
   検証 (`OrchestratorKillSwitch` と同 pattern)。`kill_all_agents()` 呼出 + active run の
   `runtime_blocked` 化 + audit。CLI `tm` / 将来 UI から叩ける。
3. **CLI 専用 (API なし)** — ❌ 却下。CLI も結局 backend を叩く必要があり、緊急停止は UI からも
   叩けるべき。API endpoint を core にし CLI/UI は client にするのが正しい層分け。

## 採用案 (詳細)

### endpoint

`POST /api/v1/superintendent/emergency-stop`

- 認証: `actor_id = Depends(get_current_actor_id)` (authenticated session 必須)。
- **human-only enforce**: service layer で DB から `Actor.actor_type` を resolve し `human` 以外は
  `EmergencyStopForbiddenError` → HTTP 403 + `reason_code=non_human_actor`。`cli_artifact/decision.py`
  の human-only 強制と同 pattern (caller 申告ではなく DB resolve)。
- response model: `{ stopped_agent_count, blocked_run_count, stopped_at }` (raw secret / pid / token 非含)。

### service (`backend/app/services/superintendent/emergency_stop.py`)

1. `actor_type == "human"` を DB resolve + 検証 (fail → forbidden)。
2. `kill_all_agents()` を呼び spawned process を SIGKILL、停止した agent_id リスト取得。
3. 当該 tenant の active (非 terminal) AgentRun を `blocked` + `blocked_reason='runtime_blocked'`
   へ遷移 (既存 state machine 経由、`error_code='superintendent_emergency_stop'`)。AgentRunEvent
   `runtime_blocked` + audit_events を append-only で記録。
4. audit event payload: `actor_id` (human), `stopped_agent_count`, `blocked_run_count`,
   `reason='superintendent_emergency_stop'`, `trace_id`, `correlation_id`, `timestamp`。raw 値なし。

### auto-approve policy resolution は本 ADR scope 外 (意図的 defer)

SP-035 F-L5 のもう一方 (`superintendent_dispatch` が `POLICY_TEMPLATES["conservative"]` を hardcode し
project autonomy_level を解決しない) は、**conservative = 常に human approval = P0.1 の安全側 default**
であり、project-configured auto-approve を有効化するのは AI 権限拡大 (ADR Gate #4) でむしろ慎重に
すべき。本 ADR では **conservative-by-default を P0.1 の意図的な安全 default として確定** し、
project autonomy_level 解決は別 ADR / 別 scope に defer する (SP-035 Review に記録)。

## 却下案

- MCP tool での kill (選択肢 1): human-only 不整合。
- approval 経路経由の kill: 緊急停止が approval 待ちになるのは本末転倒。kill は approval を通さない。
- agent 個別 stop の連打: race / 取りこぼし。全停止は atomic な一括経路にする。

## リスク

- **誤操作リスク**: human が誤って全 agent を停止 → 進行中作業が `runtime_blocked` で停止。緩和:
  endpoint は明示的な POST + (将来 UI では) 確認 dialog。停止は `blocked` (terminal でない) なので
  原因解消後 resume 可能 (AgentRun state machine の `blocked → running`)。
- **DoS リスク**: 連打で繰り返し kill。緩和: kill は冪等 (既に停止済は no-op)、human-only で外部到達不可
  (Tailscale 閉域 + authenticated session)。
- **audit 改ざん**: なし (append-only audit、raw 値なし)。

## rollback 手順

1. 本変更は additive (新 endpoint + 新 service + audit event 種別)。DB schema 変更なし。
2. rollback は endpoint 登録を router から外す + service を削除する revert PR (`git revert <merge SHA>`)。
3. 既存 `kill_all_agents` / `OrchestratorKillSwitch` は元から未配線だったため、revert で従来状態に戻る
   (機能の喪失なし、安全性の追加が無効化されるだけ)。

## 実装対象ファイル

- `backend/app/services/superintendent/emergency_stop.py` (新規 service、human-only + kill + blocked 遷移 + audit)
- `backend/app/api/superintendent.py` (新規 router、`POST /emergency-stop`)
- `backend/app/api/router.py` (router 登録)
- `cli/tm/commands/superintendent.py` (新規 CLI、`tm superintendent emergency-stop`、任意・後続可)
- `backend/tests/superintendent/test_emergency_stop.py` (新規 test)

## テスト指針

- **positive**: human actor で emergency-stop → spawned agent が kill され、active run が
  `blocked`+`runtime_blocked` に遷移、audit event が raw 値なしで記録される。
- **negative (human-only)**: `agent` / `service` / `provider` / `github_app` actor_type で 403 +
  `reason_code=non_human_actor`、kill が**実行されない** (agent 残存)。
- **冪等性**: agent 不在で emergency-stop → `stopped_agent_count=0`、エラーにならない。
- **state machine**: 停止対象は非 terminal run のみ (completed/failed/cancelled は遷移しない)。
- **audit**: `assert_no_raw_secret` で raw secret / token / pid が audit payload に出ないことを確認。
- **tenant 境界**: 別 tenant の run を停止しない。

## Hard Gates / KPI への trace

- AC-HARD 直接の新規 fixture は不要 (本変更は安全性の**追加**であり既存 gate を緩めない)。
- DD-04 の human-only decision boundary + append-only audit invariant に整合。
