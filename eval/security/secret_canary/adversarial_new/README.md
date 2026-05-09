# secret_canary/adversarial_new/

月次 1-3 件追加する敵対的 fixture。secret canary 派生、stdout / stderr redaction bypass、provider_request_preflight bypass、artifact export bypass、audit payload bypass を append-only で増やす。過去 fixture は削除しない。

## 月次 refresh

- 月初に `vYYYY.MM.NN` で dataset_version を bump
- 既存 fixture は変更せず追記のみ
- adversarial fixture の作成者と policy / prompt / Matrix / 実装修正者は履歴上分離
- raw sentinel は repo に置かず、暗号化 vault 側でのみ扱う
- 追加時は immutable index に SHA-256 と split を登録する

