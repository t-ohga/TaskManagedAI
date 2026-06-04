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

## 採用案 (詳細、plan-review R1 の CRITICAL 2 + HIGH 3 を反映した改訂版)

> **重要**: 初版は「process-global kill 即時実行のみ」で設計したが、codex-plan-review R1 が
> (1) tenant 越境 kill (2) latch 不在で再 spawn 可能 (3) state machine 逸脱 (4) 弱い human gate
> (5) MCP bypass の 5 欠陥を指摘。kill switch を**正しく**作ると tenant-scoped kill + 永続
> emergency-stop latch + operator gate + MCP hardening を伴う安全サブシステムになる。以下は改訂後。

### (A) tenant-scoped agent registry + scoped kill (CRITICAL-1 fix)

- `agent_spawner` の `_active_agents: dict[UUID, SpawnedAgent]` は process-global で tenant/project を
  持たないため、`kill_all_agents()` は**全 tenant を巻き込む**。
- `SpawnedAgent` に `tenant_id` (+ `project_id`) を持たせ、`kill_agents_for_tenant(tenant_id)` を新設。
  pre-kill で tenant 一致を確認し、**同一 operation 内で同 scope の run のみ** block する。
- `kill_all_agents()` (process-global) は emergency-stop からは**呼ばない**。

### (B) 永続 emergency-stop latch (CRITICAL-2 fix、rules instincts §14 「global kill switch は新規を止める」準拠)

- **tenant-scoped emergency-stop state** を DB に持つ (`superintendent_emergency_stops` table:
  `tenant_id`, `generation` (CAS 用 bigint), `engaged_at`, `engaged_by_actor_id`, `cleared_at`,
  `cleared_by_actor_id`、`(tenant_id) WHERE cleared_at IS NULL` partial unique で active ≤ 1)。
- engage 後、以下の **enforcement point で latch を fail-closed check** し新規活動を deny:
  1. AgentRun 作成 (`run_create` / `bridge_run_create` / orchestrator dispatch)
  2. `superintendent_agent_start` / `superintendent_agent_register` / `superintendent_dispatch`
  3. autonomy policy allow (auto-approve 経路)
  4. `provider_request_preflight` (provider call 直前)
- deny 時 reason_code `emergency_stop_engaged` を audit。

### (B-1) 並行 race の直列化 (R2 CRITICAL fix、TOCTOU 防止)

latch check と side effect (spawn / run_create / provider call) を **同一 tenant-scoped critical section**
で直列化しないと、「start が latch check 通過 → engage が kill 対象列挙 → その後 spawn 完了で process 残存」
の race が起きる。対策:

- **PostgreSQL tenant-scoped advisory lock** (`pg_advisory_xact_lock(hashtext('superintendent_emergency_stop'), tenant_id)`)
  を engage / clear / 全 side-effecting enforcement point の critical section 入口で取得。
- **engage**: advisory lock 取得 → latch row 有効化 (generation++) → scoped kill + block を **同一 lock 下**
  で実行 (latch を先に立ててから kill/block するので、以後の spawn は必ず engaged latch を見る)。
- **spawn (`agent_start`)**: advisory lock 下で latch check → process 起動 → `_active_agents` 登録までを
  同一 critical section に収める (latch check 通過後に engage が割り込めない)。
- race test (concurrent engage vs start) を must-ship に含める。

### (B-2) 全 MCP mutating tool の latch gate (R2 HIGH fix、work-advance bypass 防止)

`agent_start/register/dispatch` だけでなく、既存 run を**進行・完了・承認 event 追加**する MCP mutating
tool も latch 対象にしないと、kill し損ねた agent / stale client / 再接続 client が engaged 中に作業を
進められる。対策: **MCP mutating bridge 全体を centralize し latch gate を通す**。

- deny (fail-closed, `emergency_stop_engaged`): `run_update` / `run_create` / `delegation_accept` /
  `delegation_submit` / `delegation_review` / `approval_request_create` / `ticket_comment` /
  work-result 系 / `superintendent_*` (start/register/dispatch) 等の mutating tool。
- allow (明示 allowlist): read-only / status / `run_cancel` / `superintendent_agent_stop` / list 系。
- MCP mutating tool の網羅 negative test (engaged 中 deny / cleared 後 allow) を must-ship に含める。

