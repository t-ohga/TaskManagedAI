---
id: "ADR-00045"
title: "期限リマインダー集約エンドポイント (read-only、on-read、A-7)"
status: "accepted"
date: "2026-06-02"
accepted_at: "2026-06-02"
deciders: ["t-ohga"]
adr_gate_criteria: [3]
related_adr:
  - "ADR-00034 (tickets.due_date カラム / 期限の暦日 semantics 正本)"
  - "ADR-00039 (Dashboard 集計エンドポイント / read-only aggregate の先例 = ticket_summary)"
  - "ADR-00037 (soft-delete / archive 凍結 = active-scope の正本)"
related_dd:
  - "DD-02 (データモデル / tenant・project 境界)"
related_sprints: []
supersedes: null
superseded_by: null
---

# ADR-00045: 期限リマインダー集約エンドポイント (read-only、on-read、A-7)

最終更新: 2026-06-02

## 背景

UI 改善計画の **A-7 (リマインダー)** は、`tickets.due_date` (ADR-00034 で追加済、nullable
**date**) を活用し、期限が **超過 (overdue)** または **近接 (upcoming)** している actionable な
ticket を user に気付かせる機能。現状 `due_date` は ticket 一覧 / 詳細 / 編集フォームで表示・編集
できるが、「期限が迫っている / 過ぎている」という **横断的な気付き** を与える導線がない。

A-7 の生成方式は **案A on-read 軽量** を採用 (2026-06-02 user 選択)。すなわち:

- 一覧 / dashboard を **表示したときに** `due_date` を評価して reminder を **派生計算** する。
- background worker (arq) による定期 reminder 生成や push 通知は **行わない** (P0 overkill)。
- DB schema 変更は **不要** (`due_date` カラムは ADR-00034 で追加済、本 ADR は migration なし)。

ADR-00039 (ticket_summary / role_facet) と同型の「frontend bounded 集計 → backend SQL 派生
エンドポイント」であり、既存カラム (`tickets.due_date` / `tickets.status` / `tickets.deleted_at` /
`projects.status`) のみ使うため **migration 不要**。本変更は新規 REST endpoint の追加であり、
ADR Gate Criteria **#3 (API 契約)** に該当する (#2 DB schema / #8 破壊的操作には該当しない)。

## 決定対象

read-only な **期限リマインダー集約エンドポイント** を 1 本新設する。

```
GET /api/v1/me/reminders
```

actor の tenant 内の active ticket のうち、**actionable status** かつ **due_date 設定済** かつ
**期限が超過または近接 (threshold 日以内)** のものを派生集約し、bucket 別件数 + 上位リストを返す。
notification_events への materialization は **行わない** (純粋派生、§却下案)。

## 前提 / 制約

- **read-only / 純粋派生**。mutation なし。副作用なし。migration なし。同一入力に対し冪等。
- tenant / project 境界を強制 (`tenant_id` を session から resolve、caller-supplied 禁止)。
  single-tenant membership のため tenant 境界が project 境界を兼ねる (`ticket_summary` と同方針)。
- **capability gate (adversarial R8 F-001)**: `reminders` は ticket の slug/title/status/priority/
  due_date を返す ticket read surface のため、ticket list endpoint と同じ
  `maybe_require_cli_capability("task_list")` を必須にする。ticket read 権限を持たない operation token
  に tenant-wide な ticket title 列挙を deny する (least-privilege、capability matrix read boundary)。
  `date_context` は ticket data を返さない (today + 定数のみ) ため gate なし。
- **backend strict YMD write boundary (adversarial R13 F-001)**: ticket の **write boundary**
  (`TicketCreateRequest` / `TicketUpdateRequest` REST + 内部 `TicketCreate` / `TicketUpdate`) の
  `due_date` を `StrictDueDate` (= `Annotated[date | None, BeforeValidator(coerce_strict_due_date)]`)
  にする。Pydantic v2 の `date` lax coercion が datetime 文字列 (`2026-06-01T00:00:00Z`) / epoch
  (`1772323200`) を silent に date 化するのを塞ぎ、null または full-match `YYYY-MM-DD` のみ受理、
  datetime/epoch/非実在日 (2026-02-31)/junk suffix/非ゼロパディングを 422 で reject する。**server-owned
  boundary が strict-YMD の authoritative 強制点**であり、frontend strict は defense-in-depth。
  `task_create`/`task_write` capability を持つ API/CLI/MCP/内部 promotion caller が frontend を bypass
  しても timestamp/epoch を期限日として silent 永続化できない (data integrity 不変条件)。
- **active-scope 必須 (ADR-00037 / ADR-00039 と整合)**: 既存 default read path と同一の active-scope
  predicate を適用する。reminder が一覧から隠れた削除済みデータを surface してはならない。
  - `Ticket.deleted_at IS NULL` (soft-deleted を除外)。
  - `projects.status = 'active'` (**archived project の ticket は除外**)。reminder は「今 act すべき」
    actionable nudge であり、archived project は write 凍結 (ADR-00037、ticket update/status 変更が
    409) で **act 不能** なため、frozen ticket の reminder は誤誘導になる。`assert_ticket_actionable`
    が archived project を non-actionable とする既存 semantics と一致させる。
    (注: ADR-00039 `ticket_summary` は **inventory** 目的で archived を含むが、reminder は
    **actionable** 目的のため除外する。目的差に基づく意図的な非対称。)
- **actionable status のみ**: `status IN ('open','in_progress','blocked','review')`。
  `closed` / `cancelled` は終了済で期限が actionable でないため除外する。
- **`due_date IS NULL` は reminder 対象外** (期限未設定 ticket は nudge しない)。
- **期限の暦日 semantics (ADR-00034 正本)**: `due_date` は時刻概念のない `date`。"today" も
  **固定 timezone の暦日** でなければならない。本 endpoint は **Asia/Tokyo の暦日** を server 側で
  算出して基準日 (`reference_date`) とする。`new Date(due_date)` 等で TZ 変換しない (暦日破損防止)。
