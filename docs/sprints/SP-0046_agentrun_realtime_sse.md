---
id: "SP-0046_agentrun_realtime_sse"
type: "heavy"
status: "draft"
sprint_no: 46
created_at: "2026-06-01"
updated_at: "2026-06-01"
target_days: 3
max_days: 5
adr_refs:
  - "[ADR-00038](../adr/00038_agentrun_realtime_sse.md)"
related_sprints:
  - "SP-0045 (UI 改善 / 既出)"
risks:
  - "LISTEN 接続による pool 枯渇 (bounded 専用 pool で軽減)"
  - "reverse proxy SSE buffering (X-Accel-Buffering + ブラウザ検証)"
  - "asyncpg listener bridge の接続返却漏れ (try/finally + disconnect cleanup)"
---

# SP-0046: AgentRun リアルタイム進捗 (L-3 SSE + PostgreSQL LISTEN/NOTIFY)

## 目的

UI 改善計画の最終未実装項目 **L-3「リアルタイム進捗」(Tier 4)** を、ADR-00038 採用案 **SSE + PostgreSQL LISTEN/NOTIFY** で実装する。`/runs/[id]` を static SSR から、AgentRun の status / event を server push で realtime 反映する live 画面にする。

## 背景

- 現状 `/runs/[id]` は `loadRun` で 1 回 fetch する static SSR。進行中 run の状態が手動リロードまで見えない。
- ADR-00038 で transport=SSE / 検知=LISTEN/NOTIFY / scope=run 詳細 を design approval 済 (2026-06-01)。
- core invariant (AgentRun 16 状態 / event_type / ContextSnapshot 10 列 / DD-05 network 境界) は不変更。SSE は read-only transport、NOTIFY trigger は additive。

## 対象外

- runs 一覧 / dashboard の realtime 化 (follow-up、本 ADR architecture の自然な拡張)。
- WebSocket / 双方向通信 (ADR-00038 で却下)。
- Redis pub/sub 経路 (却下)。
- 新 AgentRun state / 新 event_type の追加 (transport であり enum を増やさない)。
- network 境界変更 (Funnel / public bind は引き続き deny)。
- OTel / Prometheus metrics 本格化 (Sprint 11.5 scope)。

## 設計判断

ADR-00038 採用案に準拠。堅牢化 10 要件 (NOTIFY trigger / catch-up-on-connect / bounded LISTEN pool / listener bridge / heartbeat / terminal close / max lifetime / disconnect cleanup / redaction 再利用 / proxy buffering 無効化) を must_ship とする。

| 判断 | 採用 | 根拠 |
|---|---|---|
| transport | SSE (fetch-based client) | 一方向 push / HTTP / Tailscale Serve ネイティブ / app 制御 reconnect + `?last_event_id=` resume |
| event 検知 | PostgreSQL LISTEN/NOTIFY (AFTER INSERT trigger) | push 型 / 新 infra なし / 単一 source of truth / append 経路非依存 |
| catch-up | **LISTEN 確立 → catch-up → wake-up ごと `seq_no>last_sent` 再 query** (R1 CRITICAL) | NOTIFY を dirty-signal 化、catch-up/LISTEN race を構造的に閉じる |
| 接続管理 | 専用 bounded asyncpg pool + **custom ASGI response の単一 `__call__` で acquire/503/release** (R1+R2+R3 HIGH) | pool 枯渇防止 + handoff 窓の leak 排除 |
| redaction | **SSE 全 DTO allowlist** (event=`_to_event_read` / status=最小 field / stream_end=reason) (R1 HIGH) | status snapshot 経路の raw 漏洩を封じる |
| stream 中 scope | tail/status query に active-scope 組み込み + `scope_revoked` 停止 (R1 HIGH) | soft-delete 後の配信継続を停止 |
| queue | bounded dirty-signal (maxsize=1, coalesce) (R1 MEDIUM) | 無関係 notify 蓄積 / queue 肥大を回避 |
| flag-off / reconnect / resume | **fetch-based SSE client** (`?last_event_id=` resume + backoff/max + flag-off 非生成 + 恒久停止 204) (R1 MEDIUM + R3 HIGH + R4 HIGH) | native EventSource の header/reconnect 制約を回避し storm 制御と resume を両立 |
| scope 境界 | `soft_deleted_ticket_run_exclusion()` + tenant | 全 read path active-scope (ADR-00037) と整合 |

