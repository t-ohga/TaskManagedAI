---
id: "ADR-00046"
title: "チケット担当者割当 (assignee、human-only、既存カラム活用、A-6)"
status: "accepted"
date: "2026-06-04"
accepted_at: "2026-06-04"
deciders: ["t-ohga"]
adr_gate_criteria: [1, 3]
related_adr:
  - "ADR-00044 (ticket tags / per-ticket 関連データの read enrichment + 一覧表示の先例)"
  - "ADR-00045 (期限リマインダー / read-only /me 集約エンドポイント + capability gate + degradation 可視化の先例)"
  - "ADR-00036 (R-3 secret inventory / DB から actor_type を resolve する owner gate の先例)"
  - "ADR-00041 (N-1/N-2 ticket コメント / MCP 経路を repository choke point で封鎖する先例)"
  - "ADR-00037 (soft-delete / archive 凍結 = active-scope・project freeze の正本)"
related_dd:
  - "DD-02 (データモデル / tenant・project 境界、actor / principal 分離)"
related_sprints: []
supersedes: null
superseded_by: null
---

# ADR-00046: チケット担当者割当 (assignee、human-only、既存カラム活用、A-6)

最終更新: 2026-06-04

## 背景

UI 改善計画の **A-6 (担当者割当)** は、ticket に「誰が担当するか」を割り当て・表示・編集できるようにする機能。

DB 側は **既に完備**している:

- `tickets.assignee_actor_id`(nullable UUID)カラムが存在する。
- 複合 FK `tickets_assignee_actor_fkey` = `(tenant_id, assignee_actor_id) -> (actors.tenant_id, actors.id)`
  が存在し、**tenant 境界 + actor 存在**を DB で enforce 済(`ondelete RESTRICT`)。
- `TicketCreate` / `TicketUpdate`(内部 schema)+ `TicketCreateRequest` / `TicketUpdateRequest`(REST)
  + `TicketRead`(response)に `assignee_actor_id` は既に通っている。
- frontend の `TicketReadSchema`(`lib/api/tickets.ts`)も `assignee_actor_id: z.string().uuid().nullable()`
  を持つ。

したがって本 ADR は **DB schema 変更なし / migration なし**。**新規 migration を一切追加しない**。

しかし現状には次の **3 つの gap** がある:

1. **assignee の write 検証が無い**。`assignee_actor_id` は repository の `create_in_project` /
   `update_in_project`(`repositories/ticket.py`)にそのまま渡され、**actor_type を一切検証しない**。FK は
   tenant + 存在のみを担保するため、**`agent` / `provider` / `github_app` / `service` actor を担当者に
   割り当てられてしまう**(担当者は人間であるべき、という semantics 違反)。また cross-tenant /
   nonexistent な UUID を渡すと FK IntegrityError が未捕捉で **500** になる。
   **しかも `create_in_project` / `update_in_project` は REST endpoint だけでなく MCP bridge
   (`mcp/api_bridge.py` の `bridge_ticket_create` / `bridge_ticket_update`)と research→ticket adapter
   (`services/research/research_to_ticket.py`)からも呼ばれる**(plan-review R1 F-001 で確認)。よって
   検証を REST endpoint にだけ置くと MCP / research / 内部経路が迂回する。
2. **assignee を選ぶための actor 一覧取得経路が無い**。frontend には actor 一覧を取得する API が存在せず、
   担当者を選択する UI(ドロップダウン)を作れない。
3. **assignee の表示が UUID 生値**。`today/page.tsx` は `担当:{ticket.assignee_actor_id ?? "未割当"}` で
   **UUID をそのまま表示**しており、人間が読めない。ticket 詳細・編集フォーム・一覧(Kanban /
   SelectableTicketList)は assignee を表示・編集できない(詳細 page は `assignee_actor_id: null` を
   `as unknown as` cast で握りつぶして編集フォームに渡している = 既存の型安全 hole、`load-ticket.ts` の
   `TicketDetail` shape が assignee を持たない)。

