---
id: "ADR-00039"
title: "Dashboard / Runs 集計エンドポイント (read-only、D-5 / C-4)"
status: "proposed"
date: "2026-06-01"
deciders: ["t-ohga"]
adr_gate_criteria: [3]
related_adr:
  - "ADR-00033 (AgentRun コスト集計エンドポイント / read-only aggregate の先例)"
related_dd:
  - "DD-02 (データモデル / tenant・project 境界)"
related_sprints: []
supersedes: null
superseded_by: null
---

# ADR-00039: Dashboard / Runs 集計エンドポイント (read-only、D-5 / C-4)

最終更新: 2026-06-01

## 背景

UI 改善監査の残項目 **D-5 (ダッシュボードのチケット集計)** と **C-4 (Runs のロール facet)** は、
現状 frontend が bounded な list 取得結果から client 集計しており、件数が上限を超える環境で
不正確になる。

- **D-5**: `dashboard/page.tsx` の `readProjectSummaries` は各 project の `/tickets` を取得し、
  status 別内訳 (open / in_progress / closed / cancelled) を **取得済み items (limit 200) から
  client 集計**している。`ticket_total` は tickets endpoint の `total` (= `len(tickets)`、正確) を
  使うが、**status 内訳は 200 件上限で母数が欠ける**。
- **C-4**: `runs/page.tsx` の role facet は非ページング fetch から `role_id` の distinct を作るが、
  fetch 自体が上限付きで、上限超のロールが filter chip に出ない (コード内コメントで既知)。

ADR-00033 (cost summary) と同型の「frontend bounded 集計 → backend SQL 集計エンドポイント」
への移行であり、`agent_runs` / `tickets` の既存カラムのみ使うため **migration 不要**。

## 決定対象

read-only な集計エンドポイントを 2 本新設する。ADR Gate Criteria #3 (API 契約) に該当。

1. `GET /api/v1/me/ticket_summary` — actor の全 project 横断のチケット集計 (D-5)
2. `GET /api/v1/agent_runs/role_facet` — actor の AgentRun の role_id distinct facet (C-4)

## 前提 / 制約

- read-only。mutation なし。migration なし。
- tenant / project 境界を強制 (`tenant_id` を session から resolve、caller-supplied 禁止)。
  `ticket_summary` は actor がアクセス可能な project に限定。
- 既存 `list_agent_runs_endpoint` / `me` endpoint と同じ actor / tenant dependency pattern。
- 集計は SQL `func.count` / `group_by` で実行、unbounded な行 materialize を避ける。
- raw secret / provider key は含まない (件数のみ)。
- `agent_runs.role_id` は nullable (single-agent run は null)。facet は **null を除外**し、
  P0.1 multi-agent 前提を持ち込まない (既存 P0 カラムの read-only 集計に閉じる)。
- **active-scope 整合 (Codex ADR R1、必須)**: 集計エンドポイントは既存の default read path と
  **同一の active-scope predicate** を適用する。集計が一覧から隠れている削除済みデータを
  母数に復活させてはならない (D-5/C-4 の「母数正確性」目的と矛盾するため)。
  - `ticket_summary`: 既存の default ticket read path と同じ active-scope を適用する。
    `Ticket.deleted_at IS NULL` (Q-3 / ADR-00037 soft-delete) を必須条件とし、soft-deleted
    ticket を `ticket_total` / `status_counts` に含めない。archived ticket の扱いは既存 list
    read path の convention に合わせる (archive = read-only-visible のため list と同方針)。
  - `role_facet`: 既存 `list_agent_runs_endpoint` / cost_summary と同じ
    `soft_deleted_ticket_run_exclusion()` (`backend.app.domain.agent_runtime.active_scope`) を
    適用し、soft-deleted ticket に bound する run の role を facet に含めない
    (ticket-less run は含む、restore で復帰、という既存方針と一致)。

## 選択肢

1. **新規 read-only 集計エンドポイント (採用)**: SQL `COUNT` / `GROUP BY` で正確な母数を返す。
2. frontend で `limit` を引き上げて全件取得し集計: 上限を上げても根本解決にならず、転送量増。却下
   (ADR-00033 D-4 / 既存 D-1 で同じ反 pattern が Codex に指摘済み)。
3. 既存 list endpoint に集計を相乗り: list の責務 (ページング表示) と集計 (母数) を混在させ
   contract が曖昧になる。却下。

## 採用案

### D-5: `GET /api/v1/me/ticket_summary`

```
GET /api/v1/me/ticket_summary

Response (TicketSummaryResponse):
{
  "ticket_total": number,
  "status_counts": [
    { "status": "open" | "in_progress" | "blocked" | "review" | "closed" | "cancelled",
      "count": number }
  ]
}
```

- actor がアクセス可能な全 project の `tickets` を tenant / project 境界内で `GROUP BY status` 集計。
- **`Ticket.deleted_at IS NULL` を必須条件**にし、soft-deleted ticket を母数に含めない (active-scope)。
- endpoint は **raw な per-status 件数** (ticket status 正本の全 enum) を返す。`status_counts` は
  欠損 status を 0 で埋めず、出現した status のみ返してもよい (frontend で 0 補完)。
