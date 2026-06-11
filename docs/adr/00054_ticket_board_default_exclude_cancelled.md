---
id: "ADR-00054"
title: "Ticket board list の既定 cancelled 除外 (server-side status filter)"
status: "accepted"
date: "2026-06-12"
authors:
  - "Claude (orchestrator) / user"
related_sprints:
  - "SP-036_ticket_board_cancelled_filter"
supersedes: null
superseded_by: null
---

ADR Gate Criteria #3 (API 契約 / event schema) に該当する。`GET /api/v1/projects/{project_id}/tickets` に server-side status filter param を additive に追加する判断を記録する。実装前に proposed として作成し、plan-review + 合意後に accepted へ更新する。

最終更新: 2026-06-12

## 背景

- 決定対象: ticket 看板/一覧 (board) の既定表示から「中止 (cancelled)」を除外し、ステータスフィルターで「中止」を選んだ時のみ表示する (#7)。証跡 access は残す。
- 関連 Sprint: SP-036_ticket_board_cancelled_filter
- 前提 / 制約:
  - cancel dialog (`ticket-delete-button`) は既に「看板から非表示になります」と表示しており、実挙動 (`STATUS_TO_KANBAN` で `cancelled: "done"`) と矛盾している。
  - `GET /tickets` → `list_tickets_endpoint` → `repo.list_in_project()` は **SQL limit なしで全 ticket をメモリに取得**し、endpoint が `tickets[offset:offset+limit]` で in-memory paginate する (`limit` max 200)。
  - frontend board は status / search / priority / range を **client-side filter** している (`tickets-board.ts` は `limit` / `tag_id` のみ backend へ渡す)。
  - **adversarial review (R1 HIGH)**: 既定除外を client-side (応答 200 行 cap の後) で行うと、>200 ticket の project で first page が cancelled 優勢な場合、cap 越えの非 cancelled ticket が未 fetch のまま除外され、空/誤誘導 board (`0 / 200`) になる。client-side では根本解決できない。
  - `list_in_project` の caller は REST endpoint **1 箇所のみ**。MCP `bridge_ticket_list` は **独自 raw SQL** で REST endpoint を経由しないため、本変更は MCP に波及しない (board のみ影響)。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: frontend-only client filter | 応答後に client で cancelled 除外 | backend 変更不要 / ADR 不要 | **R1 HIGH**: cap 越えの非 cancelled を誤って隠す (>200 ticket project)。user の「根本的に良い設計」に反する |
| B: additive server-side param (採用) | `status` (exact filter) + `exclude_cancelled` (board default) を `GET /tickets` に additive 追加。pagination **前**に全件 (in-memory) を filter | cap 問題を根本解消 (全件から抽出) / additive で既存挙動非破壊 / board のみ影響 | API 契約変更 (ADR Gate) / count・truncation 意味の調整が必要 |
| C: default 挙動変更 (param なし既定除外) | endpoint の default を cancelled 除外に変更 | param 不要でシンプル | 明示性が低い / 既存 consumer (将来) の暗黙前提を破壊し得る (board のみとはいえ将来 risk) |
| D: 全 status filter を server-side 化 + 全件 paginate 廃止 | DB 側 WHERE + LIMIT/OFFSET に全面移行 | 大規模に最適 | scope 過大 (search/priority/range も巻き込む)、#7 を超える |

## 採用案

- 採用: **B (additive server-side param)**
- 理由: cap 問題を根本解消しつつ (pagination 前に全件 in-memory から filter)、additive param で既存挙動を非破壊に保つ。default 挙動変更 (C) より明示的で将来 consumer への risk が小さい。全面 DB paginate (D) は #7 を超える scope。
- 実装 Sprint: SP-036_ticket_board_cancelled_filter
- 実装対象ファイル:
  - `backend/app/api/tickets.py` (`list_tickets_endpoint` に `status` / `exclude_cancelled` Query param + tag filter 後・pagination 前に filter 適用。`TicketListResponse` に `total_unfiltered: int` 追加し、tag filter 後・status filter 前の件数を返す)
  - `frontend/lib/api/tickets-board.ts` (`loadTickets` に status / excludeCancelled 引数 + query param 付与、`TicketBoardResult` に `totalUnfiltered` / `truncated` を未 tag load でも反映)
  - `frontend/app/(admin)/tickets/page.tsx` (client-side status filter + cancelled 除外を撤去し backend へ param を渡す。count/truncation 表示の整合 + 中止のみ project の hint + truncated 警告)
  - `frontend/components/ticket-delete-button.tsx` (dialog copy 整合、実装済)
- 実装ガイダンス:
  - **param 契約**: 外部 query 名は `status` (exact filter、precedence 最優先) / `exclude_cancelled: bool = False` (`status` が None の時だけ適用)。両立時は `status` 優先。default (param なし) は **従来どおり全 status** (非破壊)。
  - **(plan-review R4 HIGH) `status` shadow 回避**: 現行 `list_tickets_endpoint` は `from fastapi import ... status` の `status.HTTP_404_NOT_FOUND` で tag invalid を 404 に写像している。引数名 `status` は関数内で `fastapi.status` module を shadow し、`TagNotFoundError` 経路を 500 に退行させる。よって **内部変数は `ticket_status: TicketStatus | None = Query(default=None, alias="status")`** とする (外部契約は `status` のまま)。`exclude_cancelled: bool = Query(default=False)`。実装後 `grep -n "status\." backend/app/api/tickets.py` で `fastapi.status` 参照が壊れていないことを確認する。
  - **filter 位置**: `list_in_project()` 取得後 + tag filter 後 + `total = len(...)` / `paginated` の **前**。`total` は filter 後件数。
  - **board の呼び方**: 既定表示 → `exclude_cancelled=true` (status なし)。StatusFilter=X (cancelled 含む) → `status=X`。これで cancelled 除外も cancelled-only 表示も cap 越えを正しく扱う。
  - **count metadata**: `TicketListResponse` に `total_unfiltered: int` を追加 = **tag filter 後・status/exclude_cancelled filter 前**の件数。`total` は **全 server filter 後**の件数。param なし call では `total_unfiltered == total` (非破壊、追加 field のみ)。
  - **truncation 警告 (plan-review R1/R3 HIGH fix、一律)**: `truncated = total > items.length` を **全 load (tag 有無・status 有無を問わず)** `TicketBoardResult` に反映し、**truncated なら常に**「全 {total} 件中 先頭 {items.length} 件のみ読み込み。絞り込み・件数は不完全な可能性があります」警告を出す。これで「default view の cap 越え」「status=中止 が 201 件以上」「client filter を truncated page に適用」を **一律にカバー**する (cap 越えを silent に隠さない)。**`StatusFilter=中止` は cap 越え全件表示を保証せず**、先頭 page + 本 truncation 警告で部分表示を明示する (証跡参照は filter + 警告で担保。完全な全件 paginate は別 Sprint)。
  - **cancelled-only-empty hint (plan-review R2/R3 HIGH fix、純粋既定 view 限定)**: server count は client-side filter (q/priority/range) 適用後の実画面を表せないため、本 hint は **「純粋な既定 view」= `statusFilter` 未指定 AND `exclude_cancelled=true` AND `q`/`priority`/`range` すべて未指定 AND `!truncated`** の時に限定する。この条件下でのみ表示 items は server `total` (非 cancelled) と一致し、`total_unfiltered` (=全件、tag scope) が cancelled 込み全件を表す:
    - `total==0 && total_unfiltered>0` → **「現在の表示条件では中止チケットのみです。ステータスで『中止』を選ぶと表示されます」** (silent empty にしない。tag 指定中は「現在の表示条件」scope で project 全体を断定しない)。
    - `total==0 && total_unfiltered==0` → 通常の「チケットがありません」。
    - 上記以外 (statusFilter 指定 / q・priority・range のいずれか指定 / truncated) → cancelled-only hint を **出さない**。特に `status=X` で 0 件 (例 blocked) は「該当ステータスのチケットがありません」、client filter で 0 件は通常の空表示。
  - **「中止 N 件は非表示」hint は採用しない** (server count と client filter 適用後の実画面が食い違い得るため、count 整合を単純化。証跡 access は dialog copy + StatusFilter で担保)。
  - **search/priority/range の client filter は本 ADR の対象外** (pre-existing。上記 truncation 警告で不完全を可視化する。完全な server 化は別 Sprint)。証跡: cancelled は DB に残り `status=cancelled` で常時参照可能。
- テスト指針:
  - backend: `uv run pytest backend/tests` の ticket list contract test に negative/boundary 追加 — `status=X` で exact filter / `exclude_cancelled=true` で cancelled 除外 / 両立時 `status` 優先 / param なしは全 status (非破壊) / pagination との相互作用 (filter 後に offset/limit) / **(R4) invalid・cross-project tag_id が `status`/`exclude_cancelled` 併用後も 404 のまま (500 退行しない) regression**。
  - frontend: board が param を正しく渡すこと、既定で cancelled 非表示、StatusFilter=cancelled で cancelled 表示、count/truncation 表示の整合 (vitest)。
  - `uv run ruff check backend tests` + `uv run mypy backend` + `pnpm exec tsc --noEmit` + `pnpm exec eslint`。

## 却下案

- A (frontend-only): adversarial R1 HIGH の cap 越え誤隠蔽を構造的に解決できない。user の「そのばしのぎではなく」方針に反する。
- C (default 挙動変更): board のみ consumer とはいえ、param なしで暗黙に挙動を変えると将来 consumer / debug 時に意図が読めない。additive の方が明示的で安全。
- D (全面 DB paginate 化): search/priority/range/tag を含む全 filter の server 化は #7 の scope を大きく超え、回帰 risk が高い。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| 中止のみ project と真の空 project が区別できず silent empty 誤表示 (plan-review R1 HIGH) | frontend vitest (中止のみ project の hint test) + 実機 | `total_unfiltered` を response に追加し `total==0 && total_unfiltered>0` を hint 表示。test で固定 |
| count/truncation 表示が server filter 後の値とズレて誤表示 | frontend vitest (count 表示 test) + 実機確認 | `total`/`total_unfiltered`/`truncated` を server filter 後で再定義し test で固定 |
| truncated page に client filter (search/priority/range) 適用で 0/M 誤表示 (plan-review R1 HIGH) | frontend vitest (truncated + filter 警告 test) | `truncated` を非 tag load でも反映し、client filter 適用時に不完全警告 |
| cancelled-only hint が status filter 0 件 (例 blocked) で誤発火 (plan-review R2 HIGH) | frontend vitest (status=blocked 0 件 negative test) | hint を **既定 view (statusFilter 未指定 + exclude_cancelled) に限定**、status=X 0 件は別文言 |
| tag 指定中に「project 中止のみ」と過剰断定 (plan-review R2 MEDIUM) | frontend vitest (tag_id + cancelled-only case) | 文言を「現在の表示条件」scope に限定 (project 全体を断定しない) |
| `status` param が `fastapi.status` を shadow し tag 404 が 500 退行 (plan-review R4 HIGH) | backend contract test (invalid tag + status 併用で 404 維持) + `grep status.` | 内部変数 `ticket_status` + `Query(alias="status")`、`fastapi.status` を温存 |
| `status` と `exclude_cancelled` 両立時の precedence ミス | backend contract test (両立 case) | `status` 優先を明文化 + test |
| 既定挙動を誤って変えて MCP / 他 consumer に波及 | `list_in_project` caller grep (現状 REST のみ) + MCP は独自 SQL を確認済 | additive param (default 非破壊) を厳守 |
| backend filter 漏れで cancelled が board に leak | backend contract test + frontend vitest | server-side filter を choke point 化、frontend client filter は撤去 |

## rollback 手順

1. rollback trigger: board の count 誤表示 / cancelled 表示漏れ / 既存 board 回帰が実機で確認された場合。
2. rollback step: `tickets.py` の param + filter を revert、`tickets-board.ts` / `page.tsx` を client-side filter に戻す (本 PR を revert)。API は param を無視するだけなので後方互換、DB migration なし。
3. verification: board 既定表示で全 status が出る (従来挙動) + `pnpm exec vitest` + `uv run pytest backend/tests` の ticket list test green を確認。
