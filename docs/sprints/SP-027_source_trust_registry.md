---
id: "SP-027_source_trust_registry"
type: "heavy"
status: "completed"
sprint_no: 27
created_at: "2026-05-26"
updated_at: "2026-06-09"
adr_refs:
  - "[ADR-00053](../adr/00053_source_trust_registry.md)"
related_sprints:
  - "SP-032_research_advanced"
  - "SP-010_research_evidence"
risks:
  - "tenant-scoped evidence_sources の owner gate コンテキスト"
  - "provenance view の secret-shaped id/type redaction + size cap"
  - "manual trust_level/trust_score の組合せ invariant"
---

> SP-010 BL-0121 placeholder (source trust registry) の P1 activation。SP-032 の domain_trust_registry を
> 入力に per-source trust を派生し、citation render mode + provenance 可視化を追加する (ADR-00053)。

## 目的

- `evidence_sources.trust_level` / `trust_score` (per-source manual trust) を additive に追加
- **effective source trust 派生** (manual > domain 由来 (SP-032) > 未設定/invalid) を read-only で提供
- **provenance 構造化 view** (raw 非展開、ProvBundle validate + secret redact + size cap)
- **citation render mode** (compact / detailed / provenance、device-local UI preference)
- owner-gated source trust set + research 詳細 UI 拡張

## 背景

- SP-010 BL-0121 で `evidence_sources.trust_level` / `trust_score` を P1 defer placeholder として明記。
- SP-032 (ADR-00052) で domain-level `domain_trust_registry` を landing。SP-027 はその上に per-source を載せる。
- `prov_validator.ProvBundle` (W3C PROV-DM、SP-010) を provenance 構造化に reuse。
- `domain_from_url` / `DomainTrustRepository` / `redact_if_secret` (SP-032) を reuse。

## 対象外

- P0 invariant 変更。破壊的 migration (additive のみ: nullable 列 2 件)。
- AI による source trust 自動スコアリング (deterministic manual + domain 由来のみ)。
- research-advanced (ADR-00052) endpoint の契約変更 (別 endpoint で追加)。
- per-project / per-actor の citation render mode DB 設定 (device-local UI preference)。
- raw provenance_json の表示 (構造化 + redact のみ)。

## 設計判断

ADR-00053 採用案 + R1 反映を参照。要点:

- `trust_level` は SP-032 `TrustTier` reuse (5+ source enum integrity)。manual override は level 必須、
  score 任意、両 null = clear、score 単独 = 400 (DB CHECK `trust_level IS NOT NULL OR trust_score IS NULL`)。
- effective 派生: manual > domain (exact hostname、SP-032 secret-shaped reject 継承) > none/invalid。
- provenance view: invalid → `{valid:false, reason:"invalid_schema"}` (raw 非露出)、valid → 構造 (全 string
  redact、relation 5-enum、nodes≤200/relations≤500/str≤128 + truncated)。
- citation render mode: default `detailed`、SSR default + client localStorage (SecurityError-safe)。
- 認可: trust write = P0 owner (tenant-level)、read = 認証 tenant actor + research_task/claim 404 確認、
  cross-tenant 404。audit 固定 allowlist (id/action/trust_level/trust_score/origin)。

## 実装チケット

| BL ID | 内容 | depends_on |
|---|---|---|
| BL-S027-1 | migration 0046 (evidence_sources.trust_level + trust_score) + model + schema + CHECK | ADR-00053 |
| BL-S027-2 | service: source_trust (effective 派生) + provenance_view (構造化 + redact + cap) (純/read) | BL-S027-1 |
| BL-S027-3 | repository (trust set) + API: PATCH evidence-sources/{id}/trust (owner) + source-trust read + provenance read + audit | BL-S027-1, BL-S027-2 |
| BL-S027-4 | frontend: citation render mode (device-local) + per-source trust badge + manual set + provenance viz | BL-S027-3 |
| BL-S027-5 | tests: introspection / migration / repository / service 純関数 / API contract / owner wiring / cross-tenant / redaction / vitest | 全 BL |

## タスク一覧

- [x] ADR-00053 plan-review (codex-plan-review R1、18 findings 全 adopt) + accepted 昇格
- [x] BL-S027-1: migration 0046 + model + schema
- [x] BL-S027-2: services (source_trust / provenance_view)
- [x] BL-S027-3: repository + API + audit
- [x] BL-S027-4: frontend
- [x] BL-S027-5: tests
- [x] codex-adversarial-review R1-R3 clean (R3 approve、CRITICAL=0 / HIGH=0)
- [x] Sprint Exit: Pack `## Review` + ADR-00053 accepted_at 記録

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| evidence_sources.trust_level + trust_score + CHECK | ○ | — |
| effective source trust 派生 (read-only) | ○ | — |
| provenance 構造化 view (redact + cap) | ○ | — |
| owner-gated source trust set + audit | ○ | — |
| citation render mode (device-local) | ○ | — |
| cross-tenant / owner gate negative test | ○ | — |
| frontend: trust badge + render mode + provenance viz | ○ | — |
| AI 自動スコアリング | × | 対象外 |

