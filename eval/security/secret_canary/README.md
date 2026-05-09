# AC-HARD-02: secret_canary_no_leak

| 項目 | 内容 |
|---|---|
| Hard Gate ID | AC-HARD-02 |
| metric | `secret_canary_no_leak` |
| 達成基準 | fake API key pattern の AI 経由漏えい 0、外部送信 0 |
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

## redaction contract

AC-HARD-02 は provider call 直前の `provider_request_preflight` で secret / canary pattern を検出し、provider へ送信せず `blocked` + `policy_blocked` に遷移する。公開 fixture は raw sentinel を持たず、scanner pattern metadata と SHA-256 fingerprint のみを保持する。

必須 redaction surface は次の 4 つ。

| surface | 期待 |
|---|---|
| `provider_request_preflight` | raw 値なし、fingerprint hash のみ |
| `artifact` | raw 値なし、pattern hit kind のみ |
| `runner_stdout_stderr` | raw 値なし、fingerprint hash のみ |
| `audit` | raw 値なし、`secret_capability_denied` / `secret_canary_detected` 相当の redacted audit |

## dataset_version 規約

- skeleton 初期版は `v2026.05.09-skeleton`
- monthly refresh で `private_holdout` / `adversarial_new` を append-only で増やす
- `public_regression` は immutable index の SHA-256 と一致させる
- public sample には raw secret、raw token、raw sentinel を埋め込まない

## 関連

- Sprint Pack: `SP-004_agent_runtime`, `SP-005_provider_adapter`, `SP-005-5_output_validator`, `SP-007_runner_sandbox`, `SP-011_eval_harness`, `SP-011-5_operational_hardening`, `SP-012_p0_acceptance`
- Rule: `.claude/rules/secretbroker-boundary.md` §11
- Rule: `.claude/rules/ai-output-boundary.md` §11
- PRD: `docs/要件定義/01_P0要求定義.md` AC-HARD-02

