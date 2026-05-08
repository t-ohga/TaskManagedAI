# tenant_isolation/adversarial_new/

月次 1-3 件追加する敵対的 fixture。cross-tenant SELECT / INSERT / UPDATE / DELETE、cross-project relation、`agent_runs.parent_run_id` 境界、repository layer tenant WHERE 漏れを append-only で増やす。過去 fixture は削除しない。Sprint 11 / 12 で 5-10 件追加予定。

## 月次 refresh

- 月初に `vYYYY.MM.NN` で dataset_version を semver bump
- 既存 fixture は変更せず追記のみ
- adversarial fixture の作成者と migration / repository / policy 修正者は履歴上分離

