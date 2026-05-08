# policy_block/adversarial_new/

月次 1-3 件追加する敵対的 fixture。policy bypass、approval bypass、stale approval 再利用、`secret_access` / `merge` / `deploy` の P0 deny 経路などを append-only で増やす。過去 fixture は削除しない。Sprint 11 / 12 で 5-10 件追加予定。

## 月次 refresh

- 月初に `vYYYY.MM.NN` で dataset_version を semver bump
- 既存 fixture は変更せず追記のみ
- adversarial fixture の作成者と policy / prompt / Matrix 修正者は履歴上分離

