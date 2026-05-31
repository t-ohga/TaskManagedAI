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
- 理由: 新 infra を足さず (既存 PostgreSQL のみ)、event-append を単一 source of truth に保ったまま push 型 realtime を実現する。DB trigger は append 経路 (repository / 将来の別 writer) を問わず全 insert を捕捉するため、notify の漏れが構造的に起きない。SSE は P0 の閉域 HTTP 境界 (DD-05) と最も整合し、EventSource の標準機能 (auto-reconnect / `Last-Event-ID`) で resume を堅牢化できる。
- 実装 Sprint: SP-0046_agentrun_realtime_sse。

### 採用 architecture の堅牢化要件 (must_ship)

1. **NOTIFY trigger (migration, additive)**: `agent_run_events` に `AFTER INSERT` trigger を追加し、`pg_notify('agent_run_event_appended', json_build_object('tenant_id', NEW.tenant_id, 'run_id', NEW.run_id, 'seq_no', NEW.seq_no)::text)` を発火。payload は最小 (8KB NOTIFY 上限に余裕)。event schema / 列は変更しない。downgrade は trigger + function を drop するだけの lossless。
2. **LISTEN-before-catch-up + dirty-signal 再 query + drain-to-empty (R1 CRITICAL + R2 HIGH fix)**: 順序は (1) `LISTEN agent_run_event_appended` を先に登録 → (2) `Last-Event-ID` header (client が最後に受けた `seq_no`、default 0) を読み `seq_no > last` を catch-up query → (3) 以後 wake-up ごとに **必ず `seq_no > last_sent` を DB 再 query** する。notify payload を直接 stream に乗せず、dirty-signal (再 query 契機) としてのみ扱う。これにより catch-up/LISTEN 境界で insert された event の取りこぼし (CRITICAL race) と NOTIFY 取りこぼしの両方を、DB query を真の source として構造的に吸収する。
   - **drain-to-empty (R2 HIGH fix)**: tail query は `seq_no > last_sent ORDER BY seq_no LIMIT N` を使うが、1 つの dirty-signal / catch-up につき **取得件数 < N になるまで loop で drain** する。queue が maxsize=1 で coalesce され、1 signal あたり N 超の event が溜まっても、全 `seq_no` を漏れなく配信してから wait に戻る (burst > N でも event 落とさない)。
3. **専用 bounded LISTEN pool + single-scope acquire/release (custom ASGI response、R1 HIGH + R2 HIGH + R3 HIGH fix)**: LISTEN は接続を stream 持続中保持するため、transactional session pool と分離した **専用 asyncpg pool** (例: max 10) を使う。
   - **validation/auth/scope は FastAPI deps で response 前に確定**: Last-Event-ID は整数 `seq_no` のみ受理 (非整数/UUID は `400/422`、acquire しない) / auth + active-scope (`404`) + tenant 照合。
   - **acquire と release を custom ASGI streaming response の単一 `__call__` 内 try/finally に収める (R3 HIGH fix)**: endpoint は (deps 通過後) custom response を return するだけ。response の `__call__(scope, receive, send)` 内で **(i) `pool.acquire(timeout=0)` → 枯渇なら `503` + `Retry-After` を `__call__` 内から送出して return、(ii) 成功なら 200 SSE header 送出 → LISTEN → catch-up → stream、(iii) `finally` で listener remove + connection release**。`StreamingResponse` factory への pre-response handoff (return 後〜body iterator 開始前に cancel されると generator `finally` が走らない leak 窓) を構造的に排除する。`__call__` に入った後の cancel は `await` を貫通して `finally` に到達するため release が保証される。
