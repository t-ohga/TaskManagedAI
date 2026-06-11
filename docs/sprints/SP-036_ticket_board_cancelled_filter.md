---
id: "SP-036_ticket_board_cancelled_filter"
type: "heavy"
status: "draft"
sprint_no: 36
created_at: "2026-06-12"
updated_at: "2026-06-12"
target_days: 1
max_days: 2
adr_refs:
  - "[ADR-00054](../adr/00054_ticket_board_default_exclude_cancelled.md)"
related_sprints: []
risks:
  - "count/truncation 表示が server filter 後の値とズレて誤表示"
  - "status と exclude_cancelled の precedence ミス"
  - "backend filter 漏れで cancelled が board に leak"
---

## 目的

ticket 看板/一覧 (board) の既定表示から「中止 (cancelled)」を除外し、ステータスフィルターで「中止」を選んだ時のみ表示する (#7)。cancel dialog の「看板から非表示」と実挙動の矛盾を解消する。証跡 access は維持。**root fix として server-side filter** を採用し、frontend-only client filter の cap 越え誤隠蔽 (adversarial R1 HIGH) を構造的に避ける。

## 背景

ADR-00054 §背景 参照。`GET /tickets` は全件 in-memory 取得 → in-memory paginate。client-side 除外は 200 行 cap の後に効くため >200 ticket project で非 cancelled を誤隠蔽。`list_in_project` の caller は REST endpoint のみ、MCP は独自 SQL で非影響。

## 対象外

- search / priority / range の client-side filter (pre-existing、本 Sprint では server 化しない)。
- MCP `bridge_ticket_list` / `bridge_ticket_list_all` の cancelled 扱い (AI 向けで board と別 concern)。
- ticket 一覧の DB 全面 paginate 化 (scope 過大)。

## 設計判断

ADR-00054 採用案 B (additive server-side param)。`GET /tickets` に `status: TicketStatus | None` + `exclude_cancelled: bool = False` を additive 追加、pagination 前に filter。board は既定→`exclude_cancelled=true`、StatusFilter=X→`status=X`。client-side status filter + cancelled 除外を撤去。

## 実装チケット / タスク一覧

1. backend: `list_tickets_endpoint` に `status` / `exclude_cancelled` Query param + tag filter 後・pagination 前の filter。precedence (`status` 優先)。`TicketListResponse` に `total_unfiltered`(tag 後・status 前件数)追加。**(R4) 内部変数は `ticket_status` + `Query(alias="status")` で `fastapi.status` shadow を回避**。
2. backend test: ticket list contract test に status exact / exclude_cancelled / precedence / param なし非破壊 / pagination 相互作用 / `total_unfiltered`(中止のみ project で total=0・total_unfiltered>0)/ **(R4) invalid・cross-project tag が status/exclude_cancelled 併用後も 404 のまま (500 退行しない) regression** を追加。
3. frontend: `loadTickets` に status/excludeCancelled 引数 + query、`TicketBoardResult` に `totalUnfiltered`/`truncated` を未 tag load でも反映。
4. frontend: `page.tsx` の client-side status filter + cancelled 除外撤去、param 渡し、`truncated` 時は常に不完全警告、純粋既定 view 限定の cancelled-only-empty hint。
5. frontend: dialog copy / 「完了」列 hint 整合 (実装済)。
6. frontend test: 既定 cancelled 非表示 / StatusFilter=cancelled 表示 / **status=cancelled total=201 で truncation 警告** / 純粋既定 view で中止のみ→hint(silent empty 回避)+真の空との区別 / **status=blocked 0 件で cancelled-only hint を出さない negative** / **q/priority/range 指定で 0 件でも cancelled-only hint を出さない negative** / truncated 時の一律警告。

## must_ship / defer_if_over_budget 対応表

| 項目 | 区分 |
|---|---|
| backend additive param + pagination 前 filter | must_ship |
| frontend param 渡し + client filter 撤去 | must_ship |
| backend/frontend 回帰 test | must_ship |
| dialog copy / hint 整合 | must_ship |
| count/truncation 表示の厳密整合 | must_ship (誤表示は誤誘導のため) |
| search/priority/range の server 化 | defer (別 Sprint) |

## 受け入れ条件

- 既定 board (statusFilter 未指定) に cancelled が出ない (>200 ticket でも server filter で正しい)。
- StatusFilter=「中止」で cancelled が表示され証跡参照できる。**cap 越え (cancelled 201+) は全件保証せず**、先頭 page + truncation 警告で部分表示を明示する (status=cancelled total=201 の test)。
- StatusFilter=他 status に cancelled が混ざらない。
- param なしの `GET /tickets` は従来どおり全 status を返す (非破壊、MCP 非影響)。`total_unfiltered` は追加 field のみ (param なしでは `== total`)。
- **(R1/R3 HIGH) truncation 警告は `total > items.length` の時は常に出す** (default / status=中止 / client filter を一律カバー、cap 越えを silent に隠さない)。
- **(R2/R3 HIGH) cancelled-only-empty hint は「純粋な既定 view」(`statusFilter` 未指定 AND `exclude_cancelled=true` AND `q`/`priority`/`range` 未指定 AND `!truncated`) に限定**:
  - 純粋既定 view で `total=0 && total_unfiltered>0` → 「現在の表示条件では中止のみ、フィルターで表示」hint (silent empty 回避、文言は scope 限定で project 全体を断定しない)。
  - 純粋既定 view で `total=0 && total_unfiltered=0` → 通常の空表示。
  - **status=X 0 件 (例 blocked) / q・priority・range で 0 件 / truncated の時は cancelled-only hint を出さない** (negative test 必須)。
- **「中止 N 件は非表示」hint は採用しない** (server count と client filter 適用後の実画面が食い違うため。証跡 access は dialog + StatusFilter で担保)。

## 検証手順

- `uv run ruff check backend tests` + `uv run mypy backend` + `uv run pytest backend/tests`(ticket list contract)。**DB (Docker) 必須**。
- `pnpm exec tsc --noEmit` + `pnpm exec eslint app components lib __tests__ --max-warnings=0` + `pnpm exec vitest run`。
- adversarial review (R1 の cap finding が server-side で閉じたことを確認)。
- 実機: board 既定で中止非表示 / StatusFilter=中止 で表示 / 中止のみ project で count 表示。

## レビュー観点

- additive param が既存挙動を破壊しないか (param なし = 全 status)。
- filter が pagination 前か (cap 越えを正しく扱うか)。
- precedence (`status` vs `exclude_cancelled`)。
- count/truncation の再定義が誤表示を生まないか。
- tenant/project boundary を壊さないか (filter は既存 where に追加するのみ)。

## 残リスク

- search/priority/range の cap 越え限界は残る (pre-existing、対象外)。別 Sprint で server 化を検討。
- 全件 in-memory 取得自体の scalability は pre-existing (本 Sprint で変えない)。

## 次スプリント候補

- 全 board filter (search/priority/range) の server-side 化 + DB paginate。

## 関連 ADR

- ADR-00054 (本 Sprint で proposed → accepted 昇格)。

## Review

- ADR-00054 accepted_at: 2026-06-12 (実装着手直前に proposed→accepted 昇格、§12 準拠)。
- plan-review (codex-adversarial-review, working-tree): R1 HIGH (total_unfiltered 追加) / R2 HIGH+MED (hint を既定 view scope + tag scope 文言) / R3 HIGH×2 (server count ≠ client-filtered 実画面 → 純粋既定 view 限定 + 一律 truncation 警告 + cap 越え全件保証撤回 + N-hidden hint 撤去) / R4 HIGH (`status` shadow → `ticket_status` + alias + 404 regression) → READY。全 findings adopt。
- (実装後に追記: code adversarial round、検証結果 frontend vitest/tsc/lint + backend pytest)。
