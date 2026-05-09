---
id: "SP-005_provider_adapter"
type: "heavy"
status: "draft"
sprint_no: 5
created_at: "2026-05-08"
updated_at: "2026-05-09"
target_days: 5.1
max_days: 7
adr_refs:
  - "[ADR-00010](../adr/00010_provider_change.md) # 2026-05-09 accepted (proposed → accepted、Provider Compliance Matrix v2 + ordinal + preflight 運用方針)"
planned_adr_refs: []
related_sprints:
  - "SP-004_agent_runtime"
downstream_sprints:
  - "SP-005-5_output_validator"
risks:
  - "Provider Compliance Matrix runtime drift"
  - "secret canary preflight 漏れ"
  - "structured output schema validation 不一致"
---

このテンプレの使い方: Sprint 5 の Provider Adapter Foundation で、Mock / OpenAI Responses / Anthropic Messages / Gemini ProviderAdapter、Structured Outputs、Provider Compliance Gate、`provider_request_preflight`、BudgetGuard 連動、provider_request_fingerprint、Gold Task v0 contract test、AC-HARD-01 / AC-HARD-02 統合を実装するための heavy Sprint Pack。ADR Gate Criteria #10 Provider 追加 / 切替、#3 API / event schema、#4 AI エージェント権限、#6 Secrets 境界に該当するため、ADR-00010 を accepted 化してから着手する。

最終更新: 2026-05-09 (Sprint 5 着手前 ADR Gate: ADR-00010 proposed → accepted)

## 目的

- ProviderAdapter を統一 contract にし、Mock、OpenAI Responses、Anthropic Messages、Gemini を同じ `execute()` / structured output / status mapping で扱えるようにする。
- Provider call 前に Compliance Gate と `provider_request_preflight` を必ず通し、`payload_data_class` 未設定、Matrix 未登録、data class 越境、secret / canary 検出を provider 未送信で止める。
- Structured Outputs を Pydantic schema と JSON Schema で検証し、refusal / incomplete / unsupported schema / max token truncation を AgentRun status に正しく mapping する。
- BudgetGuard と provider usage を接続し、`cost_per_completed_task` の source を作る。
- `provider_request_fingerprint` に `model_resolved` / `api_version` / `sdk_version` / schema fingerprint を含め、ContextSnapshot と stale approval invalidation に接続する。
- Gold Task v0 contract test を作り、ProviderAdapter の成功 / refusal / incomplete / budget / compliance deny を再現可能にする。
- AC-HARD-01 `policy_block_recall` fixture と AC-HARD-02 `secret_canary_no_leak` preflight を ProviderAdapter 境界へ統合する。

## 背景

- Sprint 4 は AgentRun 16 状態、ContextSnapshot 10 カラム、BudgetGuard、SecretBroker issue / redeem、plan artifact schema を作る。Sprint 5 はその runtime に provider 呼び出しを接続する。
- ADR-00010 は Provider Compliance Matrix v2、`payload_data_class` / `allowed_data_class`、ordinal map、runtime `effective_allowed_data_class`、`provider_request_preflight` を定義している。Sprint 5 実装前に accepted 化する。
- Provider Compliance rule は Matrix を `config/provider_compliance.toml` 正本とし、`allowed_data_class` を caller / UI から受け取る設計を禁止している。
- AI Output Boundary は Provider call を `ProviderAdapter.execute()` 経由に限定し、deny 時は provider 未送信で AgentRun を `blocked` + `policy_blocked` または `budget_blocked` にすることを要求している。
- P0 では provider bake-off の詳細比較より、fail-closed、structured output、status mapping、Hard Gate / KPI source を優先する。

## 対象外

