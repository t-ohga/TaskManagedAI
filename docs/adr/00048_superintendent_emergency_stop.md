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
- **pgid 再利用誤 kill 窓 (B2 adversarial LOW-6、honest limit)**: managed_agents の `boot_id` が None (boot_id 取得不能 host / 旧 row) かつ kill 実行 host の boot_id も None の場合、host reboot 後に死亡 process の pgid を無関係 process が再利用していると **誤 kill する窓**が残る (boot_id 照合が無効化されるため)。boot_id 取得可能環境 (Linux `/proc/sys/kernel/random/boot_id`) では発生しない。緩和: B4 で kill 前の `started_at` 照合を追加 (§A-2)。host scope (別 host の pgid は絶対 signal しない) で blast radius は同 host 内に限定される。
- **B4 started_at 照合の psutil 依存 (B4 adversarial M1、honest limit)**: B4 の `started_at` 照合は `psutil` の lazy optional import で実装。`psutil` が runtime に無い deploy では started_at 防御は inert になり、pgid 再利用 misfire 防御は host scope + (取得可能なら) boot_id のみに縮退する (B2 と同等の窓)。started_at 防御を有効化するには psutil を runtime 依存に追加する。started_at は窓を「縮める」補助であり主防御 (host scope) ではない。
- **macOS boot_id 安定化 (B4 adversarial M2)**: `kern.boottime` の raw string は末尾 human-readable timestamp が OS/locale 依存で揺れ得るため、boot 時刻の `sec`/`usec` のみを抽出して boot_id 化する (raw string だと同一 boot でも spawn 時と kill 時で不一致 → `_killable` False → **kill-miss (fail-open)** リスク)。`host_identity._macos_boot_id`。
- **B4 kill 結果分類 EPERM (B4 adversarial H2)**: supervisor の killpg は `ProcessLookupError`/ESRCH (= 消滅、terminalize 可) と `EPERM` 等 (= **生存**だが signal 不能) を区別し、**生存・signal 不能の row を terminalize しない** (loud error log + 次 poll で retry)。一律「死亡」扱いにすると un-killable agent を `stopped` と誤記録し以後 retry されず fail-open になるため。
- **B4 supervisor は単一 PID namespace process のみ (B4 adversarial HIGH-1、最重要)**: supervisor は **agent を spawn した同一 PID namespace の process でのみ動かす**。当初 MCP server + worker 両方に配線したが、**worker は Docker container (= 別 PID namespace) で managed agent を spawn しない**。worker supervisor が `TASKMANAGEDAI_SUPERVISOR_HOST_ID` 共有等で MCP-spawned row を選ぶと、別 namespace で `killpg(pgid)` → ProcessLookupError → 「消滅」誤判定 → `mark_terminal(stopped)` で実 process は host で生存 = **fail-open** (以後 host supervisor も stopped row を見ず永久 kill-miss)。`boot_id` は container 間共有、`started_at` は namespace-blind で全防御 inert。→ **worker への supervisor 配線を除去**し、**MCP server lifespan のみ**で配線する。invariant: `TASKMANAGEDAI_SUPERVISOR_HOST_ID` を **異なる PID namespace (container) 間で共有してはならない** (host_id 等価が killpg の唯一の gate)。`§(F)` / `§A-2` 参照。
- **B4 killpg(0) self-kill guard (B4 adversarial HIGH-2)**: `os.killpg(0, SIGKILL)` は呼び出し元 (supervisor) 自身の process group 全体に SIGKILL を送る (self-kill + 巻き添え)。負 pgid も POSIX kill の特殊指定。`_killpg` で `process_group_id <= 0` を killpg 前に skip (loud error + STILL_ALIVE = terminalize しない) し、さらに **migration 0054 DB CHECK `process_group_id IS NULL OR process_group_id > 0` + ORM CheckConstraint** で構造的に排除する (supervisor guard と合わせ 4-layer)。0/負 pgid は正規経路 (`mark_running` の `os.getpgid()` 結果) では発生しないが corrupted データに対し fail-safe。
- **B4 同一 PID namespace 内の kill 直列化 (B4 adversarial H1)**: 同一 PID namespace process 内でも (将来 supervisor を複数起動した場合に備え) kill 列挙は `FOR UPDATE SKIP LOCKED` で行い、片方が掴んだ row をもう片方が触らない (reused-pgid 二重 signal + audit double-count 防止)。SIGKILL は冪等、`mark_terminal` は active-state 条件付きで二重 terminalize は no-op。**B4 現状は supervisor を MCP server 1 process のみで起動する (HIGH-1) ため並走は無いが、SKIP LOCKED は将来の多重起動 / restart overlap に対する defense-in-depth**。
- **B4 supervisor mark_terminal の freeze gate exempt (B4 adversarial MEDIUM-3)**: supervisor poll の `mark_terminal` commit を host-freeze DML mutation gate から exempt する (`mark_emergency_stop_bypass`、`_EMERGENCY_STOP_BYPASS_ALLOWED_MODELS` に `ManagedAgentRecord` 追加)。supervision (cross-process kill) は host-freeze と独立した安全機構であり、freeze 中も terminalize を永続化しないと「kill したのに記録が残らず以後 retry されない」fail-open になる (§A-3 と同思想)。
- **B4 MCP spawn commit 失敗時の orphan kill (B4 adversarial LOW-4)**: `superintendent_agent_start` の `session.commit()` が freeze gate 等で reject されると、`managed_agents` 行は rollback されるが live subprocess は残る (committed row 無しの unkillable orphan)。commit 失敗時は起動済 live process を `killpg` で kill してから re-raise する (`_kill_spawned_orphan`、`spawn_agent_managed` 内 compensating path と同 semantics)。本 window は §A-1 ordering の commit-failure 経路に該当。
- **B4 wake publisher の client leak 防止 (B4 adversarial LOW-5)**: `publish_emergency_stop_wake` が `redis_url` から内部生成した Redis client は publish 後に `try/finally` で close する (engage 毎に新 client を作って close しないと connection leak)。injected publisher (caller 所有) は close しない。
- **B4 stale `spawning` 行の reconciliation 未実装 (B4 adversarial M3、honest defer)**: §A-1 §4 の「crash で process だけ残った場合は supervisor reconciliation (boot_id/started_at) で回収」は **B4 では未実装**。`kill_managed_agents_on_host` は `spawning` (pgid NULL) 行を skip するのみで、A-1 ordering 外の経路や crash で残った stale `spawning` 行を terminalize しない (永続 `spawning` で残り得る)。A-1 ordering 下の live spawn は advisory lock 内で `running` へ進むため kill-miss にはならない。stale `spawning` sweep (spawn timeout 超過 + pid NULL → `failed` 化) は **B6 (budget/UI/CLI/exit) の reconciliation で実装** する。それまで stale `spawning` 行は手動 / 次の clear cycle で整理。
- **B4 `superintendent_agent_register` 未移行 (B4 adversarial M4、honest defer)**: B4 で移行したのは `superintendent_agent_start` のみ。`superintendent_agent_register` は in-process `_active_agents` dict にのみ書き managed_agents 登録も latch check も持たない (process spawn しない登録 step)。latch gate は **B5 (MCP mutating bridge latch gate)** で閉じる。
- **B3 時点の coverage 限界 (PR #361 Codex auto-review P1-1 / P1-3、honest limit)**: B3 merge 時点で kill switch の「新規活動 deny」は **`spawn_agent_managed` 経路 (advisory lock + latch check、P1-2 fix 済) + emergency-stop block-source run (`running`/`policy_linted`/`diff_ready`/`waiting_approval`) のみ** covered。**未 cover の 2 経路 (fail-open)**:
  - **P1-1: MCP `superintendent_agent_start` は legacy `spawn_agent` (sessionless) を呼び latch を確認しない** → engage 後でも MCP 経路で新 agent process が起動し得る。**B4 (MCP→`spawn_agent_managed` 移行 + cross-process supervisor) + B5 (MCP mutating bridge latch gate) で閉じる**。B3 interim は behavior 不変 + bypass を観測する WARN log (`agent_spawn_legacy_path_bypasses_emergency_stop_latch`) のみ (sessionless 即 deny は MCP agent_start を無条件に壊し B3 scope 外)。
  - **P1-3: `bridge_run_create` / `bridge_delegation_accept` 等の run create/advance choke point は latch checker を呼ばない**。`queued`/`gathering_context` run は block-source allowlist 外で engage に触られず、engage 後も bridge 経由で新規 AI 活動 (run create / delegation advance / provider preflight) を deny しない。**B5a (core choke point latch gate: run_create/dispatch/agent_start/autonomy allow/provider preflight) + B5b (MCP mutating bridge centralize) で閉じる** (Sprint Pack B5a/B5b に既設計)。
  - **結論**: B3 単独では kill switch は full coverage **でない**。完全な「新規活動 deny + in-flight subprocess kill」は B4 (cross-process kill 配線) + B5 (全 mutating choke point latch gate) 完了で達成する。B3 は latch 永続化 + operator gate + endpoint + `spawn_agent_managed` 経路 + block-source run resume までを安全に提供する。

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
- **honest limit (B2 adversarial LOW-6)**: B2 は `host_id` scope + `boot_id` 照合 (取得可能環境のみ) + `started_at` 列を実装。kill 側の `_killable` 判定は **row.boot_id が None かつ host boot_id も None の場合に boot_id 照合が無効化され、reboot 後の pgid 再利用で誤 kill する窓が残る** (boot_id 取得不能 host = macOS 以外で sysctl 失敗時 / 旧 row)。boot_id 取得可能環境 (Linux `/proc/sys/kernel/random/boot_id`) では誤 kill しない。B4 で **kill 前の `started_at` 照合** (process 起動時刻 vs DB row started_at) を追加してこの窓をさらに縮める。§残リスクにも記載。
- **PID namespace invariant (B4 adversarial HIGH-1、最重要)**: supervisor は **agent を spawn した同一 PID namespace の process でのみ動かす**。`killpg(pgid)` の唯一の gate は **`host_id` 等価**であり、`boot_id` / `started_at` は **PID namespace を識別しない** (container 間で boot_id 共有、started_at は namespace-blind)。よって supervisor は **managed agent を spawn する MCP server host process のみ**に配線し、**worker (別 container = 別 PID namespace、agent を spawn しない) には配線しない** (別 namespace の MCP-spawned pgid を killpg → ProcessLookupError 誤判定 → `stopped` 誤記録で実 process 生存 = fail-open)。**`TASKMANAGEDAI_SUPERVISOR_HOST_ID` を異なる PID namespace (container) 間で共有してはならない**。
- **killpg(0) self-kill guard (B4 adversarial HIGH-2)**: `_killpg` は `process_group_id <= 0` を killpg 前に skip する (`killpg(0)` = supervisor self-kill)。migration 0054 DB CHECK + ORM CheckConstraint `process_group_id IS NULL OR process_group_id > 0` と合わせ 4-layer で 0/負 pgid を排除する。

### A-3. registry 二重化防止 + active_registry_gate との責務分離 (R4-HIGH-5 / MEDIUM-8, #9)

- `managed_agents` = **agent process supervision の正本** (host/pgid/pid/state、cross-process kill 用)。
- 既存 `active_registry_worker_gate` / `with_active_registry_gate` = **host-fleet DML mutation gate** (host freeze 用、別責務)。両者は混同しない。
- **emergency-stop engage/clear の DB 書込は active_registry_mutation_gate に阻まれてはならない** (安全機能が host freeze 状態に左右されない)。engage/clear は mutation gate を bypass する allowlist 経路 or before_commit hook 除外を明記。

### A-4. (G) provider postflight CAS の配置確定 + 同期 execute の honest limit (R4-MEDIUM-11/13)

- `provider_request_preflight(ProviderRequest)` は tenant/session/latch generation を持たないため **CAS を preflight に置かない**。CAS は **provider response 後、`record_provider_usage` / artifact / status / event append の前**に、driver/orchestrator の transaction 境界 (`execute_provider_step`) で実行: 同一 tenant advisory lock 下で latch generation CAS + status check → mismatch なら usage/artifact/status を **discard/quarantine**。
- **honest limit (Codex PR #358 adopt、修正)**: 同期 `provider.execute` は engage で中断不能。CAS は engage 後の usage 記録 / artifact 永続化 / status 進行を防ぐが、**engage 時点で既に in-flight な provider call の provider 側課金確定は防げない**。複数 agent/worker が同時に preflight 済みで execute 中なら **その全 in-flight call 分のコストが発生し得る** (1 call ではない。tenant-wide single-flight 制約は本 Sprint scope 外)。新規 provider call は同期 latch check で deny されるため、被害は **engage 時点で既に execute 中の全 call** に限定 (engage 後に新たに開始される call は無い)。本限界を §残リスクに明記。コスト上限を厳密化するなら tenant-wide provider single-flight lease を将来 must-ship 化 (Phase 2+ defer)。

- **A-4 補強 (B5 adversarial P1-2/3/5、monotonic generation history + preflight-active-fail)**: B5 実装時の active-only generation 等価比較 (preflight `get_active().generation` vs postflight `get_active().generation`) には **3 つの穴**が判明した。これを **monotonic generation history (`max_generation_ever`) + preflight-active-fail** に再設計する:
  - **P1-2 (latch 既 active で step 開始)**: latch が既に active な状態で step に入ると preflight も postflight も同 active generation = 等価で通り、provider.execute + usage/status が進行してしまう。→ **provider.execute の前に latch が currently active なら `EmergencyStopEngagedError` を raise** し、新規 provider call をさせない (latch 既 active での新規課金を構造的に防ぐ)。
  - **P1-3 (preflight 後・execute 前に engage)**: call は launch 済のため active-only postflight では捉えられる場合もあるが、`max_generation_ever` の `G1 > G0` で確実に discard する。
  - **P1-5 (call 中に engage→clear)**: active latch は preflight/postflight 共 `None` になり active-only 等価比較は**通してしまう穴**。`max_generation_ever` は cleared 行も MAX に残り engage で +1 されるため `G1 > G0` で discard できる。
  - 配置: (preflight) ① latch currently active なら provider.execute 前に deny (P1-2)、② `G0 = max_generation_ever(tenant)` を記録。(provider.execute、lock 非保持で engage を高速に保つ)。(postflight) 同一 tenant advisory lock 下で ③ currently active なら、または ④ `G1 = max_generation_ever(tenant) > G0` なら → **discard** (`discarded_emergency_stop`、usage/artifact/status を進めず `runtime_blocked` へ confine)。else 通常記録。
  - lock は **call を通して保持しない** (postflight でのみ取得) ため engage は高速のまま (A-4 の趣旨を維持)。`max_generation_ever` は当該 tenant の全 latch 行 (cleared 含む) の `MAX(generation)` query (engage 毎に +1 の monotonic、clear で減らない)。同期 in-flight call 自体の中断不能性 (上記 honest limit) は維持しつつ、**結果の commit を防ぐ + latch 既 active なら call させない**。

### A-5. (H) state machine 改訂の具体化 (R4-HIGH-4 / MEDIUM-15/17)

- emergency block source = `running`/`policy_linted`/`diff_ready`/`waiting_approval` → `blocked` (blocked_reason=`runtime_blocked`)。これらの (from, blocked) edge を `ALLOWED_TRANSITIONS` + `EVENT_TYPE_FOR_TRANSITION` に **具体的 (from→to, event_type)** で追加 (曖昧な「or 再評価」を残さない)。`runtime_blocked` event を使う (新 event_type を増やさない)。
- 非 block-source state (`queued`/`gathering_context`/`generated_artifact`/`schema_validated`/`validation_failed`/`provider_incomplete`)・既 blocked・terminal の run は **status 遷移させず latch 任せ** (不正 transition history を作らない)。
- resume は `pre_stop_status` 復元表 + generation CAS。復元先 edge (`blocked`→元 status: running/policy_linted/diff_ready/waiting_approval) を ALLOWED_TRANSITIONS に追加 (`blocked`→policy_linted/diff_ready は新規)。resume / `blocked->running` / `provider_incomplete->running` も **新規活動として latch gate (choke point) で deny** (engaged 中は resume 不可)。
- **`pre_stop_status` 永続先**: `agent_runs` に **専用 additive 列** (`pre_stop_status`) を B2 migration で追加 (event payload より resume CAS の atomicity が単純)。
- **emergency block/resume の event witnessing (user 承認 2026-06-22)**: 汎用 event 再利用は audit semantic を不正確化する (repair_exhausted 前例「汎用 event に意味を隠さない」に反する) ため、**専用 event_type `emergency_stop_engaged` + `emergency_stop_resumed` を 2 つ追加** (5+source: event_type frozenset / DB CHECK / ORM CheckConstraint / Literal / Pydantic / test EXPECTED / frontend)。ADR-00048 (H) 初版の「event_type 増やさない」を R4 honesty 原則で上書き。block transition (running/policy_linted/diff_ready/waiting_approval → blocked) は `emergency_stop_engaged` event で witness (blocked_reason は `runtime_blocked`、A-6 の通り status/reason enum は不変)。resume transition (blocked → pre_stop_status) は `emergency_stop_resumed` event で witness。**event_type 37→39 (現 head Literal/CHECK は既に 37 = P0.1 extension 29-37 を含む)、emergency_stop_* (38-39) を P0 event として追加** (P0.1 sealed extension 29-37 とは別位置、sealed guard に抵触しない)。BLOCKED_EVENT_TYPE_REASON_MAPPING に `emergency_stop_engaged`→`runtime_blocked` を追加。

### A-6. reason_code `emergency_stop_engaged` の位置づけ (R4-MEDIUM-16)

- `emergency_stop_engaged` は **(i) blocked_reason enum (3 種) に追加しない** (status='blocked' + blocked_reason='runtime_blocked' を使う)、**(ii) Provider Compliance 13-reason_code にも追加しない**、**(iii) 独立した application-level reason_code** として audit payload + emergency-stop 専用 enum で 5+source 整合 (cross-source-enum-integrity §1)。既存の sealed enum を汚さない。

### A-7. advisory lock key 形式統一 (R4-MEDIUM-9)

advisory lock key は codebase 既存形式に統一: `pg_advisory_xact_lock(hashtextextended('superintendent-emergency-stop:' || tenant_id::text, 0))` の単一 64bit 文字列 key (二 int32 形式の int4 切り詰め衝突を回避)。

### A-8. budget global_kill_switch との関係 (R4-MEDIUM-12)

emergency-stop latch と既存 budget `global_kill_switch` (policy engine 配線済) は別目的で **共存**: budget=コスト緊急停止 / latch=human 即時全停止。choke point で **OR 評価** (どちらか engaged なら deny)。latch を新設正本とし global_kill_switch は budget 経路の従属。両者の OR を autonomy/provider choke point に明記。

### A-9. worker driver atomic claim point は interface contract (R4-CRITICAL-2 / HIGH-6)

**SP-004-5 worker driver (ADR-00057) は未マージ** (workers は noop_task のみ、AgentRun claim point は実コードに存在しない)。よって SP-PHASE1 は claim point に latch を「貫通」できない。→ SP-PHASE1 は **claim point latch check を interface contract として予約**: (1) `assert_not_emergency_stopped(tenant_id)` 等の共有 latch-check helper を提供、(2) 「worker driver の atomic claim point (queued→gathering_context) は claim 確定 transaction 内で本 helper を呼ぶ」ことを **契約 (ADR + contract test)** として固定。Phase 2 (SP-004-5/ADR-00057) の driver 実装時にこの契約を honor する。SP-PHASE1 の exit「claim→provider 窓なし」は **stub driver / contract test で claim point が latch を見ることを検証**し、実 driver 駆動は Phase 2 で確認。

**A-9 補強 (B5 adversarial LOW-3、TOCTOU 再導入防止)**: read-only な latch check (`assert_not_emergency_stopped`) **だけ** を claim point に置くと、**spawn (§A-1) が P1-2 で解消したのと同じ TOCTOU race** を実 driver が再導入し得る (latch を読んでから claim を確定するまでの窓に engage が割り込み、engaged tenant の run を `gathering_context` へ進めてしまう)。よって worker driver claim point の契約は、spawn (`spawn_agent_managed`、A-1 §0) と **同一 helper・同一 advisory lock key** で serialize することを要求する:

1. claim 確定 transaction 内で **まず `acquire_emergency_stop_lock(session, tenant_id)` を取得** する (spawn と同じ `pg_advisory_xact_lock(hashtextextended('superintendent-emergency-stop:' || tenant_id::text, 0))` の transaction-scoped lock、A-7 key 形式)。
2. lock 保持下で `assert_not_emergency_stopped(session, tenant_id)` を呼ぶ (engaged なら abort、claim しない)。
3. lock 保持下で claim 確定 SQL (queued→gathering_context の atomic UPDATE) を実行し、caller が commit する (commit で lock 解放)。

engage / clear は同一 key の advisory lock を取るため、claim が先に lock を取れば engage は claim COMMIT 後に `gathering_context` 行を観測して kill でき、engage が先なら claim の latch check が engaged を見て abort する。**lock 外で claim が確定する窓は無い** (spawn A-1 §3 と同じ線形化保証)。本 advisory-lock 要件は worker driver contract test の docstring + `assert_not_emergency_stopped` helper の docstring に明記し、実 driver (Phase 2) が必ず honor する固定契約とする。

### A-10. AC-HARD trace + operator role (R4-MEDIUM-10 / LOW-18)

- cross-tenant 非干渉 → **AC-HARD-03** negative fixture、MCP/agent 経路の latch 迂回試行 → **AC-HARD-07** (権限昇格拒否) に明示 trace。`emergency_stop_engaged` を eval fixture loader (23 invariant fixture pattern) に追加。
- `require_emergency_stop_operator` は P0 では `_require_authenticated_owner` と同一 owner gate (authenticated + human + default owner) を流用、別 emergency-stop role は新設せず (P0.1 で role 化を forward-compat 予約)。
