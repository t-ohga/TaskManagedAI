# citation_coverage/public_regression/

公開 regression fixture。5 claims / 4 evidence IDs / 3 cited claims の最小データから `coverage_ratio = 3 / 5 = 0.60` を deterministic に再計算する。

## policy

- `expected_aggregate` は loader が `input.sample_claims` から再計算する
- `evidence_set_hash` は 64 文字 lowercase SHA-256 hex を必須にする
- `claim_text` は synthetic text のみを置き、private research payload を含めない
- sample の変更時は `manifest.json` の `fixture_immutable_index` を同じ canonical hash で更新する

