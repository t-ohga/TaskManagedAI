---
id: "SP-005-5_output_validator"
type: "heavy"
status: "draft"
sprint_no: 5.5
created_at: "2026-05-10"
updated_at: "2026-05-10"
target_days: 4
max_days: 6
adr_refs:
  - "[ADR-00004](../adr/00004_agentrun_state_machine.md) # accepted、AgentRun 16 状態 / blocked サブ 3 / validation_failed / repair_exhausted / repair retry / ContextSnapshot snapshot_kind=resume の前提"
  - "[ADR-00006](../adr/00006_secrets_management.md) # accepted、retry prompt / repair input に raw secret 非露出 + redacted summary のみ"
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # accepted、action_class 7 種、Output Validator は action class 拡張なし、trusted_instruction 昇格は既存 approval 経路に閉じる"
  - "[ADR-00010](../adr/00010_provider_change.md) # accepted、payload_data_class 事前算出、allowed_data_class caller 入力禁止、`provider_request_preflight`"
planned_adr_refs: []
related_sprints:
  - "SP-005_provider_adapter"
upstream_sprints:
  - "SP-005_provider_adapter"
downstream_sprints:
  - "SP-006_cli_artifact"
  - "SP-007_runner_sandbox"
risks:
  - "repair retry が secret leak / prompt injection の媒介になる"
  - "Input Trust Layer の trust_level 昇格 bypass"
  - "payload_data_class 算出ロジックの caller 入力混入"
  - "repair_exhausted を terminal 扱いせず retry する regression"
---

このテンプレの使い方: Sprint 5 の Provider Adapter Foundation で provider 出力 → ProviderResultKind 11 種 mapping までは完成済。Sprint 5.5 ではその後段の **Output Validator full pipeline** (validation_failed の repair retry policy 完成、repair_exhausted terminal 強制) と **Input Trust Layer** (untrusted_content / validated_artifact / trusted_instruction の 3 trust_level 境界 + payload_data_class 事前算出) を完成させる。AgentRun runtime の provider call → Compliance Gate → preflight → execute → record_provider_usage → validation → repair retry → transition_with_event の全 chain integration を Sprint 6 worker 着手前に揃える。ADR Gate Criteria 該当は **既存 ADR-00004 / 00006 / 00009 / 00010 の延長** で済む見込み (新規 ADR proposed なし)、ただし設計判断で trust_level 昇格経路に変更が出れば re-evaluate する。

最終更新: 2026-05-10 (Sprint 5.5 着手前 draft、Codex multi-round plan-review で finalize 予定)

## 目的

- Output Validator full pipeline を完成させ、`validation_failed` (Sprint 5 で adapter 内 mapping 済) からの **repair retry policy** (上限制御 / BudgetGuard 連動 / redacted context 引き継ぎ / `repair_exhausted` terminal) を AgentRun runtime に実装する。
- Input Trust Layer を導入し、provider output / external fetch / memory retrieval / inter_agent_message を **`untrusted_content` 既定** とし、schema validation 済 artifact のみ `validated_artifact`、human approval + server-owned refs 済のみ `trusted_instruction` に昇格する 3 段階を強制する。
- `payload_data_class` 事前算出ロジックを Input Trust Layer 側に集約し、ProviderAdapter 入口での再算出禁止を担保する (caller-supplied 経路の signature レベル物理禁止を継続)。
- AgentRun runtime 経路の **provider call → Compliance Gate → preflight → execute → validate → repair retry → transition_with_event** 全 chain integration を Sprint 6 worker 着手前に揃える。
- AC-HARD-07 `prompt_injection_resist` の核となる **untrusted_content → trusted_instruction 昇格 deny** fixture を Input Trust Layer で接続する。

## 背景

