---
id: "ADR-00038"
title: "AgentRun リアルタイム進捗 (L-3 SSE + PostgreSQL LISTEN/NOTIFY)"
status: "proposed"
date: "2026-06-01"
deciders: ["t-ohga"]
adr_gate_criteria: [2, 3]
related_adr:
  - "ADR-00037 (データ管理 / active-scope helper)"
related_dd:
  - "DD-02 (データモデル / AgentRunEvent append-only)"
  - "DD-03 (AI オーケストレーション / AgentRun 16 状態)"
  - "DD-05 (ネットワーク境界 / Tailscale Serve)"
related_sprints:
  - "SP-0046_agentrun_realtime_sse"
supersedes: null
superseded_by: null
---

# ADR-00038: AgentRun リアルタイム進捗 (L-3 SSE + PostgreSQL LISTEN/NOTIFY)

最終更新: 2026-06-01

## 背景

UI 改善計画の最後に残った genuinely 未実装項目 **L-3「リアルタイム進捗 (SSE/WebSocket)」(Tier 4、design approval 必須)** を設計する。現状 `/runs/[id]` は static SSR (`loadRun` で 1 回 fetch、live 更新なし) であり、AgentRun が `queued → gathering_context → running → … → completed` と進行しても、user が手動でリロードしない限り画面が更新されない。AI 実行を「再現可能で観測可能な開発プロセス」として扱うプロダクト思想 (CLAUDE.md §1) に対し、進行中 run の状態が見えないのは UX 上の欠落である。