- raw secret / provider key は含まない。response が運ぶ ticket metadata (slug / title / status /
  priority / due_date) は **既存の ticket 一覧 endpoint が露出済の field のみ** であり、新規の
  情報露出面を作らない。
- **bounded materialize + bucket 別 cap (plan-review R1 F-001 ADOPT)**: bucket 別件数は SQL `COUNT`
  で **正確** に返す。reminder リストは **bucket ごとに独立して** `due_date` 順で上限件数
  (`REMINDER_BUCKET_LIST_LIMIT`) に capped する。**全 bucket 横断の単一 LIMIT は採らない**:
  overdue は下限なし (古い超過も超過) のため、stale overdue が大量にあると単一 LIMIT が overdue で
  枯渇し、`due_today` / `upcoming` の件数が非ゼロでも items が 1 件も出ない bucket 単位の silent
  truncation が起きる (最も見せるべき「今日 / 近日」が隠れる)。bucket ごとに count + capped items +
  truncated を返すことで、overdue が due_today / upcoming の表示枠を枯渇させない。各 bucket の
  `truncated` (= `count > len(items)`) で frontend は bucket 単位の欠落を明示できる。

## 選択肢

1. **純粋派生 read-only 集約エンドポイント (採用)**: 表示時に SQL で due_date を評価し、bucket 別
   件数 + 上位リストを返す。永続化なし、stale row なし、due_date 変更で即座に整合。
2. **notification_events に `due_reminder` event を on-read materialize**: GET 時に reminder 行を
   notification_events へ insert し、既存 inbox / triage / badge に統合する。**却下** (§却下案):
   GET が write する anti-pattern + due_date 変更 / ticket close / archive / soft-delete で stale
   row が残り、派生真実 (`tickets.due_date`) と persisted 通知が drift する (fail-open 構造)。
3. **arq worker で定期 reminder 生成 + push 通知**: 定期実行で reminder を生成し inbox / 外部通知に
   push。**却下**: P0 (個人専用 / 単一 VPS / on-read 軽量方針) に対し過剰。worker 障害時の欠落、
   重複生成、dedupe 整合の負債を生む。P0.1+ でチーム運用 / push 要件が出たら別 ADR で扱う。
4. **frontend で全 ticket を取得して client 集計**: 一覧の bounded fetch から client 評価。**却下**:
   ADR-00039 / ADR-00033 で繰り返し Codex に指摘された反 pattern。上限超で母数不正確、転送量増、
   "today" 算出が client 依存になり server 権威を失う。

## 採用案

### `GET /api/v1/me/reminders`

```
GET /api/v1/me/reminders

Response (ReminderSummaryResponse):  // bucket 別 cap (plan-review R1 F-001 ADOPT)
{
  "reference_date": "YYYY-MM-DD",   // server 算出の today (Asia/Tokyo 暦日、"today" 唯一権威)
  "threshold_days": 7,              // upcoming 窓 (REMINDER_UPCOMING_WINDOW_DAYS)
  "overdue":   ReminderBucket,
  "due_today": ReminderBucket,
  "upcoming":  ReminderBucket
}

ReminderBucket:
{
  "count": number,        // SQL COUNT (正確、capped と無関係)
  "truncated": boolean,   // count > len(items)
  "items": [              // bucket 内で order、REMINDER_BUCKET_LIST_LIMIT で独立 cap
    {
      "ticket_id": "uuid",
      "project_id": "uuid",
      "slug": "string",
      "title": "string",
      "status": "open" | "in_progress" | "blocked" | "review",
      "priority": "low" | "medium" | "high" | "critical" | null,
      "due_date": "YYYY-MM-DD",
      "days_until": number   // signed: <0 超過 / 0 当日 / >0 近接
    }
  ]
}
```

- **対象 SQL 条件** (tenant 境界内):
  - `Ticket.tenant_id = :tenant_id`
  - `Ticket.deleted_at IS NULL` (active-scope)
  - `projects.status = 'active'` (active-project、JOIN tickets→projects、archived 除外)
  - `Ticket.status IN ('open','in_progress','blocked','review')` (actionable)
  - `Ticket.due_date IS NOT NULL`
  - `Ticket.due_date <= :reference_date + :threshold_days` (overdue または upcoming のみ。
    `reference_date + threshold_days` より先の期限は reminder 対象外)
- **bucket 判定** (純粋関数 `compute_reminder_bucket(due_date, reference_date, threshold_days)
  -> Literal["overdue","due_today","upcoming"] | None`、plan-review R2 F-001 ADOPT):
  - `due_date < reference_date` → `overdue` (`days_until = (due_date - reference_date).days < 0`)
  - `due_date == reference_date` → `due_today` (`days_until = 0`)
  - `reference_date < due_date <= reference_date + threshold_days` → `upcoming`
    (`0 < days_until <= threshold_days`)
  - `due_date > reference_date + threshold_days` → `None` (window 外、reminder 対象外)
  - **関数が bucket 判定の正本** (SQL prefilter に依存しない)。SQL の `due_date <= reference_date +
    threshold_days` と関数の `threshold_days` は **同一値**を渡す。frontend `dueDateBucket` も
    同一 signature (`due_date, referenceDate, thresholdDays`) + 同一 4 値 (`overdue` / `due_today` /
    `upcoming` / `null`) を返し、backend と drift しない。
