# Provider Compliance Matrix

Provider Compliance Matrix の列、data class ordinal、runtime downgrade、ADR 必須条件、audit payload の整理。  
`config/provider_compliance.toml` と同期し、ProviderAdapter の機械判定に使う。

## 1. 目的

- provider / feature ごとの送信可否を機械判定する。
- `payload_data_class` と `allowed_data_class` の越境を送信前に止める。
- ZDR / retention / training / region / plan の未確認を fail-closed にする。
- audit / metrics で後追いできる payload を残す。
- Provider 追加 / 切替の ADR 判断を支える。

## 2. 正本

| 資料 | 役割 |
|---|---|
| `config/provider_compliance.toml` | runtime 正本 |
| `docs/基本設計/04_セキュリティ_権限_監査設計.md` | design 正本 |
| `.claude/rules/provider-compliance.md` | 常時 rule |
| `.claude/reference/provider-compliance-matrix.md` | 詳細 reference |
| `docs/adr/ADR-00010_*` | Provider 追加 / 切替判断 |

## 3. Columns

| column | required | enum / format | policy use |
|---|---:|---|---|
| `provider` | yes | string | yes |
| `api_or_feature` | yes | string | yes |
| `zdr_eligible` | yes | `yes` / `no` / `conditional` / `n/a` | yes |
| `retention` | yes | `0d` / `30d` / `90d` / `unverified` | yes |
| `training_use` | yes | `no` / `yes` / `unverified` | yes |
| `region_or_data_transfer` | yes | `verified` / `unverified` | yes |
| `subprocessor_or_doc_url` | yes | URL string | evidence |
| `plan_required` | yes | `api_tier` / `business` / `enterprise` / `none` | yes |
| `allowed_data_class` | yes | `public` / `internal` / `confidential` / `pii` | yes |
| `condition_status` | yes | `verified` / `unverified` / `not_applicable` | yes |
| `p0_policy_note` | yes | string | no |
| `last_verified_at` | yes | date | governance |

## 4. Data Class Ordinal

```text
public < internal < confidential < pii
```

Ordinal map:

```json
{
  "public": 0,
  "internal": 1,
  "confidential": 2,
  "pii": 3
}
```

比較:

```text
allow iff ordinal(payload_data_class) <= ordinal(effective_allowed_data_class)
```

禁止:

- alphabetical order。
- provider-specific order。
- multiple allowed classes。
- caller-provided `allowed_data_class`。
- missing `payload_data_class`。

## 5. Data Class Definition

| data class | 例 | P0 方針 |
|---|---|---|
| `public` | 公開 docs、公開 issue、公開 URL | Matrix 登録済 provider へ送信可 |
| `internal` | dogfooding task、非公開だが secret なし設計 | 条件確認済み provider のみ |
| `confidential` | private repo code、private issue、未公開設計 | ZDR / retention / region / ADR が必要 |
| `pii` | 個人情報、顧客情報、認証情報に近い情報 | P0 原則送信しない |

## 6. Runtime Effective Allowed Class

`effective_allowed_data_class` は Matrix の `allowed_data_class` を基に runtime downgrade した値。

downgrade 条件 (いずれかに該当で confidential 以上 → internal 以下に低下):

- `zdr_eligible=conditional` and `condition_status != verified`。
- `retention=unverified`。
- **`training_use != no` (yes / unverified その他)** — provider 訓練利用される経路は fail-closed で禁止。
- `region_or_data_transfer=unverified`。
- `plan_required=none` かつ confidential 以上を許可しようとしている。
- external docs の確認期限切れ。
- provider_request_preflight が violation。
- policy version と matrix version の不整合。

downgrade 結果:

- **`training_use != no` (yes / unverified その他) の場合、`effective_allowed_data_class <= public` に強制低下** (internal 以上の送信経路を持たない)。public-only 例外は ADR 承認済みのみ。
- それ以外の downgrade 条件で confidential / pii は `internal` 以下へ落とす。
- `payload_data_class` が落とせない場合は deny。
- audit に original / effective を残す場合も raw data は残さない。

## 7. Conditional ZDR

conditional ZDR 解禁の最低条件 (**すべて満たす必要あり**):

| 条件 | 必須値 |
|---|---|
| `condition_status` | `verified` |
| `retention` | `unverified` 以外 |
| **`training_use`** | **`no` のみ** (yes / unverified は不可、provider 訓練経路を fail-closed で禁止) |
| `region_or_data_transfer` | `verified` |
| `plan_required` | `none` 以外 |
| ADR | accepted / proposed with approval |
| `last_verified_at` | 外部仕様確認日 |

