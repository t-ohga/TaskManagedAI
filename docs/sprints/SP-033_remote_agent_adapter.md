---
id: "SP-033_remote_agent_adapter"
type: "light"
status: "partial"
sprint_no: 33
created_at: "2026-05-26"
updated_at: "2026-06-04"
target_days: 5
max_days: 8
---

## 目的

- Codex App Server + Claude Agent SDK + Remote Control adapter + MCP gateway 拡張

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

(2026-06-04 台帳監査) **部分実装 (P0.1 deny-only stub のみ)**。`backend/app/services/remote_agent_gateway/deny_only.py` の deny-only gateway stub は実装済 (ADR-00013 Remote Agent Extension Point boundary 準拠の P0.1 deny-only 方針)。ただし Pack 目的の full adapter (Codex App Server / Claude Agent SDK / Remote Control adapter / MCP gateway 拡張) は未実装・将来スコープ。受け入れ条件も全て未チェック。commit `1b9cad6` (#261) の一括 status flip 対象。実態に合わせ `partial` へ訂正。
