---
id: "ADR-00045"
title: "期限リマインダー集約エンドポイント (read-only、on-read、A-7)"
status: "proposed"
date: "2026-06-02"
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
- **bucket 判定** (純粋関数 `compute_reminder_bucket(due_date, reference_date)`):
  - `due_date < reference_date` → `overdue` (`days_until = (due_date - reference_date).days < 0`)
  - `due_date == reference_date` → `due_today` (`days_until = 0`)
  - `due_date > reference_date` → `upcoming` (`0 < days_until <= threshold_days`)
- **件数は bucket ごとに SQL COUNT で正確** (条件別 COUNT、list cap に依存しない)。
- **items は bucket ごとに独立して cap** (`REMINDER_BUCKET_LIST_LIMIT`)。bucket 内 order:
  - `overdue`: `due_date ASC, slug ASC` (最古 = 最も超過 = 最も放置 を先頭。最長 overdue を優先表示)。
  - `due_today`: `slug ASC` (単一 due_date のため slug 決定順)。
  - `upcoming`: `due_date ASC, slug ASC` (期限が近い順)。
  - 各 bucket の意図した緊急度順を上記で固定 (plan-review R1 F-001: 並び順を ADR で明文化)。
- **全 bucket 横断の単一 LIMIT は採らない** (overdue が due_today / upcoming の表示枠を枯渇させる
  silent truncation を防ぐ、F-001 ADOPT)。各 bucket の `truncated` で欠落を明示。
- `reference_date` は **server (FastAPI backend) 算出の "today" 唯一権威** (Asia/Tokyo 暦日)。
  この値が bucket / count / list の API 契約の基準。UI はこの値で基準日を表示する。
- 定数: `REMINDER_UPCOMING_WINDOW_DAYS = 7` / `REMINDER_BUCKET_LIST_LIMIT = 50` (backend 固定、
  caller 入力不可)。閾値変更は本 ADR の更新を要する。

### "today" 権威の一本化 (plan-review R1 F-002 ADOPT)

reminder endpoint と ticket 一覧の期限強調が **同一の基準日 (Asia/Tokyo 暦日) を共有** することを
API 契約で保証する。FastAPI backend を "today" の唯一権威とし、Next.js server / client では
"today" を独立算出しない (JST 深夜 0 時境界で同一 ticket の bucket が画面間で矛盾するのを防ぐ)。

- backend 共有 helper `_today_jst(now: datetime | None = None) -> date` を 1 つ定義し、reminder
  endpoint と **ticket 一覧 endpoint の両方** がこれを使う。