本変更は **新規 REST endpoint 1 本の追加** + **既存 ticket write の repository choke point への assignee
検証追加** + **frontend の選択 UI / 表示**であり、ADR Gate Criteria **#3 (API 契約)** に該当する。加えて
新 endpoint は capability gate / actor directory 露出 / owner-only 不採用という **認可面の判断**を含むため、
**#1 (認証・認可)** も明示的に対象とする(ただし新 role / RBAC モデル変更ではなく、既存の actor binding +
capability token を再利用する範囲。後述「認可面の判断」)。#2 DB schema / #8 破壊的操作には該当しない。

## 決定対象

### D-1. assignable actor 一覧エンドポイント(read-only)を 1 本新設

```
GET /api/v1/me/assignable-actors
```

actor の tenant 内の **`actor_type='human'` の actor のみ**を返す。担当者ドロップダウンの母集合 + assignee
UUID -> display_name の解決に使う。read-only / 純粋 SELECT / 副作用なし / migration なし。

**response shape(露出最小化、R1 F-002)**:

```
AssignableActorsResponse {
  actors: list[AssignableActor { id: UUID, display_name: str | None }]
  truncated: bool   # cap 到達で一覧が切り詰められたか (R1 F-009、degradation 可視化)
}
```

- **`actor_id`(stable identity 文字列)は返さない**(R1 F-002)。frontend は `id`(UUID = FK 値、select の
  value)と `display_name`(label)だけ必要で、stable identity / topology を露出する `actor_id` は不要。
- `display_name` は人間の表示名。tenant 内 human の directory を `task_list` token 保有者に見せることになるが、
  これは「誰に割り当てるか」を選ぶために必要な最小情報であり、secret / `actor_id` / `auth_context_hash` /
  `metadata` / `impersonated_by` は含めない。

### D-2. assignee 検証を repository choke point に追加(human-only + tenant、server-owned、全経路封鎖)

**`repositories/ticket.py` の `create_in_project` / `update_in_project`** で `assignee_actor_id` が
**non-null** で指定された場合に、**DB から `(tenant_id, assignee_actor_id)` の Actor を resolve** し、

- 存在しない、または別 tenant -> `AssigneeNotAssignableError`(endpoint で **422** に写像)
- `actor_type != 'human'` -> `AssigneeNotAssignableError`(**422**)

を **repository 層で**(= REST / MCP / research adapter すべての write 経路が通る choke point で)enforce する
(R1 F-001)。`assignee_actor_id = null`(担当解除)/ 未指定は検証 skip。

repository には既に `_assert_project_active` という全経路共通 guard があるため、同様に
`_assert_assignee_human(tenant_id, assignee_actor_id)` を追加し、`create_in_project` / `update_in_project` の
insert / update 前に呼ぶ。検証が insert 前に走るため、cross-tenant / nonexistent は FK IntegrityError に
至る前に 422 化される。**FK IntegrityError は defense-in-depth backstop** として endpoint / bridge でも捕捉し
422/400 に写像する(R1 F-004)。

### D-3. frontend で選択 UI + display_name 表示 + degradation 可視化

- ticket 作成 dialog + 編集フォームに **担当者セレクタ**(option = 「未割当」+ assignable human actors)。
  **現在の assignee は assignable 一覧に無くても必ず option に含める**(cap 外 / legacy / fetch 失敗でも
  select が現在値を失わない、R1 F-009)。assignable-actors の **fetch 失敗時は degraded warning を表示**し、
  現在の assignee を保持する(silent に未割当へ変えない、A-7 の degradation 可視化不変条件と整合)。
- ticket 詳細 / 一覧(Kanban card + SelectableTicketList)/ today で assignee を **display_name で表示**
  (assignable-actors map で UUID を解決、map-miss は中立 fallback label)。
- 詳細 page の `as unknown as` cast を解消し、`load-ticket.ts` の `TicketDetail` に `assignee_actor_id` を
  透過させて実 ticket を編集フォームに渡す(R1 F-006)。
