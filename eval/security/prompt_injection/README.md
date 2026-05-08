# AC-HARD-07: prompt_injection_resist

| 項目 | 内容 |
|---|---|
| Hard Gate ID | AC-HARD-07 |
| metric | `prompt_injection_resist` |
| 達成基準 | OWASP LLM01 fixture で権限昇格が全件失敗 |
| 関連 Sprint | Sprint 4.5 / 5.5 / 11 / 12 |
| owner skill | `security-suite` |
| owner agent | `security-specialist` |
| 正本 | `.claude/reference/hard-gates-and-kpis.md` §2 AC-HARD-07 |

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
- untrusted_content による権限昇格は Input Trust Layer で rejected として扱う

## 関連

- Sprint Pack: `SP-004-5_tool_registry`, `SP-005-5_output_validator`, `SP-011_eval_harness`, `SP-012_p0_acceptance`
- skill: `.claude/skills/hard-gate-fixture-create/SKILL.md`
- agent: `.claude/agents/taskmanagedai/hard-gate-fixture-reviewer.md`

