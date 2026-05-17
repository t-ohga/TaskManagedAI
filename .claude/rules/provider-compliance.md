# Provider Compliance

Provider Compliance Matrix の機械判定 invariant。  
`payload_data_class`、`allowed_data_class`、data class ordinal、`provider_request_preflight`、conditional ZDR を fail-closed で扱う。

## 1. 正本

- Matrix 正本は `config/provider_compliance.toml`。
- 設計正本は `docs/基本設計/04_セキュリティ_権限_監査設計.md`。
- reference は `.claude/reference/provider-compliance-matrix.md`。
- Provider 追加 / 切替 / Matrix 引き上げは ADR Gate Criteria。
- `allowed_data_class` の runtime 判定は Matrix 以外を信頼しない。

## 2. Matrix Columns

| column | 型 / enum |
|---|---|
| `provider` | string |
| `api_or_feature` | string |
| `zdr_eligible` | `yes` / `no` / `conditional` / `n/a` |
| `retention` | `0d` / `30d` / `90d` / `unverified` |
| `training_use` | `no` / `yes` / `unverified` |
| `region_or_data_transfer` | `verified` / `unverified` |
| `subprocessor_or_doc_url` | URL string |
| `plan_required` | `api_tier` / `business` / `enterprise` / `none` |
| `allowed_data_class` | `public` / `internal` / `confidential` / `pii` |
| `condition_status` | `verified` / `unverified` / `not_applicable` |
| `p0_policy_note` | free text、policy 判定に使わない |
| `last_verified_at` | date |

## 3. Data Class Ordinal

固定順序:

```text
public < internal < confidential < pii
```

実装値:

```json
{
  "public": 0,
  "internal": 1,
  "confidential": 2,
  "pii": 3
}
```

禁止:

- string 比較。
- provider ごとの別順序。
- `allowed_data_class` の複数値。
- UI / caller からの `allowed_data_class` 入力。
- `p0_policy_note` を policy 判定に使うこと。

## 4. `payload_data_class`

- request / artifact metadata から事前算出する。
- ProviderAdapter は再算出しない。
- ProviderAdapter は必須入力として検証する。
- 未設定は classification 前に deny。
- enum 外は deny。
- `payload_data_class >= confidential` は ZDR / retention / region / plan を厳格に見る。
- `pii` は P0 では原則送信しない。
- sanitize / exclusion が必要な場合は artifact と audit に残す。

## 5. `allowed_data_class`

- Matrix からのみ解決する。
- provider + api_or_feature で一意に決まる。
- Matrix に行がなければ deny。
- `allowed_data_class` は最大許可分類であり、リストではない。
- `allowed_data_class >= confidential` の行は解禁条件を満たす必要がある。
- runtime downgrade 後の値を audit に残す。
- caller が指定した値は無視ではなく設計違反として reject する。

## 6. 機械判定 invariant

- `payload_data_class` 未設定 -> deny。
- provider / feature 未登録 -> deny。
- enum 不正 -> deny。
- `payload_data_class > allowed_data_class` -> deny。
- unverified が残る provider / feature に `payload_data_class >= confidential` -> deny。
- `zdr_eligible=no` で `internal` 以上を許すには ADR が必要。
- `zdr_eligible=conditional` で `condition_status != verified` -> confidential 以上 deny。
- `retention=unverified` -> confidential 以上 deny。
- **`training_use != no` (`yes` / `unverified` / その他)** -> **internal 以上 deny / BLOCK**。training_use=yes/unverified の provider に internal 以上の payload を送信する経路は P0 全体で禁止。public-only 例外を許容するには ADR で個別承認が必要。
- `region_or_data_transfer=unverified` -> confidential 以上 deny。
- **`plan_required=none` AND `effective_allowed_data_class >= confidential`** -> downgrade `effective_allowed_data_class = internal` (reason: `plan_unverified`)。`zdr_eligible=yes` 行であっても `plan_required != none` を満たさないと confidential 解禁不可。

## 7. Conditional ZDR

`zdr_eligible=conditional` の confidential 解禁条件 (**すべて満たす必要あり**):

- `condition_status=verified`
- `retention != unverified`
- **`training_use=no`** (yes / unverified は不可、provider 訓練利用される経路を fail-closed で禁止)
- `region_or_data_transfer=verified`
- `plan_required != none`
- ADR で条件と根拠を明示
- `last_verified_at` が更新済み
- policy version / matrix version が更新済み

