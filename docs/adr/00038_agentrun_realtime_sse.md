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

- ★ **transport = SSE** (Server-Sent Events): 進捗は server→client の **一方向 push** で十分。SSE は HTTP/1.1 上で動き Tailscale Serve / Next.js proxy を upgrade 交渉なしにそのまま通る。EventSource が auto-reconnect + `Last-Event-ID` resume を標準提供する。双方向が要る操作 (cancel 等) は既存の POST endpoint を使う。
- ★ **event 検知 = PostgreSQL LISTEN/NOTIFY** (push 型、新 infra なし): 「最善で最も品質の良いもの」(user design approval, 2026-06-01) として、poll ではなく **event-driven push** を採用。`agent_run_events` の `AFTER INSERT` trigger が `pg_notify` を発火し、SSE handler が専用接続で `LISTEN` する。単一 source of truth (PostgreSQL) のまま低 latency を得る。Redis を event-append path に挟まない。
- ★ **scope = run 詳細画面** (`/runs/[id]`): live status + live event tail。runs 一覧 / dashboard の realtime 化は本 ADR の採用 architecture (SSE + NOTIFY) を自然に拡張できるため **follow-up** とし、最初の高品質 delivery を run 詳細に集中する。
- ★ **status 変化も event-append notify 1 channel で検知**: rules/agentrun-state-machine.md §5「status update と AgentRunEvent append は同一 transaction」を前提に、event append を 1 つの notify channel とし、handler は notify 受信時に「新 event tail + 現在の run status snapshot」を再 query して stream する。status 専用 channel を増やさない。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| **A: SSE + PostgreSQL LISTEN/NOTIFY (採用)** | `AFTER INSERT` trigger で `pg_notify`、SSE handler が専用 asyncpg 接続で LISTEN、catch-up + push stream | push 型で低 latency / 新 infra 不要 (既存 Postgres) / 単一 source of truth / poll 負荷なし / append 経路を問わず trigger が全 insert 捕捉 | stream ごとに LISTEN 用 dedicated 接続が要る (接続上限管理) / asyncpg listener → async generator の bridge 実装 / proxy buffering 無効化が必要 |
| B: SSE + DB-poll | SSE handler が `seq_no > last` を ~1-2s 間隔で poll | 実装最小 / 接続 1 本 (session pool 利用) | latency = poll 間隔 / 進行中 run × stream 数だけ周期 query / 「event-driven」でなく最善でない |
| C: SSE + Redis pub/sub | event append で Redis publish、SSE subscribe | 低 latency / 一覧 fan-out 拡張容易 | event-append critical path に Redis 依存追加 / publish の transactional 整合 (DB commit と Redis publish の二重書き) が難しく、source of truth が二重化 |
| D: WebSocket | 双方向 WS | 双方向 | 一方向 progress に over-spec / Tailscale Serve + Next 経由の WS upgrade 交渉が SSE より複雑 / auto-reconnect/resume を自前実装 |

## 採用案

- 採用: **A (SSE + PostgreSQL LISTEN/NOTIFY)**。
- 理由: 新 infra を足さず (既存 PostgreSQL のみ)、event-append を単一 source of truth に保ったまま push 型 realtime を実現する。DB trigger は append 経路 (repository / 将来の別 writer) を問わず全 insert を捕捉するため、notify の漏れが構造的に起きない。SSE は P0 の閉域 HTTP 境界 (DD-05) と最も整合し、EventSource の標準機能 (auto-reconnect / `Last-Event-ID`) で resume を堅牢化できる。
- 実装 Sprint: SP-0046_agentrun_realtime_sse。

### 採用 architecture の堅牢化要件 (must_ship)