- **件数は bucket ごとに SQL COUNT で正確** (条件別 COUNT、list cap に依存しない)。
- **items は bucket ごとに独立して cap** (`REMINDER_BUCKET_LIST_LIMIT`)。bucket 内 order は
  **`due_date, slug, project_id, id`** で固定 (緊急度順 + 一意 tie-breaker):
  - `overdue`: `due_date ASC` (最古 = 最も超過 = 最も放置 を先頭。最長 overdue を優先表示)。
  - `due_today`: 単一 due_date のため tie-breaker が実順序を決める。
  - `upcoming`: `due_date ASC` (期限が近い順)。
  - **一意 tie-breaker `project_id, id` 必須** (adversarial R1 F-002): slug は `(tenant, project)`
    一意のため、tenant 横断 reminder では別 project の同 slug + 同 due_date が tie になり、cap 超過
    bucket で表示行と「他に N 件」が request ごとに揺れる。`due_date, slug, project_id, id` まで含め
    決定的にする。
  - 各 bucket の意図した緊急度順を上記で固定 (plan-review R1 F-001: 並び順を ADR で明文化)。
- **全 bucket 横断の単一 LIMIT は採らない** (overdue が due_today / upcoming の表示枠を枯渇させる
  silent truncation を防ぐ、F-001 ADOPT)。各 bucket の `truncated` で欠落を明示。
- `reference_date` は **server (FastAPI backend) 算出の "today" 唯一権威** (Asia/Tokyo 暦日)。
  この値が bucket / count / list の API 契約の基準。UI はこの値で基準日を表示する。
- 定数: `REMINDER_UPCOMING_WINDOW_DAYS = 7` / `REMINDER_BUCKET_LIST_LIMIT = 50` (backend 固定、
  caller 入力不可)。閾値変更は本 ADR の更新を要する。

### "today" 権威の一本化 (plan-review R1 F-002 + R2 F-002 ADOPT)

reminder endpoint と ticket 一覧の期限強調が **同一の基準日 (Asia/Tokyo 暦日) + 同一 threshold を
共有** することを API 契約で保証する。FastAPI backend を "today" の唯一権威とし、Next.js server /
client では "today" を独立算出しない (JST 深夜 0 時境界で同一 ticket の bucket が画面間で矛盾するのを
防ぐ)。

- backend 共有 helper `_today_jst(now: datetime | None = None) -> date` を 1 つ定義し、
  reminder endpoint と date_context endpoint の **両方** がこれを使う。
- **一覧画面用の単一 backend authority endpoint** `GET /api/v1/me/date_context` を新設し、
  `{ "reference_date": "YYYY-MM-DD", "threshold_days": number }` を返す (R2 F-002 ADOPT)。
  一覧 page は **この 1 endpoint を一度だけ fetch** し、`reference_date` + `threshold_days` を
  `SelectableTicketList` に渡して **全 row に同一基準**で赤/橙/neutral を分類する。
- **`TicketListResponse` は変更しない** (R2 F-002): 一覧 page は all view で list endpoint を
  project ごとに複数回呼ぶため、各 list response に `reference_date` を載せると「どの response の
  基準日を採るか」が未定義になる (深夜境界で project 間で割れる)。基準日を **list payload から
  分離**し、画面ごとに 1 回だけ取得する date_context に集約することで、all view でも単一基準を保証する。
- reminder response の `reference_date` / `threshold_days` と date_context の値は **同一 backend
  helper / 同一定数** 由来のため、同一 backend clock で算出され、Next.js server / client clock の
  drift を受けない (異なる HTTP request 間の sub-second 差は許容、別画面であり同一 backend clock の
  ため境界での恒常的矛盾は起きない)。
- `date_context` 取得失敗 / schema 不正は一覧 page で **fail-closed** に倒す (基準日なしでは期限を
  誤分類するため、強調なしの neutral 表示にフォールバックするか degraded notice を出す。
  不完全な基準日で赤/橙を誤表示しない)。

### Frontend

1. **reminder loader** (`frontend/lib/api/reminders.ts`): zod-backed `fetchReminders()` が
   `fetchBackendJson("/api/v1/me/reminders", ReminderSummarySchema)` を呼ぶ。response 全 field を
   Zod で必須検証 (data 完全性: 不完全を完全と見せない)。malformed / auth 失効 / schema drift は
   throw し、呼出側が degraded (ok/error) に倒す。**`reference_date` / item `due_date` は実在する
   暦日 (`isValidYmd`: full-match regex + UTC round-trip) のみ許容**し、`2026-13-40` / `2026-02-31`
   等の非実在日を取得失敗に倒す (adversarial R1 F-001: 壊れた基準日で赤/橙を誤表示しない)。
   `threshold_days` は非負・妥当上限内に制限する。

2. **dashboard reminder section** (`dashboard/page.tsx`): `fetchReminders()` を `ticket_summary` と
   同じ ok/error fail-closed pattern で呼ぶ。取得失敗は「—」/「取得できませんでした」表示にし、
   真の 0 件 (reminder なし) と区別する。overdue → due_today → upcoming の順に **bucket 別 count +
   上位 items リンク** を表示。各 bucket の `truncated` が true なら「他に N 件」(N = count - items 長)
   を明示する (bucket 単位の silent truncation 回避、F-001)。