上記を満たさない場合:

- runtime で `effective_allowed_data_class <= internal` に downgrade。
- **`training_use != no` の場合、`effective_allowed_data_class <= public` に強制低下** (yes/unverified は internal 以上の送信経路を持たない)。public-only 例外は ADR 承認済みのみ。
- 該当 reason_code (`zdr_ineligible` / `training_use_not_no` / `condition_unverified` / `retention_unverified` / `region_unverified` / `plan_unverified`) を audit。
- provider へ confidential / pii を送信しない。

## 8. `provider_request_preflight`

Provider call 前に必須。

確認項目:

- secret canary pattern。
- provider token / key pattern。
- GitHub token / key pattern。
- Tailscale auth key pattern。
- SOPS / age key pattern。
- raw secret 値。
- `secret_ref` URI の直接展開違反。
- payload size / max token / schema fingerprint。
- `payload_data_class` と Matrix version。

違反時:

- provider へ送信しない。
- AgentRun は `blocked` + `policy_blocked`。
- `provider_blocked` または `policy_decision_created` を audit。
- raw 値は保存しない。
- pattern hit 種別と reason_code だけを残す。

## 9. Reason Codes (正本: 13 種 = 12 deny/downgrade + 1 allow)

| # | reason_code | 状態 |
|---:|---|---|
| 1 | `payload_data_class_unset` | deny (未設定 / enum 不正どちらも含む) |
| 2 | `payload_data_class_exceeds_allowed` | deny (`payload_data_class > allowed_data_class` Matrix 値直接比較) |
| 3 | `effective_allowed_data_class_exceeded` | deny (`payload_data_class > effective_allowed_data_class` runtime 計算後) |
| 4 | `zdr_ineligible` | deny (`zdr_eligible=no` 行への `internal` 以上送信) |
| 5 | `training_use_not_no` | deny (`training_use != no` 行への `internal` 以上送信、effective=public 強制) |
| 6 | `condition_unverified` | deny / downgrade (`zdr_eligible=conditional` AND `condition_status != verified` で effective=internal 低下) |
| 7 | `retention_unverified` | downgrade (`retention=unverified` AND effective>=confidential で effective=internal 低下) |
| 8 | `region_unverified` | downgrade (`region=unverified` AND effective>=confidential で effective=internal 低下) |
| 9 | `plan_unverified` | downgrade (`plan_required=none` AND effective>=confidential で effective=internal 低下) |
| 10 | `provider_not_in_matrix` | deny |
| 11 | `provider_request_preflight_violation` | deny (secret canary / token pattern hit) |
| 12 | `budget_exceeded` | `blocked` + `budget_blocked` |
| 13 | `allow` | allow (provider call 実行) |

**Note**: `payload_data_class_invalid` は `payload_data_class_unset` に統合 (未設定 / enum 不正どちらも「不正な classification」)。`provider_unverified` は coarse label として削除 (細粒 reason_code が優先)。

## 10. AgentRun Mapping

| Provider / Gate result | AgentRun status |
|---|---|
| preflight deny | `blocked` + `policy_blocked` |
| data class deny | `blocked` + `policy_blocked` |
| budget exceeded | `blocked` + `budget_blocked` |
| provider refusal | `provider_refused` |
| provider incomplete / max token | `provider_incomplete` |
| unsupported schema | `validation_failed` |
| schema validation failed | `validation_failed` |
| repair exhausted | `repair_exhausted` |
| success | next pipeline stage |

## 11. Audit Payload

必須 key:

- `event_type`
- `decision`
- `reason_code`
- `provider`
- `api_or_feature`
- `payload_data_class`
- `allowed_data_class` (Matrix raw 値、行固定)
- `effective_allowed_data_class` (runtime downgrade 後の effective 上限。`zdr_eligible=no` / `training_use != no` / `condition_status != verified` / `retention=unverified` / `region=unverified` / `plan_required=none` で `allowed_data_class` から低下する)
- `provider_compliance_matrix_version`
- `policy_version`
- `provider_request_fingerprint`
- `run_id`
- `actor_id`
- `trace_id`
- `correlation_id`
- `timestamp`

禁止:

- raw prompt secret。
- provider key。
- capability token 生値。
- canary raw value。
- unredacted request body。


<!-- Phase E 圧縮 (2026-05-17 PR #?): 末尾 verify checklist 削除、plan §3.1.1 invariant trace matrix で自動 verify -->