### (B-3) clear / resume の state 復元 (R2 HIGH fix、gate skip 防止)

clear で一律 `blocked -> running` に戻すと、元が `waiting_approval` / `diff_ready` / `policy_linted` の
run が承認 / diff / policy gate を**飛ばして実行再開**してしまう。対策:

- emergency-stop で block する際、**`pre_stop_status` を AgentRunEvent payload (または専用列) に保存**。
- clear / resume は **human-only operator (engage と同 gate) + latch generation CAS** (stale clear 防止)。
- 復元表 (一律 running にしない):
  - `running` 由来 → `running` へ resume 可
  - `waiting_approval` 由来 → `waiting_approval` へ戻す (approval 待ち継続)
  - `diff_ready` / `policy_linted` 由来 → 元 gate へ戻す or 再評価必須
- resume 操作を latch generation CAS 付きで test (古い generation の clear は reject)。

### (C) endpoint + operator gate (HIGH-4 fix)

`POST /api/v1/superintendent/emergency-stop` (engage) + `POST .../emergency-stop/clear` (clear)

- 専用 dependency `require_emergency_stop_operator` を新設 (`get_current_actor_id` のみでは不十分):
  1. authenticated session 必須 (`request.state.authenticated` 検証、me.py `_require_authenticated_owner` 準拠)
  2. DB resolve した `actor_type == "human"`
  3. configured owner / 明示 emergency-stop role (同 tenant の別 human が勝手に発動できない)
  4. tenant context を明示
  5. unauthenticated / other-human / non-human は fail-closed (403)
- response: `{ engaged, stopped_agent_count, blocked_run_count, engaged_at }` (raw secret/pid/token 非含)。

### (D) state machine 整合 (HIGH-3 fix)

- emergency-stop の run block は **`-> blocked` の正当 source state のみ** に限定:
  `running` / `policy_linted` / `diff_ready` / `waiting_approval` (AgentRun state machine table 準拠)。
- それ以外の非 terminal state (`queued` / `gathering_context` / `generated_artifact` / `schema_validated`
  / `validation_failed` / `provider_incomplete`) は **latch (B) で新規活動を止める**ことでカバーし、
  既存 row の status は直接遷移させない (不正 transition history を作らない)。
- status update と AgentRunEvent `runtime_blocked` append は同一 transaction。terminal は不変。

### (E) MCP agent-facing stop の hardening (HIGH-5 fix)

- 現状 MCP `superintendent_agent_stop` / `_start` / `_register` は human check 無しで、AI agent が
  1 体ずつ stop して human-only kill boundary を迂回できる。
- emergency-stop latch (B) を `superintendent_agent_start` / `_register` / `_dispatch` の前段で check し、
  latch engaged 中は MCP 経路の spawn/dispatch を deny。
- `superintendent_agent_stop` (個別停止) は latch とは独立だが、emergency-stop 設計と整合するよう
  MCP tool-list / direct-call negative test で「latch engaged 中の start/register/dispatch deny」を固定。

### (F) cross-process agent supervision (R3 CRITICAL fix、実装 prerequisite)

**最重要・前提覆し**: 現状 `agent_spawner` の `_active_agents` は **MCP stdio server process** に閉じた
process-local dict で、`superintendent_agent_start` はその process 内で subprocess を spawn する。
一方 emergency-stop は **FastAPI process** (別 process / 別 container) で動くため、**API から MCP が
spawn した subprocess を直接 kill できない** (in-process dict も pgid signal も跨げない)。

→ 「(A) tenant_id 付与 + `kill_agents_for_tenant`」だけでは **kill が届かない**。正しい kill switch は
**agent supervision の cross-process 化**を prerequisite とする:

- spawn 時に agent の `host` / `process_group_id` / `tenant_id` / `project_id` / `supervisor_id` を
  **DB (or Redis) に永続登録** (in-process dict を kill の正本にしない)。
- kill の実行は、**当該 subprocess を実際に signal できる process** (agent supervisor service /
  MCP supervisor) が担い、FastAPI は latch engage + 永続 registry 更新 + control channel 通知 or
  supervisor が latch を観測して self-terminate する設計にする。