1. **NOTIFY trigger (migration, additive)**: `agent_run_events` に `AFTER INSERT` trigger を追加し、`pg_notify('agent_run_event_appended', json_build_object('tenant_id', NEW.tenant_id, 'run_id', NEW.run_id, 'seq_no', NEW.seq_no)::text)` を発火。payload は最小 (8KB NOTIFY 上限に余裕)。event schema / 列は変更しない。downgrade は trigger + function を drop するだけの lossless。
2. **catch-up-on-connect (Last-Event-ID resume)**: handler は接続時に `Last-Event-ID` header (client が最後に受けた `seq_no`、default 0) を読み、`seq_no > last` の event を redacted shape で先に流し切ってから LISTEN に入る。これにより接続前 / 切断中に発生した event の取りこぼしを構造的に防ぐ (NOTIFY 取りこぼしも catch-up query が吸収する)。
3. **専用 bounded LISTEN pool + 上限**: LISTEN は接続を stream 持続中保持するため、transactional session pool と分離した **専用 asyncpg pool** (例: max 10) を使う。上限到達時は `503` (retry-after) で reject し、main pool 枯渇を防ぐ。同時 stream 数を bound する。
4. **listener → async generator bridge**: `asyncio.Queue` を介す。`add_listener` callback が `queue.put_nowait(payload)`、generator は `asyncio.wait_for(queue.get(), timeout=heartbeat)` で待機。payload の `tenant_id` + `run_id` を **両方** 照合し、対象 run のみ反応 (UUID 衝突想定でも tenant 境界を二重に enforce)。
5. **heartbeat**: 約 15s ごとに SSE comment (`: keepalive\n\n`) を送り、proxy の idle timeout 回避 + 死活検知。
6. **terminal close**: run が terminal (`completed`/`failed`/`cancelled`/`provider_refused`/`repair_exhausted`) に達したら最終 status を流して `event: stream_end` で正常終了する (無限保持しない)。
7. **max stream lifetime**: 上限 (例: 30 分) で server 側から close、client は `Last-Event-ID` 付きで自動再接続 → 長時間接続の滞留を防ぐ。
8. **disconnect cleanup**: `request.is_disconnected()` / asyncio cancellation で LISTEN 接続を確実に pool へ返却。
9. **redaction 再利用**: stream する event は `_to_event_read` (payload_keys のみ / `blocked_by_secret_scan` redaction status) を共用。raw payload / raw secret を絶対に stream に乗せない。
10. **proxy buffering 無効化**: response に `Cache-Control: no-cache` / `X-Accel-Buffering: no` / `Content-Type: text/event-stream` を付与。Next.js proxy と Tailscale Serve が SSE を buffer せず pass-through することを検証する (検証項目、後述リスク)。

- 実装対象ファイル:
  - `migrations/versions/0041_agent_run_event_notify_trigger.py` (NOTIFY trigger + function、additive、両方向)
  - `backend/app/services/realtime/agent_run_stream.py` (LISTEN pool 管理 + SSE event generator + catch-up + redaction 共用)
  - `backend/app/api/agent_runs.py` (`GET /{run_id}/events/stream` SSE endpoint 追加。既存 auth deps + `soft_deleted_ticket_run_exclusion()` 再利用)
  - `backend/app/config.py` (LISTEN pool max / heartbeat interval / max stream lifetime / SSE enabled flag)
  - `frontend/app/(admin)/runs/[id]/` (run 詳細を live 化する Client Component。EventSource で status/events 反映、terminal/error/reconnect handling)
  - `tests/api/test_agent_run_stream.py` / `tests/realtime/…` (contract + negative)
- 実装ガイダンス:
  - SSE endpoint は **read-only** (mutation なし)。AgentRun status / event の append は既存経路のみが行い、stream は観測専用。
  - tenant / active-scope を最初に enforce (`soft_deleted_ticket_run_exclusion()`)、対象 run が無ければ stream を開かず `404`。
  - feature flag (env、default on) で endpoint を無効化可能にし、無効時 frontend は static SSR + 手動更新に fallback (rollback path)。
  - audit: stream open/close は AgentRunEvent / audit を増やさない (read であり状態遷移ではない)。必要なら structured log の correlation_id のみ。
- テスト指針:
  - `uv run pytest tests/api/test_agent_run_stream.py`
  - catch-up: `Last-Event-ID=N` で `seq_no>N` のみ流れる。
  - redaction: stream payload に raw secret / raw payload が無い (`assert_no_raw_secret` 相当)。
  - active-scope: soft-deleted ticket bound run の stream は `404`。
  - tenant isolation: 別 tenant の run_id を stream できない (negative)。
  - terminal close: terminal run は `stream_end` で閉じる。
  - bound: LISTEN pool 上限超過で `503`。
  - trigger: `agent_run_events` insert で `pg_notify` が発火する (DB test、`TASKMANAGEDAI_RUN_DB_TESTS=1`)。
  - migration: `alembic upgrade head` → trigger 存在、`downgrade` → trigger/function drop の lossless。
  - frontend: EventSource mock で status/event 反映 + reconnect (Vitest)。

## 却下案

