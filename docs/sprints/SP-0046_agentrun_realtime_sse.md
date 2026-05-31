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
| transport | SSE | 一方向 push / HTTP / Tailscale Serve ネイティブ / auto-reconnect / Last-Event-ID |
| event 検知 | PostgreSQL LISTEN/NOTIFY (AFTER INSERT trigger) | push 型 / 新 infra なし / 単一 source of truth / append 経路非依存 |
| catch-up | Last-Event-ID + `seq_no>last` query | NOTIFY 取りこぼし / 接続断中 event を構造的に吸収 |
| 接続管理 | 専用 bounded asyncpg pool + 上限 503 | main session pool 枯渇防止 |
| redaction | `_to_event_read` (payload_keys のみ) 共用 | raw payload / secret 非露出 |
| scope 境界 | `soft_deleted_ticket_run_exclusion()` + tenant | 全 read path active-scope (ADR-00037) と整合 |

## 実装チケット

| ID | 内容 | 主ファイル |
|---|---|---|
| T1 | NOTIFY trigger migration (additive, 両方向 lossless) | `migrations/versions/0041_agent_run_event_notify_trigger.py` |
| T2 | LISTEN pool + SSE event generator + catch-up + redaction 共用 | `backend/app/services/realtime/agent_run_stream.py` |
| T3 | SSE endpoint `GET /{run_id}/events/stream` (auth + active-scope + 404) | `backend/app/api/agent_runs.py` |
| T4 | config (pool max / heartbeat / max lifetime / enabled flag) | `backend/app/config.py` |
| T5 | frontend live Client Component (EventSource / status・events 反映 / reconnect / terminal) | `frontend/app/(admin)/runs/[id]/` |
| T6 | backend contract + negative test | `tests/api/test_agent_run_stream.py` |
| T7 | frontend EventSource test (Vitest) | `frontend/app/(admin)/runs/[id]/__tests__/` |

## タスク一覧

1. ADR-00038 proposed → accepted 昇格 (codex-plan-review R1 + 採否判定後、実装着手直前)。
2. T1 migration: `AFTER INSERT ON agent_run_events` trigger + function、`pg_notify('agent_run_event_appended', json{tenant_id,run_id,seq_no})`。upgrade で create、downgrade で drop。`alembic upgrade head` / `downgrade` を fresh DB で確認。
3. T2 stream service: bounded asyncpg pool (lazy init)、`listen_run(tenant_id, run_id, last_event_id)` async generator、catch-up query → LISTEN bridge (asyncio.Queue) → heartbeat → terminal close → finally cleanup。
4. T3 endpoint: `StreamingResponse(media_type="text/event-stream")` + `X-Accel-Buffering:no` / `Cache-Control:no-cache`。auth deps 再利用、active-scope 404、tenant + run_id 二重照合。
5. T4 config: `agentrun_sse_enabled` (default True) / `agentrun_sse_listen_pool_max` / `agentrun_sse_heartbeat_seconds` / `agentrun_sse_max_lifetime_seconds`。
6. T5 frontend: run 詳細を live 化。EventSource 接続、`agent_run_event` / `agent_run_status` / `stream_end` handling、reconnect、SSE 無効時 static fallback。
7. T6/T7 test 群 (受け入れ条件に対応)。
8. Codex adversarial loop (mode=code) で R{N} clean (CRITICAL=0 / HIGH≤2) まで polish。
9. 実装後ブラウザ検証 (ADR-00038 §ブラウザ側検証必須項目 を 1 回でまとめ依頼)。

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| NOTIFY trigger + catch-up + redaction + active-scope + tenant 境界 | ✅ | |
| bounded LISTEN pool + 上限 503 + disconnect cleanup | ✅ | |
| heartbeat + terminal close + max lifetime | ✅ | |
| frontend live run 詳細 + reconnect + fallback | ✅ | |
| 一覧 / dashboard realtime | | ✅ (follow-up) |
| 詳細な接続 metrics (Prometheus) | | ✅ (Sprint 11.5) |

## 受け入れ条件

- [ ] `agent_run_events` insert で `pg_notify` 発火 (DB test)。
- [ ] SSE endpoint が `Last-Event-ID=N` で `seq_no>N` の redacted event のみ catch-up。
- [ ] stream payload に raw secret / raw payload が無い (redaction)。
- [ ] soft-deleted ticket bound run の stream は `404` (active-scope)。
- [ ] 別 tenant の run_id を stream できない (negative)。
- [ ] terminal run は `stream_end` で閉じ、再接続ループしない。
- [ ] LISTEN pool 上限超過で `503`。
- [ ] disconnect で LISTEN 接続が pool へ返却される (接続数 assert)。
- [ ] frontend が EventSource で status/event を live 反映、SSE 無効時 static fallback。
- [ ] `alembic upgrade head` / `downgrade` lossless、event 行不変。
- [ ] AgentRun 16 状態 / event_type / ContextSnapshot 10 列の 5+ source 整合 test を壊さない。

## 検証手順

- Backend: `uv run ruff check backend tests` + `uv run mypy backend` + `uv run pytest tests/api/test_agent_run_stream.py` + `TASKMANAGEDAI_RUN_DB_TESTS=1` で trigger/migration DB test。
- DB: `uv run alembic upgrade head` (fresh DB) + `downgrade` + `alembic check`。
- Frontend: `cd frontend && pnpm exec eslint . --max-warnings=0` + `pnpm typecheck` + Vitest EventSource test。
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
