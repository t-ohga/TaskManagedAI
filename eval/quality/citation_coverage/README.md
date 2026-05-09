# AC-KPI-04: citation_coverage

| 項目 | 内容 |
|---|---|
| KPI ID | AC-KPI-04 |
| metric | `citation_coverage` |
| 達成基準 | Deep Research の claim → evidence → citation 紐付け率 0.9 以上 |
| source | `input.sample_claims[].citation_ids` |
| 関連 Sprint | Sprint 4 / 10 / 11 / 12 |
| owner skill | `quality-suite` |
| owner agent | `code-reviewer` |

## fixture 構成

| split | 用途 | gitignore |
|---|---|---|
| `public_regression/` | 公開 fixture、PR レビューで参照可 | tracked |
| `private_holdout/` | 期待値漏えい禁止、別 vault 管理 | tracked (`.gitkeep` + README のみ、内容は別 path) |
| `adversarial_new/` | 月次追加、append-only | tracked (`.gitkeep` + README のみ) |

## source of truth

`citation_coverage` は `sample_claims` から deterministic に再計算する。

- `total_claims`: claim 件数
- `claims_with_citation`: `citation_ids` が 1 件以上ある claim 件数
- `coverage_ratio`: `claims_with_citation / total_claims`

`expected_aggregate` は loader の `_validate_aggregate_consistency` で入力から再計算される。`evidence_set_hash` は EvalResult trace と ContextSnapshot `evidence_set_hash` へ渡すため、64 文字 lowercase SHA-256 hex を必須にする。

## dataset_version 規約

- skeleton 初期版は `v2026.05.09-skeleton`
- monthly refresh で `private_holdout` / `adversarial_new` を append-only で増やす
- `public_regression` は migration / metric service 互換性確認のため変更時 ADR または Sprint Pack に理由を残す

## 関連

- Sprint Pack: `SP-004_agent_runtime`, `SP-010_deep_research`, `SP-011_eval_harness`, `SP-012_p0_acceptance`
- PRD: `docs/要件定義/01_P0要求定義.md` AC-KPI-04
- Reference: `.claude/reference/hard-gates-and-kpis.md` §3 AC-KPI-04