3. **ticket 一覧の期限強調** (`selectable-ticket-list.tsx`): 既存の amber 一律 chip を、backend 由来
   `referenceDate` + `thresholdDays` で 3 段階に強調する。bucket 判定は純粋関数
   `dueDateBucket(due_date, referenceDate, thresholdDays) -> "overdue"|"due_today"|"upcoming"|null`
   (backend `compute_reminder_bucket` と同一 signature / 同一 4 値、`new Date(due_date)` を介さず
   `YYYY-MM-DD` 文字列比較で TZ ずれを排除、ADR-00034 と整合)。**入力が実在しない暦日 / 不正形式 /
   不正 threshold の場合は `null` (強調なし) に倒す** (adversarial R1 F-001: `isValidYmd` で full-match +
   UTC round-trip 検証、非実在日の JS Date 正規化による誤分類を防ぐ)。一覧の色 mapping:
   - `overdue` → 赤 (danger)
   - `due_today` / `upcoming` → 橙 (attention、期限近接)
   - `null` (window 外の未来) → neutral (既存の控えめ表示)
   `referenceDate` / `thresholdDays` は **`GET /api/v1/me/date_context` の backend 算出値** を一覧
   page が **一度だけ** fetch して `SelectableTicketList` に prop で渡す (R2 F-002: all view の複数
   list 呼びでも単一基準、"today" 権威を backend に一本化)。date_context の取得失敗 / schema 不正は
   一覧 page で fail-closed: 強調を neutral に倒す **かつ degraded warning を可視化する** (R9 F-001:
   silent に neutral 化すると open/active の超過/本日 ticket の強調消失をユーザーが検知できず dashboard
   reminder panel と silent に乖離するため、`{ok,ctx}/{ok:false}` を保持し失敗時に警告 notice を出す。
   期限の日付自体は表示され、色分け強調のみ無効化)。一覧 endpoint (`TicketListResponse`) は変更しない。
   **backend reminders と同一ゲート (adversarial R3 F-001 / R4 F-001)**: 強調は共有 helper
   `ticketDueBucket(due, ticketStatus, projectActive, ref, threshold)` 経由で適用し、backend reminders
   query の対象条件 (`projects.status='active'` + actionable status + due_date) と**同じゲート**を frontend
   強調にも適用する:
   - **非 active project (archived)** → bucket=null (neutral)。archived は write 凍結で非 actionable
     (R4 F-001: backend reminders が archived を除外するのに一覧/Kanban が urgent 表示する不整合を防ぐ)。
     project 状態は `/me/projects` の `status` を一覧 page が各 ticket row に `projectActive` として渡す。
     `ProjectBoardItemSchema.status` は **required + enum (`active`/`archived`、backend ProjectStatus と
     同一)** とし、`status` 欠落 / 不正値は schema failure に倒す (R5 F-001: unknown を archived と誤マップ
     して active project の reminder 強調を silent に消さない)。**failClosed (具体 project / tag filter)
     は `loadProjects(true)` で 1 行でも schema failure なら throw** (不完全を完全と見せない)。
     **all view は `loadProjectsAllView` で row-level omission** (R6 F-001: 配列一括 safeParse だと 1 行の
     status drift が全 project を消し silent empty board になるため、各 row を個別 safeParse して valid を
     保持、malformed row だけ omission して件数を warning 化、valid project の tickets を消さない)。
     **whole-list failure (R10 F-001)**: envelope 不正 / fetch 失敗 (auth 失効 / backend 障害 / schema
     drift) で project 一覧そのものが読めない場合は `degraded: true` を返し、page が「取得失敗」warning を
     必ず表示する (project/ticket 0 件の genuine empty と区別、silent empty board を避ける)。
   - **非 actionable status (closed/cancelled)** → bucket=null (neutral、R3 F-001)。
   - frontend の actionable 集合 (`REMINDER_ACTIONABLE_STATUSES`) は backend `_REMINDER_ACTIONABLE_STATUSES`
     と同一に揃える。一覧 (SelectableTicketList) と Kanban (TicketCard) の両 view が同 helper を使う。

## 却下案

- **notification_events materialization (選択肢 2)**: GET-side-effect anti-pattern + stale row drift
  (due_date 変更 / close / archive / soft-delete で派生真実と persisted 通知が乖離 = fail-open)。
  L-2 (ADR-00042) で確立した「派生可能なものを persisted projection にすると fail-open 構造を作る」
  教訓に反する。reminder は `tickets.due_date` から **常に派生** できるため persist 不要。
- **arq worker 定期生成 (選択肢 3)**: P0 on-read 軽量方針に対し過剰、欠落 / 重複 / dedupe 負債。
- **frontend client 集計 (選択肢 4)**: 母数不正確 + "today" の server 権威喪失、ADR-00039 と同理由。
- **closed/cancelled を含める**: 終了済 ticket の期限は actionable でない。除外。
- **archived project を含める**: write 凍結で act 不能。reminder の actionable 目的に反するため除外
  (inventory 目的の ticket_summary とは目的が異なる意図的非対称)。

## リスク

- LOW。read-only、既存カラムのみ、tenant / project 境界強制、migration なし、副作用なし。
- 集計クエリ性能: `tickets(tenant_id, project_id)` index が既存。tickets→projects は複合 FK で
  JOIN 軽量。P0 規模 (個人 dogfooding) では COUNT / GROUP BY + bounded SELECT は軽量。
- **"today" の境界 (深夜、F-002 適用後)**: reminder endpoint と `date_context` endpoint が **同一の
  backend helper `_today_jst()`** から `reference_date` を算出する (権威一本化、R2: tickets list
  endpoint は基準日を算出しない)。Next.js server / client では "today" を独立算出しない。異なる
  HTTP request 間の sub-second 差は許容 (別画面であり、同一 backend clock のため境界での恒常的な
  画面間矛盾は起きない)。視覚強調・件数表示のみで write 境界ではない。
- rollback は endpoint + schema + frontend section/emphasis の削除で完結 (DB 変更なし)。

## rollback 手順

1. `me.py` の `reminders` / `date_context` endpoint + `ReminderSummaryResponse` / `ReminderBucket` /
   `ReminderItem` / `DateContextResponse` schema を削除。`TicketListResponse` は本 ADR で未変更のため
   revert 不要。
2. frontend: `lib/api/reminders.ts` 削除、`dashboard/page.tsx` の reminder section 削除、
   `selectable-ticket-list.tsx` の 3 段階強調を旧 amber 一律 chip に revert、`tickets/page.tsx` の
   `date_context` fetch + `referenceDate`/`thresholdDays` prop 受け渡しを revert。`tickets-board.ts`
   は本 ADR で未変更のため revert 不要。
