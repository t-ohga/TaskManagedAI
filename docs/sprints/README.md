# Sprint Pack

機能単位スプリントの Pack（実装前必須ゲート）と Review（実装後追記）を保管する。

## 構成

| ファイル | 内容 |
|----------|------|
| `_template_light.md` | 軽量 Pack テンプレ（UI / 土台系、最大 1 ページ） |
| `_template_heavy.md` | 重量 Pack テンプレ（権限 / 実行 / 外部連携系、ADR 込み） |
| `SP-000_bootstrap.md` | Sprint 0 Pack（横断基盤の bootstrap） |
| `SP-001_<feature-name>.md` 〜 | Sprint 1 以降の Pack |

## 運用ルール

- Sprint Pack は実装前の**必須ゲート**（計画 v2 §Documentation And Sprint System 参照）
- ADR Gate Criteria 該当時は重量 Pack + ADR を必ず作成
- Sprint Review は Pack の末尾に `## Review` セクションで追記（changed / verified / deferred / risks の 4 項目）
- Documentation Definition of Done に従い、過剰な記述は避ける（軽量 Pack は最大 1 ページ）

### Frontmatter field 規約

- **Heavy Pack**: 12 fields 必須 (`id` / `type` / `status` / `sprint_no` / `created_at` / `updated_at` / `target_days` / `max_days` / `adr_refs` / `planned_adr_refs` / `related_sprints` / `risks`)
- **Light Pack**: 8 fields のみ (`id` / `type` / `status` / `sprint_no` / `created_at` / `updated_at` / `target_days` / `max_days`)。ADR Gate Criteria に該当しない軽量 Pack は `adr_refs` / `planned_adr_refs` / `related_sprints` / `risks` を frontmatter に持たない。これらは必要なら本文の対応節 (関連 ADR / 残リスク 等) で扱う前提
- Heavy → Light の変更や逆は ADR Gate Criteria 確認のうえで行う

## 上位資料への参照

- 計画（v2 改訂版）: `../設計検討/計画(仮).md`
- ADR: `../adr/`
