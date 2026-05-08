# prompt_injection/adversarial_new/

月次 1-3 件追加する敵対的 fixture。OWASP LLM01、untrusted_content による権限昇格、tool call 誘導、provider preflight bypass、SecretBroker capability 誘導を append-only で増やす。過去 fixture は削除しない。Sprint 11 / 12 で 5-10 件追加予定。

## 月次 refresh

- 月初に `vYYYY.MM.NN` で dataset_version を semver bump
- 既存 fixture は変更せず追記のみ
- adversarial fixture の作成者と prompt / policy / Input Trust Layer 修正者は履歴上分離
- injection prompt は必要最小限の redacted text と expected metadata に限定する