- must-ship test: 「MCP process が spawn した agent を FastAPI endpoint から (supervisor 経由で) kill できる」。

### (G) provider postflight generation CAS (R3 CRITICAL fix)

provider call を advisory lock 内に長時間保持すると即時停止にならず、lock 外にすると engage 後の
stale provider response が usage/artifact/status を進める。対策:

- preflight 時に **latch generation を予約/記録**。
- provider response 後、usage 記録 / artifact / status / event append の **前に同一 tenant lock 下で
  generation CAS + current status check**。generation が変わっていれば result を **discard / quarantine**。
- in-flight worker / provider task の cancellation / timeout 方針を明記 (kill 後の hang 防止)。

### (H) AgentRun state machine 改訂 (R3 HIGH fix)

`runtime_blocked` は canonical で `running -> blocked` のみ許可。gate-state (`policy_linted` /
`diff_ready` / `waiting_approval`) からの emergency block と、clear での復元先は **現行 transition table に
無い**。実装前に canonical state machine (rules/agentrun-state-machine.md + DB/API/frontend 5+ source +
`EVENT_TYPE_FOR_TRANSITION`) を **明示改訂**し、emergency-stop 用の block source / resume target /
event type を**実装可能な遷移列として固定**する (曖昧な「or 再評価」を残さない)。enum drift test +
resume transition test を must-ship に含める。

> **実装 prerequisite の結論 (R3 を受けて)**: (F) cross-process agent supervision の基盤再設計が
> **kill switch 実装の前提**であり、これは「1 機能の配線」ではなく **agent runtime architecture の
> 拡張**である。SP-035 の在来実装 (agent = MCP process 内 subprocess) を前提にした「即配線」は
> 不可能。本 ADR は安全要件を網羅した設計正本として残し、**実装は (F) supervisor 基盤 → (G) provider
> CAS → (H) state machine 改訂 → emergency-stop service/endpoint/latch → tests の順で、専用の
> architecture sprint として行う**。

### auto-approve policy resolution は本 ADR scope 外 (意図的 defer、F-L5 のもう一方)

