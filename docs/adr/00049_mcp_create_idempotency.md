---
id: "ADR-00049"
title: "MCP create idempotency (ticket_create / run_create の retry 重複防止、SP-034 gap)"
status: "accepted"
date: "2026-06-05"
accepted_at: "2026-06-05"
deciders: ["t-ohga"]
adr_gate_criteria: [2, 3]
related_adr:
  - "ADR-00026 (MCP Server Gateway / SP-034 の正本、本 ADR はその idempotency acceptance gap を塞ぐ)"
  - "ADR-00041 (N-1/N-2 / repository choke point で MCP 経路も封鎖する先例)"
related_dd:
  - "DD-02 (データモデル / tenant・project 境界、actor / principal 分離)"
  - "DD-03 (AI オーケストレーション / AgentRun 作成 chokepoint)"
related_sprints:
  - "SP-034_mcp_server_gateway (partial_skeleton。本 ADR は idempotency acceptance の設計 = planned/blocking follow-up、proposed・未実装)"
supersedes: null
superseded_by: null
---

# ADR-00049: MCP create idempotency (ticket_create / run_create の retry 重複防止、SP-034 gap)

最終更新: 2026-06-05

## 背景

2026-06-04 の Sprint Pack 台帳監査 (PR #321) + Codex CLI F-L4 で、**SP-034 MCP Server Gateway の
受け入れ条件「`ticket_create` / `run_create` の idempotency_key で retry 重複防止」(SP-034 Pack 行
113/114/175/183) が未達**であることが実コードで確定した:

- `backend/app/mcp/server.py:297` の `ticket_create` は `idempotency_key: str | None = None` を受けるが、
  docstring「idempotency_key で重複防止」に反し `bridge_ticket_create` に**渡していない (dead param)**。
  `run_create` も同様に `bridge_run_create` へ渡していない。
- `bridge_ticket_create` / `bridge_run_create` (AgentRun / ticket 作成の chokepoint) も idempotency 引数を
  持たない。`tickets` table に idempotency column は無い。
- 結果、**MCP client の retry (network 再送 / timeout 再試行) で duplicate ticket / duplicate AgentRun が
  作成可能**。これは AI が自動で MCP tool を叩く本プロダクトで、二重 run = 二重 provider call = 二重
  コスト + 二重 artifact という integrity / cost 問題に直結する。

なお `agent_run_events` には `(tenant_id, run_id, idempotency_key)` の **event-level** idempotency
(migration 0008) があるが、これは run 内の event 重複防止であり、**run / ticket の作成-level idempotency
ではない**。

## 決定対象

MCP create 系 tool (`ticket_create` / `run_create`) に **作成-level idempotency** を導入し、同一
idempotency_key の再送が新規作成ではなく既存 resource を返すようにする。SP-034 行 183 の spec に従い
`(tenant_id, actor_id, tool_name, idempotency_key)` で bind し cross-actor replay を deny する。

## 前提 / 制約

- P0/P0.1 invariant 不変 (AgentRun 16 status / blocked_reason 3 / ContextSnapshot 10 / 複合 FK)。
- **DB migration を伴う (ADR Gate #2)**: 新 `mcp_idempotency_keys` table (additive、downgrade lossless)。
- repository choke point 原則 (ADR-00041): idempotency は **bridge (`bridge_ticket_create` /
  `bridge_run_create`) = 作成 chokepoint** で enforce し、MCP 以外の経路 (REST / research adapter) と
  整合させる。MCP tool 層だけで実装しない。
- tenant / project 境界を越えない。actor / principal 分離を維持。
- raw secret を idempotency_key / fingerprint / audit に出さない。

## 選択肢

1. **`tickets` / `agent_runs` に idempotency_key column を直接追加** — ❌ 却下。table ごとに散在し、
   `(tenant_id, actor_id, tool_name, key)` の cross-actor bind / tool_name scope を表現しづらい。
   ticket と run で別実装になり整合が取りにくい。
2. **共有 `mcp_idempotency_keys` table で `(tenant_id, actor_id, tool_name, idempotency_key)` を一元管理** —
   ✅ 採用。created_resource_kind / id を記録し、再送時に stored resource を返す。SP-034 行 183 の
   bind spec に直接対応。ticket / run 共通の 1 機構。
3. **Redis 等の external store** — ❌ 却下。P0 は DB を source of truth にする方針。DB の atomic
   constraint で重複防止する方が単純で監査可能。

## 採用案 (詳細)

### `mcp_idempotency_keys` table

| column | 内容 |
|---|---|
| `id` | UUID PK |
| `tenant_id` | bigint NOT NULL |
| `actor_id` | UUID NOT NULL (発行 actor、cross-actor replay deny) |
| `tool_name` | text NOT NULL (`ticket_create` / `run_create`、tool scope) |
| `idempotency_key` | text NOT NULL (client 指定) |
| `request_fingerprint` | text NOT NULL (正規化 request payload の SHA-256。同一 key + 異 payload を検出) |
| `created_resource_kind` | text **NULLABLE** (`ticket` / `agent_run`。reservation 中は NULL、completed で set) |
| `created_resource_id` | UUID **NULLABLE** (同上) |
| `created_at` | timestamptz NOT NULL (reservation 時刻) |
| `completed_at` | timestamptz **NULLABLE** (resource 作成完了時刻) |

- **unique constraint**: `(tenant_id, actor_id, tool_name, idempotency_key)`。これが cross-actor replay
  deny の核 (別 actor が同 key を使っても別 row、互いに干渉しない)。
- **CHECK constraint** (R2 F-N3 fix): `(created_resource_kind IS NULL AND created_resource_id IS NULL
  AND completed_at IS NULL) OR (created_resource_kind IS NOT NULL AND created_resource_id IS NOT NULL
  AND completed_at IS NOT NULL)` — reservation 中 (全 NULL) か completed (全 NOT NULL) のいずれかのみ。
  これにより reservation-first の初回 INSERT (NULL) が NOT NULL violation にならず、かつ「半端な
  resource を loser が返す」ことも防ぐ (resource_id が set される時は必ず completed)。
- request_fingerprint: NFC UTF-8 + JCS canonical JSON + SHA-256 で request の本質部分 (project_id /
  title / description 等、actor 申告でない server-resolved 値) から計算。raw secret は含めない。

### bridge での enforce (reservation-first、race-safe、R1 F-N1 fix)

> **R1 F-N1 fix**: 初版は「resource 作成 → idempotency row insert」順だったが、race の敗者が
> ON CONFLICT 経路で duplicate resource を commit する / IntegrityError で abort transaction のまま
> 再 SELECT できない欠陥があった。**reservation-first** に変更: idempotency row を**先に**予約し、
> winner だけが resource を作成する。

`bridge_ticket_create` / `bridge_run_create` に `idempotency_key: str | None = None` +
`actor_id` (解決済 caller actor) を渡し、**同一 transaction 内で**:

1. `idempotency_key is None` → 従来通り作成 (idempotency なし)。
2. key あり、**reservation-first**:
   1. `INSERT INTO mcp_idempotency_keys (tenant_id, actor_id, tool_name, idempotency_key,
      request_fingerprint, created_resource_kind=NULL, created_resource_id=NULL)
      ON CONFLICT (tenant_id, actor_id, tool_name, idempotency_key) DO NOTHING RETURNING id`。
   2. **RETURNING に row (= winner)** → resource 作成 → 同一 transaction で
      `UPDATE mcp_idempotency_keys SET created_resource_kind=..., created_resource_id=...,
      completed_at=now() WHERE id=:id` (**3 列を同時に set**、CHECK constraint「completed = 全 NOT NULL」
      を満たす。R3 F-N4: completed_at を含めないと CHECK violation で全 create が失敗する) → commit。
      作成した resource を返す。
   3. **RETURNING 空 (= loser、既に予約済)** → `SELECT ... FROM mcp_idempotency_keys
      WHERE (tenant_id, actor_id, tool_name, idempotency_key) FOR UPDATE` で **winner の commit を待つ**
      (row lock が winner transaction commit まで block)。lock 取得後:
      - `request_fingerprint` 不一致 → `IdempotencyKeyConflictError` (同一 key 異 payload、HTTP 409)。
      - 一致 + `completed_at` 設定済 → `created_resource_id` の既存 resource を返す (新規作成しない)。
   - **winner rollback 時の loser 昇格 (R2 F-N3)**: `INSERT ... ON CONFLICT DO NOTHING` は競合相手の
     transaction commit/rollback まで **block** する。winner が rollback すれば conflict が消え loser の
     INSERT が成功 → loser が winner に昇格し resource を作成する (孤立 reservation も resource も残らない)。
     よって loser の FOR UPDATE 経路は winner が **commit 済 (= completed、CHECK で resource_id 必ず set)**
     の時のみ到達する。万一 `completed_at IS NULL` を観測したら recoverable error として扱い 500 を返さない。
   - これにより **「2 request → 1 resource」invariant** が race / winner rollback でも成立。
3. winner の reservation insert + resource 作成 + row 完了は**同一 transaction** (どれか失敗で全 rollback、
   孤立 reservation row も残らない)。

### MCP / 他経路の配線 + actor 解決 (R1 F-N2)

- `server.py` の `ticket_create` / `run_create` が `idempotency_key` を bridge に渡す (dead param 解消)。
- **actor_id の解決 (R1 F-N2)**: idempotency の `(tenant, actor, tool, key)` bind は actor が正しく
  解決される前提。**現行 MCP context は固定 `DEFAULT_SUPERINTENDENT_ACTOR_ID` で per-client actor を
  解決しない** (SP-016 api_capability_tokens による per-actor MCP 認証は別 scope)。本 ADR の P0.1 実装:
  - bridge は `actor_id` を **caller 申告でなく MCP context 解決値** (現状は default superintendent) で受ける。
  - その結果、P0.1 では actor 次元が実質単一 → idempotency は **「同一 (default) actor の同 key 再送で
    重複作成しない」**という core 目的 (F-L4 = duplicate 作成防止) を満たす。
  - **per-actor cross-actor replay deny は、SP-016 per-actor MCP 認証が wired された時点で自動的に
    有効化**される設計 (unique constraint に actor_id を含むため、actor が分かれれば bucket が分かれる)。
  - 本 ADR は actor 次元を **forward-compatible に schema へ含める**が、per-actor 認証自体は本 scope 外
    (固定 default actor で ship してよいが、その制約を本 ADR + SP-034 Review に明記)。must-ship test は
    bridge 直呼びで distinct actor_id を渡し、actor 分離が schema/算法レベルで成立することを固定する。
- REST / research adapter 経路は idempotency_key を持たない呼出が大半 → `None` で従来通り (後方互換)。

## 却下案

- table ごとの idempotency column (選択肢 1): cross-actor bind / tool scope を表現しづらい。
- MCP tool 層だけの dedup: bridge を通らない経路で重複、chokepoint 原則違反。
- 逐次 check→create (atomic でない): race で重複。必ず unique constraint + ON CONFLICT。

## リスク

- **key 衝突 (異 client 同 key)**: `(tenant_id, actor_id, tool_name, key)` scope で別 actor は干渉せず、
  同 actor 同 tool で同 key + 異 payload は fingerprint mismatch で 409 (silent 重複より安全)。
- **fingerprint 過敏 / 過鈍**: server-resolved 本質値のみで計算 (timestamp 等揺らぎを含めない)。過鈍で
  別 payload を同一視しないよう、idempotency の対象 field を ADR/test で固定。
- **table 肥大**: idempotency row は無期限蓄積。P0 では低頻度のため許容、将来 TTL/cleanup を検討
  (本 ADR では cleanup 不要、note のみ)。
- **後方互換**: idempotency_key=None は従来挙動。既存 REST / research 経路に影響なし。

## rollback 手順

1. additive (新 table + bridge の optional 引数 + server.py 配線)。
2. rollback: revert PR (`git revert <merge SHA>`) + migration downgrade (table drop、lossless)。
3. bridge の `idempotency_key=None` default のため、revert 後も既存呼出は影響なし。

## 実装対象ファイル

- `migrations/versions/00NN_sp034_mcp_idempotency.py` (新 `mcp_idempotency_keys` table + unique index)
- `backend/app/db/models/mcp_idempotency_key.py` (ORM)
- `backend/app/services/mcp_idempotency/` (lookup / record / fingerprint helper)
- `backend/app/mcp/api_bridge.py` (`bridge_ticket_create` / `bridge_run_create` に idempotency_key + actor_id)
- `backend/app/mcp/server.py` (`ticket_create` / `run_create` が idempotency_key を bridge へ渡す)
- `backend/tests/mcp/test_create_idempotency.py` (新 test)

## テスト指針 (must-ship)

- **replay**: 同一 `(actor, tool, key, payload)` 再送 → 同一 resource_id を返し、**2 個目を作成しない**
  (ticket / agent_run の DB row 数が 1)。
- **conflict**: 同一 `(actor, tool, key)` + 異 payload → 409 `IdempotencyKeyConflictError`、新規作成しない。
- **cross-actor**: 別 actor が同 key → 別 resource (干渉しない、replay deny の意味は「別 actor の key で
  既存を奪えない」)。
- **race (atomic)**: 並行同一 key 2 request → 1 resource のみ作成、両 request が同一 resource_id を返す。
- **winner rollback 昇格 (R2 F-N3)**: winner の resource 作成が失敗し rollback → 後続の同一 key request が
  winner に昇格し resource を作成する (孤立 reservation row が残らない、重複もしない)。
- **reservation 整合 (R2 F-N3)**: reservation row は (全 NULL) か (resource_id + completed_at 全 set) の
  いずれかのみ (CHECK constraint)。loser が半端な resource を返さない。
- **null key**: idempotency_key=None → 従来通り毎回新規作成 (後方互換)。
- **tenant 境界**: 別 tenant の同 key は別 row。
- **audit / secret**: request_fingerprint / idempotency_key に raw secret を含めない (`assert_no_raw_secret`)。

## Hard Gates / KPI への trace

- AC-KPI-05 (cost_per_completed_task): 二重 run = 二重 provider call の防止はコスト整合に寄与。
- DD-02 tenant/project/actor 境界 + ADR-00041 chokepoint 原則に整合。
- cross-source: `IdempotencyKeyConflictError` の HTTP/MCP error mapping を整合させる。
