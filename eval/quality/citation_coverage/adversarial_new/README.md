# citation_coverage/adversarial_new/

月次で追加する citation_coverage の敵対的 fixture。引用なし claim、証拠だけある claim、citation spoof、重複 claim id、古い evidence set hash などを append-only で増やす。過去 fixture は削除しない。

## 月次 refresh

- 月初に `vYYYY.MM.NN` で dataset_version を bump
- 既存 fixture は変更せず追記のみ
- adversarial fixture の作成者と prompt / retrieval / metric / 実装修正者は履歴上分離
- 追加時は immutable index に SHA-256 と split を登録する