`superintendent_dispatch` の `POLICY_TEMPLATES["conservative"]` hardcode は **conservative = 常に human
approval = P0.1 の安全側 default**。project-configured auto-approve を有効化するのは AI 権限拡大
(ADR Gate #4) でむしろ慎重にすべき。本 ADR は conservative-by-default を P0.1 の意図的な安全 default
として確定し、project autonomy_level 解決は別 ADR に defer する (SP-035 Review に記録)。

## 却下案

- **process-global `kill_all_agents()` を emergency-stop から直接呼ぶ** (初版設計): CRITICAL-1 (tenant 越境)。
- **latch 無しの「現プロセス kill のみ」** (初版設計): CRITICAL-2 (再 spawn で無力化)。
- **「全 active run → blocked」** (初版設計): HIGH-3 (state machine 逸脱)。
- **`get_current_actor_id` + actor_type のみ gate** (初版設計): HIGH-4 (authenticated / owner 未検証)。
- MCP tool での kill: human-only 不整合 (選択肢 1)。
- approval 経路経由の kill: 緊急停止が approval 待ちになるのは本末転倒。

## リスク

- **誤操作リスク**: human が誤って emergency-stop → 進行中作業が停止 + 新規 deny。緩和: 明示 POST +
  (将来 UI) 確認 dialog、clear で復帰可能 (`blocked → running` resume)。
- **latch clear 忘れ**: engage 後 clear し忘れると新規活動が永続 deny。緩和: latch 状態を UI/CLI/API で
  可視化、`tm superintendent status` で engaged 表示。
- **cross-tenant 巻き込み**: (A) の scoped kill + pre-kill tenant 一致 check + negative test で防止。
- **DoS / 改ざん**: kill は冪等、human-only operator + Tailscale 閉域で外部到達不可、append-only audit。

## rollback 手順

1. 本変更は **migration を伴う** (`superintendent_emergency_stops` table) + 新 endpoint + service +
   enforcement point の latch check。
2. rollback: revert PR (`git revert <merge SHA>`) + migration downgrade (table drop、lossless)。
3. 既存 `kill_all_agents` / `OrchestratorKillSwitch` は元から未配線のため、revert で従来状態 (安全性の
   追加が無効化されるだけ、機能喪失なし)。
4. enforcement point の latch check は **fail-closed だが latch row が無ければ常に allow** なので、
   revert 後も既存挙動に影響しない設計にする。

## 実装対象ファイル

- `migrations/versions/00NN_sp035_emergency_stop.py` (新規 `superintendent_emergency_stops` table、tenant scoped active ≤ 1 partial unique index)
- `backend/app/db/models/superintendent_emergency_stop.py` (ORM)
- `backend/app/services/superintendent/emergency_stop.py` (engage / clear / is_engaged、human-only、scoped kill、blocked 遷移、audit)
- `backend/app/services/superintendent/agent_spawner.py` (SpawnedAgent に tenant_id 追加 + `kill_agents_for_tenant`)
- `backend/app/api/superintendent.py` (新規 router、engage / clear endpoint)
- `backend/app/api/dependencies/emergency_stop_operator.py` (`require_emergency_stop_operator`)
- enforcement point: AgentRun 作成 / `superintendent_dispatch` / `agent_start` / `agent_register` /
  autonomy allow / `provider_request_preflight` に latch check 追加
- `backend/app/api/router.py` (router 登録)
- `cli/tm/commands/superintendent.py` (engage / clear / status、後続可)
- test 群 (下記)

## テスト指針 (must-ship、plan-review R1 next steps 準拠)

- **cross-tenant 非干渉 (CRITICAL-1)**: tenant 1 の emergency-stop で tenant 2 の agent process / run が
  **一切影響を受けない**。
- **post-stop 新規 deny (CRITICAL-2)**: latch engaged 後、AgentRun 作成 / dispatch / agent_start /
  provider preflight が `emergency_stop_engaged` で全 deny。clear 後は再び allow。
- **state machine (HIGH-3)**: block は `running`/`policy_linted`/`diff_ready`/`waiting_approval` のみ
  遷移。`queued`/`gathering_context`/`generated_artifact`/`schema_validated`/`validation_failed`/
  `provider_incomplete` の row は直接遷移しない (latch で新規活動を止める)。terminal は不変。
- **operator gate (HIGH-4)**: unauthenticated / 同 tenant 別 human / non-human (agent/service/provider/
  github_app) は全 fail-closed (403)、kill / latch engage が**実行されない**。
- **MCP bypass (HIGH-5)**: latch engaged 中の MCP `superintendent_agent_start`/`_register`/`_dispatch`
  が deny されることを tool-list / direct-call negative test で固定。
- **冪等性**: 二重 engage は no-op + 同一 latch、agent 不在 engage は `stopped_agent_count=0`。
- **audit**: `assert_no_raw_secret` で raw secret / token / pid が audit payload に出ない。

## Hard Gates / KPI への trace

- AC-HARD 既存 gate を緩めない (本変更は安全性の追加 + 新規活動 deny)。
- DD-04 human-only decision boundary + append-only audit + instincts §14 「global kill switch は新規
  AgentRun / provider call を止める」invariant に整合。
- cross-source-enum-integrity: reason_code `emergency_stop_engaged` を 5+ source で整合させる。

## 実装 status (2026-06-05)

- **status: proposed (設計正本、実装未着手)**。本 ADR は codex-plan-review **R1-R3 で計 11 設計欠陥
  (CRITICAL 5 + HIGH 6) を捕捉・反映**した安全設計の正本。
- **実装は専用の architecture sprint** とする。理由 (R3 (F)): SP-035 在来実装では agent が MCP
  stdio process 内 subprocess であり、FastAPI (別 process) の kill switch から直接届かない。正しい
  kill switch は **agent supervision の cross-process 化 (DB 永続 registry + supervisor/control
  channel) を prerequisite** とし、(F) supervisor 基盤 → (G) provider postflight CAS → (H) AgentRun
  state machine 改訂 → emergency-stop latch/service/endpoint → tests の順で実装する。
- 在来のまま「即配線」すると **kill が cross-process に届かず壊れた安全機能になる**ため、急がない。
- SP-035 Pack の Review に本 ADR への参照を記録済。`status: proposed` のまま (実装着手時に
  architecture sprint Pack + 本 ADR accepted 化)。