- **B (SSE + DB-poll)**: 実装は最小だが、latency が poll 間隔に律速され、進行中 run × stream 数だけ周期 query が走る。user の「最善で最も品質の良いもの」要求に対し event-driven でない点で劣る。NOTIFY が新 infra を要さず P0 で十分機能するため、poll を採る理由がない。
- **C (SSE + Redis pub/sub)**: event-append という critical path に Redis publish を挟むと、DB commit と Redis publish の二重書きで transactional 整合が崩れる余地が生じ (publish 漏れ / commit rollback 後の幽霊 publish)、source of truth が二重化する。DB trigger NOTIFY は同一 transaction 内で commit と原子的に整合し、この問題が無い。一覧 fan-out が必要になった段階でも NOTIFY 拡張で対応可能。
- **D (WebSocket)**: 一方向 progress に双方向 transport は over-spec。Tailscale Serve + Next.js 経由の WS upgrade 交渉は SSE の素の HTTP より複雑で、auto-reconnect / resume を自前実装する負担も増える。P0 の閉域 HTTP 境界との適合は SSE が勝る。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| LISTEN 接続が main pool を枯渇させる | 接続数監視 / pool timeout エラー | 専用 bounded asyncpg pool (max N) に分離 + 上限超過 `503` + max stream lifetime で滞留防止 |
| reverse proxy (Tailscale Serve / Next.js) が SSE を buffer し realtime にならない | ブラウザ検証で event 到達が遅延/まとめ届き | `X-Accel-Buffering: no` + `Cache-Control: no-cache` + Next.js streaming response 確認。**ブラウザ側検証必須項目** (後述) |
| NOTIFY 取りこぼし (接続断中の event) | catch-up query との突合 test | `Last-Event-ID` catch-up query が接続時に欠落分を必ず補填する設計 (NOTIFY は「起こせ」信号、真の source は DB query) |
| asyncpg listener → generator bridge の leak / 例外で接続返却漏れ | 接続数が減らない / pool 枯渇 | `try/finally` で remove_listener + 接続 return、disconnect 検知で確実に cleanup、test で接続返却を assert |
| NOTIFY payload 8KB 上限 | trigger で大 payload を送ると失敗 | payload は `{tenant_id, run_id, seq_no}` のみ (数十 bytes)。event 本体は handler が query |
| stream に raw payload/secret が漏れる | redaction test / `assert_no_raw_secret` | `_to_event_read` (payload_keys のみ) を共用、raw payload を stream に乗せる経路を作らない |
| 多数 client が同 run を stream し DB query 増 | query 数監視 | notify 1 回につき軽量 tail query (limit), heartbeat で idle、上限 bound |
| AgentRun 16 状態 / event_type を誤って拡張 | enum 5+ source 整合 test | SSE は transport であり enum を増やさない。migration は trigger のみ (event schema 不変)、CI enum drift test で担保 |

## rollback 手順

1. rollback trigger: SSE endpoint で接続滞留 / pool 枯渇 / proxy buffering 未解決 / realtime が不安定。
2. rollback step:
   - 即時: feature flag (env `AGENTRUN_SSE_ENABLED=false`) で endpoint を無効化 → frontend は static SSR + 手動更新に自動 fallback (機能停止のみ、データ影響なし)。
   - schema 戻し: `alembic downgrade -1` で `0041` の NOTIFY trigger + function を drop。trigger は additive かつ event data に触れないため **lossless** (event 行は不変、downgrade で realtime が止まるだけ)。
3. verification after rollback: run 詳細が static で正しく表示される / `alembic check` clean / `agent_run_events` 件数・内容が rollback 前後で不変 (trigger は read-only side-effect のみ) / SSE endpoint が無効化され 404 or 503 を返す。

## ブラウザ側検証必須項目 (実装後、所要 ~15 分)

> 実装完了後に 1 回でまとめて依頼する (CLAUDE.md ブラウザ側検証依頼ルール準拠)。詳細手順は Sprint Pack 検証手順に記載。

1. 進行中 run の `/runs/[id]` で、別経路で event が append された時に **リロードなしで** status バッジ + event tail が更新される (DevTools Network で `text/event-stream` 接続が 1 本維持、buffer されず逐次 `data:` 到達)。
2. terminal 到達で stream が `stream_end` で閉じ、再接続ループしない。
3. 接続を一時切断→復帰で `Last-Event-ID` 付き再接続が起き、切断中の event が catch-up で漏れなく表示。
4. Console error 0 (hydration / EventSource error の有無)。
