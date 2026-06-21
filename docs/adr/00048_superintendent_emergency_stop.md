---
id: "ADR-00048"
title: "Superintendent emergency stop (human-only kill switch 配線、SP-035 gap)"
status: "accepted"
date: "2026-06-05"
accepted_at: "2026-06-22"
deciders: ["t-ohga"]
adr_gate_criteria: [1, 2, 3, 4, 5, 9]
related_adr:
  - "ADR-00027 (Superintendent Agent / SP-035 の正本、本 ADR はその kill switch acceptance gap を塞ぐ)"
  - "ADR-00014 (Multi-Agent Orchestration / orchestrator lease・kill switch boundary)"
  - "ADR-00036 (DB から actor_type を resolve する owner/human gate の先例)"
related_dd:
  - "DD-03 (AI オーケストレーション / AgentRun state machine、runtime_blocked)"
  - "DD-04 (セキュリティ・権限・監査 / human-only decision boundary、audit)"
related_sprints:
  - "SP-035_superintendent_agent (partial_skeleton。本 ADR は kill switch の **設計正本** = planned/blocking follow-up。proposed・未実装であり、acceptance は実装完了で初めて充足する)"
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

- P0/P0.1 invariant 不変: AgentRun 16 status / blocked_reason 3 種 / ContextSnapshot 10 列を変えない
  (ただし (H) で `runtime_blocked` の transition source/target を canonical state machine に**追記**する
  改訂は伴う。enum 自体は増やさない)。