- `ticket_total` は (active な) **全 status の合計** (= 既存 active list の `total` と整合)。
- **表示 bucket mapping を固定 (Codex ADR R2)**: 既存 dashboard と同じ集約を維持する。frontend は
  raw status_counts を次の 4 bucket に折り畳む。`ticket_total` と 4 bucket 合計は常に一致する
  (どの status も必ずいずれかの bucket に入り、欠落・二重計上しない):
  - `進行中 (in_progress)` = `in_progress + blocked + review`
  - `未着手 (open)` = `open` (+ 未知 status の fallback)
  - `完了 (closed)` = `closed`
  - `中止 (cancelled)` = `cancelled`

### C-4: `GET /api/v1/agent_runs/role_facet`

```
GET /api/v1/agent_runs/role_facet?status=<AgentRunStatus | omitted>

Response (RoleFacetResponse):
{
  "roles": [ { "role_id": string, "count": number } ],
  "status": string | null
}
```

- `agent_runs` を tenant 境界内で集計。`role_id is not null` に絞り `GROUP BY role_id`。
- **`soft_deleted_ticket_run_exclusion()` を適用** (list / cost_summary と同じ active-scope。
  soft-deleted ticket bound run の role を facet に出さない)。
- **任意 `status` query param** (Codex ADR R1): 指定時は `AgentRunStatus` enum で検証し、
  list endpoint と **同じ status predicate** を適用する。既存 runs UI は statusFilter ありで
  role 候補を作るため、status scoped facet を表現できないと「選択中 status に存在しない role chip
  をクリック → 空一覧」という facet drift が起きる。status 省略時は tenant-wide facet。
- `role_id` 昇順 (安定した chip 並び)。null (single-agent) は facet に出さない。
- **route 登録順序 (Codex ADR R2、必須)**: `agent_runs.py` には `@router.get("/{run_id}")` の UUID
  detail route が既存。FastAPI/Starlette は定義順照合のため、`role_facet` を `/{run_id}` より **後**に
  定義すると `/role_facet` が `run_id` として解釈され UUID 422 になる。`role_facet` は
  **`cost_summary` と同じ静的 route block・`/{run_id}` より前**に定義する。

## 却下案

- frontend 集計 (選択肢 2): 上限で母数不正確、ADR-00033 と同じ理由で却下。
- mutation を伴う集計キャッシュ table: read-only 要件に対し過剰、整合性負債を生む。却下。

## リスク

- LOW。read-only、既存カラム、tenant / project 境界強制、migration なし。
- 集計クエリ性能: `tickets(tenant_id, project_id)` / `agent_runs(tenant_id, ...)` index が既存。
  P0 規模 (個人 dogfooding) では COUNT / GROUP BY は軽量。
- rollback は endpoint + schema の削除で完結 (DB 変更なし)。

## rollback 手順

- ルート定義 (`me.py` / `agent_runs.py`) と response schema の削除で revert 完結。DB 変更なし。
- frontend は bounded client 集計の旧経路に戻す (1 commit revert)。

## 実装対象ファイル

- `backend/app/api/me.py`: `ticket_summary` endpoint + `TicketSummaryResponse` schema
  (`Ticket.deleted_at IS NULL` active-scope 込み)
- `backend/app/api/agent_runs.py`: `role_facet` endpoint + `RoleFacetResponse` schema
  (`soft_deleted_ticket_run_exclusion()` + 任意 status predicate 込み)
- backend repository / service: project 横断チケット集計 + run role 集計 (tenant / project 境界 SQL、
  `backend.app.domain.agent_runtime.active_scope.soft_deleted_ticket_run_exclusion` を再利用)
- `backend/tests/api/test_ticket_summary.py` / `test_agent_runs_role_facet.py`:
  tenant・project 越境 negative + 集計正確性 + null role 除外
- `frontend/app/(admin)/dashboard/page.tsx`: status 内訳を `ticket_summary` に置換
- `frontend/app/(admin)/runs/page.tsx`: role facet を `role_facet` に置換

## テスト指針

- **tenant / project 越境 negative**: 別 tenant / 別 project のチケット・run が集計に混入しないこと
- status_counts の母数が limit に依存せず正確 (>200 ticket project でも全件集計)
- `role_id is null` の run が role_facet に出ないこと
- raw secret が response に含まれないこと (`assert_no_raw_secret`)
- 空集合 (ticket 0 件 / role 0 件) で安全に空配列を返すこと
- **active-scope negative (Codex ADR R1、必須)**:
  - `ticket_summary`: 同一 tenant / project 内の **soft-deleted (deleted_at IS NOT NULL) ticket が
    `ticket_total` / `status_counts` に含まれない**こと。restore 後は再び含まれること。
  - `role_facet`: **soft-deleted ticket bound run の role が facet に出ない**こと。
    ticket-less run の role は **出る**こと (既存 active-scope 方針と一致)。
- **status-scoped facet (Codex ADR R1)**: `role_facet?status=<X>` が list endpoint と同じ status
  predicate を適用し、当該 status に属する role だけを返すこと (status 省略時は tenant-wide)。
  不正な status 値は 422 で reject。
- **route ordering (Codex ADR R2)**: `GET /api/v1/agent_runs/role_facet` が 200 を返し
  (`/{run_id}` detail に食われない)、`?status=not-a-status` が 422 になる route-order regression test。
- **表示 bucket 整合 (Codex ADR R2)**: `blocked` / `review` を含む fixture で、`ticket_total` が
  raw status_counts 合計とも 4 表示 bucket (`in_progress = in_progress+blocked+review` 等) 合計とも
  一致し、いずれの status も欠落・二重計上しないこと。