- `GET /api/v1/projects/{project_id}/tickets` の `TicketListResponse` に **`reference_date`
  (Asia/Tokyo 暦日) を追加** (additive、ADR Gate #3、本 ADR scope)。一覧 page はこの backend 由来の
  `reference_date` を `SelectableTicketList` に渡し、それだけで赤/橙/neutral を分類する。
- reminder response の `reference_date` と 一覧 response の `reference_date` は同一 backend helper
  由来のため、同一 backend clock で算出され、Next.js server / client clock の drift を受けない。
  (異なる HTTP request 間の sub-second 差は許容 — 別画面であり、同一 backend clock のため境界での
  恒常的矛盾は起きない。)

### Frontend

1. **reminder loader** (`frontend/lib/api/reminders.ts`): zod-backed `fetchReminders()` が
   `fetchBackendJson("/api/v1/me/reminders", ReminderSummarySchema)` を呼ぶ。response 全 field を
   Zod で必須検証 (data 完全性: 不完全を完全と見せない)。malformed / auth 失効 / schema drift は
   throw し、呼出側が degraded (ok/error) に倒す。

2. **dashboard reminder section** (`dashboard/page.tsx`): `fetchReminders()` を `ticket_summary` と
   同じ ok/error fail-closed pattern で呼ぶ。取得失敗は「—」/「取得できませんでした」表示にし、
   真の 0 件 (reminder なし) と区別する。overdue → due_today → upcoming の順に **bucket 別 count +
   上位 items リンク** を表示。各 bucket の `truncated` が true なら「他に N 件」(N = count - items 長)
   を明示する (bucket 単位の silent truncation 回避、F-001)。

3. **ticket 一覧の期限強調** (`selectable-ticket-list.tsx`): 既存の amber 一律 chip を、backend 由来
   `referenceDate` との **文字列比較** (`YYYY-MM-DD` lexicographic) で 3 段階に強調する:
   - `overdue` (due_date < referenceDate): 赤 (danger)
   - `due-soon` (referenceDate <= due_date <= referenceDate + threshold): 橙 (attention)
   - `future` (due_date > referenceDate + threshold): neutral (既存の控えめ表示)
   `referenceDate` は一覧 endpoint (`TicketListResponse.reference_date`) **backend 算出値**を一覧
   page が `SelectableTicketList` に prop で渡す (F-002: "today" 権威を backend に一本化、Next.js
   server / client で独立算出しない)。bucket 判定は純粋関数 `dueDateBucket(due_date, referenceDate,
   thresholdDays)` (`new Date(due_date)` を介さず文字列比較で TZ ずれを排除、ADR-00034 と整合)。
   `referenceDate` が欠落/不正な response (schema parse 失敗) では一覧自体が degraded に倒れる
   (data 完全性: 不完全な基準日で誤分類しない)。

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
- **"today" の境界 (深夜、F-002 適用後)**: reminder endpoint と tickets list endpoint が **同一の
  backend helper `_today_jst()`** から `reference_date` を算出する (権威一本化)。Next.js server /
  client では "today" を独立算出しない。異なる HTTP request 間の sub-second 差は許容 (別画面であり、
  同一 backend clock のため境界での恒常的な画面間矛盾は起きない)。視覚強調・件数表示のみで write
  境界ではない。
- rollback は endpoint + schema + frontend section/emphasis の削除で完結 (DB 変更なし)。

## rollback 手順

1. `me.py` の `reminders` endpoint + `ReminderSummaryResponse` / `ReminderBucket` / `ReminderItem`
   schema を削除。`tickets.py` の `TicketListResponse.reference_date` を revert (F-002)。
2. frontend: `lib/api/reminders.ts` 削除、`dashboard/page.tsx` の reminder section 削除、
   `tickets-board.ts` の `reference_date` を revert、`selectable-ticket-list.tsx` の 3 段階強調を旧
   amber 一律 chip に revert、`tickets/page.tsx` の `referenceDate` prop 受け渡しを revert。
3. DB 変更なし (due_date カラムは ADR-00034 管理、本 ADR では触れない)。

## 実装対象ファイル

- `backend/app/api/me.py`: `reminders` endpoint + `ReminderSummaryResponse` / `ReminderBucket` /
  `ReminderItem` schema (active-scope + active-project + actionable + due_date NOT NULL +
  bucket window + bucket 別 cap 込み)。`TicketListResponse` に `reference_date` を追加する箇所は
  `backend/app/api/tickets.py` (F-002)。
- `backend/app/domain/...` (または共有 module): `compute_reminder_bucket(due_date, reference_date)`
  純粋関数 + `_today_jst(now=None)` helper (reminder endpoint と tickets endpoint が共有) +
  `REMINDER_UPCOMING_WINDOW_DAYS` / `REMINDER_BUCKET_LIST_LIMIT` 定数
- `backend/app/api/tickets.py`: `TicketListResponse.reference_date` 追加 (`_today_jst()` 由来、F-002)
- `backend/tests/...`: 純粋関数 unit (overdue/due_today/upcoming/window 境界) + `_today_jst` の
  JST 深夜境界 unit (F-002) + DB-gated 集約 integration (tenant/project 越境 negative + active-scope +
  archived 除外 + closed/cancelled 除外 + due_date NULL 除外 + bucket 別件数正確性 + bucket 別 capped
  truncation) + tickets list response の `reference_date` 整合
- `frontend/lib/api/reminders.ts`: zod schema (bucket 別) + `fetchReminders()` loader
- `frontend/lib/api/tickets-board.ts`: `TicketBoardResponseSchema` に `reference_date` 追加 (F-002)
- `frontend/app/(admin)/dashboard/page.tsx`: reminder section (fail-closed ok/error、bucket 別 +
  truncated 表示)
- `frontend/components/selectable-ticket-list.tsx`: 期限 3 段階強調 + 純粋関数 `dueDateBucket`
  (backend 由来 `referenceDate` prop)
- `frontend/app/(admin)/tickets/page.tsx`: 一覧 response の `reference_date` を list に prop で渡す
- frontend `__tests__`: reminders loader (zod fail-closed、bucket 欠落/型不正) + dueDateBucket 純粋
  関数 (overdue/soon/future 境界) + list 強調 component + dashboard reminder section (truncated 表示)

## テスト指針

- **純粋 bucket 関数** (`compute_reminder_bucket` / `dueDateBucket`): 固定 `reference_date` で
  overdue (due < today) / due_today (due == today) / upcoming (today < due <= today+threshold) /
  対象外 (due > today+threshold) / `days_until` 符号の境界値を網羅 (off-by-one を含む)。
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
  reminder endpoint の `reference_date` と tickets list endpoint の `reference_date` が
  **同一 helper 由来**であること (両 response が同じ基準日を返す integration 整合)。
- **raw secret なし**: response に raw secret が含まれないこと (`assert_no_raw_secret`)。
- **frontend loader fail-closed**: malformed (bucket 欠落 / count 型不正 / items 非配列 /
  reference_date 欠落) で `fetchReminders()` が throw し、dashboard が degraded 表示になること。
  bucket 別 truncation 表示 (`truncated` true で「他に N 件」) が出ること。
  一覧 response の `reference_date` 欠落で `loadTickets` が throw し一覧が degraded に倒れること。

## plan-review 採否記録 (codex-plan-review R1、2026-06-02)

codex-adversarial-review (mode=plan) R1 verdict=needs-attention、2 findings、いずれも **ADOPT**:

| id | severity | 指摘 | 判定 | 反映 |
|---|---|---|---|---|
| F-A7-PR-001 | HIGH | 全 bucket 横断の単一 `LIMIT` だと stale overdue が 200 件超で due_today / upcoming の items を完全に枯渇させ、count 非ゼロでも今日/近日のリンクが出ない bucket 単位の silent truncation | ADOPT | response を **bucket 別 (overdue/due_today/upcoming) の count + capped items + truncated** に再設計。各 bucket 独立 cap (`REMINDER_BUCKET_LIST_LIMIT`)。bucket 内 order を ADR 明文化。 |
| F-A7-PR-002 | MEDIUM | reminder endpoint と一覧 page が **独立時計**で Asia/Tokyo "today" を算出 → JST 深夜境界で同一 ticket の bucket が画面間で矛盾。"today" 権威が 2 箇所に分裂 | ADOPT | "today" 権威を **backend `_today_jst()` に一本化**。tickets list endpoint も `reference_date` を返し、一覧 page はそれを使う (Next.js server / client で独立算出しない)。JST 深夜境界 contract test 追加。 |

reject / defer: なし。R1 全 adopt 反映後、R2 で clean を確認してから proposed → accepted 昇格。