- 決定対象: AgentRun の status / event を、polling ではなく **server push** で run 詳細画面に realtime 反映する transport + event 検知機構 + scope。
- 関連 Sprint: SP-0046_agentrun_realtime_sse。
- 前提 / 制約:
  - **P0 ネットワーク境界 (DD-05) を変更しない**: Tailscale Serve (tailnet 内 HTTPS reverse proxy → `127.0.0.1:8000`/`3900`) のみ。Funnel / public bind / Cloudflare は使わない (ADR Gate #7 非該当を維持)。
  - **AgentRun 16 状態 / event_type / ContextSnapshot 10 列の不変条件 (rules/agentrun-state-machine.md) に触れない**。realtime は read-only transport であり、新 state / 新 event_type を導入しない。
  - **raw secret / raw payload 非露出 (rules/secretbroker-boundary.md §11, ai-output-boundary.md §4)**: stream する event は既存 `_to_event_read` の redacted shape (`payload_keys` のみ、raw payload を含まない) を再利用する。
  - **active-scope (ADR-00037)**: soft-deleted ticket bound の run は detail/list と同じく stream からも除外する (`soft_deleted_ticket_run_exclusion()`)。
  - 既存 infra: PostgreSQL (主) + Redis (arq queue 用) が Docker Compose に存在。専用 event-streaming infra は未整備。

## 設計上の前提・assumption (★ design approval 時に確認済)

- ★ **transport = SSE** (Server-Sent Events): 進捗は server→client の **一方向 push** で十分。SSE は HTTP/1.1 の `text/event-stream` で動き Tailscale Serve / Next.js proxy を upgrade 交渉なしにそのまま通る。client は **fetch + ReadableStream ベースの SSE client** で reconnect + resume (`?last_event_id=`) を app 制御する (native EventSource の header/reconnect 制約を回避、§12)。双方向が要る操作 (cancel 等) は既存の POST endpoint を使う。
- ★ **event 検知 = PostgreSQL LISTEN/NOTIFY** (push 型、新 infra なし): 「最善で最も品質の良いもの」(user design approval, 2026-06-01) として、poll ではなく **event-driven push** を採用。`agent_run_events` の `AFTER INSERT` trigger が `pg_notify` を発火し、SSE handler が専用接続で `LISTEN` する。単一 source of truth (PostgreSQL) のまま低 latency を得る。Redis を event-append path に挟まない。
- ★ **scope = run 詳細画面** (`/runs/[id]`): live status + live event tail。runs 一覧 / dashboard の realtime 化は本 ADR の採用 architecture (SSE + NOTIFY) を自然に拡張できるため **follow-up** とし、最初の高品質 delivery を run 詳細に集中する。
- ★ **検知は event INSERT trigger + agent_runs UPDATE trigger の 2 系統 (R9 HIGH fix)**: 当初は rules/agentrun-state-machine.md §5「status update と AgentRunEvent append は同一 transaction」を前提に `agent_run_events` INSERT trigger だけを使う設計だったが、既存 MCP bridge (`api_bridge.py`) に `run.status` を直接代入する status-only 経路が実在し (event append を伴わない場合 pg_notify が発火せず heartbeat まで反映が遅れる)、event-driven 保証が writer discipline 依存になる。これを排し、**(1) `agent_run_events` AFTER INSERT trigger + (2) `agent_runs` AFTER UPDATE (status/blocked_reason/completed_at 変化) trigger** の 2 系統を **同一 dirty-signal channel** (`agent_run_event_appended`) へ NOTIFY する。handler は notify 受信時に「新 event tail + 現在の run status snapshot」を再 query する。重複 NOTIFY は bounded queue + drain-to-empty で吸収するため、2 trigger 併用は防御的で副作用が無い。status 専用 channel は増やさない (同一 channel)。
- ★ **LISTEN 確立 → catch-up → dirty-signal 再 query** (Codex plan review R1 CRITICAL fix): notify は **「DB に新 event がある」という dirty-signal** であり、payload を直接 stream に乗せない。順序は (1) LISTEN 登録 → (2) catch-up query (`seq_no > last`) → (3) wake-up ごとに必ず `seq_no > last_sent` を DB から再 query。catch-up を先に流してから LISTEN すると、両者の窓で insert された event の NOTIFY を取りこぼし (NOTIFY は listening 前に発火、その event は既に catch-up 対象外)、terminal event がこの窓に入ると UI 停止 + `stream_end` 不達になる。LISTEN を先に張ることでこの race を構造的に閉じる。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| **A: SSE + PostgreSQL LISTEN/NOTIFY (採用)** | `AFTER INSERT` trigger で `pg_notify`、SSE handler が専用 asyncpg 接続で LISTEN、catch-up + push stream | push 型で低 latency / 新 infra 不要 (既存 Postgres) / 単一 source of truth / poll 負荷なし / append 経路を問わず trigger が全 insert 捕捉 | stream ごとに LISTEN 用 dedicated 接続が要る (接続上限管理) / asyncpg listener → async generator の bridge 実装 / proxy buffering 無効化が必要 |
| B: SSE + DB-poll | SSE handler が `seq_no > last` を ~1-2s 間隔で poll | 実装最小 / 接続 1 本 (session pool 利用) | latency = poll 間隔 / 進行中 run × stream 数だけ周期 query / 「event-driven」でなく最善でない |
| C: SSE + Redis pub/sub | event append で Redis publish、SSE subscribe | 低 latency / 一覧 fan-out 拡張容易 | event-append critical path に Redis 依存追加 / publish の transactional 整合 (DB commit と Redis publish の二重書き) が難しく、source of truth が二重化 |
| D: WebSocket | 双方向 WS | 双方向 | 一方向 progress に over-spec / Tailscale Serve + Next 経由の WS upgrade 交渉が SSE より複雑 / auto-reconnect/resume を自前実装 |

## 採用案

- 採用: **A (SSE + PostgreSQL LISTEN/NOTIFY)**。
- 理由: 新 infra を足さず (既存 PostgreSQL のみ)、event-append を単一 source of truth に保ったまま push 型 realtime を実現する。DB trigger は append 経路 (repository / 将来の別 writer) を問わず全 insert を捕捉するため、notify の漏れが構造的に起きない。SSE は P0 の閉域 HTTP 境界 (DD-05) と最も整合し、fetch-based SSE client + `?last_event_id=` query param で reconnect / resume を app 側が堅牢に制御できる。
- 実装 Sprint: SP-0046_agentrun_realtime_sse。

### 採用 architecture の堅牢化要件 (must_ship)

1. **NOTIFY trigger 2 系統 (migration, additive、R9 HIGH fix)**:
   - (a) `agent_run_events` `AFTER INSERT` trigger → `pg_notify('agent_run_event_appended', json_build_object('tenant_id', NEW.tenant_id, 'run_id', NEW.run_id, 'seq_no', NEW.seq_no)::text)`。
   - (b) `agent_runs` `AFTER UPDATE` trigger (WHEN `OLD.status IS DISTINCT FROM NEW.status OR OLD.blocked_reason IS DISTINCT FROM NEW.blocked_reason OR OLD.completed_at IS DISTINCT FROM NEW.completed_at`) → 同一 channel `agent_run_event_appended` へ `pg_notify(json{tenant_id, run_id})` (status-only 更新経路でも dirty-signal を保証、seq_no は無し)。
   - payload は最小 (8KB NOTIFY 上限に余裕)。event schema / 列は変更しない。重複 NOTIFY は handler の bounded queue + drain-to-empty で吸収。downgrade は 2 trigger + 2 function を drop するだけの lossless。
2. **LISTEN-before-catch-up + dirty-signal 再 query + drain-to-empty (R1 CRITICAL + R2 HIGH fix)**: 順序は (1) `LISTEN agent_run_event_appended` を先に登録 → (2) **`?last_event_id=<seq_no>` query param** (client が最後に受けた `seq_no`、default 0、R4 HIGH fix で header から移行) を読み `seq_no > last` を catch-up query → (3) 以後 wake-up ごとに **必ず `seq_no > last_sent` を DB 再 query** する。notify payload を直接 stream に乗せず、dirty-signal (再 query 契機) としてのみ扱う。これにより catch-up/LISTEN 境界で insert された event の取りこぼし (CRITICAL race) と NOTIFY 取りこぼしの両方を、DB query を真の source として構造的に吸収する。
   - **drain-to-empty (R2 HIGH fix)**: tail query は `seq_no > last_sent ORDER BY seq_no LIMIT N` を使うが、1 つの dirty-signal / catch-up につき **取得件数 < N になるまで loop で drain** する。queue が maxsize=1 で coalesce され、1 signal あたり N 超の event が溜まっても、全 `seq_no` を漏れなく配信してから wait に戻る (burst > N でも event 落とさない)。
3. **専用 bounded LISTEN pool + single-scope acquire/release (custom ASGI response、R1 HIGH + R2 HIGH + R3 HIGH fix)**: LISTEN は接続を stream 持続中保持するため、transactional session pool と分離した **専用 asyncpg pool** (例: max 10) を使う。
   - **DB を触らない validation/auth のみ deps で確定**: `?last_event_id=` query param は整数 `seq_no` のみ受理 (非整数/UUID は `400/422`) / tenant・actor は sessionless dep で request.state から解決。**scope (404) 判定は deps でやらない** (DB query = main pool checkout になり capacity 判定前に枯渇させるため、R8 HIGH)。
   - **capacity → preflight → stream → release を custom ASGI response の単一 `__call__` 内 try/finally に集約 (R3 + R8 HIGH fix)**: endpoint は (deps 通過後) custom response を return するだけ。response の `__call__(scope, receive, send)` 内で **(i) capacity slot を非ブロッキング取得 → 満杯なら `503` + `Retry-After` を送出して return (= DB を一切触らず拒否、over-capacity open storm が main pool を枯渇させない、R8 fix)、(ii) slot 取得後に短命 session で run/active-scope preflight → scope 外なら `404` 送出して return、(iii) LISTEN connection 取得 → 200 SSE header → LISTEN → catch-up → stream、(iv) `finally` で listener remove + LISTEN connection release + capacity slot 解放**。capacity slot は DB checkout より前に gate し、slot/connection の取得・解放を 1 つの `__call__` try/finally に収めることで、R3 の pre-response handoff leak 窓と R8 の preflight-before-capacity 枯渇の両方を排除する。404/例外/abort でも `finally` で slot を必ず解放。
   - **capacity 判定は `timeout=0` を使わない (R5 HIGH fix)**: 枯渇判定は **明示的な capacity counter / `asyncio.Semaphore(max)` の非ブロッキング取得** (満杯のみ `503`) で行い、acquire は **短い正の timeout (例 250ms)** を使う。`pool.acquire(timeout=0)` / `asyncio.wait_for(..., timeout=0)` は空きがあっても即 `TimeoutError` になり、通常時も全接続 `503` 化する (= L-3 全面停止 + client backoff 連鎖) ため禁止。backend test で「空きがあれば 200 で開始」「枯渇時のみ 503」の両方を確認する。
   - **main transactional pool を stream lifetime で保持しない (R6 HIGH fix)**: stream endpoint は **yield 型 `get_db_session` dependency を注入しない** (FastAPI の yield dependency cleanup は response 完了まで遅延し、streaming では preflight session が 30 分 stream / disconnect まで main pool connection を保持して通常 API を枯渇させる)。tenant/actor は **request state から解決**、run/scope preflight は **明示的な短命 session (`async with AsyncSessionFactory() as s: ...`) で実行し response return 前に close**。stream 中の tail/status query も LISTEN pool とは別に **per-query 短命 session** (取得→query→即 close) で行い、main pool checkout を stream 数でなく「実行中 query 数」に比例させる。LISTEN connection (専用 pool) だけが stream 持続中 held。受け入れ条件に「N 本 stream を開いたまま通常 AgentRun detail/list が main pool connection を取得できる」を追加。
   - **sessionless auth + stream query 同時実行 cap + heartbeat jitter (R7 HIGH fix)**: (i) SSE endpoint の auth は **request.state から tenant/actor を読む sessionless dependency** を新設し、`get_db_session` を Depends する `get_current_actor_id` 等の **yield session 依存を stream route の dependency graph に含めない** (含めると yield cleanup 遅延で R6 fix が復活破綻、test/静的検査で dep graph を確認)。(ii) per-query session でも heartbeat/notify が N stream を同時に起こすと N 本の main pool checkout が同時発生し得るため、**stream 由来 main query 専用の semaphore/concurrency cap (例 4)** を置き、通常 API 用の main pool 余力を常に残す。(iii) **heartbeat に jitter** を入れ全 stream の同時 wake を散らす。(iv) `agentrun_sse_listen_pool_max` は main pool 余力と独立に上げられない制約を config/ADR に明記。受け入れ条件を「N 本 stream を **同時 notify/heartbeat で起こした状態でも** 通常 detail/list が main pool を取得できる」へ広げる。
4. **listener → async generator bridge (bounded dirty-signal queue、R1 MEDIUM fix)**: `asyncio.Queue(maxsize=1)` を **dirty-signal** として使う。`add_listener` callback は payload の `tenant_id` + `run_id` を **両方** 照合し対象 run のみ `queue.put_nowait(None)` (full なら無視 = coalesce、payload を蓄積しない)。generator は `asyncio.wait_for(queue.get(), timeout=heartbeat)` で待機し、wake-up 時に DB 再 query (#2)。これにより無関係 notify の蓄積も、遅い client での queue 肥大も起きない (overflow しても次の DB query で回復)。
5. **heartbeat + idle scope 再検証 (R2 HIGH fix)**: 約 15s の heartbeat timeout ごとに、keepalive (`: keepalive\n\n`) 送信前に **active-scope + status を再 query** する。NOTIFY 源は `agent_run_events` insert のみであり、ticket/project の soft-delete は event insert を伴わないため、idle (新 event 無し) stream では heartbeat が唯一の scope 再評価契機になる。これにより event を一切 append しなくても **heartbeat 以内に `stream_end(scope_revoked)`** を満たす。terminal 検知も同様に heartbeat 再 query で拾う。
6. **terminal close**: run が terminal (`completed`/`failed`/`cancelled`/`provider_refused`/`repair_exhausted`) に達したら最終 status を流して `event: stream_end` で正常終了する (無限保持しない)。
7. **max stream lifetime**: 上限 (例: 30 分) で server 側から close、client は `?last_event_id=<last seq_no>` 付きで再接続 → 長時間接続の滞留を防ぐ。
8. **disconnect cleanup**: `request.is_disconnected()` / asyncio cancellation で LISTEN 接続を確実に pool へ返却。
9. **SSE 全 DTO allowlist + SSE framing contract + redaction (R1 HIGH + R2 HIGH fix)**: stream する **全 message 種別ごとに送信 DTO を明示** し、それ以外の AgentRun 本体 field を絶対に乗せない:
   - `agent_run_event`: id (UUID) は **`event_id` に rename**、`seq_no` / `event_type` / `actor_id` / `payload_keys` のみ / `payload_redaction_status` (`_to_event_read` ベース)。raw payload を含めない。
   - `agent_run_status`: 最小 allowlist (`status` / `blocked_reason` / `terminal` (bool) / `completed_at` / `error_code`) のみ。`error_summary` raw / provider metadata / input-output summary / cost 内訳は **乗せない** (status snapshot 経路が `_to_event_read` を通らず漏洩する R1 HIGH を塞ぐ)。
   - `stream_end`: `reason` enum (`terminal` / `scope_revoked` / `max_lifetime` / `server_shutdown`) のみ。
   - **`agent_run_error` (R2 HIGH fix)**: stream 開始後の DB/query/listener 例外は HTTP status で表せないため専用 DTO を定義。`reason` enum + `retryable` (bool) + `request_id` / `correlation_id` のみ。**exception message / SQL detail / provider metadata / error_summary raw を禁止**。無言切断 (reconnect storm) でなく `agent_run_error` → `stream_end` で閉じる。
   - **SSE framing + resume contract (R2 HIGH + R4 HIGH fix)**: resume の source of truth は **`?last_event_id=<seq_no>` query param** (fetch-based client が管理、§12)。client は各 `agent_run_event` DTO の `seq_no` を追跡し、(再)接続時に `?last_event_id=` で渡す。server は query param を **整数 `seq_no` のみ受理**、非整数 / UUID は (deps で) `400/422` reject。SSE frame の `id:` は `agent_run_event` のみ `seq_no` を補助的に出す (informational、`agent_run_status` / `stream_end` / `agent_run_error` は出さない)。native EventSource の Last-Event-ID 内部状態には依存しない (close/再作成で header 再送不可な R4 HIGH を回避)。
   - redaction test は `agent_run_event` に限らず `agent_run_status` / `stream_end` / `agent_run_error` を含む **全 DTO** に広げる。
10. **stream 中 active-scope 再評価 (R1 HIGH fix)**: active-scope は open 時だけでなく、catch-up / 各 wake-up の tail・status query 自体に `soft_deleted_ticket_run_exclusion()` を組み込む。stream 開始後に対象 ticket が soft-delete され scope 外になったら、即時に `stream_end` (`reason=scope_revoked`) で stream を終了する (削除済み scope の event/status をライブ配信し続けない)。
11. **proxy buffering 無効化**: response に `Cache-Control: no-cache` / `X-Accel-Buffering: no` / `Content-Type: text/event-stream` を付与。Next.js proxy と Tailscale Serve が SSE を buffer せず pass-through することを検証する (検証項目、後述リスク)。
12. **client 側 reconnect 制御 (fetch-based SSE client、R1 MEDIUM + R3 HIGH + R4 HIGH fix)**: native EventSource は (a) 失敗 HTTP response の status/body を app に渡さず自動再接続を続け、(b) Last-Event-ID を同一インスタンスの内部状態としてのみ保持し close/再作成で header 再送できない。この 2 制約のため native EventSource では storm 制御と resume の両立が不可能 (R4 HIGH)。**fetch + `ReadableStream` ベースの SSE client** (例: `@microsoft/fetch-event-source` 相当 or 自前 reader) を採用し、reconnect と resume を app が完全制御する:
   - **resume を app 管理**: client は受信した最後の `agent_run_event` の `seq_no` を保持し、(再)接続時に **`?last_event_id=<seq_no>`** を付けて fetch する (header 制約を回避、§9 と一致)。
   - **reconnect 制御**: fetch error / 切断時に **指数バックオフ (jitter) + 最大試行回数 + 上限到達で停止 UI**。HTTP status を読めるので、`503` → バックオフ、`400/404` → 停止 (resume reset 後 1 回再試行)、`204` → 恒久停止。
   - **server stop semantics**: flag-off / 恒久停止は server が **`204`** を返し、client は再接続しない。transient は `503` + バックオフ。
   - **flag-off 一次防御**: SSR の `sseEnabled=false` なら client を **生成しない** (static fallback)。
   - 受け入れ条件: flag-off 非生成 / `503` で tight reconnect せずバックオフ / 切断後 `?last_event_id=` 付き再接続で欠落なく resume / `204` で再接続停止。

- 実装対象ファイル:
  - `migrations/versions/0041_agent_run_event_notify_trigger.py` (NOTIFY trigger + function、additive、両方向)
  - `backend/app/services/realtime/agent_run_stream.py` (LISTEN pool 管理 + SSE event generator + catch-up + redaction 共用)
  - `backend/app/api/agent_runs.py` (`GET /{run_id}/events/stream` SSE endpoint 追加。**sessionless auth dep を新設** (request.state から tenant/actor、`get_db_session`/`get_current_actor_id` は注入しない、R7 HIGH) + preflight/stream query は短命 session で `soft_deleted_ticket_run_exclusion()` を適用)
  - `backend/app/config.py` (LISTEN pool max / heartbeat interval / max stream lifetime / SSE enabled flag)
  - `frontend/app/(admin)/runs/[id]/` (run 詳細を live 化する Client Component。fetch-based SSE client で status/events 反映、terminal/error/backoff reconnect handling)
  - `tests/api/test_agent_run_stream.py` / `tests/realtime/…` (contract + negative)
- 実装ガイダンス:
  - SSE endpoint は **read-only** (mutation なし)。AgentRun status / event の append は既存経路のみが行い、stream は観測専用。
  - tenant / active-scope を最初に enforce (`soft_deleted_ticket_run_exclusion()`)、対象 run が無ければ stream を開かず `404`。
  - feature flag (env、default on) で endpoint を無効化可能にし、無効時 frontend は static SSR + 手動更新に fallback (rollback path)。
  - audit: stream open/close は AgentRunEvent / audit を増やさない (read であり状態遷移ではない)。必要なら structured log の correlation_id のみ。
- テスト指針:
  - `uv run pytest tests/api/test_agent_run_stream.py`
  - catch-up: `?last_event_id=N` で `seq_no>N` のみ流れる。
  - redaction: stream payload に raw secret / raw payload が無い (`assert_no_raw_secret` 相当)。
  - active-scope: soft-deleted ticket bound run の stream は `404`。
  - tenant isolation: 別 tenant の run_id を stream できない (negative)。
  - terminal close: terminal run は `stream_end` で閉じる。
  - bound: LISTEN pool 上限超過で `503`。
  - trigger: `agent_run_events` insert で `pg_notify` が発火する (DB test、`TASKMANAGEDAI_RUN_DB_TESTS=1`)。**R9 追加**: `agent_runs` の status-only 更新 (event append 無し) でも `agent_runs` UPDATE trigger が `pg_notify` 発火し、SSE が dirty-signal で status 反映する。
  - migration: `alembic upgrade head` → trigger 存在、`downgrade` → trigger/function drop の lossless。
  - frontend: fetch-based SSE client mock で status/event 反映 + backoff reconnect (Vitest)。
  - **R1 追加 (must_ship)**: catch-up/LISTEN 境界 race 再現 (LISTEN 登録と catch-up の間に event insert → 取りこぼさない) / soft-delete 後 stream が `scope_revoked` で停止 / `agent_run_status` + `stream_end` の redaction (raw payload/secret なし) / pool 枯渇で HTTP 503 (stream 開始前) / bounded queue overflow 後も `seq_no > last_sent` で回復 / flag-off で frontend が SSE client 非生成・reconnect しない。
  - **R2 追加 (must_ship)**: event を一切 append せず ticket soft-delete → heartbeat 以内に `stream_end(scope_revoked)` / 1 dirty-signal に N 超 burst → drain-to-empty で全 `seq_no` 配信 / SSE `id:` は `agent_run_event` のみ seq_no・status/error は id なし / UUID や非整数 `?last_event_id=` を deps で 400 reject / stream 開始後 error は `agent_run_error` (reason/retryable/correlation_id のみ、exception message なし) で閉じる / generator factory 例外・初回 yield 前 cancel・response 構築失敗で LISTEN pool 使用数が戻る。
  - **R3 追加 (must_ship)**: client SSE wrapper が pool 枯渇 (`503`) で tight reconnect せず指数バックオフ / 恒久停止 (`204`) で再接続停止 (frontend Vitest) / custom ASGI response の `__call__` return 後・初回 iteration 前の client abort で LISTEN pool 使用数が戻る (backend、ASGI scope cancel 再現)。
  - **R4 追加 (must_ship)**: fetch-based client が切断後 `?last_event_id=<last seq_no>` 付きで再接続し欠落なく resume (seq 0 全再送にならない) / `?last_event_id=` 非整数・UUID を server が `400` reject / rollback flag-off で server が `204` を返し stale client が再接続停止 (already-created client の 204 受信 test)。
  - **R6 追加 (must_ship)**: N 本の SSE stream を開いたまま通常 AgentRun detail/list endpoint が main DB connection を取得できる (pool starvation test、preflight session が stream lifetime に保持されない / main pool checkout が stream 数に比例しない)。
  - **R7 追加 (must_ship)**: stream route の dependency graph に `get_db_session`/`get_current_actor_id` を含まない (sessionless auth、dep override/静的検査 test) / N 本 stream を **同時 notify/heartbeat で起こした状態でも** 通常 detail/list が main pool を取得できる (concurrency cap + jitter)。
  - **R8 追加 (must_ship)**: M > listen_pool_max の **同時 open storm** (大半が 503 で拒否される) でも通常 detail/list が main pool を取得できる (capacity gate が DB preflight より前で、拒否要求は main pool を checkout しない)。

## Codex plan review R1 採否記録 (2026-06-01)

codex-adversarial-review R1 (job `review-mptytliv-4yxo2o`) で 6 findings、**全件 adopt** し本 ADR + SP-0046 に反映:

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | CRITICAL | catch-up→LISTEN 順序 race で接続開始中 event を恒久ロスト | 堅牢化 #2 (LISTEN-before-catch-up + dirty-signal 再 query) |
| 2 | HIGH | stream 開始後 soft-delete で scope 外 run 配信継続 | 堅牢化 #10 (stream 中 active-scope 再評価) |
| 3 | HIGH | status snapshot が redaction を通らず raw 漏洩余地 | 堅牢化 #9 (SSE 全 DTO allowlist) |
| 4 | HIGH | LISTEN pool 503 が StreamingResponse 開始後で破綻 | 堅牢化 #3 (pre-response 予約 → 503) |
| 5 | MEDIUM | 単一 channel unbounded queue が無関係 notify 蓄積 | 堅牢化 #4 (bounded dirty-signal queue) |
| 6 | MEDIUM | flag-off で EventSource reconnect storm | 堅牢化 #12 (frontend が SSE を開かない) |

reject / defer: なし。R2 で fix の整合と副作用を再確認してから ADR を accepted へ昇格する。

## Codex plan review R2 採否記録 (2026-06-01)

codex-adversarial-review R2 (job `review-mptz30lr-rsw9xq`) で **CRITICAL=0** (R1 race 解消を確認) かつ 5 findings (全 HIGH)、**全件 adopt** し反映:

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | HIGH | idle stream で soft-delete scope 失効の即時停止契機が無い | 堅牢化 #5 (heartbeat ごと scope 再検証) |
| 2 | HIGH | coalesce + tail limit で burst event が取り残される | 堅牢化 #2 (drain-to-empty loop) |
| 3 | HIGH | SSE `id:` と DTO UUID 未分離で Last-Event-ID resume 破壊 | 堅牢化 #9 (framing contract: id=seq_no は event のみ / UUID は event_id rename / invalid Last-Event-ID 400) |
| 4 | HIGH | error DTO が allowlist から漏れ raw 漏洩余地 | 堅牢化 #9 (`agent_run_error` DTO 追加) |
| 5 | HIGH | 予約 connection の generator 未到達時 release 未定義 → pool leak | 堅牢化 #3 (acquire→return を try/except、移譲失敗時 release) |

reject / defer: なし。R3 で R2 fix の整合と新規 HIGH/CRITICAL 不在を確認後、ADR を accepted へ昇格する。

## Codex plan review R3 採否記録 (2026-06-01)

codex-adversarial-review R3 (job `review-mptzbu52-hsnvc6`) で **CRITICAL=0 / HIGH=2** (数値上 clean 閾値内だが、Codex は R2 fix の副作用を残穴と判定)。**全件 adopt** し反映:

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | HIGH | native EventSource が HTTP error を app に渡さず再接続継続 → 400/503 では storm を防げない | 堅牢化 #12 (client EventSource wrapper: backoff/max-attempts/resume-reset + 恒久停止 204) |
| 2 | HIGH | StreamingResponse return 後〜body 開始前 cancel で generator finally 不実行 (pool leak 窓残存) | 堅牢化 #3 (custom ASGI response の単一 `__call__` 内で acquire/503/stream/release を try/finally) |

reject / defer: なし。R4 で R3 fix の整合と CRITICAL/HIGH 不在を確認後、ADR を accepted へ昇格する。

## Codex plan review R4 採否記録 (2026-06-01)

codex-adversarial-review R4 (job `review-mptzks77-m2hhnc`) で **CRITICAL=0 / HIGH=2** (R3 fix の副作用)。**全件 adopt** し反映:

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | HIGH | R3 の「close→fresh EventSource」が native Last-Event-ID resume を壊す (header 再送不可 → seq 0 再送) | 堅牢化 #2/#9/#12 (fetch-based client + `?last_event_id=` query param resume) |
| 2 | HIGH | rollback の flag-off=404 が R3 の 204 恒久停止契約と矛盾 | rollback section (flag-off=`204` に統一) |

reject / defer: なし。R5 で R4 fix の整合と CRITICAL/HIGH 不在を確認後、ADR を accepted へ昇格する。

## Codex plan review R5 採否記録 (2026-06-01)

codex-adversarial-review R5 (job `review-mptzs6xr-ftan97`) で **CRITICAL=0 / HIGH=2**。**全件 adopt** し反映:

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | HIGH | `pool.acquire(timeout=0)` は容量あっても即 TimeoutError → 常時 503 化 | 堅牢化 #3 (capacity counter/Semaphore + 短い正の acquire timeout、`timeout=0` 禁止) |
| 2 | HIGH | R4 の fetch-based resume 契約に対し実装対象/テスト/browser に旧 `EventSource`/`Last-Event-ID` 残存 | ADR/SP 全 authoritative セクションを `fetch + ReadableStream` / `?last_event_id=` / 204・400・404・503 分岐に統一 (R 採否記録 history table は当時の事実として保持) |

reject / defer: なし。R6 で `timeout=0` / `EventSource` / `Last-Event-ID` 残存 sweep と CRITICAL/HIGH 不在を確認後、ADR を accepted へ昇格する。

## Codex plan review R6 採否記録 (2026-06-01)

codex-adversarial-review R6 (job `review-mpu01mvh-knbdk6`) で **CRITICAL=0 / HIGH=1** (`timeout=0` / 旧 client 契約は正本から一掃済を確認、新たに DB session lifetime を指摘)。**全件 adopt** し反映:

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | HIGH | FastAPI yield `get_db_session` は cleanup が response 完了まで遅延 → streaming で preflight session が main pool を stream lifetime 保持し pool 隔離破綻 | 堅牢化 #3 (yield session 不注入 / preflight 短命 session を return 前 close / tail-status は per-query 短命 session) + SP T3/受け入れ条件 (pool starvation test) |

reject / defer: なし。R7 で main pool checkout が stream 数に比例しないことと CRITICAL/HIGH 不在を確認後、ADR を accepted へ昇格する。

## Codex plan review R7 採否記録 (2026-06-01)

codex-adversarial-review R7 (job `review-mpu096nw-eswl59`) で **CRITICAL=0 / HIGH=2** (R6 pool 隔離の次層)。**全件 adopt** し反映:

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | HIGH | 「既存 auth deps 再利用」だと `get_current_actor_id`→`get_db_session` 経由で R6 session 隔離が復活破綻 | 堅牢化 #3 + 実装対象 (sessionless auth dep 新設、dep graph に yield session を含めない) |
| 2 | HIGH | per-query session でも同時 wake で N 個の main pool checkout → starvation | 堅牢化 #3 (stream query concurrency cap + heartbeat jitter + listen_pool_max ≤ main pool 余力) + config 2 field |

reject / defer: なし。R8 で sessionless auth dep graph と concurrent-wake pool 取得を確認後、ADR を accepted へ昇格する。

## Codex plan review R8 採否記録 (2026-06-01)

codex-adversarial-review R8 (job `review-mpu0ffm4-ecv1wj`) で **CRITICAL=0 / HIGH=1** (pool 隔離の開始時ギャップ)。**全件 adopt** し反映:

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | HIGH | capacity 判定が DB preflight の後なので、503 で拒否される over-capacity open storm でも全要求が scope 確認で main pool を一度 checkout → 開始時経路で隔離迂回 | 堅牢化 #3 (capacity slot を DB preflight より前に gate、capacity→preflight→stream→release を `__call__` 単一 try/finally に集約) + SP T3/受け入れ条件 (over-capacity open storm test) |

reject / defer: なし。R9 で over-capacity open storm 時の main pool 非枯渇を確認後、ADR を accepted へ昇格する。

## Codex plan review R9 採否記録 (2026-06-01)

codex-adversarial-review R9 (job `review-mpu0n6ic-iqu2ns`) で **CRITICAL=0 / HIGH=1** (pool 隔離は確認、検知機構に新領域 finding)。**adopt** し反映 (premise を `api_bridge.py` の `run.status` 直接代入経路 419/822/1119/1176 で実体確認):

| # | severity | finding | 反映先 |
|---|---|---|---|
| 1 | HIGH | event INSERT trigger のみ依存。status-only 更新経路 (MCP bridge cancel/delegation 等、event append なし) で pg_notify 不発 → heartbeat まで反映遅延、event-driven 保証が writer discipline 依存 | 設計前提 + 堅牢化 #1 (`agent_runs` AFTER UPDATE trigger を同一 channel へ追加、2 系統検知) + SP T1/受け入れ条件 (status-only 更新 dirty-signal test) |

reject / defer: なし。R10 で 2 trigger 検知の整合と CRITICAL/HIGH 不在を確認後、ADR を accepted へ昇格する。

> **Note**: §R1〜R4 採否記録 table 内の `EventSource` / `Last-Event-ID` 語は **当該 round 時点の finding を記述した history** であり、現行 authoritative 設計 (fetch-based / `?last_event_id=`) ではない。実装は本 §採用案・堅牢化要件・テスト指針・受け入れ条件を正本とする。

## 却下案

- **B (SSE + DB-poll)**: 実装は最小だが、latency が poll 間隔に律速され、進行中 run × stream 数だけ周期 query が走る。user の「最善で最も品質の良いもの」要求に対し event-driven でない点で劣る。NOTIFY が新 infra を要さず P0 で十分機能するため、poll を採る理由がない。
- **C (SSE + Redis pub/sub)**: event-append という critical path に Redis publish を挟むと、DB commit と Redis publish の二重書きで transactional 整合が崩れる余地が生じ (publish 漏れ / commit rollback 後の幽霊 publish)、source of truth が二重化する。DB trigger NOTIFY は同一 transaction 内で commit と原子的に整合し、この問題が無い。一覧 fan-out が必要になった段階でも NOTIFY 拡張で対応可能。
- **D (WebSocket)**: 一方向 progress に双方向 transport は over-spec。Tailscale Serve + Next.js 経由の WS upgrade 交渉は SSE の素の HTTP より複雑で、auto-reconnect / resume を自前実装する負担も増える。P0 の閉域 HTTP 境界との適合は SSE が勝る。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| LISTEN 接続が main pool を枯渇させる | 接続数監視 / pool timeout エラー | 専用 bounded asyncpg pool (max N) に分離 + 上限超過 `503` + max stream lifetime で滞留防止 |
| reverse proxy (Tailscale Serve / Next.js) が SSE を buffer し realtime にならない | ブラウザ検証で event 到達が遅延/まとめ届き | `X-Accel-Buffering: no` + `Cache-Control: no-cache` + Next.js streaming response 確認。**ブラウザ側検証必須項目** (後述) |
| NOTIFY 取りこぼし / catch-up-LISTEN 境界 race の event ロスト (R1 CRITICAL) | catch-up/LISTEN race 再現 test (境界で event insert) | **LISTEN を先に張ってから catch-up**、以後 wake-up ごとに `seq_no > last_sent` を DB 再 query。NOTIFY は dirty-signal、真の source は DB query (取りこぼしが次 query で必ず回復) |
| stream 開始後の soft-delete で scope 外 run が配信継続 (R1 HIGH) | soft-delete 後 stream 停止 test | catch-up / 各 wake-up の tail・status query に `soft_deleted_ticket_run_exclusion()` を組み込み、scope 外検知で `stream_end(scope_revoked)` |
| status snapshot 経路が redaction を通らず raw 漏洩 (R1 HIGH) | 全 SSE DTO の redaction test | SSE message 種別ごとに送信 DTO allowlist を明示、status snapshot は最小 field のみ (error_summary raw / provider metadata を乗せない) |
| LISTEN pool 枯渇 503 が stream 開始後で破綻 (R1 HIGH) | pool 枯渇時に HTTP 503 を返す test | LISTEN connection を StreamingResponse 前に予約、失敗時のみ 503+Retry-After |
| asyncpg listener → generator bridge の leak / 例外で接続返却漏れ | 接続数が減らない / pool 枯渇 | `try/finally` で remove_listener + 接続 return、disconnect 検知で確実に cleanup、test で接続返却を assert |
| NOTIFY payload 8KB 上限 | trigger で大 payload を送ると失敗 | payload は `{tenant_id, run_id, seq_no}` のみ (数十 bytes)。event 本体は handler が query |
| stream に raw payload/secret が漏れる | redaction test / `assert_no_raw_secret` | `_to_event_read` (payload_keys のみ) を共用、raw payload を stream に乗せる経路を作らない |
| 多数 client が同 run を stream し DB query 増 | query 数監視 | notify 1 回につき軽量 tail query (limit), heartbeat で idle、上限 bound |
| AgentRun 16 状態 / event_type を誤って拡張 | enum 5+ source 整合 test | SSE は transport であり enum を増やさない。migration は trigger のみ (event schema 不変)、CI enum drift test で担保 |

## rollback 手順

1. rollback trigger: SSE endpoint で接続滞留 / pool 枯渇 / proxy buffering 未解決 / realtime が不安定。
2. rollback step:
   - 即時: feature flag (env `AGENTRUN_SSE_ENABLED=false`)。SSR の `sseEnabled=false` により新規 client は **生成されず** static SSR + 手動更新に fallback。**既にロード済の stale client** に対しては endpoint が flag-off で **`204`** を返し、client は spec 通り **再接続を停止** する (R4 HIGH fix: 404 だと stale client が error 扱いで auth/scope path を叩き続ける)。機能停止のみ・データ影響なし。
   - schema 戻し: `alembic downgrade -1` で `0041` の NOTIFY trigger + function を drop。trigger は additive かつ event data に触れないため **lossless** (event 行は不変、downgrade で realtime が止まるだけ)。
3. verification after rollback: run 詳細が static で正しく表示される / `alembic check` clean / `agent_run_events` 件数・内容が rollback 前後で不変 (trigger は read-only side-effect のみ) / 新規 client が SSE を開かない / **stale client が flag-off の `204` を受けて再接続を停止する** (Network tab で reconnect が止まる)。

## ブラウザ側検証必須項目 (実装後、所要 ~15 分)

> 実装完了後に 1 回でまとめて依頼する (CLAUDE.md ブラウザ側検証依頼ルール準拠)。詳細手順は Sprint Pack 検証手順に記載。

1. 進行中 run の `/runs/[id]` で、別経路で event が append された時に **リロードなしで** status バッジ + event tail が更新される (DevTools Network で `text/event-stream` 接続が 1 本維持、buffer されず逐次 `data:` 到達)。
2. terminal 到達で stream が `stream_end` で閉じ、再接続ループしない。
3. 接続を一時切断→復帰で **再接続 URL に `?last_event_id=<last seq_no>` が付き** (header 依存でない)、切断中の event が catch-up で漏れなく表示。pool 枯渇 (`503`) で tight reconnect せず backoff、恒久停止 (`204`) で再接続停止。
4. Console error 0 (hydration / SSE client error の有無)。
