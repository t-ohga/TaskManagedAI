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

## Sprint Pack canonical registry + alias map (R29 統合計画書 §3.5.4 反映)

修正まとめ統合計画 R29 (`../設計検討/修正まとめ統合計画.md`) §3.5.4 で確定した Pack inventory を正本として登録する。`docs/実装計画/P0_バックログ.md` の `sprint_pack_ref` 列に書かれた **PLAN-01 参照名** が実 file 名と揺れる場合、本 registry を正本として alias map で解決する。

### Pack inventory (match 3 + alias 6 + create_required 1 = 10 entry + match-only 12 entry)

| sprint_pack_ref (PLAN-01 参照名) | actual_file (実 file 名) | resolution | notes |
|---|---|---|---|
| SP-000_bootstrap | SP-000_bootstrap.md | match | - |
| SP-001_project_foundation | SP-001_project_foundation.md | match | - |
| SP-001-5_host_portable_amendment | SP-001-5_host_portable_amendment.md | match | ADR-00021 (host-portable) accepted 化対応 |
| SP-002_core_data_model | SP-002_core_data_model.md | match | - |
| SP-003_policy_approval | SP-003_policy_approval.md | match | - |
| SP-004_agent_runtime | SP-004_agent_runtime.md | match | - |
| SP-005_provider_adapter | SP-005_provider_adapter.md | match | - |
| **SP-0055_io_boundary** | **SP-005-5_output_validator.md** | **alias** | naming 整理のみ、security boundary 同一 |
| SP-006_cli_artifact_orchestration | SP-006_cli_artifact.md | alias | CLI artifact orchestration が canonical 名 |
| SP-007_docker_runner | SP-007_runner_sandbox.md | alias | runner sandbox が canonical 名 |
| SP-008_github_draft_pr | SP-008_github_app_repoproxy.md | alias | RepoProxy が canonical 名 (前 session commit `369672b` で起票) |
| SP-009_p0_ui | SP-009_p0_ui_pack.md | alias | P0 UI Pack が canonical 名 |
| **SP-010_research_evidence** | **SP-010_research_evidence.md** | **match** | Sprint 10 batch 0 (BL-0113/BL-0114) commit `314b5bb` で着手済 (Codex R1-R2 clean) |
| **SP-011_eval_harness** | **SP-011_eval_harness.md** | **match** | - |
| **SP-0115_operational_hardening** | **SP-011-5_operational_hardening.md** | **alias** | 命名揺れ整理 (SP-0115 → SP-011-5) |
| **SP-012_p0_acceptance** | **SP-012_p0_acceptance.md** | **match** | host migration acceptance + Research-to-PR 別表 (R29 §6 U-01) |
| SP-013_multi_agent_orchestration | SP-013_multi_agent_orchestration.md | match | P0.1+ sealed (P0 sealed CI guard 対象) |
| SP-014_orchestrator_agent | SP-014_orchestrator_agent.md | match | P0.1+ sealed |
| SP-015_inter_agent_communication | SP-015_inter_agent_communication.md | match | P0.1+ sealed |
| SP-016_ui_cli_parity | SP-016_ui_cli_parity.md | match | CLI canonical name `tm` 維持 (R29 §6 U-04) |
| SP-017_ai_society_visualization | SP-017_ai_society_visualization.md | match | P1 read-only AI Society board + role visualization; character generation remains SP-021 |
| SP-018_hermes_memory_integration | SP-018_hermes_memory_integration.md | match | P1 memory backend completed; read-only retrieval API remains feature-flag disabled by default |
| SP-020_curator_insights_integration | SP-020_curator_insights_integration.md | match | P1 curator + insights plan-only gate; implementation starts after ADR-00032 acceptance |
| SP-022_framework_intake_hardening | SP-022_framework_intake_hardening.md | match | framework intake checklist + host migration 自動化 (P0.1+) |
| **SP-0045_tool_registry** | **SP-0045_tool_registry.md** | **create_required** | **security boundary 独立、SP-005-5 alias 禁止** (R26 T-P2R1-012-residual)、本 PR で新規起票 |

### Alias map (PLAN-01 参照名 ↔ 実 file 名)

`docs/実装計画/P0_バックログ.md` の `sprint_pack_ref` 列が実 file 名と揺れる場合、以下を正本として解決:

| PLAN-01 参照名 | 実 file 名 | 解決ポリシー |
|---|---|---|
| `SP-0055_io_boundary` | `SP-005-5_output_validator.md` | naming 整理のみ、security boundary 同一 |
| `SP-0115_operational_hardening` | `SP-011-5_operational_hardening.md` | 命名揺れ整理 (`SP-0115` → `SP-011-5`) |
| `SP-006_cli_artifact_orchestration` | `SP-006_cli_artifact.md` | CLI artifact orchestration を含む |
| `SP-007_docker_runner` | `SP-007_runner_sandbox.md` | Docker isolated runner + sandbox |
| `SP-008_github_draft_pr` | `SP-008_github_app_repoproxy.md` | RepoProxy + Draft PR flow |
| `SP-009_p0_ui` | `SP-009_p0_ui_pack.md` | P0 UI Pack |

**重要**: `SP-0045_tool_registry` は **alias map に登録しない**。`create_required` の独立 Pack として §Missing Pack creation policy で扱い、SP-005-5_output_validator への alias / functional-near reuse は **security boundary 独立** のため禁止 (R29 R26 T-P2R1-012-residual)。

### Missing Pack creation policy

- `resolution=create_required` は **SP-0045 (Tool Registry) 1 件のみ** (R29 §3.5.4 確定)
- それ以外の `alias` は **registry 化 + naming 整理のみ**、新規 Pack 作成は不要
- `match` は **file 名完全一致**、`actual_file` は `docs/sprints/` 内の実在 file と **exact match 必須**。`match` → `alias` / `create_required` への変更は ADR Gate 対象 + registry lint (例: `scripts/docs/validate_sprint_pack_registry.py` 相当の verify、R2 P2R1 F-P2R1-013 反映で Pack 名規約の silent rename 防止)
- 4 Pack (SP-008 / SP-010 / SP-011 / SP-011-5) は前 session commit `369672b` で既に作成済、本 PR では registry 化のみ

### Registry を正本にする運用

- 新規 Sprint Pack 追加時は本 registry に entry 追加 (PR で同期)
- `docs/実装計画/P0_バックログ.md` の `sprint_pack_ref` 列の変更は本 registry の alias map と **同一 PR で同期**
- registry に存在しない `sprint_pack_ref` を BL- が指す状態は **drift** とみなし、Sprint Pack DoD 違反として扱う
- ADR Gate Criteria #2 (DB schema) / #3 (API 契約) / #4 (AI 権限) / #5 (MCP 権限) / #6 (Secrets) 該当 Pack の追加・命名変更は ADR と同期

## 上位資料への参照

- 計画（v2 改訂版）: `../設計検討/計画(仮).md`
- 修正まとめ統合計画 (R29、status: clean): `../設計検討/修正まとめ統合計画.md`
- P0 Exit Master Plan: `../設計検討/2026-05-13_p0_exit_master_plan.md`
- ADR: `../adr/`
