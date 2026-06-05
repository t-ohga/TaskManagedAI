---
id: "SP-028_webhook_ux"
type: "light"
status: "completed"
sprint_no: 28
created_at: "2026-05-26"
updated_at: "2026-06-05"
target_days: 3
max_days: 5
adr_refs:
  - "[ADR-00050](../adr/00050_github_webhook_events.md)"
---

## 目的

- GitHub webhook event (PR / CI) の **parse + persist + read API + activity view** (ADR-00050)
- (当初目的の toast / CI live update / PR timeline 統合のうち) 本 Sprint scope = **read-only activity view +
  polling refresh**。real-time SSE / toast / 最新 status projection は follow-up (ADR-00050 §却下案 / frontend §)

## 対象外

- P0 invariant の変更 (16 status / 3 blocked_reason / 10 ContextSnapshot columns は不変)
- 破壊的 migration (additive のみ)
- **既存 webhook ingress security contract の変更** (verifier / secret resolver / replay store は不変、
  ADR-00050 §前提・R2-F-001/F-002/F-005)。webhook parse/persist は verification 後の **best-effort enrichment**
- real-time push (SSE) / toast / 最新 CI status projection (follow-up ADR)

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

(2026-06-04 台帳監査) **部分実装**。`backend/app/api/github_webhooks.py` で GitHub webhook **受信** は実装済だが、SP-028 の目的である UX 層 (webhook event の toast 通知 / CI status live update / PR timeline 統合) は未実装。受け入れ条件も全て未チェック。commit `1b9cad6` (#261) の一括 status flip 対象。実態に合わせ `partial_skeleton` へ訂正 (seed→in_progress、bare `partial` は未対応のため、Codex App F-L1)。残 UX 着手時に frontend 配線 + test。

(2026-06-05、PR #325 merged → **completed**) ADR-00050 に基づき read-only activity view scope を実装完遂。

- **ADR-00050 accepted_at: 2026-06-05** (codex-plan-review R1 15 + R2 5 + R3 0 = 20 findings 全 adopt、収束)。R2 で「厳密 no-loss は既存 ingress security replay store 改修=別 ADR」と判明し **best-effort read-only enrichment、security 境界不変** に reframe (user 承認)。
- 実装: migration 0044 + ORM + parser (allowlist 抽出 + 値 redaction Cc/Cf strip + tenant-scope repo lookup + dedup hash anomaly + best-effort persist) + best-effort parse hook + project-scoped read endpoint (owner gate) + frontend (pure domain + fail-closed loader + activity view + nav)。
- codex-adversarial-review R1 (2 findings: F-1 owner gate / F-2 zero-width redaction bypass、全 adopt) → R2 **approve (clean)**。
- 受け入れ条件: 実装完了 + lint/typecheck/test PASS (✅、my files ruff/mypy clean、23 unit + 2 wiring + 12 vitest pass、DB-gated 12 は CI)、既存 Hard Gate/KPI regression なし (✅、ingress 不変・既存 16 webhook test 維持)、Review 章更新 (✅ 本記録)。
- **scope 限定 (in-scope のみ completed)**: 当初目的の toast / CI status live update (最新 status projection) / real-time SSE は **follow-up** (ADR-00050 §frontend / 却下案)。本 Sprint は read-only activity view + polling refresh を completed とする。
- 残: ブラウザ実機検証 (activity view 表示) は user 委譲。