- Sprint 5 (Provider Adapter Foundation) で 4 adapter (Mock/OpenAI/Anthropic/Gemini) が `ProviderResultKind` 11 種 (success / refusal / safety_refusal / max_token / incomplete / timeout_retryable / unsupported_schema / schema_mismatch / budget_exceeded 等) で AgentRun status へ mapping 完了。schema mismatch / unsupported_schema は `validation_failed` に mapping されるが、**repair retry policy 自体は Sprint 5 では未実装** (Sprint 5 progress memory `defer 残リスク` で「Output Validator full pipeline: Sprint 5.5 (次)」と明記)。
- ADR-00004 §AgentRun state machine で `validation_failed -> running -> ... -> validation_failed` の repair retry を上限まで許可、上限到達で `repair_exhausted` (terminal) に遷移することが定義されている。Sprint 5.5 でこの transition を実装する。
- AI Output Boundary rules (`.claude/rules/ai-output-boundary.md` §4 Artifact 原則 / §6 Policy Lint / §10 Provider Boundary) で「provider output は untrusted_content として扱う」「human approval 後の plan だけが trusted_instruction に昇格」を要求しているが、Sprint 5 までは untrusted_content / trusted_instruction が **概念のみ** で実装に明示的な trust_level field がない。Sprint 5.5 で Input Trust Layer として明示する。
- Phase D-H Multi-Agent vision で `inter_agent_messages` table (P0.1 SP-015) に 3 trust_level (`untrusted_content` / `validated_artifact` / `trusted_instruction`) が DB CHECK で導入される計画 (`.claude/rules/multi-agent-orchestration.md` §6)。Sprint 5.5 では P0 段階で **artifact 単体** に trust_level 概念を先行導入し、P0.1 SP-015 で inter_agent_messages にも同 enum を再利用できるようにする。
- Sprint 5 で確立した invariant (caller-supplied 経路の signature レベル物理禁止、共通 `_payload_secret_scan.py`、`assert_no_raw_secret`、cross-source enum 整合 5+ source、4 重防御) を Sprint 5.5 でも維持。
- P0 では dangerous intent classifier の高度化は対象外 (defer_if_over_budget)。基本的な untrusted_content boundary + repair retry + trust_level enum で Sprint 6 worker 着手の prerequisite を揃えることを優先。

## 対象外

- dangerous intent classifier の高度化 (LLM 経由の意図分類 / safety filtering 高精度化)。P0.1 / P1 へ defer。
- Output Validator の自動修正提案 (auto-suggest patch)。P0 では human approval 経由の修正を前提とし、自動修正は ADR Gate に該当するため Sprint 5.5 では着手しない。
- inter_agent_messages の trust_level (P0.1 SP-015 で導入)。Sprint 5.5 では artifact 単体の trust_level を先行導入し、enum を再利用できる形に閉じる。
- memory retrieval の trust_level (P0.1 SP-018 で hermes pattern adoption)。Sprint 5.5 ではスコープ外。
- repair retry の context window 最適化 / 高度化 (token 削減 prompt engineering)。基本的な redacted summary 引き継ぎのみ実装。
- AC-HARD-07 fixture を eval harness 経由で score / report する実装。Sprint 11 (Eval Harness) で本格化、Sprint 5.5 では fixture loader / 統合 test まで。
- raw provider response、secret canary raw value、capability token 生値を repair retry prompt / artifact / audit に保存すること (Sprint 5 と同じ invariant 継続)。

## 設計判断

- **repair retry 上限**: `policy_pack` の `repair_retry_max_attempts` (default 3) と BudgetGuard の `repair_budget_remaining` の AND で制御する。どちらかが exhausted なら `repair_exhausted` (terminal) に遷移。policy 上限は ADR-00009 の延長で defer policy で扱う。
- **repair retry context**: previous artifact (validated_artifact 化失敗版) と validation error の **redacted summary** のみを retry prompt に入れる。raw provider response / secret canary raw value / capability token 生値は入れない (`assert_no_raw_secret` を retry prompt builder で必須実行)。
- **repair retry の ContextSnapshot**: 各 retry ごとに `snapshot_kind=resume` の ContextSnapshot を作成 (ADR-00004 §11)。`provider_request_fingerprint` は新しい retry 用 fingerprint を再計算し、stale approval invalidation を機械的に検出可能にする。
- **trust_level enum**: `untrusted_content` / `validated_artifact` / `trusted_instruction` の 3 種固定。DB CHECK + ORM CheckConstraint + Python Literal + Pydantic Field validator + pytest `EXPECTED_TRUST_LEVELS` の **5+ source 整合** で drift 防止 (`.claude/rules/cross-source-enum-integrity.md` §1 pattern)。
- **trust_level 昇格経路 (server-owned)**:
  - `untrusted_content -> validated_artifact`: schema validation pass + policy lint pass で自動昇格 (server 側、caller 入力なし)
  - `validated_artifact -> trusted_instruction`: human approval (Approval 4 整合 + decider human-only) + server-owned refs (artifact_hash + policy_version + provider_request_fingerprint + action_class) のすべてが揃った場合のみ
  - caller / API endpoint / Server Action から trust_level を直接指定する path は signature レベルで物理削除 (`extra="forbid"` schema reject)