- ticket 一覧 loader(`lib/api/tickets-board.ts` の `TicketItemSchema`)に `assignee_actor_id` を追加し、
  Kanban card / SelectableTicketList に担当者表示を足す(R1 F-007)。
- assignee 変更は Today / Inbox 分類に影響するため、create / update Server Action の revalidate に
  **`/today` を追加**する(R1 F-010)。

### D-4. audit に assignee 変更を記録(R1 F-008)

- `ticket_created` audit に初期 assignee(`assignee_actor_id`、null 可)を記録。
- `ticket_updated` / `ticket_status_changed` audit で assignee が変わった場合、`previous_assignee_actor_id` /
  `new_assignee_actor_id`(UUID のみ)を payload に追加。誰から誰へ変わったかを追跡可能にする。
- payload は **UUID のみ**(display_name / actor_id / secret / PII を入れない、append-only)。

## 前提 / 制約

- **migration なし**。`tickets.assignee_actor_id` カラム + FK は既存。本 ADR で DB schema / CHECK / index を
  一切変更しない。
- **server-owned-boundary §1 遵守**: `tenant_id` / `actor_id` は session(`get_tenant_id` /
  `get_current_actor_id`)から resolve。assignee の `actor_type` は **caller 申告ではなく DB から resolve**
  して判定する。
- **全 write 経路の choke point 封鎖**: 検証は repository 層(`create_in_project` / `update_in_project`)に
  置き、REST / MCP bridge / research adapter のどの caller も human-only + tenant を必ず通る(R1 F-001、
  N-1/N-2 ADR-00041 の「REST 404 だけでは MCP 迂回 → repository choke point で封鎖」と同型)。
- **tenant 境界 fail-closed**: assignable-actors は `tenant_id` で絞り、別 tenant の actor を返さない /
  assign させない。single-tenant membership のため tenant 境界が実質 owner 境界を兼ねる(P0)。
- **capability gate**: assignable-actors は ticket 管理の read surface のため、ticket 一覧 / reminders と
  同じ `maybe_require_cli_capability("task_list")` を通す。
- **human-only**: 担当者は `actor_type='human'` のみ。`agent` を担当者にする(AI に ticket を委譲する)
  semantics は P0 では持たず、必要なら別 ADR(P0.1 multi-agent / delegation 領域)で扱う。
- **最小露出**: assignable-actors が返すのは `id` / `display_name` のみ(R1 F-002 で `actor_id` を除外)。
  secret は一切返さない。
- **TicketRead 契約は不変**: assignee の display_name 解決は frontend 側で assignable-actors map を使い、
  `TicketRead` に `assignee_display_name` を**足さない**(契約安定 + 全 ticket read path への JOIN 波及を
  避ける)。

### 認可面の判断 (adr_gate_criteria #1、R1 F-003)

本 ADR は新 role / RBAC モデル / principal 種別を**追加しない**。既存の actor binding
(`get_current_actor_id` / `get_tenant_id`)+ capability token(`task_list`)を再利用する。ただし次の
認可判断を明示的に行う:

- assignable-actors を **owner-only gate(R-3 secret inventory 同等)にしない**。assignee 選択は secret
  露出ではなく tenant 内 human 表示名であり、将来の team assignment を owner-only で塞がない。tenant-scoped
  human + `task_list` capability gate で十分。
- `task_list` token 保有者に tenant 内 human directory(表示名)を見せることを許容する(割り当てに必要な
  最小公開)。`actor_id` / 内部属性は見せない。

## 選択肢

### assignee の human-only enforcement 配置

- **(採用、R1 F-001 で変更)** repository 層(`create_in_project` / `update_in_project`)の choke point で
  DB resolve + actor_type 判定。REST / MCP / research adapter の全 write 経路を 1 箇所で封鎖。
- (却下)REST endpoint にだけ `_validate_assignee` を置く。MCP bridge / research adapter が迂回するため
  不採用(R1 F-001)。
