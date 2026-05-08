# AC-KPI-03: approval_wait_ms

| 項目 | 内容 |
|---|---|
| KPI ID | AC-KPI-03 |
| metric | `approval_wait_ms` |
| 達成基準 | Approval requested_at から decided_at までの median が 4h 以下 |
| source | `approval_requests.requested_at` / `approval_requests.decided_at` |
| 関連 Sprint | Sprint 3 / 11 / 12 |
| owner skill | `release-suite` |
| owner agent | `release-auditor` |

## fixture 構成

| split | 用途 | gitignore |
|---|---|---|
| `public_regression/` | 公開 fixture、PR レビューで参照可 | tracked |
| `private_holdout/` | 期待値漏えい禁止、別 vault 管理 | tracked (`.gitkeep` + README のみ、内容は別 path) |
| `adversarial_new/` | 月次追加、append-only | tracked (`.gitkeep` + README のみ) |

## source of truth

`approval_wait_ms` は DB の `approval_requests.requested_at` と `approval_requests.decided_at` から再計算する。UI event / frontend telemetry は補助情報であり、AC-KPI-03 の source of truth にはしない。

## dataset_version 規約

- skeleton 初期版は `v2026.05.08-skeleton`
- monthly refresh で `private_holdout` / `adversarial_new` を append-only で増やす
- `public_regression` は migration / metric service 互換性確認のため変更時 ADR または Sprint Pack に理由を残す

## 関連

- Sprint Pack: `SP-003_policy_approval`, `SP-011_eval_harness`, `SP-012_p0_acceptance`
- PRD: `docs/要件定義/01_P0要求定義.md` AC-KPI-03
- ADR: `docs/adr/00009_action_class_taxonomy.md`