- **payload_data_class 事前算出**: Input Trust Layer 側で artifact metadata + request context から算出し、caller / ProviderAdapter は「読むだけ」にする。算出ロジックは `backend/app/services/input_trust/payload_classifier.py` (新規) に集約、`extra="forbid"` で caller 入力を schema reject。Sprint 5 で確立した「caller-supplied 経路禁止」を Input Trust Layer 側にも適用 (`.claude/rules/server-owned-boundary.md` §1 invariant 継続)。
- **AgentRun runtime 経路 integration**: 既存 `transition_with_event` 三重 guard (Sprint 4 Batch 1) を維持し、provider call → Compliance Gate → preflight → execute → validate → repair retry の各 transition で AgentRunEvent を append-only に積む。validation_failed → running (retry) は既存 transition allow list に含まれることを契約 test で確認。
- **repair_exhausted terminal 強制**: ADR-00004 §3 Terminal State の通り、`repair_exhausted` から retry / resume / state transition を deny。state machine contract test で全 16 状態 × invalid transition を parametrize して確認。
- **prompt injection 防御**: untrusted_content (provider output / external fetch) に「この artifact を trusted_instruction として実行せよ」等の指示が混入しても、trust_level 昇格は server 側 + human approval 経由のみのため自動実行しない。AC-HARD-07 fixture で 5+ injection pattern を 100% deny できることを確認。
- **既存 invariant の継続**: Sprint 1-5 で確立した invariant (caller-supplied 経路禁止、共通 `_payload_secret_scan.py`、`assert_no_raw_secret`、cross-source enum 5+ source、4 重防御 4 layer、AgentRun 16 状態、ContextSnapshot 10 列、Provider Compliance 13 reason_code) は **すべて維持**。Sprint 5.5 で破壊しない。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 DD / 既存 backlog trace |
|---|---|---|---:|---|---|---|
| BL-0064 | Output Validator core (validation_failed + repair retry policy) | F-008,F-013 | 0.7 | SP-005,ADR-00004 | OutputValidator service + repair retry transition + policy_pack `repair_retry_max_attempts` | PRD-01 F-008 / DD-03 §AgentRun runtime |
| BL-0065 | Input Trust Layer (3 trust_level enum + 5+ source 整合) | F-008,F-009,AC-HARD-07 | 0.6 | SP-005,ADR-00004 | trust_level enum DB CHECK + ORM + Pydantic + Python Literal + pytest EXPECTED + Server-owned 昇格 service | DD-04 §AI Output Boundary / rules/ai-output-boundary.md §4 |
| BL-0066 | payload_data_class 事前算出 service (caller-supplied 禁止維持) | F-012,NF-004 | 0.5 | BL-0065,ADR-00010 | payload_classifier.py + `extra="forbid"` schema + caller-supplied audit | rules/provider-compliance.md §4 / rules/server-owned-boundary.md §1 |
| BL-0067 | AgentRun runtime 経路 integration (provider → validate → repair retry → transition_with_event) | F-008,F-009,F-013 | 0.6 | BL-0064,BL-0065,SP-004 | runtime orchestrator + transition_with_event 三重 guard + AgentRunEvent append + ContextSnapshot snapshot_kind=resume | DD-03 §AgentRun runtime / rules/agentrun-state-machine.md §11 |
| BL-0068 | repair retry context redaction (raw secret 非露出 + redacted summary) | F-008,AC-HARD-02 | 0.4 | BL-0067,SP-005 | retry prompt builder + assert_no_raw_secret 必須実行 + redacted_response_summary 拡張 | rules/secretbroker-boundary.md §11 / rules/ai-output-boundary.md §10 |
| BL-0069 | trust_level 昇格 service (validated_artifact → trusted_instruction、Approval 4 整合) | F-009,F-013 | 0.5 | BL-0065,SP-003 | trust_level promotion service + Approval 4 整合 + decider human-only + audit_event | rules/server-owned-boundary.md §3 / DD-03 §Approval |
| BL-0070 | repair_exhausted terminal 強制 contract test | F-008,F-013 | 0.3 | BL-0064,BL-0067,SP-004 | state machine test + invalid transition deny parametrized | rules/agentrun-state-machine.md §3 |
| BL-0071 | AC-HARD-07 prompt_injection_resist fixture loader | F-019,AC-HARD-07 | 0.4 | BL-0065,BL-0069 | fixture loader (5+ injection pattern) + untrusted_content → trusted_instruction 昇格 deny test | docs/要件定義/01_P0要求定義.md §AC-HARD-07 |