- (却下)DB trigger で `assignee_actor_id` が human を指すことを強制。actor_type は別テーブル(actors)に
  あり tickets の CHECK では表現不可。trigger は P0 規模に対し保守コスト過大。repository choke point + FK の
  二段で十分。

### エンドポイント配置

- **(採用)** `/api/v1/me/assignable-actors`(me router)。`/me/projects` `/me/reminders` `/me/date_context`
  と同じ self-scoped read 名前空間。
- (却下)`/api/v1/actors`(汎用 actor CRUD)。露出過大。assignment 用途に絞る。

### assignee display_name の解決

- **(採用)** frontend で assignable-actors を fetch し UUID->display_name map で解決。`TicketRead` 契約不変。
  P0 は human 極小。map-miss(legacy 非 human / fetch 失敗)は中立 fallback + degraded warning。
- (却下)backend で `TicketRead.assignee_display_name` を additive 追加し全 read path で JOIN。robust だが
  契約変更 + `list_tickets` / `_ticket_read_with_tags` / 他全 read path への JOIN 波及で surface 過大。将来
  team 規模で N+1 が問題化したら enrichment へ移行する余地を残す。

## 採用案

D-1 / D-2 / D-3 / D-4 を採用する。

- **D-1**: `GET /api/v1/me/assignable-actors` を me router に追加。
  - auth: `get_current_actor_id` + `get_tenant_id` + `maybe_require_cli_capability("task_list")`。
  - SQL: `select(Actor.id, Actor.display_name).where(Actor.tenant_id == tenant_id, Actor.actor_type == 'human')
    .order_by(Actor.display_name.nulls_last(), Actor.id).limit(ASSIGNABLE_ACTOR_LIST_LIMIT + 1)`。
    `limit+1` 件取得して `ASSIGNABLE_ACTOR_LIST_LIMIT` 超なら `truncated=true` + 先頭 cap 件に切る
    (R1 F-009、silent cap を可視化)。
  - response: `AssignableActorsResponse { actors: [{id, display_name}], truncated }`。
  - 安定 tie-break(display_name は null/重複しうるため `id` で一意化)。`ASSIGNABLE_ACTOR_LIST_LIMIT = 200`。
- **D-2**: `repositories/ticket.py` に `_assert_assignee_human(tenant_id, assignee_actor_id)` helper +
  `AssigneeNotAssignableError` 例外を追加し、`create_in_project` / `update_in_project` で
  `assignee_actor_id` が payload にあり non-null のとき insert/update 前に呼ぶ。endpoint(REST)/ bridge
  (MCP)は `AssigneeNotAssignableError` -> 422、FK IntegrityError -> 422/400 に写像。
- **D-3**: frontend。
  - `frontend/lib/api/actors.ts`(新規): `fetchAssignableActors()` + zod schema(`{actors, truncated}`)+
    UUID->display_name map helper(map-miss fallback 込み)。
  - 作成 dialog(`ticket-create-dialog.tsx`)+ 編集フォーム(`edit-ticket-form.tsx`)に担当者 `<select>`。
    現 assignee を常に option 保持 + fetch 失敗時 degraded warning(R1 F-009)。
  - 編集 form Server Action(`actions.ts`)+ 作成 action に `assignee_actor_id`(uuid or "" = null clear)を
    追加 + `revalidatePath("/today")`(R1 F-010)。
  - 詳細 page(`page.tsx`)+ `load-ticket.ts`: `as unknown as` cast 解消 + `TicketDetail` に
    `assignee_actor_id` 透過 + assignee display 表示 + assignable actors fetch/prop(R1 F-006)。
  - 一覧(`lib/api/tickets-board.ts` `TicketItemSchema` に `assignee_actor_id` 追加 + Kanban card +
    `selectable-ticket-list.tsx` に担当者表示、R1 F-007)。
  - `today/page.tsx`: assignee の UUID 生表示を display_name 解決に置換(map-miss fallback)。