## 受け入れ条件

- migration `alembic upgrade head` + `alembic check` drift 0
- `trust_level` 5+ source (TrustTier) 整合、`trust_score` 範囲 + `trust_level IS NOT NULL OR trust_score IS NULL` CHECK
- effective 派生が manual > domain > none > invalid を deterministic に返す (secret-shaped host → invalid)
- provenance view が valid → 構造 (全 string redact)、invalid → `{valid:false}` (raw 非露出)、size cap 動作
- trust write が owner gate を通り、service/agent/non-owner は 403、cross-tenant は 404
- audit payload が固定 allowlist (url/domain/locator/raw なし)
- frontend: render mode 切替 + trust badge (origin 明示) + provenance viz、fail-closed loader
- lint / typecheck / test 全 PASS、既存 Hard Gate / KPI regression なし

## 検証手順

```bash
uv run alembic upgrade head && uv run alembic check
uv run pytest tests/research_evidence/ tests/services/research/ tests/db/ tests/api/ tests/security/ -q
uv run ruff check backend tests && uv run mypy backend
cd frontend && pnpm typecheck && pnpm lint && pnpm test
```

## レビュー観点

- evidence_sources tenant-scoped + owner gate (P0 owner tenant-level、cross-tenant 404)
- effective 派生の origin (manual/domain/none/invalid) + domain exact match (SP-032 継承)
- provenance raw 非露出 + 全 string redact + size cap (DoS)
- audit 固定 allowlist (raw secret / url / domain / locator なし)
- citation render mode device-local + SecurityError-safe
- research-advanced (ADR-00052) 契約を変更していない

## 残リスク

- domain 由来 trust 精度は registry 整備度依存 → origin を UI 明示
- provenance id/type の過剰 redaction (機能影響なし、表示のみ)
- render mode device-local (multi-device 非同期) → 非監査 preference として許容

## 次スプリント候補

- Sprint 11.5: source trust の Observability metric
- 将来: per-actor / per-project citation render mode、source trust の evaluator 自動付与

## 関連 ADR

- ADR-00053 (Source Trust Registry) — 本 Sprint で proposed → accepted
- ADR-00052 (Research Advanced) — domain_trust_registry を入力に派生
- ADR-00002 (DB schema) / ADR-00003 (API contract)

## Review

### 実装完了記録 (2026-06-09、ADR-00053 accepted_at: 2026-06-09)

- **ADR-00053**: codex-plan-review R1 で 18 findings 全 adopt (tenant-scoped owner gate / 404・403 /
  manual trust invariant / domain exact match / provenance redaction + size cap / citation render mode /
  audit allowlist) → accepted。
- **backend**: migration 0046 (evidence_sources.trust_level + trust_score、TrustTier reuse、
  score-requires-level CHECK)、effective source trust 派生 (manual > domain exact > none/invalid、
  secret-shaped host reject 継承)、provenance 構造化 view (ProvBundle validate + 全 string redact +
  pre-validation size guard)、owner-gated PATCH trust + source-trust read + claim provenance read + 固定
  allowlist audit。
- **frontend**: citation render mode (compact/detailed/provenance、device-local SecurityError-safe) +
  per-source trust badge (origin 明示) + owner 手動設定 + provenance lazy viz。
- **検証**: ruff/mypy clean (自分の file、5 mypy は pre-existing mcp)、backend no-DB 98 pass + DB-gated
  16 skip (CI)、frontend typecheck / eslint / 499 vitest / next build green。

### codex-adversarial-review (R1-R3、計 5 findings adopt)

- **R1** (1 HIGH + 2 MEDIUM adopt): ① provenance size cap が validation 後 → pre-validation cap に移動
  (extreme oversize → too_large)、② audit payload が 5-field allowlist 超過 → `build_trust_audit_payload`
  で narrow + exact-key test、③ manual score 空欄 silent null → defaultValue で round-trip。
- **R2** (2 HIGH adopt): ① provenance を全 claim SSR prefetch → mode=provenance のとき client lazy 取得
  (Server Action、hard cap 50 claim + concurrency 8)、② PATCH omitted score が silent null →
  `model_fields_set` で omitted/explicit-null 区別 + 既存 score 保持 (`resolve_trust_write`、unit test)。
- **R3**: **approve / no material findings** (provenance/trust DoS・trust_score 消失・owner gate bypass・
  cross-tenant・secret 露出に外部到達可能な迂回なし)。

### 残課題 / follow-up (機能削減ではない)

- DB-gated test (5 件) は host に postgres がないため CI 実行。on-host は unit (28) + offline migration SQL。
- provenance lazy viz は先頭 50 claim cap (research_task の claim 数 bounded、超過は「先頭 N 件」明示)。
- citation render mode は device-local 非監査 preference (multi-device 非同期は許容、将来 per-actor 拡張可)。