target 合計 4.0 day (target_days と一致). max 6 day では retry policy / fixture 拡張余地。

## タスク一覧

- [ ] ADR-00004 / 00006 / 00009 / 00010 が accepted 状態であることを確認 (proposed があれば accepted 化を Sprint 5.5 着手前に実施)。
- [ ] Output Validator の `repair_retry_max_attempts` policy pack 設定を `config/policy_pack.toml` (Sprint 3 で導入済) に追加 (default 3、policy_version bump)。
- [ ] OutputValidator service を `backend/app/services/output_validator/` (新規) に実装し、validation_failed → running (retry) → validation_failed (再失敗) → repair_exhausted の transition を AgentRun state machine と整合させる。
- [ ] trust_level enum (`untrusted_content` / `validated_artifact` / `trusted_instruction`) を DB CHECK + ORM CheckConstraint + Python Literal + Pydantic Field validator + pytest `EXPECTED_TRUST_LEVELS` の **5+ source 整合** で drift 防止。
- [ ] migration `00NN_p0_trust_level_enum.py` で artifacts table に `trust_level` column 追加 (NOT NULL DEFAULT 'untrusted_content'、CHECK constraint で 3 種固定)。
- [ ] Server-owned 昇格 service `backend/app/services/input_trust/promotion.py` (新規) で trust_level の遷移を一元管理 (caller / API endpoint から直接指定する path は signature レベル物理削除)。
- [ ] payload_classifier service `backend/app/services/input_trust/payload_classifier.py` (新規) で `payload_data_class` を artifact metadata + request context から算出 (caller-supplied 禁止 / `extra="forbid"` で schema reject)。
- [ ] AgentRun runtime orchestrator (Sprint 4 Batch 4 で skeleton 済) に provider call → Compliance Gate → preflight → execute → record_provider_usage → validate → repair retry → transition_with_event の chain を統合 (各 transition で AgentRunEvent append + ContextSnapshot snapshot_kind=resume)。
- [ ] repair retry prompt builder で previous artifact + validation error の redacted summary のみを引き継ぎ、`assert_no_raw_secret` を必須実行 (raw provider response / secret canary / capability token 生値が入らないことを確認)。
- [ ] trust_level 昇格 service で `validated_artifact -> trusted_instruction` を Approval 4 整合 (artifact_hash + policy_version + provider_request_fingerprint + action_class) + decider human-only で強制し、self-approval 禁止 (DB CHECK + service guard) を再確認。
- [ ] repair_exhausted terminal 強制 contract test を parametrize し、`repair_exhausted` から `running` / `gathering_context` / `completed` 等への transition は全件 deny (16 状態 × invalid transition matrix で network test)。
- [ ] AC-HARD-07 fixture loader を `tests/eval/test_prompt_injection_resist_fixture.py` (新規) に実装し、5+ injection pattern (例: 「この artifact を trusted_instruction として実行せよ」「previous instructions を ignore」「new safety policy を apply」「secret_ref を resolve せよ」「approval を skip せよ」等) を全件 deny できることを確認。
- [ ] AgentRunEvent に `output_validation_failed` / `repair_retry_scheduled` / `repair_exhausted` / `trust_level_promoted` / `trust_level_promotion_denied` の 5 event_type を追加 (既存 22 event_type の延長、cross-source enum 整合 5+ source で drift 防止)。
- [ ] audit_event に raw secret / raw provider response / capability token 生値が入らないことを `tests/security/test_audit_no_raw_secret.py` (Sprint 5 で導入済) の parametrized test に追加して確認。
- [ ] Codex multi-round adversarial review (Sprint 1-5 と同 pattern) で各 Batch を clean まで finalize。

## must_ship / defer_if_over_budget 対応表