- bake-off 詳細比較、provider ranking UI、モデル自動選択の高度化。P0.1 / P1 へ defer する。
- Output Validator / Input Trust Layer の full 実装。Sprint 5.5 で扱う。ただし Sprint 5 は structured output schema と adapter contract を提供する。
- Provider Compliance Matrix の `allowed_data_class` 引き上げ、conditional ZDR の verified 化、外部仕様の例外解禁。ADR-00010 更新なしに行わない。
- Codex App Server / Claude Remote Control / GitHub agent adapter。Sprint 6 以降の候補に残す。
- raw provider key、raw API key、raw canary 値を docs / fixture / audit / artifact に保存すること。
- Provider SDK の exhaustive wrapper。P0 は `execute()` contract と structured output path に必要な最小 adapter に絞る。

## 設計判断

- ProviderAdapter contract は `execute(request) -> ProviderResult` に統一する: request は provider、api_or_feature、model_requested、schema_ref、payload_data_class、artifact refs、run_id、actor_id、budget context を持つ。
- `allowed_data_class` は request に入れない: Compliance Gate が Matrix から解決し、caller が渡した場合は設計違反として reject する。
- Compliance Gate は **13 reason_code (正本: `.claude/rules/provider-compliance.md` §9)** を持つ: `payload_data_class_unset`、`payload_data_class_exceeds_allowed`、`effective_allowed_data_class_exceeded`、`zdr_ineligible`、`training_use_not_no`、`condition_unverified`、`retention_unverified`、`region_unverified`、`plan_unverified`、`provider_not_in_matrix`、`provider_request_preflight_violation`、`budget_exceeded`、`allow` (allow 含む)。
- BudgetGuard の `budget_exceeded` は Compliance Gate reason とは分け、AgentRun `blocked` + `budget_blocked` に mapping する。
- `effective_allowed_data_class` は runtime 計算する: Matrix raw の `allowed_data_class` を上限にしつつ、ZDR、training_use、condition_status、retention、region、plan_required の条件で低下させる。
- `provider_request_preflight` は provider call 前の必須 gate にする: secret canary pattern、provider / GitHub / Tailscale / SOPS / age key pattern、raw secret、`secret_ref` 直接展開違反を scan し、raw 値を保存しない。
- Structured Outputs は Pydantic schema を正本にし、adapter は provider 固有 schema 変換を隠蔽する。unsupported schema は provider failure ではなく `validation_failed` として扱う。
- Provider result mapping は Sprint 4 の AgentRun state machine に合わせる: refusal は `provider_refused`、incomplete / max token は `provider_incomplete`、unsupported schema / schema mismatch は `validation_failed`、success は `generated_artifact`。
- `provider_request_fingerprint` は `model_resolved`、`api_version`、`sdk_version`、schema fingerprint、safety / compliance matrix version から作り、ContextSnapshot と approval stale invalidation に使う。
- Mock adapter は contract test の正本にする: external provider の flaky を避け、Gold Task v0 と Hard Gate fixture を deterministic に通す。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 DD / 既存 backlog trace |
|---|---|---|---:|---|---|---|
| BL-0052 | ProviderAdapter contract (execute / structured output / status mapping) | F-012,F-008 | 0.5 | SP-004,ADR-00010 | interface、request/result model | PLAN-01 BL-0062 |
| BL-0053 | Mock provider adapter | F-012,F-019 | 0.4 | BL-0052 | deterministic success / error fixtures | Gold Task Seed v0 |
| BL-0054 | OpenAI Responses adapter | F-012,NF-004 | 0.6 | BL-0052 | structured output path、fingerprint | PLAN-01 BL-0063 |
| BL-0055 | Anthropic Messages adapter | F-012,NF-004 | 0.6 | BL-0052 | structured output path、fingerprint | PLAN-01 BL-0064 |
| BL-0056 | Gemini adapter | F-012,NF-004 | 0.5 | BL-0052 | structured output path、fingerprint | PLAN-01 BL-0065 |
| BL-0057 | Compliance Gate middleware (`effective_allowed_data_class` 計算 / 13 reason_code) | F-012,NF-004,AC-HARD-01 | 0.7 | BL-0052,ADR-00010 | ordinal map、Matrix resolver、audit | PLAN-01 BL-0066/0070 |
| BL-0058 | `provider_request_preflight` (secret canary regex + raw 値非露出 audit) | F-012,NF-004,AC-HARD-02 | 0.6 | BL-0057,SP-004 | preflight scan、deny audit | PLAN-01 BL-0154 |
| BL-0059 | `provider_request_fingerprint` (model_resolved / api_version / sdk_version) | F-009,F-012,NF-009 | 0.4 | BL-0052,SP-004 | fingerprint builder、ContextSnapshot連携 | PLAN-01 BL-0068 |
| BL-0060 | BudgetGuard 連動 (provider usage → AC-KPI-05) | F-010,F-012,AC-KPI-05 | 0.5 | BL-0052,SP-004 | usage logging、budget block、cost source | PLAN-01 BL-0069 |
| BL-0061 | Gold Task v0 contract test | F-019,NF-009 | 0.5 | BL-0053,BL-0057 | provider contract suite、dataset trace | PLAN-01 BL-0006 |
| BL-0062 | AC-HARD-01 fixture (`policy_block_recall`) | F-019,AC-HARD-01 | 0.4 | BL-0057,SP-003 | policy block fixture、reason_code expected | PLAN-01 BL-0041 |
| BL-0063 | AC-HARD-02 preflight 統合 | F-019,AC-HARD-02 | 0.4 | BL-0058,SP-004 | secret canary preflight integration | PLAN-01 BL-0160 |