## 実装チケット

| ID | 内容 | 主ファイル |
|---|---|---|
| T1 | NOTIFY trigger 2 系統 migration (events INSERT + agent_runs UPDATE、additive, 両方向 lossless) | `migrations/versions/0041_agent_run_event_notify_trigger.py` |
| T2 | LISTEN pool + SSE event generator + catch-up + redaction 共用 | `backend/app/services/realtime/agent_run_stream.py` |
| T3 | SSE endpoint `GET /{run_id}/events/stream` (auth + active-scope + 404) | `backend/app/api/agent_runs.py` |
| T4 | config (pool max / heartbeat / max lifetime / enabled flag) | `backend/app/config.py` |
| T5 | frontend live Client Component (**fetch-based SSE client** / `?last_event_id=` resume / status・events 反映 / backoff reconnect / 204 停止 / terminal) | `frontend/app/(admin)/runs/[id]/` |
| T6 | backend contract + negative test | `tests/api/test_agent_run_stream.py` |
| T7 | frontend SSE client test (Vitest) | `frontend/app/(admin)/runs/[id]/__tests__/` |

## タスク一覧

1. ADR-00038 proposed → accepted 昇格 (codex-plan-review R1 + 採否判定後、実装着手直前)。
2. T1 migration (2 trigger): (a) `AFTER INSERT ON agent_run_events` → `pg_notify('agent_run_event_appended', json{tenant_id,run_id,seq_no})`、(b) `AFTER UPDATE ON agent_runs WHEN status/blocked_reason/completed_at DISTINCT` → 同 channel `pg_notify(json{tenant_id,run_id})` (status-only 経路カバー、R9)。upgrade で 2 trigger+2 function create、downgrade で drop (lossless)。`alembic upgrade head` / `downgrade` を fresh DB で確認。
3. T2 stream service: bounded asyncpg pool (lazy init)。`listen_run(...)` async generator は **(1) LISTEN 登録 → (2) catch-up query (`seq_no>last`, active-scope 組み込み, drain-to-empty: 取得 < N まで loop) → (3) bounded dirty-signal queue (maxsize=1, coalesce) で wake-up 待ち → 各 wake-up で `seq_no>last_sent` + status を active-scope 込みで drain-to-empty 再 query → scope 外なら `stream_end(scope_revoked)`** → **heartbeat timeout ごとに keepalive 前 scope/status 再検証** (idle 失効) → terminal close → 開始後例外は `agent_run_error` で閉じる → finally で listener remove + connection 返却。SSE DTO は event/status/stream_end/error ごとに allowlist、framing は event のみ `id:<seq_no>`。
4. T3 endpoint: **(a) deps (DB 不使用): `?last_event_id=` validation (非整数/UUID は 400/422) + tenant/actor を新設 sessionless dep で request state から解決 (`get_db_session`/`get_current_actor_id` を dep graph に含めない、R6+R7) → (b) custom ASGI streaming response を return** (resource 未取得)。custom response の `__call__` 内で **(i) capacity slot 非ブロッキング取得 (Semaphore/counter、満杯のみ 503+Retry-After、DB を触らず拒否 = R8) → (ii) slot 取得後に短命 session で run/active-scope preflight (scope 外 404) → (iii) LISTEN connection 取得 (短い正の timeout、`timeout=0` 禁止) → 200 SSE header (`text/event-stream` + `X-Accel-Buffering:no` + `Cache-Control:no-cache`) → LISTEN → catch-up → stream (tail/status は per-query 短命 session + concurrency cap) → (iv) finally で LISTEN release + slot 解放** を単一 try/finally に収める (R3 handoff leak 窓 + R8 preflight-before-capacity 枯渇を排除)。flag-off / 恒久停止は 204。
5. T4 config: `agentrun_sse_enabled` (default True) / `agentrun_sse_listen_pool_max` / `agentrun_sse_heartbeat_seconds` / `agentrun_sse_max_lifetime_seconds` / **`agentrun_sse_query_concurrency` (stream 由来 main query の同時実行 cap、R7)** / **`agentrun_sse_heartbeat_jitter_seconds` (R7)**。`listen_pool_max` は main pool 余力と独立に上げない制約を comment 明記。
6. T5 frontend: run 詳細を live 化。**fetch-based SSE client** で接続 (受信 `seq_no` を追跡 → 再接続時 `?last_event_id=` 付与)、`agent_run_event` / `agent_run_status` / `stream_end` / `agent_run_error` handling、指数バックオフ reconnect (503=backoff / 204=停止 / 400=resume reset)、SSE 無効時 (`sseEnabled=false`) static fallback。
7. T6/T7 test 群 (受け入れ条件に対応)。
8. Codex adversarial loop (mode=code) で R{N} clean (CRITICAL=0 / HIGH≤2) まで polish。
9. 実装後ブラウザ検証 (ADR-00038 §ブラウザ側検証必須項目 を 1 回でまとめ依頼)。

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| NOTIFY trigger + **LISTEN-before-catch-up + dirty-signal 再 query** + 全 DTO redaction + **stream 中 active-scope 再評価** + tenant 境界 | ✅ | |
| bounded LISTEN pool + **pre-response 予約 503** + bounded dirty-signal queue + disconnect cleanup | ✅ | |
| heartbeat + terminal close + max lifetime | ✅ | |
| frontend live run 詳細 + **fetch-based client (`?last_event_id=` resume + backoff + 204 停止)** + flag-off 非生成 fallback | ✅ | |
| 一覧 / dashboard realtime | | ✅ (follow-up) |
| 詳細な接続 metrics (Prometheus) | | ✅ (Sprint 11.5) |

