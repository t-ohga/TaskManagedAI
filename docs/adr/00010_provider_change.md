---
id: "ADR-00010"
title: "Provider Compliance Matrix v2 運用 / 機械判定 enum / data class ordinal 固定"
status: "proposed"
date: "2026-05-07"
authors:
  - "t-ohga"
related_sprints:
  - "SP-000_bootstrap"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-07

## 背景

- 決定対象: Provider Compliance Matrix v2、`payload_data_class` / `allowed_data_class`、data class ordinal、`provider_request_preflight`、Provider 追加 / 切替時の gate。
- 関連 Sprint: SP-000_bootstrap
- 前提 / 制約: P0 は OpenAI Responses、Anthropic Messages、Anthropic Batches、Gemini、Mock の 5 行を `config/provider_compliance.toml` の正本として扱う。Provider call 前の data class gate であり、`tool_mutating_gateway_stub` や `runner_mutation_gateway` とは別境界。ADR Gate Criteria #10（Provider 追加 / 切替 / Matrix 上限変更）に該当する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: Matrix TOML + Pydantic enum + ordinal 固定 | TOML 正本、Pydantic enum、ordinal map、`provider_request_preflight` で機械判定する | deny-by-default を実装しやすく、Matrix drift を検知できる | provider 仕様更新時に `last_verified_at` と policy version 更新が必要 |
| B: Matrix なし caller 判定 | caller が `allowed_data_class` 相当を判断する | 実装が短い | `payload_data_class` / `allowed_data_class` 混同で fail-open しやすい |
| C: Provider 全許可 + audit 後追い | 送信後に audit で検出する | 開発初期は楽 | deny-by-default 違反。secret / confidential 送信を未然に止められない |

## 採用案

- 採用: A: Matrix TOML + Pydantic enum + data class ordinal 固定 + `provider_request_preflight`
- 理由: Provider 仕様は変化するため、自由記述や caller 入力に頼らず、TOML 正本と enum で fail-closed にする。
- 実装 Sprint: SP-000_bootstrap で contract 固定、SP-005 で ProviderAdapter 実装前に accepted 化
- 実装対象ファイル:
  - `config/provider_compliance.toml`
  - `backend/app/providers/adapter.py`
  - `backend/app/middleware/compliance.py`
- 実装ガイダンス:
  - data class ordinal は `public < internal < confidential < pii`、ordinal map は `{public:0, internal:1, confidential:2, pii:3}` に固定する。文字列比較、provider 別順序、複数値 `allowed_data_class` を禁止する。
  - `allowed_data_class` は Matrix からのみ解決する。caller / UI から渡された `allowed_data_class` は無視ではなく設計違反として reject する。
  - `payload_data_class` 未設定、enum 外、provider / feature 未登録は provider へ送信せず deny する。
  - `payload_data_class > allowed_data_class` は middleware で必ず deny し、AgentRun は `blocked` + `policy_blocked` にする。
  - `training_use != no` の行は internal 以上を deny し、runtime の effective 上限を public まで強制低下する。public-only 例外は別 ADR を要求する。
  - `allowed_data_class >= confidential` は、`zdr_eligible=yes` または `zdr_eligible=conditional` + `condition_status=verified` に加え、`retention != unverified`、`training_use=no`、`region_or_data_transfer=verified`、**`plan_required != none`** をすべて満たす場合だけ許可する。`plan_required = none` AND effective >= confidential は `effective_allowed_data_class = internal` に runtime downgrade する (reason: `plan_unverified`)。他の条件不一致も同様に runtime downgrade。
  - `provider_request_preflight` は `ProviderAdapter.execute()` の必須段階とし、secret canary、provider / GitHub / Tailscale / SOPS / age key pattern、raw secret、`secret_ref` 直接展開違反を provider call 前に検知する。audit には raw 値を残さない。
  - **Matrix 行更新条件 (allow gate)**: `condition_status` を `unverified` → `verified` に変更する PR は次をすべて満たす場合のみ accept:
    - 根拠 URL (provider 公式 docs / DPA / subprocessor list) を `subprocessor_or_doc_url` に記録
    - `last_verified_at` を ISO 日付で更新
    - `provider_compliance_matrix_version` を semver bump
    - 該当 PR と connected な policy / matrix version 更新を `audit-ownership-matrix.md` の対応 owner agent (`provider-compliance-reviewer`) で確認
    - confidential 以上の解禁を伴う場合は ADR 更新 (本 ADR の supersedes / superseded_by 連鎖を作る) を必須にする
  - **`zdr_eligible=no` 行への internal 以上送信 deny**: `zdr_eligible=no` の行は `payload_data_class >= internal` を送信前 deny。これを許す経路を作るには **個別 ADR 必須** (P0 では原則不可)。`training_use=yes` または `unverified` の行も同様に `payload_data_class >= internal` deny。public-only 例外も ADR 承認済みのみ許可。
- テスト指針:
  - data class ordinal: map 比較のみで `payload_data_class <= allowed_data_class` を判定する。
  - unset / invalid / provider_not_in_matrix: すべて deny し、provider 未送信を確認する。
  - unverified deny / runtime downgrade: `condition_status != verified`、`training_use != no`、`region_or_data_transfer=unverified` を negative test 化する。
  - preflight canary: raw canary を provider request、runner stdout/stderr、artifact、audit payload に残さない。
  - Matrix drift: TOML 必須列、enum、`last_verified_at`、docs 同期を検証する。

## 却下案

- B: Matrix なし caller 判定: caller が `allowed_data_class` を持つと trust boundary が混ざり、fail-open の原因になるため却下する。
- C: Provider 全許可 + audit 後追い: `policy_blocked` の事前停止ができず、P0 の deny-by-default と Hard Gate の前提に反するため却下する。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| provider 仕様が変わり Matrix が古くなる | `last_verified_at` review、Matrix drift test | Provider 追加 / 切替 / 上限引き上げを ADR 必須にする |
| ordinal 実装が文字列比較になる | unit test、code review | Pydantic enum + ordinal map を shared 定義にする |
| `allowed_data_class` が caller 入力で上書きされる | negative test、request schema validation | caller 入力を reject し、Matrix 由来だけ audit に残す |
| 厳格すぎて必要 provider が使えない | 該当 reason_code (`zdr_ineligible` / `training_use_not_no` / `condition_unverified` / `retention_unverified` / `region_unverified` / `plan_unverified`) audit、blocked reason 集計 | public / internal の範囲で迂回せず、必要なら ADR + Matrix 更新で解禁する |

## rollback 手順

1. Provider 誤送信、Matrix 上限ミス、preflight bypass、provider 仕様 drift を検知したら、該当 provider / feature の effective 上限を `public` へ下げるか Matrix 行を一時 deny にする。
2. `provider_compliance_matrix_version` と `policy_version` を戻し、必要なら Mock provider のみに切り替える。`condition_status=verified` 変更は根拠が確認できるまで `unverified` に戻す。
3. `provider_blocked`、`policy_decision_created`、AgentRun `blocked` + `policy_blocked`、raw secret 非混入、Matrix TOML parse / enum test を確認し、provider 未送信で止まることを検証する。