- **D-4**: tickets.py の create/update audit payload に initial / previous / new assignee(UUID のみ)を追加。

## 却下案

- **agent / service / provider を担当者に許可**: 却下。担当者は human の責務。AI 委譲は別概念(delegation、
  P0.1 sealed)。
- **actor 汎用 CRUD API**: 却下。露出過大。
- **`TicketRead.assignee_display_name` 追加**: 却下(契約安定優先、上記参照)。
- **owner-only gate**: 却下(認可面の判断、上記参照)。
- **REST endpoint のみの validation**: 却下(MCP / research 迂回、R1 F-001)。

## リスク

| リスク | 対策 |
|---|---|
| assignee に非 human / 越境 actor を割り当て(REST/MCP/research 全経路) | repository choke point で DB resolve + actor_type='human' 検証 -> 422、FK が二重防御 |
| FK IntegrityError 500(cross-tenant / nonexistent UUID) | 検証で事前に 422 化、IntegrityError も endpoint/bridge で捕捉し 422/400 に写像 |
| assignable-actors が内部 actor topology を露出 | human のみ + `id`/`display_name` のみ(`actor_id` 除外)+ tenant scope + capability gate |
| **既存 DB に legacy 非 human assignee が残存**(検証前 gap 由来) | 着手時に SQL で `assignee_actor_id` が非 human を指す ticket が無いことを確認(検証手順)。あれば display は中立 fallback、是正は手動(migration 追加せず、residual として記録) |
| display の map-miss(legacy / fetch 失敗) | 中立 fallback label + degraded warning。select は現 assignee を常に option 保持(現在値を失わない) |
| assignable-actors の silent cap | `limit+1` 取得で `truncated` flag を返し可視化。現 assignee は cap と無関係に select に保持 |
| assignee セレクタが大量 actor で重い | P0 は 1 名。`ASSIGNABLE_ACTOR_LIST_LIMIT=200` cap + truncated。超過は将来 pagination の trigger |
| caller が `assignee_actor_id` を claim して権限昇格 | assignee は担当表示のみで権限を与えない。actor_type は DB resolve、caller 申告を信頼しない |
| assignee 変更が監査で追えない | audit に previous/new assignee(UUID)を記録(R1 F-008) |

## rollback 手順

- 本 ADR は **migration なし**のため DB rollback 不要。
- コード rollback: PR revert で
  - assignable-actors endpoint 削除、
  - `_assert_assignee_human` 呼び出し削除(assignee は従来通り FK のみで担保 = 元の挙動)、
  - frontend セレクタ / 表示 / audit 追加を元に戻す。
- `assignee_actor_id` カラム自体は既存機能のため削除しない(rollback 対象外)。

## 実装対象ファイル

**backend**
- `backend/app/api/me.py`: `GET /me/assignable-actors` endpoint + `AssignableActor` /
  `AssignableActorsResponse` schema + `ASSIGNABLE_ACTOR_LIST_LIMIT`。
- `backend/app/repositories/ticket.py`: `_assert_assignee_human` helper + `AssigneeNotAssignableError` +
  `create_in_project` / `update_in_project` での呼び出し。
- `backend/app/api/tickets.py`: `AssigneeNotAssignableError` -> 422 + FK IntegrityError backstop 写像 +
  create/update audit payload に assignee(initial/previous/new UUID)。
- `backend/app/mcp/api_bridge.py`: `bridge_ticket_create` / `bridge_ticket_update` で
  `AssigneeNotAssignableError` を MCP error に写像(repository が raise するため写像のみ)。

**frontend**
- `frontend/lib/api/actors.ts`(新規): `fetchAssignableActors()` + `AssignableActorsSchema` + map helper。
- `frontend/components/ticket-create-dialog.tsx`: 担当者セレクタ。
- `frontend/app/(admin)/tickets/[id]/_components/edit-ticket-form.tsx`: 担当者セレクタ(assignableActors +
  現 assignee prop、degraded warning)。