## 受け入れ条件

- [ ] `agent_run_events` insert で `pg_notify` 発火 (DB test)。
- [ ] **(R9 HIGH)** `agent_runs` の status-only 更新 (event append 無し、例: MCP bridge cancel) でも `agent_runs` UPDATE trigger が `pg_notify` 発火し、SSE が heartbeat 待ちでなく dirty-signal で status を反映する (DB test + stream test)。
- [ ] SSE endpoint が `?last_event_id=N` で `seq_no>N` の redacted event のみ catch-up。
- [ ] stream payload に raw secret / raw payload が無い (redaction)。
- [ ] soft-deleted ticket bound run の stream は `404` (active-scope)。
- [ ] 別 tenant の run_id を stream できない (negative)。
- [ ] terminal run は `stream_end` で閉じ、再接続ループしない。
- [ ] LISTEN pool 上限超過で `503`。
- [ ] disconnect で LISTEN 接続が pool へ返却される (接続数 assert)。
- [ ] frontend が fetch-based SSE client で status/event を live 反映、SSE 無効時 static fallback。
- [ ] `alembic upgrade head` / `downgrade` lossless、event 行不変。
- [ ] AgentRun 16 状態 / event_type / ContextSnapshot 10 列の 5+ source 整合 test を壊さない。
- [ ] **(R1 CRITICAL)** LISTEN 登録と catch-up の境界で event を insert しても取りこぼさない (race 再現 test、wake-up ごとに `seq_no > last_sent` 再 query)。
- [ ] **(R1 HIGH)** stream 開始後に対象 ticket が soft-delete されたら `stream_end(scope_revoked)` で停止 (tail/status query に active-scope 組み込み)。
- [ ] **(R1 HIGH)** `agent_run_status` / `stream_end` / error payload に raw secret / raw payload / provider metadata / error_summary raw が乗らない (全 DTO redaction test)。
- [ ] **(R1 HIGH)** LISTEN pool 枯渇時に **stream 開始前に** HTTP 503 + Retry-After を返す (StreamingResponse 後の切断にしない)。
- [ ] **(R1 MEDIUM)** bounded dirty-signal queue (maxsize=1, coalesce)、overflow しても `seq_no > last_sent` 再 query で回復。
- [ ] **(R1 MEDIUM)** flag-off で frontend が SSE client を生成せず reconnect ループしない。
- [ ] **(R2 HIGH)** event を一切 append せず ticket を soft-delete → heartbeat 以内に `stream_end(scope_revoked)` (idle scope 失効)。
- [ ] **(R2 HIGH)** 1 dirty-signal に対し tail limit N 超の burst → drain-to-empty で全 `seq_no` を漏れなく配信。
- [ ] **(R2 HIGH)** SSE frame `id:` は `agent_run_event` のみ `seq_no`、`agent_run_status`/`stream_end`/`agent_run_error` は `id:` を出さない。UUID/非整数 `?last_event_id=` は deps で `400` reject。
- [ ] **(R2 HIGH)** stream 開始後の例外は `agent_run_error` (reason/retryable/correlation_id のみ、exception message/SQL detail なし) で閉じる (無言切断 reconnect storm にしない)。
- [ ] **(R2 HIGH)** generator factory 例外 / 初回 yield 前 cancel / response 構築失敗で LISTEN pool 使用数が戻る (leak なし、恒久 503 防止)。
- [ ] **(R3 HIGH)** client SSE wrapper: pool 枯渇 (`503`) で tight reconnect せず指数バックオフ / 恒久停止 (`204`) で再接続停止。
- [ ] **(R3 HIGH)** acquire/release を custom ASGI response の単一 `__call__` try/finally に収め、return 後・初回 iteration 前の client abort でも LISTEN pool 使用数が戻る。
- [ ] **(R4 HIGH)** fetch-based SSE client が切断後 `?last_event_id=<last seq_no>` 付きで再接続し欠落なく resume (seq 0 全再送にならない)。`?last_event_id=` 非整数/UUID は server が `400` reject。
- [ ] **(R4 HIGH)** rollback flag-off で server が `204` を返し、既にロード済の stale client が再接続を停止する (404 で error ループにしない)。
- [ ] **(R6 HIGH)** N 本の SSE stream を開いたまま通常 AgentRun detail/list が main DB connection を取得できる (preflight session が stream lifetime に保持されず、main transactional pool が枯渇しない)。
- [ ] **(R7 HIGH)** stream route の dependency graph に `get_db_session` / `get_current_actor_id` を含まない (sessionless auth、test/静的検査)。
- [ ] **(R7 HIGH)** N 本 stream を **同時 notify/heartbeat で起こした状態でも** 通常 detail/list が main pool を取得できる (stream 由来 query の concurrency cap + heartbeat jitter)。
- [ ] **(R8 HIGH)** M > listen_pool_max の **同時 open storm (拒否される要求を含む)** でも通常 detail/list が main pool を取得できる (capacity slot を DB preflight より前に gate、503 拒否要求は main pool を一切 checkout しない)。