3. DB 変更なし (due_date カラムは ADR-00034 管理、本 ADR では触れない)。

## 実装対象ファイル

- `backend/app/api/me.py`: `reminders` endpoint + `ReminderSummaryResponse` / `ReminderBucket` /
  `ReminderItem` schema (active-scope + active-project + actionable + due_date NOT NULL +
  bucket window + bucket 別 cap 込み)。`date_context` endpoint + `DateContextResponse` schema
  (`{reference_date, threshold_days}`、R2 F-002)。
- `backend/app/domain/...` (または共有 module): `compute_reminder_bucket(due_date, reference_date,
  threshold_days) -> Literal[...] | None` 純粋関数 (R2 F-001) + `_today_jst(now=None) -> date` helper
  (reminder / date_context endpoint が共有) + `REMINDER_UPCOMING_WINDOW_DAYS` /
  `REMINDER_BUCKET_LIST_LIMIT` 定数
- `backend/tests/...`: 純粋関数 unit (overdue/due_today/upcoming/**window 外 None** + off-by-one、
  R2 F-001) + `_today_jst` の JST 深夜境界 unit (F-002) + SQL introspection (tenant 境界 +
  deleted_at IS NULL + projects.status='active' join + actionable status + due_date NOT NULL +
  bucket 別 query/LIMIT) + DB-gated 集約 integration (越境 negative + active-scope + archived 除外 +
  closed/cancelled 除外 + due_date NULL 除外 + bucket 別件数正確性 + bucket 別 capped truncation) +
  date_context endpoint (route + schema + reference_date が reminder と同一 helper 由来)
- `frontend/lib/api/reminders.ts`: zod schema (bucket 別) + `fetchReminders()` + `DateContextSchema`
  + `fetchDateContext()` loader
- `frontend/app/(admin)/dashboard/page.tsx`: reminder section (fail-closed ok/error、bucket 別 +
  truncated 表示)
- `frontend/components/selectable-ticket-list.tsx`: 期限 3 段階強調 + 純粋関数 `dueDateBucket`
  (backend 由来 `referenceDate` + `thresholdDays` prop、R2 F-001 signature)
- `frontend/app/(admin)/tickets/page.tsx`: `fetchDateContext()` を一度だけ呼び `referenceDate` +
  `thresholdDays` を list に prop で渡す (fail-closed、R2 F-002)。`TicketListResponse` /
  `tickets-board.ts` は変更しない。
- frontend `__tests__`: reminders loader (zod fail-closed、bucket 欠落/型不正/reference_date 欠落) +
  date_context loader (fail-closed) + dueDateBucket 純粋関数 (overdue/due_today/upcoming/null 境界) +
  list 強調 component (referenceDate+thresholdDays prop) + dashboard reminder section (truncated 表示)

## テスト指針

- **純粋 bucket 関数** (`compute_reminder_bucket(due, ref, threshold)` / `dueDateBucket`、R2 F-001):
  固定 `reference_date` + `threshold_days` で overdue (due < today) / due_today (due == today) /
  upcoming (today < due <= today+threshold) / **None (due > today+threshold、window 外)** /
  `days_until` 符号の境界値を網羅。**上限 off-by-one** (`due == today+threshold` → upcoming /
  `due == today+threshold+1` → None) を必須。backend / frontend で同一入力→同一 4 値であること。
- **tenant / project 越境 negative**: 別 tenant のチケットが reminder に混入しないこと。
- **active-scope negative**: soft-deleted (deleted_at IS NOT NULL) ticket が reminder / 件数に
  含まれないこと。restore 後は再び含まれること。
- **archived project 除外**: archived project の actionable + due_date 設定済 ticket が reminder /
  件数に含まれないこと。unarchive 後は含まれること。
- **status 除外**: `closed` / `cancelled` の due_date 設定済 ticket が含まれないこと。
- **due_date NULL 除外**: due_date 未設定 ticket が含まれないこと。
- **window 境界**: `due_date == today + threshold_days` は含まれ、`today + threshold_days + 1` は
  含まれないこと (上限境界)。overdue は下限なし (古い超過も含まれる)。
- **bucket 別件数正確性 + bucket 別 capped (F-001 必須)**: ある 1 bucket (例 overdue) が
  `REMINDER_BUCKET_LIST_LIMIT` を大きく超える fixture で、(a) 各 bucket の `count` が正確
  (cap と無関係)、(b) `items` 長 == min(bucket 対象数, LIMIT)、(c) `truncated` が正しい、かつ
  **overdue の cap 超過が due_today / upcoming の items を枯渇させない** (due_today / upcoming の
  items が overdue の件数に関わらず満たされる) こと。
- **bucket 内順序決定性**: overdue / upcoming は `due_date ASC, slug ASC`、due_today は `slug ASC`。
- **"today" 権威一本化 (F-002 必須)**: `_today_jst()` の JST 深夜境界 unit
  (`2026-06-02T23:59:59+09:00` → 2026-06-02 / `2026-06-03T00:00:00+09:00` → 2026-06-03 /
  UTC instant `2026-06-02T15:30:00Z` = JST 翌 00:30 → 2026-06-03 で **JST であり UTC でない**こと)。
  reminder endpoint の `reference_date` と `date_context` endpoint の `reference_date` /
  `threshold_days` が **同一 helper / 同一定数 由来**であること (route + schema field + 同値 integration)。
  一覧画面は `date_context` を **一度だけ** 取得し全 row に適用する (all view の複数 list 呼びでも
  単一基準、R2 F-002)。
- **raw secret なし**: response に raw secret が含まれないこと (`assert_no_raw_secret`)。
- **frontend loader fail-closed**: malformed (bucket 欠落 / count 型不正 / items 非配列 /
  reference_date 欠落) で `fetchReminders()` が throw し、dashboard が degraded 表示になること。
  bucket 別 truncation 表示 (`truncated` true で「他に N 件」) が出ること。
  **`date_context` の `reference_date` / `threshold_days` 欠落 / schema 不正で `fetchDateContext()`
  が throw し、一覧 page が期限強調なし (neutral) / degraded に倒れること** (R2/R3 F-002:
  `TicketListResponse` / `loadTickets` は `reference_date` を要求しない。基準日は date_context のみ
  が authority で、list API 契約は不変)。

## plan-review 採否記録 (codex-plan-review R1、2026-06-02)

codex-adversarial-review (mode=plan) R1 verdict=needs-attention、2 findings、いずれも **ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-PR-001 | HIGH | 全 bucket 横断の単一 `LIMIT` だと stale overdue が 200 件超で due_today / upcoming の items を完全に枯渇させ、count 非ゼロでも今日/近日のリンクが出ない bucket 単位の silent truncation | ADOPT | response を **bucket 別 (overdue/due_today/upcoming) の count + capped items + truncated** に再設計。各 bucket 独立 cap (`REMINDER_BUCKET_LIST_LIMIT`)。bucket 内 order を ADR 明文化。 |
| F-A7-PR-002 | MEDIUM | reminder endpoint と一覧 page が **独立時計**で Asia/Tokyo "today" を算出 → JST 深夜境界で同一 ticket の bucket が画面間で矛盾。"today" 権威が 2 箇所に分裂 | ADOPT | "today" 権威を **backend `_today_jst()` に一本化**。JST 深夜境界 contract test 追加。**(注: R1 時点では tickets list endpoint に reference_date を載せる案だったが、R2 F-002 で all view 複数呼びの曖昧さを排除するため `GET /me/date_context` 単一 authority へ変更。最終設計は R2 行参照。)** |

reject / defer: なし。

### plan-review R2 (R1 fix 確認、2026-06-02)

R1 fix 後の R2 verdict=needs-attention、2 findings、いずれも **ADOPT** (R1 fix が残した実装時の割れ穴):

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-PR-R2-001 | MEDIUM | `compute_reminder_bucket(due, ref)` が threshold 非受領で `due > ref+threshold` を None 判定できず、window 外を fail-open / テスト不能にする (SQL prefilter 依存) | ADOPT | 純粋関数を `compute_reminder_bucket(due, ref, threshold_days) -> Literal[...] | None` に変更。SQL と同一 threshold。frontend `dueDateBucket` も同 signature / 同 4 値。`today+threshold`→upcoming / `+1`→None の境界 test 必須化。 |
| F-A7-PR-R2-002 | MEDIUM | list endpoint に `reference_date` を載せる案は all view の複数 list 呼びで「どの基準日を採るか」未定義 + `threshold_days` 欠落で list 強調と dashboard reminder が再 drift | ADOPT | Codex 推奨の「単一 backend authority endpoint を一度だけ取得」を採用。`GET /api/v1/me/date_context` → `{reference_date, threshold_days}` を新設、一覧 page が 1 回 fetch して全 row に適用。`TicketListResponse` は **変更しない** (基準日を list payload から分離)。 |

reject / defer: なし。

### plan-review R3 (R2 fix 確認、2026-06-02)

R2 fix 後の R3 verdict=needs-attention、1 finding、**ADOPT** (stale text の契約矛盾):

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-PR-R3-001 | MEDIUM | テスト指針 / risk 節に R2 で削除したはずの「一覧 response の reference_date 欠落で loadTickets が throw」「tickets list endpoint が同一 helper」表現が残存。実装者が従うと TicketListResponse に reference_date を戻し R2 F-002 を破壊する契約矛盾 | ADOPT | 該当 stale text を date_context 契約に統一: テスト指針を「date_context の reference_date/threshold_days 欠落で fetchDateContext が throw、一覧 page は neutral/degraded に倒す。TicketListResponse/loadTickets は reference_date を要求しない」に修正。risk 節の「tickets list endpoint が同一 helper」→「date_context endpoint が同一 helper」。R1 採否表に R2 supersede 注記を追加。 |

reject / defer: なし。R3 全 adopt 反映後、R4 で clean を確認してから proposed → accepted 昇格。

### adversarial-review (mode=code、実装、2026-06-02)

実装 (commit b78c615) に対する codex-adversarial-review R1 verdict=needs-attention、2 findings、
いずれも **ADOPT** (実装時の fail-closed / 決定性の欠陥):

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R1-001 | MEDIUM | `dueDateBucket` / zod が `YYYY-MM-DD` の prefix しか見ず、非実在日 (`2026-13-40` / `2026-02-31`) を通す。`addDaysYmd` の JS Date 正規化で別日に化け、壊れた基準日でも null に倒れず赤/橙を誤表示する | ADOPT | `isValidYmd` (full-match regex + UTC round-trip) を新設し dueDateBucket / `DateContextSchema.reference_date` / `ReminderItem.due_date` / `ReminderSummary.reference_date` に適用。`threshold_days` を `min(0).max(366)` に。非実在日 / 不正 threshold は null / parse 失敗 → neutral/degraded。 |
| F-A7-CODE-R1-002 | MEDIUM | bucket list の `ORDER BY due_date, slug` だけでは、slug が `(tenant, project)` 一意のため tenant 横断 reminder で別 project の同 slug + 同 due_date が tie になり、cap 超過 bucket で表示/「他に N 件」が request ごとに揺れる | ADOPT | `ORDER BY due_date, slug, project_id, id` の一意 tie-breaker を追加し cap 境界を決定的に。SQL introspection test + ADR order spec も更新。 |

reject / defer: なし。

R1 fix 後の **adversarial-review R2** verdict=needs-attention、1 finding、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R2-001 | MEDIUM | R1 の `isValidYmd` が `value.slice(0,10)` 検証のため、`2026-06-01T23:30:00Z` / `2026-06-01junk` の timestamp / junk suffix を通す。due_date は backend の `date` 型 (厳密に `YYYY-MM-DD`) なので timestamp は schema drift であり、JST 深夜境界で別暦日に誤分類しうる (R1 の full-match 意図を満たさない) | ADOPT | `isValidYmd` を **全文字列 full-match** に厳格化 (slice 廃止)。timestamp / junk suffix を null / parse 失敗に倒す。dueDateBucket / addDaysYmd の slice も廃止。timestamp / junk suffix の negative test を dueDateBucket / 両 schema に追加。 |

reject / defer: なし。

R2 fix 後の **adversarial-review R3** verdict=needs-attention、1 finding、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R3-001 | MEDIUM | 一覧/Kanban が `ticket.status` を見ずに全 row へ `dueDateBucket` を適用するため、`closed` / `cancelled` で過去/本日 due_date の ticket も赤/橙 (超過/本日) 強調される。backend reminders query は actionable status (open/in_progress/blocked/review) のみなので、dashboard reminder panel が除外するのに一覧/Kanban が urgent 表示する画面間不整合 | ADOPT | 共有 helper `ticketDueBucket(due, status, ref, threshold)` + `REMINDER_ACTIONABLE_STATUSES` (backend と同一集合) を domain module に追加。非 actionable は bucket=null (neutral)。SelectableTicketList / TicketCard 両 view を helper 経由に。closed/cancelled の overdue/today が赤/橙にならない frontend test 追加。 |

reject / defer: なし。

R3 fix 後の **adversarial-review R4** verdict=needs-attention、1 finding、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R4-001 | MEDIUM | `ticketDueBucket` が ticket status だけゲートし project status を見ないため、**archived project の actionable ticket** (open/in_progress 等) で過去/本日 due_date が赤/橙強調される。backend reminders は `projects.status='active'` も要求し archived を除外するので、dashboard panel が除外するのに一覧/Kanban が urgent 表示する R3 と同クラスの画面間不整合 | ADOPT | `ticketDueBucket` に `projectActive` 引数を追加し非 active project は null (neutral)。`ProjectBoardItemSchema.status` を optional 追加し一覧 page が各 row に `projectActive` を渡す。archived project の actionable overdue が赤/橙にならない frontend test (unit + 一覧 component) + loadProjects status 捕捉 test を追加。 |

reject / defer: なし。

R4 fix 後の **adversarial-review R5** verdict=needs-attention、1 finding、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R5-001 | MEDIUM | R4 で `ProjectBoardItemSchema.status` を optional にし `p.status === "active"` で `projectActive` を導出したため、`/me/projects` が version-skew で `status` を omit すると active project が非 active 扱いになり全 due ticket が silent に neutral 化。dashboard reminder は依然 count するので逆方向の silent 不整合。unknown ≠ archived で fail-closed data 完全性に反する | ADOPT | `status` を **required + enum (`active`/`archived`)** に厳格化。欠落 / 不正は schema failure → failClosed (具体 project) で throw → degraded/error、fail-soft (all view) で omission。silent neutral にしない。load-ticket / tickets-board の test fixture に status を追加 (実 backend は常に返す)、欠落 / 不正 enum reject の regression を追加。 |

reject / defer: なし。

R5 fix 後の **adversarial-review R6** verdict=needs-attention、1 finding (HIGH)、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R6-001 | HIGH | R5 で `status` を required enum にした結果、`loadProjects(false)` (all view) は配列全体を一括 safeParse するため、`/me/projects` の 1 行だけ status 欠落/不正でも全体 reject → `[]` で valid な他 project の tickets まで silent に消える (silent neutral を silent empty board に置換)。`omittedProjects` も増えず可視化されない | ADOPT | `loadProjectsAllView` を新設し all view を **row-level safeParse** に。valid row を保持、malformed row だけ omission して件数を返し tickets page の warning に合算 (1 行 drift で全 project を消さない)。failClosed (具体 project/tag) は `loadProjects(true)` で従来通り 1 行でも throw。partial malformed all-view の regression test (valid 2 + malformed 1 → valid 2 + omission 1) 追加。 |

reject / defer: なし。

R6 fix 後の **adversarial-review R7** verdict=needs-attention、1 finding、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R7-001 | MEDIUM | `TicketItemSchema.due_date` が `z.string().nullable()` (任意文字列) のため、timestamp / junk suffix / 非実在日 (2026-02-31) が `loadTickets` を通る。`ticketDueBucket` は strict YMD で null (neutral) を返すが `formatDueDate` が raw を echo し、一覧/Kanban が bogus deadline を neutral 表示する。dashboard/date_context が strict なのに一覧は serializer drift を fail-closed しない画面間不整合 | ADOPT | `TicketItemSchema.due_date` を `z.string().refine(isValidYmd).nullable()` に (reminders/date_context と同じ strict YMD)。malformed は loadTickets で fail-closed (A-5 strict tags と同方針)。`formatDueDate` 2 箇所も raw echo を廃し非実在日 / 不正は null (defense-in-depth)。malformed due_date reject + valid 通過の regression 追加。 |

reject / defer: なし。

R7 fix 後の **adversarial-review R8** verdict=needs-attention、1 finding (HIGH)、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R8-001 | HIGH | `reminders_endpoint` は ticket の slug/title/status/priority/due_date を返す ticket read surface だが、既存 ticket read endpoint (`/projects/{id}/tickets` 等) が持つ `maybe_require_cli_capability("task_list")` がない。ticket read 権限を持たない operation token でも tenant-wide に ticket title を列挙でき、capability matrix の read boundary / least-privilege を破る | ADOPT | `reminders_endpoint` に `_cli_capability = Depends(maybe_require_cli_capability("task_list"))` を追加 (ticket list endpoint と同じ read boundary)。route の capability gate wiring を introspect する host test + ticket list との consistency 確認を追加。functional denial は既存 DB-gated capability test 基盤がカバー。`date_context` は ticket data 非返却のため gate なし。 |

reject / defer: なし。

R8 fix 後の **adversarial-review R9** verdict=needs-attention、1 finding、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R9-001 | MEDIUM | `fetchDateContext()` 失敗を `null` に潰し referenceDate/thresholdDays を undefined で渡すため、`ticketDueBucket` が null bucket を返し open/active の超過/本日 ticket の赤/橙/「超過」「本日」が消えて neutral 化するが、画面に degraded warning がない。date_context だけ壊れると dashboard reminder panel と silent に乖離し、ユーザーが期限強調の失敗を検知できない (fail-closed data completeness / screen consistency 違反) | ADOPT | date_context 結果を `{ok,ctx}/{ok:false}` で保持し、失敗時に一覧/Kanban の近くに degraded warning notice を表示 (強調は neutral のまま、degradation を visible に)。date_context 成功で warning なし + 超過強調 / 失敗で warning + neutral の full-page render regression test を追加。 |

reject / defer: なし。

R9 fix 後の **adversarial-review R10** verdict=needs-attention、1 finding (HIGH)、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R10-001 | HIGH | `loadProjectsAllView` が envelope 不正 / fetch 失敗でも `{items:[], omittedProjects:0}` を返し、page は `omittedProjects>0` でしか warning を出さないため、401/500/schema drift で project 一覧そのものが読めない whole-list failure が「横断表示に project/ticket なし」の空状態と区別できず silent empty board になる | ADOPT | `loadProjectsAllView` の戻り値に `degraded: boolean` を追加 (envelope/fetch failure=true、genuine empty=false)。page は `degraded` 時に「取得失敗」warning を必ず表示し空状態と区別。loadProjectsAllView の degraded test (envelope/fetch=true / empty=false) + page の whole-list failure warning render test を追加。 |

reject / defer: なし。

R10 fix 後の **adversarial-review R11** verdict=needs-attention、1 finding (HIGH)、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R11-001 | HIGH | A-7 が reminders/date_context/board に strict YMD を適用した一方、ticket detail/edit が使う共有 `TicketReadSchema.due_date` (lib/api/tickets.ts) が `z.string()` のまま。detail formatter が prefix-match、edit form が `due_date.slice(0,10)` を date input default に使い、update action が任意 string を backend に送るため、timestamp/junk/非実在日の serializer drift で board は fail-closed だが detail/edit は malformed を表示・truncate し、保存で sliced date を authoritative に書き戻して deadline を silent 改変しうる (strict-YMD all-surface invariant 違反) | ADOPT | 共有 `TicketListItemSchema.due_date` (= TicketReadSchema/TicketDetailSchema 基底) を `z.string().refine(isValidYmd).nullable()` に。detail formatter を harden (raw echo 廃止)、edit form の `slice(0,10)` を validated 値直接使用に、update action の `TicketUpdateFormSchema.due_date` を strict YMD に。TicketReadSchema malformed reject regression を追加。 |

reject / defer: なし。

R11 fix 後の **adversarial-review R12** verdict=needs-attention、1 finding (HIGH)、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R12-001 | HIGH | R11 で `TicketReadSchema.due_date` を strict 化したが、実際の detail loader `loadTicket` (`[id]/load-ticket.ts`) は by-id response を `TicketDetail` に cast 直返しし tags のみ検証するため、strict schema を呼ばない。backend serializer drift で `due_date: "2026-06-30T00:00:00Z"` / `2026-02-31` が detail/edit まで到達し、formatter が「未設定」に隠蔽、edit form が raw 値を date input に渡して保存で deadline を silent clear/改変しうる (strict-YMD all-surface invariant が loader で破れる) | ADOPT | `loadTicket` に **targeted strict YMD validation** を追加 (due_date は null または実在 YYYY-MM-DD のみ許可、timestamp/junk/非実在日/欠落は fail-closed throw)。full `TicketReadSchema` parse は loader の path-pid 設計 (response project_id 無視) + tags-only 検証戦略と非整合のため targeted check で invariant を enforce。malformed due_date reject + valid 通過の loadTicket regression を追加。 |

reject / defer: なし。

R12 fix 後の **adversarial-review R13** verdict=needs-attention、1 finding (HIGH)、**ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-CODE-R13-001 | HIGH | A-7 が frontend/detail loader に strict YMD を適用したが、実 backend write boundary (`TicketCreateRequest`/`TicketUpdateRequest`) は `date \| None` のまま。Pydantic v2 lax coercion で datetime 文字列 / epoch を date に silent coerce するため、`task_create`/`task_write` capability を持つ API/CLI caller が frontend strict validator を通らず timestamp/epoch を期限日として永続化できる data integrity gap (server-owned boundary と frontend invariant の trust boundary ずれ) | ADOPT | `StrictDueDate` (`BeforeValidator(coerce_strict_due_date)`) を `schemas/ticket.py` に定義し、REST request (`TicketCreateRequest`/`TicketUpdateRequest`) + 内部 write schema (`TicketCreate`/`TicketUpdate`) 全 write boundary に適用。null または full-match `YYYY-MM-DD` のみ受理、datetime/epoch/非実在日/junk を 422 reject。pure validator + 全 write schema の reject/accept contract test を追加 (server-owned boundary を authoritative 強制点に)。 |

reject / defer: なし。R13 全 adopt 反映後、R14 で clean を確認してから merge。検証: backend ruff/mypy +
backend 61 strict due_date pytest + 143 ticket regression、frontend 352 vitest + typecheck + lint 全 green。