## タスク一覧

- [ ] ADR-00010 を Sprint 5 実装前に accepted 化し、Matrix columns、ordinal map、runtime downgrade、preflight、rollback を確認する。
- [ ] ProviderAdapter request / result model を Pydantic で定義し、`allowed_data_class` caller input を schema reject する。
- [ ] ProviderResult に `status`, `artifact_ref`, `usage`, `model_resolved`, `api_version`, `sdk_version`, `provider_request_fingerprint`, `error_code` を持たせる。
- [ ] Mock adapter で success、refusal、incomplete、unsupported_schema、budget_exceeded、compliance deny を deterministic に返せるようにする。
- [ ] OpenAI Responses adapter を structured output path に限定して実装し、raw response の保存を redacted summary に制限する。
- [ ] Anthropic Messages adapter を structured output path に限定して実装し、provider-specific continuation は `provider_continuation_ref` に閉じる。
- [ ] Gemini adapter を structured output path に限定して実装し、unsupported schema を `validation_failed` に mapping する。
- [ ] Compliance Gate で Matrix TOML を parse し、provider / api_or_feature / `payload_data_class` / ordinal map を fail-closed にする。
- [ ] 13 reason_code を policy_decision / provider_blocked audit に保存し、raw prompt / raw secret / raw canary を payload に入れない。
- [ ] `effective_allowed_data_class` を runtime 計算し、Matrix raw `allowed_data_class` と別 dimension で audit / metric に残す。
- [ ] `provider_request_preflight` を ProviderAdapter.execute() の前に必ず通し、違反時は provider 未送信で `blocked` + `policy_blocked` にする。
- [ ] BudgetGuard を provider call 前後に接続し、hard limit 超過を `blocked` + `budget_blocked`、usage を cost source にする。
- [ ] `provider_request_fingerprint` を ContextSnapshot へ保存し、approval stale invalidation の比較対象にする。
- [ ] Gold Task v0 contract test を Mock adapter 中心に作り、external provider の flaky に依存しない suite にする。
- [ ] AC-HARD-01 `policy_block_recall` fixture で known dangerous provider_call / action を 100% block できることを確認する。
- [ ] AC-HARD-02 secret canary preflight を Sprint 4 fixture source と接続し、provider request 送信前に停止する。

## must_ship / defer_if_over_budget 対応表