4. **listener → async generator bridge (bounded dirty-signal queue、R1 MEDIUM fix)**: `asyncio.Queue(maxsize=1)` を **dirty-signal** として使う。`add_listener` callback は payload の `tenant_id` + `run_id` を **両方** 照合し対象 run のみ `queue.put_nowait(None)` (full なら無視 = coalesce、payload を蓄積しない)。generator は `asyncio.wait_for(queue.get(), timeout=heartbeat)` で待機し、wake-up 時に DB 再 query (#2)。これにより無関係 notify の蓄積も、遅い client での queue 肥大も起きない (overflow しても次の DB query で回復)。
5. **heartbeat + idle scope 再検証 (R2 HIGH fix)**: 約 15s の heartbeat timeout ごとに、keepalive (`: keepalive\n\n`) 送信前に **active-scope + status を再 query** する。NOTIFY 源は `agent_run_events` insert のみであり、ticket/project の soft-delete は event insert を伴わないため、idle (新 event 無し) stream では heartbeat が唯一の scope 再評価契機になる。これにより event を一切 append しなくても **heartbeat 以内に `stream_end(scope_revoked)`** を満たす。terminal 検知も同様に heartbeat 再 query で拾う。
6. **terminal close**: run が terminal (`completed`/`failed`/`cancelled`/`provider_refused`/`repair_exhausted`) に達したら最終 status を流して `event: stream_end` で正常終了する (無限保持しない)。
7. **max stream lifetime**: 上限 (例: 30 分) で server 側から close、client は `Last-Event-ID` 付きで自動再接続 → 長時間接続の滞留を防ぐ。
8. **disconnect cleanup**: `request.is_disconnected()` / asyncio cancellation で LISTEN 接続を確実に pool へ返却。
9. **SSE 全 DTO allowlist + SSE framing contract + redaction (R1 HIGH + R2 HIGH fix)**: stream する **全 message 種別ごとに送信 DTO を明示** し、それ以外の AgentRun 本体 field を絶対に乗せない:
   - `agent_run_event`: id (UUID) は **`event_id` に rename**、`seq_no` / `event_type` / `actor_id` / `payload_keys` のみ / `payload_redaction_status` (`_to_event_read` ベース)。raw payload を含めない。
   - `agent_run_status`: 最小 allowlist (`status` / `blocked_reason` / `terminal` (bool) / `completed_at` / `error_code`) のみ。`error_summary` raw / provider metadata / input-output summary / cost 内訳は **乗せない** (status snapshot 経路が `_to_event_read` を通らず漏洩する R1 HIGH を塞ぐ)。
   - `stream_end`: `reason` enum (`terminal` / `scope_revoked` / `max_lifetime` / `server_shutdown`) のみ。
   - **`agent_run_error` (R2 HIGH fix)**: stream 開始後の DB/query/listener 例外は HTTP status で表せないため専用 DTO を定義。`reason` enum + `retryable` (bool) + `request_id` / `correlation_id` のみ。**exception message / SQL detail / provider metadata / error_summary raw を禁止**。無言切断 (reconnect storm) でなく `agent_run_error` → `stream_end` で閉じる。
   - **SSE framing contract (R2 HIGH fix)**: SSE frame の `id:` は **`agent_run_event` のみが `seq_no` を出す**。`agent_run_status` / `stream_end` / `agent_run_error` は `id:` を出さない (browser が status/error の id を `Last-Event-ID` として返さない)。`Last-Event-ID` は整数 `seq_no` のみ受理し、非整数 / UUID は pool acquire 前に `400/422` で reject (resume parse 失敗・重複再送・欠落を防ぐ)。
   - redaction test は `agent_run_event` に限らず `agent_run_status` / `stream_end` / `agent_run_error` を含む **全 DTO** に広げる。
10. **stream 中 active-scope 再評価 (R1 HIGH fix)**: active-scope は open 時だけでなく、catch-up / 各 wake-up の tail・status query 自体に `soft_deleted_ticket_run_exclusion()` を組み込む。stream 開始後に対象 ticket が soft-delete され scope 外になったら、即時に `stream_end` (`reason=scope_revoked`) で stream を終了する (削除済み scope の event/status をライブ配信し続けない)。
11. **proxy buffering 無効化**: response に `Cache-Control: no-cache` / `X-Accel-Buffering: no` / `Content-Type: text/event-stream` を付与。Next.js proxy と Tailscale Serve が SSE を buffer せず pass-through することを検証する (検証項目、後述リスク)。
12. **client 側 reconnect 制御 (EventSource wrapper、R1 MEDIUM + R3 HIGH fix)**: native EventSource は失敗した HTTP response の status/body を app に渡さず自動再接続を続けるため、HTTP 400/503 だけでは reconnect storm を防げない (invalid resume 値ループ / 容量不足で auth/scope を叩き続ける)。client 側で storm を止める:
   - **EventSource wrapper**: `onerror` で即 `close()` し、**app 管理の指数バックオフ (jitter 付き) + 最大試行回数 + 上限到達で停止 UI**。native の無制限 auto-reconnect に依存しない。
   - **resume reset**: catch-up parse 失敗 / 一定回数連続失敗で、`Last-Event-ID` を捨てて fresh EventSource (seq 0 から catch-up) で復旧。invalid `Last-Event-ID` の永久ループを断つ。
   - **server stop semantics**: flag-off / 恒久停止は server が **`204`** を返す (EventSource は 204 で **再接続を停止** する spec 動作)。transient (`503`) は wrapper のバックオフで間隔を空ける。
   - **flag-off 一次防御**: SSR の `sseEnabled=false` なら wrapper を **生成しない** (static fallback)。
   - 受け入れ条件: flag-off 非生成 / pool 枯渇 (`503`) で tight reconnect しない (バックオフ) / invalid `Last-Event-ID` で永久ループしない (reset) / 恒久停止 (`204`) で再接続停止。

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
  - **R1 追加 (must_ship)**: catch-up/LISTEN 境界 race 再現 (LISTEN 登録と catch-up の間に event insert → 取りこぼさない) / soft-delete 後 stream が `scope_revoked` で停止 / `agent_run_status` + `stream_end` の redaction (raw payload/secret なし) / pool 枯渇で HTTP 503 (stream 開始前) / bounded queue overflow 後も `seq_no > last_sent` で回復 / flag-off で frontend が EventSource 非生成・reconnect しない。
  - **R2 追加 (must_ship)**: event を一切 append せず ticket soft-delete → heartbeat 以内に `stream_end(scope_revoked)` / 1 dirty-signal に N 超 burst → drain-to-empty で全 `seq_no` 配信 / SSE `id:` は `agent_run_event` のみ seq_no・status/error は id なし / UUID や非整数 `Last-Event-ID` を pool acquire 前に 400 reject / stream 開始後 error は `agent_run_error` (reason/retryable/correlation_id のみ、exception message なし) で閉じる / generator factory 例外・初回 yield 前 cancel・response 構築失敗で LISTEN pool 使用数が戻る。
  - **R3 追加 (must_ship)**: client EventSource wrapper が pool 枯渇 (`503`) で tight reconnect せず指数バックオフ / invalid `Last-Event-ID` で永久ループせず resume reset / 恒久停止 (`204`) で再接続停止 (frontend Vitest) / custom ASGI response の `__call__` return 後・初回 iteration 前の client abort で LISTEN pool 使用数が戻る (backend、ASGI scope cancel 再現)。

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
   - 即時: feature flag (env `AGENTRUN_SSE_ENABLED=false`)。SSR の `sseEnabled=false` により frontend は **EventSource を生成せず** static SSR + 手動更新に fallback する (R1 MEDIUM fix: server が 404 を返しても client が開かないので reconnect storm にならない)。endpoint 自体も flag-off で 404 を返す (二重防御、機能停止のみ・データ影響なし)。
   - schema 戻し: `alembic downgrade -1` で `0041` の NOTIFY trigger + function を drop。trigger は additive かつ event data に触れないため **lossless** (event 行は不変、downgrade で realtime が止まるだけ)。
3. verification after rollback: run 詳細が static で正しく表示される / `alembic check` clean / `agent_run_events` 件数・内容が rollback 前後で不変 (trigger は read-only side-effect のみ) / frontend が EventSource を開かない (Network tab に `text/event-stream` 接続が出ない) / endpoint が flag-off で 404。

## ブラウザ側検証必須項目 (実装後、所要 ~15 分)

> 実装完了後に 1 回でまとめて依頼する (CLAUDE.md ブラウザ側検証依頼ルール準拠)。詳細手順は Sprint Pack 検証手順に記載。

1. 進行中 run の `/runs/[id]` で、別経路で event が append された時に **リロードなしで** status バッジ + event tail が更新される (DevTools Network で `text/event-stream` 接続が 1 本維持、buffer されず逐次 `data:` 到達)。
2. terminal 到達で stream が `stream_end` で閉じ、再接続ループしない。
3. 接続を一時切断→復帰で `Last-Event-ID` 付き再接続が起き、切断中の event が catch-up で漏れなく表示。
4. Console error 0 (hydration / EventSource error の有無)。