- **DB migration を伴う (ADR Gate #2)**: 永続 latch table `superintendent_emergency_stops` +
  `agent_runs`/agent registry の cross-process 化 ((F)) のための schema 追加。additive のみ、
  downgrade lossless。破壊的 (drop/rename) は行わない。
  ※ 初版 (v1) は「DB schema 変更なし」だったが、R1 で永続 latch table を、R3 で cross-process registry を
  追加したため本制約を訂正 (Codex App F-M1)。
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
  (将来 UI) 確認 dialog、clear で復帰可能。**ただし resume は一律 `blocked → running` ではなく
  (B-3) の `pre_stop_status` 復元表 + generation CAS に従う** (`waiting_approval`/`diff_ready`/
  `policy_linted` 由来は元 gate へ戻し、approval/diff/policy gate を skip しない。Codex App F-M3)。
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

## 実装 status (2026-06-22 update: accepted)

- **status: accepted (2026-06-22)**。codex-plan-review R1-R3 (11 設計欠陥) + **SP-PHASE1 plan-review R4 (20 findings、§Amendment A-1〜A-10)** を反映した安全設計の正本。PLAN-10 Phase 1 (architecture sprint = SP-PHASE1) 着手直前に §12.4 (Workflow plan-review + 全 adopt、user 承認の Codex 代替) を経て accepted 昇格。
- **実装 = SP-PHASE1 architecture sprint** (batch B1-B6)。順序: (H) state machine 改訂 (B1、単独 PR) → (F) DB-backed registry (B2、spawn ordering A-1) → emergency-stop latch/service/endpoint (B3) → cross-process kill hybrid supervisor (B4、A-2) → choke point latch + worker driver contract + MCP bridge + provider CAS (B5a/b/c、A-9) → budget/UI/CLI/exit (B6)。
- 在来のまま「即配線」すると kill が cross-process に届かず壊れた安全機能になるため、cross-process supervision 基盤を prerequisite とする (R3 (F))。supervisor = hybrid (DB latch 権威 + Redis pub/sub wake、user 承認 2026-06-21)。
- SP-035 Pack の Review に本 ADR への参照を記録済。SP-PHASE1 Sprint Pack の adr_refs に accepted として登録。

## Amendment (R4 — SP-PHASE1 plan-review 反映、2026-06-22)

SP-PHASE1 (kill switch フル版) 実装着手前の Workflow plan-review (R4) が 20 findings (CRITICAL 2 + HIGH 4 + MEDIUM 11 + LOW 3) を捕捉。全 adopt。本 amendment で設計を確定し、本 ADR を **proposed→accepted** へ昇格する根拠とする。adr_gate_criteria を [1,2,3,4] → **[1,2,3,4,5,9]** に拡張 (#5 MCP mutating bridge centralize / #9 in-process→DB-backed registry)。

### A-1. (F) spawn↔DB 登録 ordering 固定 (R4-CRITICAL-1)

DB-authoritative registry では「process 生存だが managed_agents 行 未 commit」の窓に engage が来ると supervisor が当該 subprocess を列挙できず **kill 漏れ** (unkillable orphan が provider に到達)。逆順は spawn 失敗で stale 行。→ spawn を以下の順に**固定** (must_ship):

> **A-1 補強 (Codex PR #358 P1 adopt)**: `pg_advisory_xact_lock` は **transaction-scoped** (commit/rollback で解放) のため、spawning 行を **commit してから** process 起動すると **commit 時点で lock が解放** → engage が pid-less row を観測して spawner が **lock 外で child を起動** → kill 前に side effect 実行の窓が残る。よって **advisory lock + 同一 transaction を process 起動まで保持**する (下記)。spawn は短時間のため transaction 内 subprocess 起動は許容。connection 保持を避けたい場合の代替は process を **suspended (SIGSTOP) で起動 → 登録 commit → SIGCONT** だが、P0 は hold-through-start を primary とする。

1. **BEGIN + advisory lock 取得 → latch check** (engaged なら abort、commit せず rollback)。
2. **同一 transaction (lock 保持) 内で**: `managed_agents` 行を `state='spawning'` (latch generation 刻印) で INSERT → process 起動 (`create_subprocess_exec`、`start_new_session=True`) → pid/process_group_id 確定 → 行更新 `state='running'` → **COMMIT** (ここで初めて lock 解放)。
3. concurrent engage は同 advisory lock を待ち、spawn の COMMIT 後に running 行 (pid 確定済) を観測して kill。spawn が engage より先に lock を取れば、engage は spawn COMMIT 後に running 行を見る。engage が先なら spawn の latch check が engaged を見て abort。**lock 外で child が起動する窓は無い**。
4. **compensating path**: 起動失敗・commit 失敗・crash 時は transaction rollback で spawning 行も消える (orphan process が残るなら same-tx 内で kill)。crash で process だけ残った場合は supervisor reconciliation (boot_id/started_at) で回収。

supervisor は kill 時 **state∈{spawning, running}** を全対象。managed_agents の `state` enum: `spawning`/`running`/`stopped`/`failed`。A-1 race test (mid-spawn engage) は「engage が spawn の lock 待ちで直列化され、child が provider に到達する前に kill される」ことを assert。

### A-2. (F) supervisor restart kill 到達性 + pid 再利用防御 (R4-HIGH-3 / LOW-19)

- **invariant**: kill 実行は当該 subprocess を spawn した **同一 host (同一 PID namespace) の supervisor のみ**が担う。`managed_agents` に `host_id` + `process_group_id` を保存し、supervisor restart (in-process Process handle 喪失) 後も `os.killpg(process_group_id, SIGKILL)` で **in-process handle 無しに kill** できる (killpg は pgid のみで動作)。
- **pid/pgid 再利用防御**: `started_at` + host `boot_id` を managed_agents に記録し、kill 前に照合。死亡 process の pgid を無関係 process が再利用していた場合の誤 kill を防ぐ (boot_id 不一致 / started_at 乖離は signal しない)。
- 別 host の pgid を絶対 signal しない (host_id scope + negative test)。tenant scope は DB row の tenant_id で絞り、同 host 上の別 tenant subprocess を巻き込まない (pre-kill tenant + host check、negative test)。

### A-3. registry 二重化防止 + active_registry_gate との責務分離 (R4-HIGH-5 / MEDIUM-8, #9)

- `managed_agents` = **agent process supervision の正本** (host/pgid/pid/state、cross-process kill 用)。
- 既存 `active_registry_worker_gate` / `with_active_registry_gate` = **host-fleet DML mutation gate** (host freeze 用、別責務)。両者は混同しない。
- **emergency-stop engage/clear の DB 書込は active_registry_mutation_gate に阻まれてはならない** (安全機能が host freeze 状態に左右されない)。engage/clear は mutation gate を bypass する allowlist 経路 or before_commit hook 除外を明記。

### A-4. (G) provider postflight CAS の配置確定 + 同期 execute の honest limit (R4-MEDIUM-11/13)

- `provider_request_preflight(ProviderRequest)` は tenant/session/latch generation を持たないため **CAS を preflight に置かない**。CAS は **provider response 後、`record_provider_usage` / artifact / status / event append の前**に、driver/orchestrator の transaction 境界 (`execute_provider_step`) で実行: 同一 tenant advisory lock 下で latch generation CAS + status check → mismatch なら usage/artifact/status を **discard/quarantine**。
- **honest limit (Codex PR #358 adopt、修正)**: 同期 `provider.execute` は engage で中断不能。CAS は engage 後の usage 記録 / artifact 永続化 / status 進行を防ぐが、**engage 時点で既に in-flight な provider call の provider 側課金確定は防げない**。複数 agent/worker が同時に preflight 済みで execute 中なら **その全 in-flight call 分のコストが発生し得る** (1 call ではない。tenant-wide single-flight 制約は本 Sprint scope 外)。新規 provider call は同期 latch check で deny されるため、被害は **engage 時点で既に execute 中の全 call** に限定 (engage 後に新たに開始される call は無い)。本限界を §残リスクに明記。コスト上限を厳密化するなら tenant-wide provider single-flight lease を将来 must-ship 化 (Phase 2+ defer)。

### A-5. (H) state machine 改訂の具体化 (R4-HIGH-4 / MEDIUM-15/17)

- emergency block source = `running`/`policy_linted`/`diff_ready`/`waiting_approval` → `blocked` (blocked_reason=`runtime_blocked`)。これらの (from, blocked) edge を `ALLOWED_TRANSITIONS` + `EVENT_TYPE_FOR_TRANSITION` に **具体的 (from→to, event_type)** で追加 (曖昧な「or 再評価」を残さない)。`runtime_blocked` event を使う (新 event_type を増やさない)。
- 非 block-source state (`queued`/`gathering_context`/`generated_artifact`/`schema_validated`/`validation_failed`/`provider_incomplete`)・既 blocked・terminal の run は **status 遷移させず latch 任せ** (不正 transition history を作らない)。
- resume は `pre_stop_status` 復元表 + generation CAS。復元先 edge (`blocked`→元 status) も ALLOWED_TRANSITIONS に追加。resume / `blocked->running` / `provider_incomplete->running` も **新規活動として latch gate (choke point) で deny** (engaged 中は resume 不可)。
- **`pre_stop_status` 永続先**: `agent_runs` に **専用 additive 列** (`pre_stop_status`) を B2 migration で追加 (event payload より resume CAS の atomicity が単純)。

### A-6. reason_code `emergency_stop_engaged` の位置づけ (R4-MEDIUM-16)

- `emergency_stop_engaged` は **(i) blocked_reason enum (3 種) に追加しない** (status='blocked' + blocked_reason='runtime_blocked' を使う)、**(ii) Provider Compliance 13-reason_code にも追加しない**、**(iii) 独立した application-level reason_code** として audit payload + emergency-stop 専用 enum で 5+source 整合 (cross-source-enum-integrity §1)。既存の sealed enum を汚さない。

### A-7. advisory lock key 形式統一 (R4-MEDIUM-9)

advisory lock key は codebase 既存形式に統一: `pg_advisory_xact_lock(hashtextextended('superintendent-emergency-stop:' || tenant_id::text, 0))` の単一 64bit 文字列 key (二 int32 形式の int4 切り詰め衝突を回避)。

### A-8. budget global_kill_switch との関係 (R4-MEDIUM-12)

emergency-stop latch と既存 budget `global_kill_switch` (policy engine 配線済) は別目的で **共存**: budget=コスト緊急停止 / latch=human 即時全停止。choke point で **OR 評価** (どちらか engaged なら deny)。latch を新設正本とし global_kill_switch は budget 経路の従属。両者の OR を autonomy/provider choke point に明記。

### A-9. worker driver atomic claim point は interface contract (R4-CRITICAL-2 / HIGH-6)

**SP-004-5 worker driver (ADR-00057) は未マージ** (workers は noop_task のみ、AgentRun claim point は実コードに存在しない)。よって SP-PHASE1 は claim point に latch を「貫通」できない。→ SP-PHASE1 は **claim point latch check を interface contract として予約**: (1) `assert_not_emergency_stopped(tenant_id)` 等の共有 latch-check helper を提供、(2) 「worker driver の atomic claim point (queued→gathering_context) は claim 確定 transaction 内で本 helper を呼ぶ」ことを **契約 (ADR + contract test)** として固定。Phase 2 (SP-004-5/ADR-00057) の driver 実装時にこの契約を honor する。SP-PHASE1 の exit「claim→provider 窓なし」は **stub driver / contract test で claim point が latch を見ることを検証**し、実 driver 駆動は Phase 2 で確認。

### A-10. AC-HARD trace + operator role (R4-MEDIUM-10 / LOW-18)

- cross-tenant 非干渉 → **AC-HARD-03** negative fixture、MCP/agent 経路の latch 迂回試行 → **AC-HARD-07** (権限昇格拒否) に明示 trace。`emergency_stop_engaged` を eval fixture loader (23 invariant fixture pattern) に追加。
- `require_emergency_stop_operator` は P0 では `_require_authenticated_owner` と同一 owner gate (authenticated + human + default owner) を流用、別 emergency-stop role は新設せず (P0.1 で role 化を forward-compat 予約)。