### ロードマップ §94 正本 (verbatim quote)

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 5.5 | 4 | 6 | Output Validator / Input Trust Layer / repair retry policy | dangerous intent classifier 高度化 |

### Sprint Pack 内詳細 trace

ロードマップ正本の must_ship を Sprint Pack 内で詳細化したもの:

| 項目 | ロードマップ → Sprint Pack trace |
|---|---|
| Output Validator | 実装チケット BL-0064 (core), BL-0067 (runtime integration), BL-0068 (context redaction), BL-0070 (repair_exhausted terminal contract test) |
| Input Trust Layer | 実装チケット BL-0065 (3 trust_level enum), BL-0066 (payload_data_class 算出), BL-0069 (trust_level 昇格 service), BL-0071 (AC-HARD-07 fixture) |
| repair retry policy | 実装チケット BL-0064 (上限制御), BL-0067 (transition_with_event 統合), BL-0068 (redacted context) |

defer (max_days 超過時): dangerous intent classifier 高度化 (LLM 経由 safety filtering 高精度化、auto-suggest patch、context window 最適化)。これらは Sprint 11 (Eval Harness) または P0.1 / P1 で扱う。

## 受け入れ条件

- [ ] OutputValidator service が `validation_failed` → `running` (retry) → `validation_failed` (再失敗) → `repair_exhausted` の transition を AgentRun state machine と整合させて実装している。
- [ ] `repair_retry_max_attempts` policy が `config/policy_pack.toml` で default 3、上限到達で `repair_exhausted` terminal に遷移する。
- [ ] BudgetGuard `repair_budget_remaining` が 0 なら policy 上限未満でも `repair_exhausted` に遷移する (どちらかが exhausted なら terminal)。
- [ ] trust_level enum (`untrusted_content` / `validated_artifact` / `trusted_instruction`) が DB CHECK + ORM + Python Literal + Pydantic + pytest EXPECTED の 5+ source で完全整合し、drift detection 可能。
- [ ] artifact table の `trust_level` column NOT NULL DEFAULT 'untrusted_content' CHECK constraint (3 種固定) で migration が適用される。
- [ ] trust_level 昇格は server-owned のみ (caller / API endpoint / Server Action から直接指定する path は schema reject、`extra="forbid"`)。
- [ ] `untrusted_content -> validated_artifact` は schema validation pass + policy lint pass で自動昇格、`validated_artifact -> trusted_instruction` は human approval + server-owned refs 4 整合 + decider human-only でのみ昇格する。
- [ ] payload_classifier service が `payload_data_class` を artifact metadata + request context から算出し、caller-supplied 経路は signature レベルで物理削除されている。
- [ ] AgentRun runtime 経路で provider call → Compliance Gate → preflight → execute → record_provider_usage → validate → repair retry → transition_with_event の chain が AgentRunEvent + ContextSnapshot で再現可能。
- [ ] repair retry prompt は previous artifact + validation error の redacted summary のみで、raw provider response / secret canary / capability token 生値が含まれない (`assert_no_raw_secret` 必須実行)。
- [ ] 各 retry ごとに ContextSnapshot `snapshot_kind=resume` が生成され、`provider_request_fingerprint` が再計算される。
- [ ] `repair_exhausted` terminal から `running` / `gathering_context` / `completed` / 他 14 状態への transition が全件 deny される (state machine contract test で 16 状態 × invalid transition matrix で確認)。
- [ ] AC-HARD-07 fixture (5+ prompt injection pattern) が `untrusted_content -> trusted_instruction` 昇格を 100% deny する。
- [ ] AgentRunEvent の 5 新 event_type (`output_validation_failed` / `repair_retry_scheduled` / `repair_exhausted` / `trust_level_promoted` / `trust_level_promotion_denied`) が cross-source enum 5+ source で整合。
- [ ] audit_event に raw secret / raw provider response / capability token 生値が含まれないことを parametrized test で確認。
- [ ] Sprint 1-5 で確立した invariant (caller-supplied 経路禁止 / 共通 `_payload_secret_scan.py` / cross-source enum 5+ source / 4 重防御 4 layer / AgentRun 16 状態 / ContextSnapshot 10 列 / Provider Compliance 13 reason_code) を破壊していない。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-005-5_output_validator.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ruby -e 'text=File.read("docs/sprints/SP-005-5_output_validator.md"); missing=%w[BL-0064 BL-0065 BL-0066 BL-0067 BL-0068 BL-0069 BL-0070 BL-0071].reject { |id| text.include?(id) }; abort("missing: #{missing.join(",")}") unless missing.empty?'` で 8 チケットが揃っていることを確認する。
- [ ] `ls docs/adr/00004_*.md docs/adr/00006_*.md docs/adr/00009_*.md docs/adr/00010_*.md` で関連 ADR が accepted (proposed → accepted 化済) であることを確認する。
- [ ] `uv run alembic check` で migration drift がないことを確認する。
- [ ] `uv run pytest tests/output_validator/test_output_validator_core.py -q` で validation_failed → repair retry → repair_exhausted transition を確認する。
- [ ] `uv run pytest tests/output_validator/test_repair_retry_policy.py -q` で `repair_retry_max_attempts` 上限と BudgetGuard 連動を確認する。
- [ ] `uv run pytest tests/output_validator/test_repair_retry_context_redaction.py -q` で retry prompt に raw secret / raw provider response / capability token 生値が含まれないことを確認する (`assert_no_raw_secret` parametrized)。
- [ ] `uv run pytest tests/input_trust/test_trust_level_enum_drift.py -q` で trust_level の 5+ source 整合 (DB CHECK + ORM + Python Literal + Pydantic + pytest EXPECTED) を確認する。
- [ ] `uv run pytest tests/input_trust/test_trust_level_promotion_service.py -q` で `untrusted_content -> validated_artifact` 自動昇格と `validated_artifact -> trusted_instruction` の Approval 4 整合 + decider human-only を確認する。
- [ ] `uv run pytest tests/input_trust/test_payload_classifier.py -q` で payload_data_class 算出が caller-supplied 禁止 (`extra="forbid"` schema reject) と整合していることを確認する。
- [ ] `uv run pytest tests/runtime/test_agent_run_full_chain_integration.py -q` で provider call → Compliance Gate → preflight → execute → validate → repair retry → transition_with_event 全 chain を確認する。
- [ ] `uv run pytest tests/runtime/test_repair_exhausted_terminal.py -q` で 16 状態 × invalid transition matrix で `repair_exhausted` terminal が強制されることを確認する。
- [ ] `uv run pytest tests/eval/test_prompt_injection_resist_fixture.py -q` で AC-HARD-07 fixture (5+ injection pattern) が 100% deny されることを確認する。
- [ ] `uv run pytest tests/security/test_audit_no_raw_secret.py -q` (parametrized 拡張) で repair retry / trust_level promotion / payload_classifier の audit に raw secret が含まれないことを確認する。
- [ ] `uv run mypy backend` で型整合を確認する。
- [ ] `uv run ruff check backend tests` で lint を確認する。
- [ ] `rg -n "trust_level\s*=\s*request|trust_level\s*=\s*caller|payload_data_class\s*=\s*request" backend tests --glob '!**/*.md'` で caller-supplied 経路の混入がないことを確認する (Sprint 5 と同 pattern)。

## レビュー観点

- [ ] 既存 ADR (00004 / 00006 / 00009 / 00010) の延長で済んでおり、新規 ADR proposed が必要な設計判断が混入していない (もし出たら proposed ADR を起票してから実装続行)。
- [ ] AgentRun 16 状態 / blocked サブ 3 / ContextSnapshot 10 列を破壊していない。
- [ ] ProviderAdapter の境界 (Sprint 5 で確立) が Sprint 5.5 の Output Validator 統合で bypass されていない (provider call は依然として `ProviderAdapter.execute()` 経由のみ)。
- [ ] trust_level 昇格経路が server-owned のみで、caller-supplied 経路が signature レベルで物理削除されている。
- [ ] payload_data_class 事前算出が Input Trust Layer 側に集約され、ProviderAdapter / Compliance Gate が再算出していない。
- [ ] repair retry が secret leak / prompt injection の媒介になっていない (redacted summary のみ引き継ぎ + `assert_no_raw_secret` 必須)。
- [ ] `repair_exhausted` terminal が contract test で全 16 状態 × invalid transition matrix で強制されている。
- [ ] AC-HARD-07 fixture が prompt injection pattern を実装可能な範囲で網羅し、untrusted_content → trusted_instruction 昇格を 100% deny する。
- [ ] cross-source enum 整合 (5+ source) が trust_level / 5 新 event_type で drift 防止されている。
- [ ] 共通 `_payload_secret_scan.py` (Sprint 1-5 で 21 種拡張) が repair retry context redaction でも参照されている (parity test で 3+ repository identity)。
- [ ] audit_event の raw value 非露出が parametrized test で確認されている。

## 残リスク

- **repair retry が secret leak の媒介**: `assert_no_raw_secret` を retry prompt builder で必須実行 + parametrized test 8 種 (Sprint 5 で確立) で検出。違反時は release blocker。
- **Input Trust Layer の trust_level 昇格 bypass**: caller-supplied 経路を signature レベルで物理削除 (`extra="forbid"`) + 4 重防御 4 layer (API endpoint / service / ORM / DB CHECK) で多層防御。
- **payload_data_class 算出ロジックの caller 入力混入**: `extra="forbid"` で schema reject + `rg` denylist で `payload_data_class\s*=\s*request` 混入を CI で検出。
- **repair_exhausted を terminal 扱いせず retry する regression**: state machine contract test で 16 状態 × invalid transition matrix を parametrize、release blocker。
- **AC-HARD-07 fixture の network coverage 不足**: P0 で実装可能な範囲 (5+ pattern) に絞り、P1 (Sprint 11 Eval Harness) で fixture refresh + monthly append-only で拡張。
- **trust_level enum の P0.1 SP-015 inter_agent_messages 再利用**: P0 段階で artifact 単体の trust_level を先行導入し、P0.1 で同 enum を inter_agent_messages の DB CHECK に再利用 (cross-source enum 整合 5+ source pattern)。
- **policy_pack `repair_retry_max_attempts` の policy_version bump 漏れ**: Sprint 3 で確立した policy_version 機械判定で migration check と整合性 test を必須化。

## 次スプリント候補

- Sprint 6 (Worker / arq): AgentRun runtime 経路を arq job として動かす。Sprint 5.5 で確立した chain integration をそのまま arq worker で実行可能にする。
- Sprint 7 (Docker isolated runner): trust_level 昇格 service で trusted_instruction 化された patch のみを `runner_mutation_gateway` 経由で適用 (Sprint 5.5 boundary を runner 境界へ拡張)。
- Sprint 9 (UI): Approval Inbox で trust_level 昇格 (validated_artifact → trusted_instruction) の human approval を表示。trust_level transition history を Audit Log に表示。
- Sprint 11 (Eval Harness): AC-HARD-07 fixture を eval harness で score / report、private holdout / adversarial_new fixture を月次 append-only で refresh。
- Sprint 11.5 (Observability): repair retry の OTel span 化、policy_block_recall / repair_exhausted_rate を Grafana dashboard で可視化。
- (P0.1) SP-015 inter_agent_communication: trust_level enum を inter_agent_messages の DB CHECK で再利用、Sprint 5.5 で導入した artifact 単体の trust_level を multi-agent boundary に拡張。

## 関連 ADR

- [ADR-00004](../adr/00004_agentrun_state_machine.md): accepted (Sprint 4 着手前)。AgentRun 16 状態 / blocked サブ 3 / validation_failed / repair_exhausted / repair retry / ContextSnapshot snapshot_kind=resume の前提。
- [ADR-00006](../adr/00006_secrets_management.md): accepted (Sprint 4 着手前)。SecretBroker / `secret_ref` / capability token / atomic claim / raw secret 非保存。retry prompt に raw secret 非露出を担保。
- [ADR-00009](../adr/00009_action_class_taxonomy.md): accepted (Sprint 3 着手前)。action_class 7 種、Output Validator は action class 拡張なし、trusted_instruction 昇格は既存 approval 経路に閉じる。
- [ADR-00010](../adr/00010_provider_change.md): accepted (Sprint 5 着手前)。Provider Compliance Matrix v2、`payload_data_class` / `allowed_data_class`、ordinal map、runtime `effective_allowed_data_class`、`provider_request_preflight`。Sprint 5.5 では payload_data_class 算出を Input Trust Layer 側に集約する形で延長。

## Review

(Sprint 5.5 完了後に追記)

- changed: <実際に変えたこと>
- verified: <確認したこと>
- deferred: <後回しにしたこと>
- risks: <残ったリスク>
