---
id: "SP-037_shadow_aggregate_budget_cap"
type: "heavy"
status: "draft"
sprint_no: 37
created_at: "2026-06-13"
updated_at: "2026-06-13"
target_days: 1
max_days: 2
adr_refs:
  - "[ADR-00056](../adr/00056_shadow_aggregate_budget_cap.md)"
related_sprints:
  - "SP-029_shadow_mode"
risks:
  - "aggregate SUM query の perf (provider call ごと)"
  - "rolling window 境界での cap 余裕復活"
  - "per-run cap と aggregate cap の二重評価で block reason 不明瞭"
  - "production budget 非擾乱を破る (aggregate 評価が production budget を読む)"
---

## 目的

SP-029 (ADR-00055) の shadow **per-run** cap に加え、**per-tenant rolling-window の aggregate shadow cost cap** を実装し、多数の shadow run による総コスト無制限積み上げを防ぐ (SP-029 R3 residual / R12 で defer 済の項目)。

## 背景

SP-029 の `shadow_run_max_cost_usd` / `shadow_run_max_total_tokens` は 1 shadow run を上限化するが、N 個の手動 shadow run の aggregate は無制限。本 Sprint は per-tenant の window 集計 cap で aggregate を bound する。詳細は ADR-00056。

## 対象外

- per-project 粒度 aggregate / token aggregate cap (後続)
- shadow auto-trigger / A/B 比較 / provider bake-off / dashboard (後続)
- runtime worker driver / MCP・frontend 公開 (Sprint 6+ runtime 統合)
- DB schema 変更 (既存 index 再利用、migration なし)

## 設計判断 (plan-review R1 F1-F4 反映)

- config-based per-tenant rolling-window cap (ADR-00056 §採用案)。Budget table-based / all-time は却下。
- **集計源 (F3 cost-aligned)**: run.created_at でなく **`provider_responded` event の cost × event.created_at** を集計 (コスト発生時刻基準、長時間 run/retry でも window 整合)。cost 抽出は KPI `_PROVIDER_COST_EXPR` 再利用 + drift guard。
- **prospective projection (F1)**: preflight は `aggregate + projected_call_usd > cap` で課金前 block (post は保険)。
- **cross-run 排他 (F2)**: `pg_advisory_xact_lock(hashtext('shadow_aggregate'), tenant_id)` を aggregate 評価〜record の同一 transaction で取得し tenant 単位直列化 (lease は run 単位 single-flight、aggregate は cross-run なので別途)。
- **index (F4)**: partial index `agent_run_events (tenant_id, created_at) WHERE event_type='provider_responded'` を additive migration で追加。
- 評価順: kill switch → per-run USD → per-run token → **aggregate USD**。production budget 非擾乱維持 (shadow 行のみ集計、BudgetGuard 非参照)。

## 実装チケット / タスク一覧

1. config: `shadow_aggregate_max_cost_usd` (Decimal, default 10.00, gt=0) + `shadow_aggregate_window_hours` (int, default 24, gt=0)。
2. migration: partial index `agent_run_events (tenant_id, created_at) WHERE event_type='provider_responded'` (additive, down=drop index, deploy-aware cleanup)。
3. `usage_logger._shadow_aggregate_cost(session, *, tenant_id, window_start) -> Decimal` (provider_responded event cost SUM、event.created_at>=window_start、shadow run のみ)。
4. advisory lock helper + `_evaluate_shadow_block` / preflight に aggregate prospective 評価 (preflight: aggregate+projected > cap → block / post: aggregate > cap → block、budget_level `shadow_aggregate_cap`)。
5. test: unit (aggregate helper / projection / 評価順 monkeypatch) + DB-gated (window 内外 / projection / **concurrent 二重消費防止** / production 非混入 / 非擾乱 / cost-aligned / migration 可逆性 / drift guard)。

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer |
|---|---|---|
| per-tenant aggregate USD cap (preflight prospective + post) | ✓ | |
| cost-aligned event-based 集計 (F3) | ✓ | |
| cross-run advisory lock 直列化 (F2) | ✓ | |
| partial index migration (F4) | ✓ | |
| rolling window (config 化) | ✓ | |
| aggregate block の audit budget_level 明示 | ✓ | |
| per-project 粒度 / token aggregate cap | | ✓ |
| reservation ledger (advisory lock で代替) | | ✓ |

## 受け入れ条件

- [ ] preflight で `window aggregate + projected_call_usd > cap` なら provider 課金前 block。
- [ ] post-execution で cost 加算後 window aggregate > cap なら block。
- [ ] window 外 (event.created_at 古い) の cost は集計対象外、window 内 cost は run.created_at が古くても集計。
- [ ] **concurrent な同 tenant shadow run が同じ aggregate 余力を二重消費しない** (advisory lock、DB-gated concurrent test)。
- [ ] production run の cost は aggregate に混入しない (run_mode='shadow' filter)。
- [ ] aggregate 評価が production budget (BudgetGuard) を読まない (非擾乱)。
- [ ] per-run cap と二重評価で block reason が `budget_level` で区別可能。
- [ ] event cost 抽出が KPI `_PROVIDER_COST_EXPR` と一致 (drift guard test)。
- [ ] migration 可逆性 (index down→up、既存行非破壊)。

## 検証手順

```bash
uv run ruff check backend tests && uv run mypy backend
TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/runtime/test_shadow_run_cap.py tests/runtime/test_shadow_mode_db.py tests/ -q
```

## レビュー観点

- aggregate 評価が production budget 非擾乱を破らないか (shadow 行のみ集計)。
- window 集計の境界 (rolling) と timestamp (created_at) の妥当性。
- per-run cap との評価順序 + block reason 明確性。
- SP-029 不変条件 (16 status / KPI 除外 / 副作用隔離) を壊さないか。

## 残リスク

- aggregate SUM の perf (将来 shadow run 増大時に partial index / cache 増分)。
- rolling window 端での cap 余裕復活 (仕様として明示)。
- not user-reachable (driver 不在、foundational plumbing)。

## 次スプリント候補

- per-project aggregate / token aggregate cap。
- shadow runtime worker driver + MCP/frontend 公開 (Sprint 6+)。
- A/B 比較 / provider bake-off / telemetry baseline。

## 関連 ADR

- ADR-00056 (本 Sprint で proposed → accepted 昇格予定)。
- ADR-00055 (SP-029、本 Sprint が拡張する budget 設計の正本)。

## Review

(2026-06-13 起票) SP-029 完了・merged を受け、defer 済の aggregate cap を次 shadow 増分として draft 起票。ADR-00056 proposed。

(2026-06-13 plan-review R1) codex plan-review で 2 HIGH + 2 MEDIUM の設計欠陥を実装前に捕捉、全 adopt: F1 preflight prospective projection / F2 cross-run advisory lock 直列化 / F3 cost-aligned event-based 集計 / F4 partial index migration。これにより本増分は **当初想定 (config + 単純 SUM) より大幅に複雑化** (event-based 集計 + DB advisory locking + migration + projection)。

(2026-06-13 **deferred**、user 判断) plan-review で判明した通り、aggregate cap は migration + DB advisory locking を要する高リスク増分で、かつ **解く問題 (cross-run concurrency / 多数 shadow run) は runtime worker driver 不在の現状では発生しない** (shadow は MCP/REST 未公開・未駆動)。よって **実装は runtime driver 増分と同時** (concurrency が実際に発生する時点) へ defer。本 Pack + ADR-00056 (plan-review R1 反映済) は **実装 ready な planning として保存** し、runtime 統合時に plan-review R2 → ADR accepted → 実装する。status は draft 維持 (未着手)。