- `store:false` を ZDR 相当に扱う場合は ADR 必須。
- 条件を満たさない provider / feature に confidential 以上を送らない。
- `pii` は P0 では原則 deny。

## 8. TOML Skeleton

```toml
[[providers]]
provider = "mock"
api_or_feature = "local_mock"
zdr_eligible = "n/a"
retention = "0d"
training_use = "no"
region_or_data_transfer = "verified"
subprocessor_or_doc_url = "repository-docs"
plan_required = "none"
allowed_data_class = "internal"
condition_status = "not_applicable"
p0_policy_note = "local mock only; no external transmission"
last_verified_at = "2026-05-07"
```

注意:

- 実 API key は TOML に書かない。
- 実 provider の外部仕様は確認日を更新する。
- `p0_policy_note` は判定に使わない。
- URL は公式 doc / subprocessor document を優先する。

## 9. ProviderAdapter Flow

1. Matrix version を固定。
2. request の provider / api_or_feature を読む。
3. `payload_data_class` があるか確認。
4. Matrix row を取得。
5. `allowed_data_class` を Matrix から解決。
6. conditional / unverified による runtime downgrade。
7. ordinal 比較。
8. `provider_request_preflight`。
9. BudgetGuard。
10. Structured Outputs request。
11. provider call。
12. provider result mapping。
13. AgentRunEvent / audit event。

## 10. `provider_request_preflight`

検査:

- secret canary。
- API key / token pattern。
- GitHub / Tailscale / SOPS key pattern。
- raw secret 値。
- `secret_ref` 直接展開。
- payload size。
- schema fingerprint。
- `payload_data_class`。
- provider / model / API version。

違反:

- provider 未送信。
- `blocked` + `policy_blocked`。
- reason_code `provider_request_preflight_violation`。
- raw value なし audit。
- AC-HARD-02 の前提。

## 11. ADR 必須条件

- Provider 追加。
- Provider API / feature 切替。
- `allowed_data_class` 引き上げ。
- ZDR 対象外 feature への `internal` 以上送信。
- `confidential` 以上の解禁。
- `pii` 送信。
- `store:false` / ZDR / retention 前提変更。
- provider state export policy 変更。
- subprocessor / region 前提変更。
- provider SDK major update が compliance behavior に影響する場合。

## 12. Audit Payload

必須:

| key | 内容 |
|---|---|
| `event_type` | `policy_decision_created` / `provider_blocked` / `provider_requested` |
| `decision` | `allow` / `deny` |
| `reason_code` | structured reason |
| `provider` | provider |
| `api_or_feature` | feature |
| `payload_data_class` | request class |
| `allowed_data_class` | Matrix raw 値 (行固定) |
| `effective_allowed_data_class` | runtime downgrade 後の effective 上限 (`zdr_eligible=no` / `training_use != no` / `condition_status != verified` / `retention=unverified` / `region=unverified` / `plan_required=none` で `allowed_data_class` から低下) |
| `provider_compliance_matrix_version` | locked version |
| `policy_version` | policy pack version |
| `provider_request_fingerprint` | hash / model / sdk |
| `run_id` | AgentRun |
| `actor_id` | actor |
| `trace_id` | trace |
| `correlation_id` | correlation |
| `timestamp` | UTC |

禁止:

- raw prompt。
- raw secret。
- raw canary。
- provider key。
- capability token。

## 13. Metrics

| metric dimension | 説明 |
|---|---|
| `provider` | provider |
| `api_or_feature` | feature |
| `decision` | allow / deny |
| `reason_code` | reason |
| `payload_data_class` | request class |
| `allowed_data_class` | Matrix raw 値 (行固定) |
| `effective_allowed_data_class` | runtime downgrade 後の effective 上限 |
| `matrix_version` | compliance version |
| `policy_version` | policy version |

- `payload_data_class` と `allowed_data_class` を合算して `data_class` にしない。
- denial rate、downgrade count、preflight violations を dashboard 化する。
- `cost_per_completed_task` と provider usage を接続する。

## 14. Contract Test

- [ ] TOML schema validation。
- [ ] enum validation。
- [ ] ordinal comparison。
- [ ] missing payload deny。
- [ ] missing provider deny。
- [ ] conditional ZDR verified requirement。
- [ ] runtime downgrade。
- [ ] preflight canary block。
- [ ] audit payload required keys。
- [ ] no raw secret。
- [ ] AgentRun mapping。
- [ ] docs / TOML / tests synchronization。

