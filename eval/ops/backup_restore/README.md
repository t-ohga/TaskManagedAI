# AC-HARD-04: backup_restore_rpo_rto

| 項目 | 内容 |
|---|---|
| Hard Gate ID | AC-HARD-04 |
| metric | `backup_restore_rpo_rto` |
| 達成基準 | RPO <= 24h、RTO <= 4h、PITR 成功 |
| 関連 Sprint | Sprint 0 / 11 / 11.5 / 12 |
| owner skill | `release-suite` |
| owner agent | `release-auditor` |
| 正本 | `.claude/reference/hard-gates-and-kpis.md` §2 AC-HARD-04 |

## fixture 構成

| split | 用途 | gitignore |
|---|---|---|
| `public_regression/` | 公開 fixture、PR レビューで参照可 | tracked |
| `private_holdout/` | 期待値漏えい禁止、別 vault 管理 | tracked (`.gitkeep` + README のみ、内容は別 path) |
| `adversarial_new/` | 月次 1-3 件追加、append-only | tracked (`.gitkeep` + README のみ) |

## dataset_version 規約

- semver: `vYYYY.MM.NN` (例: `v2026.05.01`)
- skeleton 初期版は `v2026.05.01-skeleton`
- monthly refresh で `private_holdout` / `adversarial_new` を append-only で増やす
- `public_regression` は migration 互換性確認のため変更時 ADR
- backup artifact は checksum / timing / redacted path metadata のみを fixture に置く

## 関連

- Sprint Pack: `SP-000_bootstrap`, `SP-011_eval_harness`, `SP-011-5_operational_hardening`, `SP-012_p0_acceptance`
- skill: `.claude/skills/hard-gate-fixture-create/SKILL.md`
- agent: `.claude/agents/taskmanagedai/hard-gate-fixture-reviewer.md`

