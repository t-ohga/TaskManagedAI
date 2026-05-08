# forbidden_path/adversarial_new/

月次 1-3 件追加する敵対的 fixture。symlink、`..` traversal、escaped path、case variant、workflow path、migration path、secret inventory path を append-only で増やす。過去 fixture は削除しない。Sprint 11 / 12 で 5-10 件追加予定。

## 月次 refresh

- 月初に `vYYYY.MM.NN` で dataset_version を semver bump
- 既存 fixture は変更せず追記のみ
- adversarial fixture の作成者と runner gateway / path validator 修正者は履歴上分離
- `runner_mutation_gateway` と `tool_mutating_gateway_stub` の責務を fixture metadata で明示する

