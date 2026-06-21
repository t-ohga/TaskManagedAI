---
id: "SP-PHASE1_kill_switch"
type: "heavy"
status: "in_progress"
sprint_no: 1
created_at: "2026-06-21"
updated_at: "2026-06-22"
target_days: 8
max_days: 14
adr_refs:
  - "[ADR-00048](../adr/00048_superintendent_emergency_stop.md) (Superintendent emergency stop、accepted 2026-06-22、R4 plan-review 20 findings 反映)"
related_sprints:
  - "SP-PHASE0_local_bootstrap (completed、Phase 0 基盤)"
  - "SP-035_superintendent_agent (partial_skeleton、kill switch acceptance gap の元 Pack)"
  - "SP-029 / SP-004-5 (shadow driver / worker driver atomic claim、latch 貫通先)"
risks:
  - "cross-process kill が届かない (in-process dict→DB-backed registry + hybrid supervisor が前提)"
  - "latch check と side effect の TOCTOU race (advisory lock 直列化)"
  - "state machine 改訂が 5+source drift (単独 PR 隔離)"
  - "registry 二重化 (managed_agents vs active_registry_worker_gate、ADR で置換/共存明記)"
  - "provider call 中の engage で stale response が進行 (generation CAS)"
---

# SP-PHASE1 — kill switch フル版: cross-process supervisor + DB-backed agent registry + emergency-stop latch

> 大元計画 (PLAN-10、`docs/実装計画/10_大元計画_ローカル自律AI基盤.md`) **Phase 1 [XL]** の heavy Sprint Pack。自律実行解禁の**絶対前提**となる安全弁を、設計済 (ADR-00048 proposed、R1-R3 で 11 設計欠陥反映) だが完全未配線 (kill primitive 実装済だが caller ゼロ、in-process dict で cross-process kill 不能) から本実装する。

## 目的

「人間がいつでも全 AI を即停止できる」安全弁を、**cross-process に確実に届く**形で本実装する。具体的には:
1. **DB-backed agent registry** (`managed_agents`): in-process dict を DB-backed registry に置換し、kill の正本を process-local でなく DB にする。
2. **永続 emergency-stop latch** (`superintendent_emergency_stops`): tenant-scoped、generation CAS、active ≤ 1。engage で**新規活動を全 mutating choke point で fail-closed deny**。
3. **hybrid cross-process supervisor**: 各 host process (MCP server / worker) が DB latch を poll (権威・fail-closed) + Redis pub/sub で engage 即時 wake → 登録 subprocess を SIGKILL。
4. **human-only operator gate + FastAPI endpoint**: authenticated + actor_type=human + owner で engage/clear/status。
5. **全 mutating choke point latch gate**: run_create / dispatch / agent_start / autonomy allow / provider preflight + **worker driver atomic claim point** + **MCP mutating bridge centralize** + **provider postflight generation CAS**。
6. **state machine 改訂 (H)**: emergency block source + pre_stop_status 復元 resume target を canonical state machine に追記 (5+source、単独 PR 隔離)。
7. **停止導線 UI + CLI** + budget global_kill_switch。

## 背景