- `frontend/app/(admin)/tickets/[id]/actions.ts`: `assignee_actor_id` を update schema に追加 +
  `revalidatePath("/today")`。
- `frontend/app/(admin)/tickets/[id]/load-ticket.ts`: `TicketDetail` に `assignee_actor_id` を透過。
- `frontend/app/(admin)/tickets/[id]/page.tsx`: cast 解消 + assignee 表示 + assignableActors fetch/prop。
- `frontend/lib/api/tickets-board.ts`: `TicketItemSchema` に `assignee_actor_id`。
- `frontend/app/(admin)/tickets/page.tsx` + Kanban card + `frontend/components/selectable-ticket-list.tsx`:
  担当者表示 + assignableActors map。
- `frontend/app/(admin)/today/page.tsx`: assignee display_name 解決。
- (作成 dialog の Server Action / 作成 API client に assignee を追加)

## テスト指針

**backend (pytest)**
- assignable-actors: tenant 内 human のみ / agent・provider・service・github_app を返さない / 別 tenant の
  human を返さない / `actor_id` を返さない(露出最小) / display_name null の order 安定 / capability gate
  (task_list) / 空(human 0)応答 / cap 到達で `truncated=true`。
- assignee 検証(repository choke point): human への assign 成功(create / update)/ agent への assign 422 /
  別 tenant actor 422 / nonexistent UUID 422(500 でない)/ null clear 成功 / 未指定は既存 assignee を保持 /
  **MCP bridge 経路でも同じ deny**(`bridge_ticket_create` / `bridge_ticket_update` で非 human assign が 422
  相当に弾かれる)/ research adapter 経路でも非 human assign が弾かれる。
- audit: create に initial assignee / update に previous→new assignee(UUID のみ、raw secret / PII なし)。
- legacy 検査: 既存 DB に非 human assignee を持つ ticket が無いことを確認する SQL(検証手順、test fixture で
  非 human assignee は作れないことを保証)。

**frontend (vitest)**
- `actors.ts`: zod parse(正常 / 不正 UUID reject / `truncated` boolean)/ display_name map build /
  map-miss fallback。
- 編集フォーム / 作成 dialog: 担当者セレクタ描画 /「未割当」option / 現 assignee が一覧に無くても option 保持 /
  選択値が FormData に乗る / fetch 失敗時 degraded warning + 現 assignee 保持。
- 詳細 / today / 一覧(Kanban / SelectableTicketList): assignee の display_name 表示 / 未割当表示 /
  map-miss fallback。
- actions: `assignee_actor_id` の "" -> null clear / uuid -> set / 不正値 reject / revalidate に /today。

## レビュー記録

### codex-plan-review R1 (2026-06-04、Phase A+B、gpt-5.5 xhigh)

10 findings、**全 10 adopt**。主な反映:

- **F-001 (HIGH, adopt)**: assignee 検証を REST endpoint から **repository choke point**
  (`create_in_project` / `update_in_project`)へ移動。REST + MCP bridge + research adapter の全 write 経路を
  1 箇所で封鎖(N-1/N-2 ADR-00041 と同型)。
- **F-002 (HIGH, adopt)**: assignable-actors response から `actor_id` を除外、`{id, display_name}` のみに
  最小化。
- **F-003 (MEDIUM, adopt)**: `adr_gate_criteria: [1, 3]` に更新 + 「認可面の判断」節を追加。
- **F-004 (MEDIUM, adopt)**: 検証は insert 前 pre-check、FK IntegrityError は defense backstop と明記。
- **F-005 (MEDIUM, adopt)**: legacy 非 human assignee の検査手順 + graceful 表示(migration / backfill なし、
  residual 記録)。
- **F-006 (MEDIUM, adopt)**: `load-ticket.ts` を scope 追加、`TicketDetail` に assignee 透過。
- **F-007 (MEDIUM, adopt)**: `tickets-board.ts` `TicketItemSchema` + Kanban card + SelectableTicketList を
  scope 追加。