## 検証手順

- Backend: `uv run ruff check backend tests` + `uv run mypy backend` + `uv run pytest tests/api/test_agent_run_stream.py` + `TASKMANAGEDAI_RUN_DB_TESTS=1` で trigger/migration DB test。
- DB: `uv run alembic upgrade head` (fresh DB) + `downgrade` + `alembic check`。
- Frontend: `cd frontend && pnpm exec eslint . --max-warnings=0` + `pnpm typecheck` + Vitest SSE client test。
- regression: fresh DB + main 比較で既存 test の test-isolation hygiene 起因 failure と切り分け。
- ブラウザ: ADR-00038 §ブラウザ側検証必須項目 (4 項目、~15 分、1 回まとめ依頼)。

## レビュー観点

- SSE が read-only であり AgentRun state machine / event append に副作用を持たないこと。
- redaction (`_to_event_read`) を共用し raw payload を stream に乗せないこと。
- tenant + active-scope を stream open 時に enforce すること。
- LISTEN 接続が finally で確実に返却され、pool 枯渇 / leak が無いこと。
- NOTIFY trigger が additive で event schema を変えず、downgrade が lossless であること。
- core enum (16 状態 / event_type / 10 列) を増やしていないこと。

## 残リスク

- proxy buffering (Tailscale Serve / Next.js) はコードだけで確証できず、ブラウザ検証必須 (ADR-00038 リスク表)。
- 同時 stream が増えた場合の DB query 負荷は P0 (単一 user) では軽微だが、商用化時は notify coalescing / 一覧 fan-out 再設計が要る (follow-up)。
- asyncpg listener bridge は test で接続返却を assert するが、長時間運用での leak は運用監視に依存 (Sprint 11.5 metrics)。

## 次スプリント候補

- runs 一覧 / dashboard の realtime 化 (同 architecture 拡張)。
- 接続 metrics (Prometheus) + notify coalescing。

## 関連 ADR

- [ADR-00038](../adr/00038_agentrun_realtime_sse.md) (本 Sprint の design 正本)
- [ADR-00037](../adr/00037_data_management.md) (active-scope helper 由来)

## Review

(実装後に追記: ADR-00038 accepted_at / Codex R{N} 採否 / 検証結果 / 残リスク)