SP-035 受け入れ条件「human がいつでも Superintendent + 全 agent を即停止」が **未配線** (PR #321 台帳監査 + Codex F-L5)。ADR-00048 が plan-review R1-R3 で 11 設計欠陥 (CRITICAL 5 + HIGH 6) を反映し、**「在来のまま即配線すると kill が cross-process に届かず壊れた安全機能になる」**と結論 (R3 (F))。正しい kill switch は **agent supervision の cross-process 化を prerequisite** とする agent runtime architecture の拡張であり、専用 architecture sprint として実装する。

**安全弁先行原則** (大元計画): kill switch フル版が揃うまで production 自律実行を解禁しない。latch は **driver atomic claim point + provider 呼出前 preflight** まで貫通させ、engage→課金/駆動継続の窓を残さない。

**現状コード (調査済 2026-06-21)**:
- `kill_all_agents()` (agent_spawner.py) / `OrchestratorKillSwitch.engage()` / policy engine `global_kill_switch_enabled` は実装済だが **caller ゼロ**。
- agent registry は **process-global dict** (`_active_agents`)、cross-process kill 不能。
- `superintendent_emergency_stops` / `managed_agents` table **未作成**。
- **Redis pub/sub infra は workers/main.py に存在** (`RedisPubSubConnection`) → hybrid supervisor の wake channel に活用。
- shadow driver (SP-029) は merged だが、**worker driver (SP-004-5/ADR-00057) は未マージ** (workers は noop_task のみ、AgentRun claim point は実コードに存在しない)。よって Phase 1 は claim point に latch を「貫通」できず、**latch-check helper + contract/stub test を interface contract として予約** (ADR A-9、実 driver 駆動 deny は Phase 2)。

## 対象外 (scope_out)

- production enqueue 本格解禁 (Phase 6 に一本化、本 Sprint は安全弁配線のみ)。
- CLIAgentAdapter 本体 / 実 provider 駆動 (Phase 2)。
- L4 役割協調 / orchestrator dispatch loop 実働化 (Phase 4、本 Sprint は dispatch の latch gate のみ)。
- auto-approve policy resolution (ADR-00048 で意図的 defer、conservative-by-default 維持)。
- 個別 agent stop (`superintendent_agent_stop`) の権限改修 (latch とは独立、emergency-stop は別経路)。

## 設計判断 (確定)

- **cross-process supervisor = hybrid** (user 承認 2026-06-21): **DB latch を source of truth (権威・fail-closed)** とし、**Redis pub/sub を best-effort 低レイテンシ wake signal** とする。supervisor は (1) engage 時 pub/sub で即 wake → SIGKILL、(2) pub/sub 取りこぼし時も DB latch poll (~1-2s) で必ず engage を観測する fallback。**「新規活動 deny」は全 choke point の同期 latch check で即時** (poll 待ちでない)、「in-flight subprocess kill」のみ supervisor 経由。
- **registry 置換** (ADR Gate #2/#9): `managed_agents` を DB-backed registry の正本とし、in-process `_active_agents` は **process-local cache + supervisor が自 process の subprocess を signal する手段**に降格 (kill の正本ではない)。既存 `active_registry_worker_gate` / `with_active_registry_gate` との関係を ADR-00048 update で明記し**二重化を防ぐ** (managed_agents は agent process supervision、active_registry_gate は DML mutation gate で責務分離)。
- **latch table**: `superintendent_emergency_stops` (tenant_id, generation bigint, engaged_at/by, cleared_at/by、`(tenant_id) WHERE cleared_at IS NULL` partial unique で active ≤ 1)。
- **直列化** (ADR A-7): `pg_advisory_xact_lock(hashtextextended('superintendent-emergency-stop:' || tenant_id::text, 0))` の単一 64bit 文字列 key を engage/clear/全 side-effecting enforcement point の critical section 入口で取得 (TOCTOU 防止、B-1。codebase 既存形式統一、int4 切り詰め衝突回避)。**spawn は lock + 同一 transaction を process 起動まで保持** (ADR A-1、commit で lock 解放→lock 外 child 起動の窓を塞ぐ)。
- **state machine 改訂 (H)**: enum は不変 (16 status + blocked_reason 3)、`runtime_blocked` の transition source/target を canonical に追記。block source = running/policy_linted/diff_ready/waiting_approval のみ。resume は `agent_runs.pre_stop_status` (専用列、B2 で追加) 復元表 + generation CAS (一律 running 禁止、B-3)。
- **provider CAS (G、ADR A-4)**: preflight (`provider_request_preflight`、tenant/generation を持たない) でなく **`execute_provider_step` の transaction で**、provider response 後 `record_provider_usage`/artifact/status の前に同一 tenant lock 下で generation CAS + status check、mismatch は discard/quarantine。

## 実装チケット (batch 分解、各 batch = 1 PR + adversarial review)

| batch | 内容 | ADR Gate | depends_on |
|---|---|---|---|
| **B1** state machine (H) 改訂 | emergency block source + pre_stop_status resume target + runtime_blocked event を canonical state machine に追記 (5+source: rules/DB CHECK/ORM/Literal/Pydantic/test EXPECTED/frontend)。**単独 PR 隔離**、enum 不変・transition のみ。drift test + resume transition test | #2 (state machine) | ADR-00048 accepted |
| **B2** DB-backed managed_agents registry + schema | `managed_agents` table + ORM + migration (tenant_id NOT NULL + 複合 FK, host_id/process_group_id/pid/supervisor_id/state/**started_at/boot_id** (pid/pgid 再利用防御 A-2)、additive lossless) + **`agent_runs.pre_stop_status` 専用列 additive** (A-5、B3 resume が依存) + registry service。spawn ordering A-1 (lock 保持 + state=spawning→running)。in-process dict→DB-backed 置換、active_registry_gate 責務分離明記 (A-3)。supervisor loop skeleton + Redis pub/sub channel skeleton | #2, #9 | ADR-00048 |
| **B3** emergency-stop latch + service + operator gate + endpoint | `superintendent_emergency_stops` table + ORM + migration。emergency_stop service (engage/clear/is_engaged + advisory lock 直列化 + pre_stop_status capture) + `require_emergency_stop_operator` (authenticated+human+owner) + FastAPI endpoint (engage/clear/status) | #1, #2, #3 | B1, B2 |
| **B4** cross-process kill wiring (hybrid supervisor) | 各 host process が DB latch poll (権威) + Redis pub/sub wake → 登録 subprocess SIGKILL。**must-ship: MCP process が spawn した agent を FastAPI endpoint から supervisor 経由で kill 実証** | #9 | B2, B3 |
| **B5a** core choke point latch gate | run_create/dispatch/agent_start/register/autonomy allow に fail-closed latch check (新規活動 deny の核) + **worker driver claim point latch-check helper `assert_not_emergency_stopped(tenant_id)` を interface contract として提供 + contract test** (実 driver は Phase 2、A-9)。reason_code `emergency_stop_engaged` 5+source (独立 application reason_code、blocked_reason/Provider 13 に混ぜない、A-6) | #3, #5 | B3 |
| **B5b** MCP mutating bridge centralize | api_bridge.py の mutating bridge を centralize し deny allowlist (B-2)。engaged 中 deny / cleared 後 allow の網羅 negative test | #5 | B5a |
| **B5c** provider postflight generation CAS | provider response 後 `record_provider_usage`/artifact/status の前に execute_provider_step transaction で generation CAS + status check、mismatch は discard/quarantine (A-4)。同期 execute の in-flight 1 call honest limit 明記 | #3 | B5a |
| **B6** budget API + UI/CLI + exit verification | budget 書込 API + global_kill_switch engage (latch と OR 評価、A-8) + 停止導線 UI (engage/clear/status 可視化) + CLI (tm superintendent engage/clear/status) + Phase 1 full exit verification | #3 | B1-B5c |

## must_ship / defer_if_over_budget

| 項目 | must_ship | defer 可否 |
|---|---|---|
| DB-backed managed_agents registry + cross-process kill 実証 | ✅ | ❌ (Phase 1 の核心) |
| 永続 emergency-stop latch + 全 mutating choke point fail-closed deny | ✅ | ❌ |
| worker driver claim point latch **interface contract + helper + contract test** (実 driver は Phase 2、ADR A-9) | ✅ | ❌ (安全弁先行原則。SP-004-5 driver 未マージのため Phase 1 は契約予約 + stub/contract test、実駆動 deny は Phase 2 で検証) |
| spawn↔DB ordering 固定 (pre-register state=spawning→process→running、起動失敗 compensating terminalize、ADR A-1) | ✅ | ❌ (unkillable orphan 防止、R4-CRITICAL-1) |
| supervisor restart 後 killpg(pgid) で kill 到達 + pid/boot_id 再利用防御 (ADR A-2) | ✅ | ❌ (R4-HIGH-3) |
| provider postflight generation CAS | ✅ | ❌ |
| human-only operator gate (authenticated+human+owner) fail-closed | ✅ | ❌ |
| state machine (H) 改訂 + 5+source 整合 | ✅ | ❌ |
| advisory lock 直列化 (concurrent engage vs claim race) | ✅ | ❌ |
| 停止導線 CLI (tm superintendent engage/clear/status) | ✅ | ❌ (操作手段) |
| 停止導線 UI | - | ⏸ (CLI で代替可、UI は B6 で best-effort) |
| budget 書込 API (global_kill_switch) | - | ⏸ (kill switch とは独立の budget 経路、所在確認は deliverable) |

## 受け入れ条件 (exit、観測可能)

1. **cross-tenant 非干渉**: tenant 1 の emergency-stop で tenant 2 の agent process / run が一切影響を受けない。**tenant 2 の新規活動 (run 作成/spawn/provider) は engage 中も allow され、tenant 2 の既存 subprocess は kill されない** (tenant 1 のみ deny/kill。test は「tenant 1 deny + tenant 2 allow」で isolation regression を捕捉、Codex PR #358 adopt)。
2. **post-stop 新規 deny**: latch engaged 後、run 作成 / dispatch / agent_start / autonomy allow / provider preflight + **worker driver atomic claim** が全 `emergency_stop_engaged` deny。clear 後は再 allow。
3. **claim→provider 窓なし (interface contract、ADR A-9)**: `assert_not_emergency_stopped(tenant_id)` helper を提供し、worker driver の atomic claim point (queued→gathering_context) が claim 確定 transaction 内で本 helper を呼ぶ契約を **contract test / stub driver で latch を見ることを検証**。実 driver 駆動の deny は Phase 2 (SP-004-5/ADR-00057) で確認 (driver 未マージのため Phase 1 は契約予約)。
4. **cross-process kill 実証**: MCP / worker subprocess を FastAPI endpoint から supervisor 経由で kill できる (in-process dict 跨ぎを克服)。**supervisor restart (in-process handle 喪失) 後も DB の process_group_id から killpg で kill 到達** (ADR A-2)。
4b. **spawn race 非干渉 (ADR A-1、R4-CRITICAL-1)**: engage が spawn の最中 (DB pre-register 済 / pid 未確定) に割り込んでも当該 process が provider に到達しない (mid-spawn negative race test)。spawn 失敗時 pre-register 行が terminal 化し orphan が残らない。
5. **operator gate fail-closed**: unauthenticated / 同 tenant 別 human / non-human (agent/service/provider/github_app) は全 403、kill/engage が実行されない。
6. **concurrent engage vs claim race**: advisory lock で claim が必ず latch を見る (start が latch check 通過→engage 割り込み→spawn 残存 が起きない)。
7. **provider CAS**: engage 後の stale provider response が usage/artifact/status を進めない (generation mismatch で discard/quarantine)。
8. **state machine**: block は running/policy_linted/diff_ready/waiting_approval のみ、それ以外は latch で新規活動を止める (不正 transition history を作らない)。resume は pre_stop_status 復元 (gate skip しない) + generation CAS (stale clear reject)。
9. **冪等性**: 二重 engage は no-op + 同一 latch、agent 不在 engage は stopped_agent_count=0。
10. **audit**: `assert_no_raw_secret` で raw secret / token / pid が audit payload に出ない。
11. ADR-00048 accepted + **CLI (tm superintendent engage/clear/status) から engage/clear/status 操作可** (must-ship)。**UI は best-effort/deferable** (CLI で代替可、UI 未完でも Sprint close 可、Codex PR #358 adopt)。

## 検証手順

- Backend: 各 batch で `uv run ruff check backend tests` + `uv run mypy backend` + 該当 `pytest` (no-DB) + DB-gated test (`TASKMANAGEDAI_RUN_DB_TESTS=1`、throwaway pg)。
- 状態機械: enum drift test (5+source exact-set) + emergency block/resume transition test + negative (不正 source からの block reject)。
- latch race: concurrent engage vs claim/start の DB-gated race test (advisory lock 直列化検証)。
- cross-process kill: MCP/worker subprocess spawn → endpoint engage → supervisor kill 実証 test (integration、host 依存は operator 検証も併記)。
- choke point: 全 mutating choke point の engaged 中 deny / cleared 後 allow の網羅 negative test。
- provider CAS: engage 中 provider response の generation mismatch discard test。
- operator gate: unauthenticated/other-human/non-human の 403 negative test。
- 各 batch PR で Workflow adversarial review (security/DB/state machine 境界、CRITICAL=0/HIGH≤2 まで)。

## レビュー観点

- cross-process kill が**本当に届くか** (in-process dict を kill の正本にしていないか、supervisor が自 process の subprocess を確実に signal するか、pub/sub 取りこぼし時 DB poll fallback が効くか)。
- latch check と side effect の TOCTOU (advisory lock 範囲、claim point の latch 貫通)。
- registry 二重化 (managed_agents vs active_registry_gate の責務分離が明確か)。
- state machine 改訂が 16 status + blocked_reason 3 を不変に保ち transition のみ追記か (5+source exact-set)。
- provider CAS が課金/artifact/status 進行の窓を残さないか。
- operator gate が fail-closed (authenticated+human+owner、迂回経路なし)。
- raw secret/pid 非露出。

## 残リスク

- **supervisor poll latency**: DB poll fallback は最大 ~1-2s の in-flight subprocess kill 遅延。新規活動 deny は同期 latch check で即時のため、課金/駆動継続の窓は choke point で塞ぐ (poll は既起動 process の終了のみ)。pub/sub wake で通常は即時。
- **host crash 中の registry stale**: managed_agents の stale row (process 死亡だが DB 残存) は supervisor heartbeat + reconciliation で収束 (Phase 4 supervisor loop で本格化、Phase 1 は基本 GC)。
- **Redis 障害**: pub/sub 不達でも DB latch poll が権威 fallback (fail-closed)。Redis 障害単独で kill 不能にならない。
- **UI defer**: B6 で UI が間に合わない場合 CLI で操作可 (must_ship は CLI)。

## 次スプリント候補

- Phase 2 (CLIAgentAdapter + 実 provider 駆動、本 Sprint の latch を claim point で前提)。
- Phase 4 supervisor loop / failover / heartbeat 本格化 (managed_agents registry を統合)。

## 関連 ADR

- ADR-00048 (Superintendent emergency stop、本 Sprint の設計正本、proposed→accepted)。
- ADR-00014 (Multi-Agent Orchestration、orchestrator lease/kill boundary)。
- ADR-00027 (Superintendent Agent / SP-035 正本)。
- ADR-00036 (DB から actor_type resolve owner/human gate 先例)。
- master plan 拡張 (managed_agents registry 置換 / worker driver claim latch / budget API) が ADR-00048 scope を超える分は **ADR-00048 update で吸収** (plan-review で判断)。

## R4 plan-review 反映 (2026-06-22)

実装着手前の Workflow plan-review が **20 findings (CRITICAL 2 + HIGH 4 + MEDIUM 11 + LOW 3) を捕捉、全 adopt**。設計確定は **ADR-00048 §Amendment (R4) A-1〜A-10** に集約:
- A-1 spawn↔DB ordering 固定 (unkillable orphan 防止) / A-2 supervisor restart killpg + pid 再利用防御 / A-3 registry 二重化防止 (active_registry_gate 責務分離 + engage は freeze gate bypass) / A-4 provider CAS 配置 (execute_provider_step) + 同期 execute honest limit / A-5 state machine (H) 具体化 (ALLOWED_TRANSITIONS + EVENT_TYPE_FOR_TRANSITION、pre_stop_status 専用列) / A-6 emergency_stop_engaged は独立 reason_code / A-7 advisory lock key 統一 (hashtextextended) / A-8 budget global_kill_switch と OR 共存 / **A-9 worker driver claim point は interface contract (SP-004-5 未マージのため Phase 1 は契約予約、実駆動は Phase 2)** / A-10 AC-HARD trace + operator role。
- **AC-HARD trace**: cross-tenant 非干渉 → AC-HARD-03 / latch 迂回 → AC-HARD-07 / `emergency_stop_engaged` を 23 invariant fixture loader に追加。
- B5 を **B5a (core choke point + worker driver contract) / B5b (MCP bridge centralize) / B5c (provider CAS)** に分割 (R4-LOW-20)。

### Codex PR #358 auto-review 反映 (二重検証、9 adopt + 1 reject)

Workflow plan-review (20) と独立に Codex auto-review が **R4 amendment と Sprint Pack body の内部不整合 11 件**を捕捉:
- **adopt (9)**: ① A-1 補強 = **spawn の advisory lock を process 起動まで保持** (commit で lock 解放→lock 外 child 起動の窓、Codex P1) ② 背景の worker driver 記述を「未マージ・契約予約」に修正 ③ A-4 honest limit を「in-flight **全** call」に修正 (1 call でない) ④ 設計判断の advisory lock key を A-7 (hashtextextended) に統一 ⑤ provider CAS を preflight でなく `execute_provider_step` に修正 (A-4 整合) ⑥ B2 schema に `started_at`/`boot_id` 追加 (A-2 pid 再利用防御) ⑦ `agent_runs.pre_stop_status` 専用列を B2 に追加 (B3 resume 依存、A-5) ⑧ exit #11 を CLI-only must-ship + UI best-effort ⑨ exit #1 cross-tenant を「tenant 1 deny + tenant 2 **allow**」に修正 (isolation regression 捕捉)。
- **reject (1)**: 「accepted_at 2026-06-22 は future-date」→ **本日が 2026-06-22** のため誤検知 (Codex の date context lag)。

## Review

(実装後追記。各 batch の adversarial review round + findings closure + ADR-00048 accepted_at を記録)
