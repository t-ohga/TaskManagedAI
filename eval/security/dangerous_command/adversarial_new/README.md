# dangerous_command/adversarial_new/

月次 1-3 件追加する敵対的 fixture。shell injection、encoding tricks、download-and-execute、fork bomb 派生、Docker escape variant、host mount / host network を append-only で増やす。過去 fixture は削除しない。Sprint 11 / 12 で 5-10 件追加予定。

## 月次 refresh

- 月初に `vYYYY.MM.NN` で dataset_version を semver bump
- 既存 fixture は変更せず追記のみ
- adversarial fixture の作成者と command parser / runner gateway 修正者は履歴上分離
- command plan は fixture として保存するだけで実行しない

