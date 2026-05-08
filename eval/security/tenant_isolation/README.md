# AC-HARD-03: tenant_isolation_negative_pass

| 項目 | 内容 |
|---|---|
| Hard Gate ID | AC-HARD-03 |
| metric | `tenant_isolation_negative_pass` |
| 達成基準 | 越境 SELECT / INSERT / UPDATE / DELETE が全件失敗 |
| 関連 Sprint | Sprint 2 / 11 / 12 |
| owner skill | `postgres-boundary-audit` |
| owner agent | `tenant-project-isolation-reviewer` |
| 正本 | `.claude/reference/hard-gates-and-kpis.md` §2 AC-HARD-03 |

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

## 関連

- Sprint Pack: `SP-002_core_data_model`, `SP-011_eval_harness`, `SP-012_p0_acceptance`
- skill: `.claude/skills/hard-gate-fixture-create/SKILL.md`
- agent: `.claude/agents/taskmanagedai/hard-gate-fixture-reviewer.md`

