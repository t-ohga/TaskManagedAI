# secret_canary/public_regression/

公開 regression fixture。AC-HARD-02 の最小ケースとして、provider request preflight が redacted provider key pattern を検出し、provider call 前に `blocked` + `policy_blocked` へ遷移することを確認する。

## policy

- raw secret、raw token、raw sentinel は置かない
- 期待値は pattern hit kind と SHA-256 fingerprint のみで表現する
- provider request preflight、artifact、runner stdout/stderr、audit の 4 surface がすべて redacted であることを確認する
- sample の変更時は `manifest.json` の `fixture_immutable_index` を同じ canonical hash で更新する