### ロードマップ §94 正本 (verbatim quote)

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 5 | 5.1 | 7 | Mock + OpenAI + Claude + Gemini adapter の structured output + budget exceeded 試験 + Compliance Gate + `provider_request_preflight` | bake-off 詳細比較 |

### Sprint Pack 内詳細 trace

ロードマップ正本の must_ship を Sprint Pack 内で詳細化したもの:

| 項目 | ロードマップ → Sprint Pack trace |
|---|---|
| Mock + OpenAI + Claude + Gemini adapter の structured output | 実装チケット BL-0052, BL-0053, BL-0054, BL-0055, BL-0056 |
| budget exceeded 試験 | 実装チケット BL-0060 |
| Compliance Gate | 実装チケット BL-0057, BL-0062 |
| `provider_request_preflight` | 実装チケット BL-0058, BL-0063 |

## 受け入れ条件

- [ ] ADR-00010 が accepted 状態であり、ProviderAdapter 実装が Matrix v2、ordinal map、preflight、runtime downgrade と一致している。
- [ ] ProviderAdapter contract は Mock / OpenAI Responses / Anthropic Messages / Gemini で同一 request / result model を使う。
- [ ] request schema は `payload_data_class` を必須にし、caller-supplied `allowed_data_class` を reject する。
- [ ] Structured Outputs は Pydantic schema から JSON Schema を生成し、provider 固有変換が contract test で検証されている。
- [ ] refusal / safety refusal は `provider_refused`、incomplete / max token は `provider_incomplete`、unsupported schema / schema mismatch は `validation_failed` に mapping される。
- [ ] Compliance Gate は Matrix 未登録、`payload_data_class` 未設定、enum 不正、data class 越境を provider 未送信で deny する。
- [ ] 13 reason_code が audit / policy_decision / provider_blocked に保存され、raw request body や raw secret を含まない。
- [ ] `allowed_data_class` は Matrix raw 値、`effective_allowed_data_class` は runtime downgrade 後の値として別々に保存される。
- [ ] `training_use != no`、`zdr_eligible=no`、`condition_status != verified`、`retention=unverified`、`region_or_data_transfer=unverified`、`plan_required=none` の fail-closed / downgrade test がある。
- [ ] `provider_request_preflight` は provider call 前に必ず実行され、secret / canary / key pattern 検出時は provider 未送信で `blocked` + `policy_blocked` になる。
- [ ] preflight 違反 audit は pattern 種別と reason_code のみを保存し、raw 値を保存しない。
- [ ] BudgetGuard hard limit 超過は `blocked` + `budget_blocked` で、provider failure と混同しない。
- [ ] provider usage から `cost_per_completed_task` の source が作られ、AC-KPI-05 へ trace している。
- [ ] `provider_request_fingerprint` は `model_resolved`、`api_version`、`sdk_version`、schema fingerprint、Matrix version を含み、ContextSnapshot に保存される。
- [ ] Gold Task v0 contract test が Mock adapter で deterministic に動き、external provider の availability に依存しない。
- [ ] AC-HARD-01 `policy_block_recall` fixture が known dangerous provider_call / action を block できる。
- [ ] AC-HARD-02 preflight 統合により、secret canary が provider request に入る前に止まる。
- [ ] raw secret、API key、capability token、canary raw value が DB、audit、artifact、logs、test snapshot、docs に残らない。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-005_provider_adapter.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ruby -e 'text=File.read("docs/sprints/SP-005_provider_adapter.md"); missing=%w[BL-0052 BL-0053 BL-0054 BL-0055 BL-0056 BL-0057 BL-0058 BL-0059 BL-0060 BL-0061 BL-0062 BL-0063].reject { |id| text.include?(id) }; abort("missing: #{missing.join(",")}") unless missing.empty?'` で 12 チケットが揃っていることを確認する。
- [ ] `ls docs/adr/00010_provider_change.md` で ADR-00010 が存在することを確認する。
- [ ] `python -m tomllib config/provider_compliance.toml` で Matrix TOML が parse できることを確認する。
- [ ] `uv run pytest tests/providers/test_adapter_contract.py -q` で Mock / OpenAI Responses / Anthropic Messages / Gemini の request / result contract を確認する。
- [ ] `uv run pytest tests/providers/test_structured_outputs.py -q` で Pydantic / JSON Schema、unsupported schema、schema mismatch を確認する。
- [ ] `uv run pytest tests/providers/test_status_mapping.py -q` で refusal、incomplete、max token、unsupported schema、success の AgentRun mapping を確認する。
- [ ] `uv run pytest tests/providers/test_compliance_gate.py -q` で `payload_data_class` 未設定、Matrix 未登録、ordinal 比較、runtime downgrade、13 reason_code を確認する。
- [ ] `uv run pytest tests/providers/test_provider_request_preflight.py -q` で secret / canary scan、provider 未送信、raw 値非露出 audit を確認する。
- [ ] `uv run pytest tests/providers/test_provider_fingerprint.py -q` で `model_resolved` / `api_version` / `sdk_version` / schema fingerprint / Matrix version が fingerprint に入ることを確認する。
- [ ] `uv run pytest tests/runtime/test_provider_budget_guard.py -q` で budget exceeded が `blocked` + `budget_blocked` になることを確認する。
- [ ] `uv run pytest tests/eval/test_gold_task_v0_provider_contract.py -q` で Gold Task v0 contract test が Mock adapter で deterministic に通ることを確認する。
- [ ] `uv run pytest tests/eval/test_policy_block_recall_fixture.py -q` で AC-HARD-01 source fixture を確認する。
- [ ] `uv run pytest tests/eval/test_secret_canary_provider_preflight.py -q` で AC-HARD-02 preflight 統合を確認する。
- [ ] `rg -n "secret_value|get_secret_value|canary_value\s*[:=]|allowed_data_class\s*=\s*request" backend tests config --glob '!**/*.md'` で禁止 interface / raw 値 / caller-supplied allowed_data_class が実装に混入していないことを確認する (実装対象限定、Markdown 除外)。
- [ ] `rg -n "sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|AGE-SECRET-KEY-[A-Z0-9]{20,}" docs --glob '!docs/sprints/**' --glob '!docs/adr/**' --glob '!docs/設計検討/**'` で docs に実値らしい secret / API key / age key 値がないことを確認する (共通 token regex set)。
- [ ] `ruby -e 'text=File.read(ARGV[0]); forbidden=[["ie","shima"].join, ["academy",["ie","shima"].join].join("."), ["i","FILTER"].join("-")].select { |s| text.include?(s) }; abort("forbidden terms: #{forbidden.join(",")}") unless forbidden.empty?' docs/sprints/SP-005_provider_adapter.md` で別プロジェクト固有語がないことを確認する (検証コマンド自身が self-match しないよう禁止語は実行時組立て)。

## レビュー観点

- [ ] ADR-00010 の accepted 内容と実装が一致している。
- [ ] ProviderAdapter.execute() 以外から provider call へ進む bypass がない。
- [ ] `payload_data_class` は必須で、`allowed_data_class` は Matrix からのみ解決されている。
- [ ] ordinal map は `public < internal < confidential < pii` の数値比較で、文字列比較や provider 別順序がない。
- [ ] `effective_allowed_data_class` が runtime downgrade され、Matrix raw `allowed_data_class` と別 dimension で audit / metrics に残る。
- [ ] Compliance Gate deny と preflight deny は provider 未送信で停止する。
- [ ] secret canary、provider key、GitHub token、Tailscale auth key、SOPS / age key pattern の検出結果に raw 値が残らない。
- [ ] BudgetGuard の `budget_exceeded` は provider failure ではなく `blocked` + `budget_blocked` に mapping される。
- [ ] Provider result mapping が AgentRun state machine と一致し、`provider_incomplete` を terminal 扱いしていない。
- [ ] Mock adapter が deterministic な contract test の正本になり、external provider flaky に P0 gate が依存していない。
- [ ] AC-HARD-01 / AC-HARD-02 / AC-KPI-05 への trace が fixture、metric source、audit で説明できる。

## 残リスク

- Provider Compliance Matrix runtime drift: Matrix TOML 必須列 test、ordinal map test、`last_verified_at` review、ADR-00010 accepted gate で検出する。
- secret canary preflight 漏れ: ProviderAdapter.execute() の入口で preflight を必須化し、provider 未送信 assertion と audit raw 値非露出 test を release blocker にする。
- structured output schema validation 不一致: Pydantic schema を正本にし、provider-specific schema 変換を contract test で検出する。
- external provider SDK / API 仕様変更: P0 gate は Mock adapter contract を正本にし、外部仕様更新は ADR-00010 と Matrix version bump を要求する。
- strict policy により provider call が過剰 block される: blocked reason 集計で検出し、例外は bypass ではなく ADR + Matrix 更新で扱う。
- cost source が provider usage 差異に依存する: usage normalization を adapter result に閉じ、AC-KPI-05 は completed task 単位で再集計する。

## 次スプリント候補

- Sprint 5.5: Output Validator / Input Trust Layer。structured output schema、repair retry、payload_data_class 算出、trusted_instruction 化、secret canary preflight 統合を完成させる。
- Sprint 6: CLI Artifact Orchestration。ProviderAdapter 生成 artifact を CLI subprocess / stdout artifact へつなぐ。
- Sprint 7: Docker isolated runner。runtime_blocked、forbidden path、dangerous command、runner_mutation_gateway を本実装する。
- Sprint 9: Settings UI で provider / budget read-only state を表示し、Provider Compliance の詳細編集は P1 へ送る。
- Sprint 11: provider contract と Hard Gate fixture を Eval Harness に登録する。
- Sprint 12: AC-HARD-01、AC-HARD-02、AC-KPI-05 の final 判定へ接続する。

## 関連 ADR

- [ADR-00010](../adr/00010_provider_change.md): Sprint 5 実装前に accepted 化する。Provider Compliance Matrix v2、`payload_data_class` / `allowed_data_class`、ordinal map、runtime `effective_allowed_data_class`、`provider_request_preflight`、Provider 追加 / 切替 gate を定義する。
- ADR-00004 は Sprint 4 の AgentRun state machine と provider result mapping の前提として参照する。
- ADR-00006 は provider key を raw secret として扱わず SecretBroker mediated operation に閉じる前提として参照する。
- ADR-00009 は `provider_call` action class と policy block recall の前提として参照する。

## Review

完了日: 2026-05-09 (Batch 1-4 + Sprint Exit)

### 実装方式

Codex multi-round adversarial review pattern (Sprint 1-4 から継続):

| Batch | round | findings |
|-------|------|----------|
| Batch 1 (ProviderAdapter contract + Mock + fingerprint + BudgetGuard) | R1→R2→R3→R5 (clean) | 9 (HIGH 4 + MEDIUM 4 + LOW 1) |
| Batch 2 (Compliance Gate + preflight + AC-HARD-02 統合) | R1→R2→R3→R5 (clean) | 11 (BLOCKER 2 + HIGH 4 + MEDIUM 5) |
| Batch 3 (OpenAI + Anthropic + Gemini 3 adapter) | R1→R2→R3→R4→R5 (clean) | 8 (HIGH 4 + MEDIUM 3 + LOW 1) |
| Batch 4 (Gold Task v0 + AC-HARD-01 + AC-KPI-05) | R1→R2→R3 (clean) | 4 (BLOCKER 1 + HIGH 3) |

**累計 ~16 round / 32 findings**。Sprint 1-5 全体で約 175+ findings 解消。

### changed (実装ファイル群)

- **Batch 1** (BL-0052/0053/0059/0060): ProviderRequest/Result/Adapter Protocol + Mock 8 marker + compute_provider_request_fingerprint NFC+JCS+SHA-256 + record_provider_usage で BudgetGuard 連動。共通 `_payload_secret_scan.py` を 18→21 種に拡張 (secret_capability_token / raw_token / session_token 追加)、PEM regex を generic + typed 両対応 (`-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----`)
- **Batch 2** (BL-0057/0058/0063): `config/provider_compliance.toml` 新規 (5 entries)、ComplianceGate.evaluate (13 reason_code + 6 downgrade rule + zdr_eligible='n/a' fail-closed) + enforce (transition_with_event 三重 guard) + provider_request_preflight (canary marker + 共通 21 keys + 8 regex) + AC-HARD-02 fixture loader 統合
- **Batch 3** (BL-0054/0055/0056): OpenAIResponsesAdapter + AnthropicMessagesAdapter + GeminiAdapter (structured output limited、`secret_capability_token` broker-mediated、redact_response_summary、HTTP error mapping、Gemini unsupported_schema 4 check pre-check + RECITATION finish_reason)
- **Batch 4** (BL-0061/0062/AC-KPI-05): Gold Task v0 dataset/runner/contract test (4 adapter × 3 case)、AC-HARD-01 fixture loader 統合 test (PolicyRule lookup + reason_code strict assert)、AC-KPI-05 (`cost_per_completed_task`) fixture skeleton (23 invariant + _compute_expected_aggregate + _RAW_SECRET_VALUE_PATTERNS)

### verified

- 4 adapter (Mock / OpenAI / Anthropic / Gemini) 全て同 ProviderAdapter Protocol、ProviderResultKind 11 種で statu mapping
- Provider Compliance Matrix v2 (`config/provider_compliance.toml`、5 entries) からのみ `allowed_data_class` 解決、caller 入力 (`extra="forbid"` schema reject) で物理禁止
- effective_allowed_data_class 6 downgrade rule (training_use_not_no / zdr_ineligible / condition_unverified / retention_unverified / region_unverified / plan_unverified)
- 13 reason_code (provider-compliance.md §9 と完全一致)
- OperationContext-style fingerprint (NFC + JCS + SHA-256) で provider_compliance_matrix_version + model_resolved + api_version + sdk_version を含めた deterministic
- preflight が共通 `assert_no_raw_secret` 経由で 21 keys + 8 regex pattern (PEM generic + typed) + canary marker pattern を全 4 path (request body / messages / structured_output_schema / safety_settings) で recursive scan
- ComplianceGate.enforce が AuditEvent (`policy_decision_created` / `provider_blocked`) と AgentRunEvent (`policy_blocked` via transition_with_event 三重 guard) の 2 taxonomy で audit
- AC-HARD-01 fixture が PolicyRule lookup 経由で `task_write_requires_approval` reason_code を strict assert (Sprint 5 Batch 2 ComplianceGate ではなく Sprint 3 Batch 1 PolicyRule 経由、reason_code false positive 防止)
- AC-HARD-02 fixture が ComplianceGate + preflight で 4 path 全 redact + raw value 非含む audit
- Gold Task v0 で 4 adapter × 3 case = 12 contract test、structured_output_body validate (redacted summary でなく)
- AC-KPI-05 fixture が deterministic recompute (`_compute_expected_aggregate`) + 11 種 _PROHIBITED_REDACTED_KEYS + 8 種 _RAW_SECRET_VALUE_PATTERNS recursive scan
- ADR-00010 accepted (2026-05-09 着手前)
- markdown fence 出力禁止 prompt が全 Codex round で完全機能 (Sprint 4 Batch 3 R2 反省を活用)

### deferred (Sprint 6+ へ送った項目)

- **bake-off 詳細比較 / provider ranking / モデル自動選択**: Sprint 11 Eval Harness で本格化
- **Output Validator full pipeline**: Sprint 6 (`SP-005-5_output_validator`) で完成
- **provider settings full UI**: Sprint 9 (UI sprint) で本格化
- **AC-KPI-05 KPI dashboard**: Sprint 11.5 (OTel + Loki + Grafana) で
- **AC-HARD-01 fixture loader を Eval Harness 経由で score / report**: Sprint 11
- **bake-off / provider routing optimization**: Sprint 11 Eval Harness または Sprint 12 P0 Acceptance
- **AgentRun retry policy で error_code (http_4xx_*) を見て retry 抑制**: Sprint 6 worker retry policy で本格化 (Batch 3 R2 で defer)
- **Codex App Server / remote adapter 候補**: P1+

### risks (残リスク + 検知方法)

| risk | 検知方法 | 対応 Sprint |
|------|---------|-----------|
| Matrix drift (TOML と Pydantic schema / runtime gate 不整合) | ComplianceMatrixEntry `extra="forbid"` + matrix_version mismatch deny | 現状 PASS、Sprint 11 で eval harness 経由再検証 |
| preflight bypass (新 secret pattern を共通 module に追加忘れ) | parity test (`test_payload_secret_scan_drift.py`) で 3+ repository identity 確認 + Sprint 5 Batch 1 R3 PEM regex generic + typed 拡張 | Sprint 6+ で新 provider/secret 追加時に再評価 |
| schema mismatch / unsupported_schema (Gemini 仕様制限) | Gemini 4 check (depth + unsupported types + array-of-array + excessive properties) + Gold Task v0 contract test | 現状 PASS、Sprint 11 で実 Gemini API integration |
| SDK 仕様変更 (api_version / sdk_version drift) | provider_request_fingerprint に matrix_version + api_version + sdk_version 含める (stale request 検出) | 現状 PASS |
| 過剰 block (legitimate fixture が新 _RAW_SECRET_VALUE_PATTERNS で false positive reject) | parametrized test 8 種 + control fixtures (Sprint 4 Batch 4 control_no_canary pattern) | 現状 PASS |
| cost source normalization (各 adapter の usage 計算が drift) | Gold Task v0 で 4 adapter 同 contract、usage_logger で BudgetGuard 連動 | 現状 PASS、Sprint 11 で実 provider integration |
| AC-HARD-01 false positive (data-class deny で通る) | PolicyRule lookup 経由 + reason_code strict assert (R1-F001 fix) | 現状 PASS |

### Sprint Exit 判定

- ✅ **must_ship 全達成**: Mock + OpenAI + Anthropic + Gemini adapter + structured output + budget exceeded 試験 + Compliance Gate + provider_request_preflight
- ✅ **ADR-00010 accepted** (2026-05-09)、SP-005 frontmatter 移送完了
- ✅ **Codex multi-round review で全 batch clean 達成** (累計 ~16 round / 32 findings)
- ✅ **AC-HARD-01 + AC-HARD-02 + AC-KPI-05 fixture 統合 ready** (loader / fixture skeleton 全て、Sprint 11 で eval harness 接続)
- ✅ **defense-in-depth 4 重防御** (DB + ORM + service + loader + test) が Compliance Gate / preflight / SecretBroker 全 boundary で揃う
- ✅ **既存 Sprint (1-4) との regression なし** (cross-source enum 整合 / 共通 _payload_secret_scan / transition_with_event 三重 guard / fingerprint NFC+JCS+SHA-256 維持)

→ **Sprint 5 完了**。次 Sprint は Sprint 5.5 (Output Validator full pipeline) または Sprint 6 (Worker / arq job、AgentRun runtime 経路完成)。

**重要**: Sprint 1-4 知見の `.claude/` ハーネス恒久化 task #54 は別セッションで進行中。Sprint 5 終了時点で memory 更新 (`project_taskmanagedai_sprint5_progress.md`) とハーネス化進捗確認は次セッションでも継続。