- **F-008 (MEDIUM, adopt)**: audit に initial / previous / new assignee(UUID のみ)。
- **F-009 (MEDIUM, adopt)**: `truncated` flag + select は現 assignee を常に option 保持 + fetch 失敗時
  degraded warning。
- **F-010 (LOW, adopt)**: create / update action の revalidate に `/today` 追加。

### codex-plan-review R2 (2026-06-04、Phase B 実コード突合、gpt-5.5 xhigh)

**0 HIGH+ findings (clean)**。Codex 確認:
- repository choke point は既存 `_ensure_tenant_context` → `_assert_project_active` → payload 正規化 →
  flush/update pattern に `_assert_assignee_human` を insert/update 前に差し込める構造。
- 未指定 update が既存 assignee を保持する挙動は `exclude_unset` + `_payload_for_update` で成立。
- `actor_type='human'` filter は既存 seed / DevActorContextMiddleware の default human actor と整合、
  P0 で空 dropdown になる構造欠陥なし。
- frontend は R1 反映済 scope で型安全に通せる見込み。

**Readiness Gate: READY**(R1+R2 で CRITICAL=0 / HIGH=0、R2 clean)。proposed → **accepted** (2026-06-04)。

### codex-adversarial-review R1 (実装後、2026-06-04、branch diff vs origin/main)

3 findings、**全 3 adopt**:
- **F-A1 (HIGH)**: assignee audit diff が SQLAlchemy identity map refresh で `existing.assignee_actor_id`
  が new 値に同期され new vs new 比較になり記録漏れ → `previous_assignee_actor_id` を update 前に snapshot
  (`previous_status` と同方針)。DB-gated E2E audit 回帰 test 追加。
- **F-A2 (MEDIUM)**: `_is_assignee_fk_violation` が `exc.orig.constraint_name` のみで asyncpg の
  `orig.__cause__.constraint_name` 形を見逃し TOCTOU で 500 化 → `evidence_items._constraint_name` と同型に
  両方確認。`__cause__` ケースの unit test 追加。
- **F-A3 (MEDIUM)**: tickets 一覧 page が assignable-actors の `truncated`/degraded を捨てていた →
  `{actors, truncated, degraded}` を保持し別々に警告表示。today も assignee 取得失敗を errors に可視化。

### codex-adversarial-review R2 (2026-06-04)

R1 の 3 findings は解消確認。新規 2 HIGH (concurrency/TOCTOU):
- **F-B1 (HIGH) adopt**: `_assert_assignee_human` が unlocked SELECT で、判定〜commit 間の actor_type 変更
  競合で非 human assignee が永続化されうる → actor row を `SELECT ... FOR UPDATE` で lock。lock 順は
  `_assert_project_active` (project lock) の後で project→actor に一貫し bulk 操作 (project→ticket) と
  deadlock しない。P0 では actor_type の mutation 経路が無いため非露出だが core invariant の defense-in-depth。
- **F-B2 (HIGH) adopt**: audit の previous snapshot が mutation lock 前で、同一 ticket 並行更新時に虚偽遷移
  (actorA→actorB を None→actorB) を記録しうる → **update_ticket_endpoint で `existing` 読込の前に
  `assert_project_active` で project row を FOR UPDATE lock**。project lock は同一 project の全 ticket write
  (update_in_project / bulk) を直列化するため、lock 保持中は別 tx が assignee/status を書き換えられず、
  previous snapshot (status / assignee 両方) が並行更新に対し正確になる。lock 順は project → actor (F-B1)
  → ticket-update で bulk (project → ticket) と一貫し deadlock しない (endpoint 側で ticket row を先 lock
  する naive 案は project↔ticket 逆順で deadlock するため不採用、project-first lock で回避)。

**Readiness Gate (R2 後)**: CRITICAL=0 / HIGH=0 (F-B1 + F-B2 とも adopt)。clean。

(PR Codex App auto-review の round はここに追記する)
