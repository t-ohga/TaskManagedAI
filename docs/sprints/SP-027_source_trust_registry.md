---
id: "SP-027_source_trust_registry"
type: "light"
status: "draft"
sprint_no: 27
created_at: "2026-05-26"
updated_at: "2026-06-04"
target_days: 3
max_days: 5
---

## 目的

- Research 高度化: source trust score + citation render mode + provenance 可視化

## 対象外

- P0 invariant の変更 (16 status / 3 blocked_reason / 10 ContextSnapshot columns は不変)
- 破壊的 migration (additive のみ)

## 受け入れ条件

- [ ] 実装完了 + lint / typecheck / test PASS
- [ ] 既存 Hard Gate / KPI に regression なし
- [ ] Sprint Pack Review 章更新

## 検証手順

```bash
uv run ruff check backend tests && uv run mypy backend
cd frontend && pnpm typecheck && pnpm lint && pnpm test
uv run pytest -q
```

## 残リスク

- ADR Gate 該当の場合は heavy Pack 化 + ADR 起票が必要

## Review

(2026-06-04 台帳監査) **未実装**。本 Pack は `status: "completed"` だったが、source trust registry に対応する実装は `backend/app` / `frontend` に存在しない (grep `source_trust` / `trust_registry` = 0 件)。受け入れ条件チェックボックスも全て未チェックのまま。commit `1b9cad6` (#261、2026-05-26) が 9 つの P1 Pack を実装を伴わず `status: draft → completed` へ一括変更した over-claim。実態に合わせ `draft` へ訂正。P1 (P0.1 より先の将来スコープ) であり、着手時に ADR-first + 実装 + test が必要。
