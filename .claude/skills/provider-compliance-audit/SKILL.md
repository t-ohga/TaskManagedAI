---
name: provider-compliance-audit
description: "TaskManagedAI Provider Compliance Matrix TOML と adapter call site を全行検証する。Triggers: provider matrix, payload_data_class"
when_to_use: |
  `config/provider_compliance.toml`、ProviderAdapter、provider_request_preflight、payload_data_class / allowed_data_class の実装を監査する時。
  トリガーフレーズ: 'Provider Compliance', 'provider matrix', 'payload_data_class', 'allowed_data_class'
argument-hint: "<config/provider_compliance.toml path> [provider adapter call site paths...]"
allowed-tools: Read Bash Grep
---

# provider-compliance-audit — Compliance Matrix TOML 全行検証

## 目的

Provider Compliance Matrix v2 の TOML 全行を enum、ordinal、runtime downgrade、conditional ZDR、training_use、last_verified_at の観点で検証する。任意で ProviderAdapter call site も確認し、caller-provided `allowed_data_class` を BLOCK する。

## 必読資料

- `.claude/rules/provider-compliance.md`
- `.claude/rules/instincts.md` §5
- `.claude/reference/provider-compliance-matrix.md`
- `.claude/rules/ai-output-boundary.md`
- `.claude/rules/agentrun-state-machine.md`

## Main Agent への指示

この skill は監査だけを行う。TOML や adapter code の修正は行わず、row ごとの deny / warn / pass と reason_code を出す。

## Step 1: TOML schema と enum validation

必須 columns:

```text
provider
api_or_feature
zdr_eligible
retention
training_use
region_or_data_transfer
subprocessor_or_doc_url
plan_required
allowed_data_class
condition_status
p0_policy_note
last_verified_at
```

enum:

| column | values |
|---|---|
| `zdr_eligible` | `yes`, `no`, `conditional`, `n/a` |
| `retention` | `0d`, `30d`, `90d`, `unverified` |
| `training_use` | `no`, `yes`, `unverified` |
| `region_or_data_transfer` | `verified`, `unverified` |
| `plan_required` | `api_tier`, `business`, `enterprise`, `none` |
| `allowed_data_class` | `public`, `internal`, `confidential`, `pii` |
| `condition_status` | `verified`, `unverified`, `not_applicable` |

Validation examples:

```bash
python - <<'PY'
import sys, tomllib
path = sys.argv[1]
data = tomllib.load(open(path, "rb"))
rows = data.get("providers", [])
print(f"rows={len(rows)}")
PY
```

## Step 2: ordinal / deny / downgrade validation

固定 ordinal:

```json
{"public": 0, "internal": 1, "confidential": 2, "pii": 3}
```

row-level deny:

- missing required column: `missing_required_column`
- enum invalid: `enum_invalid`
- duplicate `(provider, api_or_feature)`: `duplicate_provider_feature`
- `last_verified_at` empty: `last_verified_at_empty`
- `training_use != no` かつ `allowed_data_class >= internal`: `training_use_not_no_internal_or_higher`
- `zdr_eligible=conditional` かつ `condition_status != verified` で `allowed_data_class >= confidential`: `conditional_zdr_unverified_confidential`
- `retention=unverified` で `allowed_data_class >= confidential`: `retention_unverified_confidential`
- `region_or_data_transfer=unverified` で `allowed_data_class >= confidential`: `region_unverified_confidential`
- `plan_required=none` で `allowed_data_class >= confidential`: `plan_none_confidential`
- `allowed_data_class=pii`: `pii_not_allowed_in_p0`

warn:

- `subprocessor_or_doc_url` が公式根拠でない。
- `p0_policy_note` が空。
- `zdr_eligible=no` で internal 以上を許すが ADR reference が見つからない。
- `last_verified_at` が古い可能性がある。

## Step 3: ProviderAdapter call site validation

任意の call site path が渡された場合に確認する。

検索例:

```bash
rg -n "payload_data_class|allowed_data_class|ProviderAdapter|provider_request_preflight|training_use|condition_status" <paths>
```

BLOCK patterns:

- `allowed_data_class` を request body、UI、caller 引数から受け取る。
- `payload_data_class` が optional。
- provider / feature 未登録時に allow。
- ordinal を文字列比較する。
- `training_use != no` の internal 以上を downgrade だけで送信可能にする。
- `provider_request_preflight` を provider call 後に実行する。
- deny 時に provider へ送信する。
- audit payload に raw prompt / raw secret / capability token 生値を含める。

## 出力 contract

```json
{
  "skill": "provider-compliance-audit",
  "verdict": "PASS|WARN|BLOCK",
  "matrix_path": "config/provider_compliance.toml",
  "rows": [
    {
      "provider": "<provider>",
      "api_or_feature": "<feature>",
      "status": "PASS|WARN|DENY",
      "allowed_data_class": "public|internal|confidential|pii",
      "effective_allowed_data_class": "public|internal|confidential|pii",
      "reason_codes": []
    }
  ],
  "call_site_findings": [
    {
      "severity": "BLOCK|WARN",
      "path": "<path>",
      "line": 0,
      "reason_code": "<code>",
      "message": "<summary>"
    }
  ],
  "ordinal_map": {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "pii": 3
  }
}
```

## 失敗時の挙動

- TOML が parse できない: BLOCK。
- Matrix path が存在しない: BLOCK。
- required column 欠落: BLOCK。
- `training_use != no` で internal 以上送信可能: BLOCK。
- caller-provided `allowed_data_class`: BLOCK。
- `last_verified_at` 欠落: WARN。P0 acceptance では BLOCK に引き上げる。
- external provider 仕様の確認が必要な場合は、未確認として WARN / BLOCK を出し、Main Agent に確認を戻す。

## TaskManagedAI 不変条件 trace

- Provider Compliance Matrix を runtime 正本として守る。
- `payload_data_class` と `allowed_data_class` を分離する。
- data class ordinal `public < internal < confidential < pii` を固定する。
- provider_request_preflight を AC-HARD-02 / 07 に接続する。
- AgentRun result mapping と audit reason_code を維持する。
- AC-KPI-05 `cost_per_completed_task` の provider usage trace を守る。

