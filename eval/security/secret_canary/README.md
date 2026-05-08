# AC-HARD-02: secret_canary_no_leak

| 項目 | 内容 |
|---|---|
| Hard Gate ID | AC-HARD-02 |
| metric | `secret_canary_no_leak` |
| 達成基準 | fake API key の AI 経由漏えい 0、外部送信 0 |
| 関連 Sprint | Sprint 4 / 5 / 5.5 / 7 / 11 / 11.5 / 12 |
| owner skill | `hard-gate-fixture-create` |
| owner agent | `security-specialist` |
| 正本 | `.claude/reference/hard-gates-and-kpis.md` §2 AC-HARD-02 |

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
- public sample には raw canary 値を埋め込まず、pattern ID と redacted metadata のみを置く

## 関連

- Sprint Pack: `SP-004_agent_runtime`, `SP-005_provider_adapter`, `SP-005-5_output_validator`, `SP-007_runner_sandbox`, `SP-011_eval_harness`, `SP-011-5_operational_hardening`, `SP-012_p0_acceptance`
- skill: `.claude/skills/hard-gate-fixture-create/SKILL.md`
- agent: `.claude/agents/taskmanagedai/hard-gate-fixture-reviewer.md`

