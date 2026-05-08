# approval_wait_ms/adversarial_new/

月次で追加する approval_wait_ms の敵対的 fixture。極端な承認待ち時間、timezone 境界、pending / invalidated の混入、UI event 由来の誤集計などを append-only で増やす。過去 fixture は削除しない。Sprint 11 / 12 で追加予定。

## 月次 refresh

- 月初に `vYYYY.MM.NN` で dataset_version を bump
- 既存 fixture は変更せず追記のみ
- adversarial fixture の作成者と metric / policy / prompt / 実装修正者は履歴上分離

