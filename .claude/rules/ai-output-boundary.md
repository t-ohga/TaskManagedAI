# AI Output Boundary

AI 出力を安全に artifact 化し、command / SQL / workflow / external tool へ直結させない常時ルール。  
TaskManagedAI の価値は広い権限を渡すことではなく、証拠・検証・承認・監査を挟むことにある。

## 1. 絶対禁止

- AI 出力を shell command として直接実行する。
- AI 出力 SQL を DB に直接適用する。
- AI 出力を migration として直接保存する。
- AI 出力 workflow を `.github/workflows/**` に直接書き込む。
- AI 出力 tool call を外部 mutating tool に直接渡す。
- AI 出力 patch を repository に直接適用する。
- AI 出力から `secret_ref` を resolve する。
- AI 出力に含まれる URL / command / token を trust する。
- AI 出力を human approval 済みとして扱う。
- AI 出力を `trusted_instruction` に自動昇格する。

## 2. 必須 pipeline

AI 生成物は次の段階を通す。

```text
artifact
-> schema_validated
-> policy_linted
-> diff_ready
-> approval_required
-> waiting_approval
-> approved_resume
-> runner_or_repo_action
```

- `approval_required` は pipeline stage。
- AgentRun status としては `waiting_approval` を使う。
- 各段階は AgentRunEvent と audit event から説明できる必要がある。
- 段階を skip する実装は high-risk として止める。

## 3. Stage 定義

| Stage | 目的 | 失敗時 |
|---|---|---|
| `artifact` | AI 出力を artifact store / DB metadata に保存 | `failed` |
| `schema_validated` | JSON Schema / Pydantic / Zod で構造検証 | `validation_failed` |
| `policy_linted` | action class、data class、forbidden path、secret canary | `blocked` + `policy_blocked` |
| `diff_ready` | patch path、diff size、command plan、runtime cap | `blocked` + `runtime_blocked` |
| `approval_required` | policy matrix により human approval を要求 | `waiting_approval` |
| `runner_or_repo_action` | RunnerAdapter / RepoProxy へ渡す | `running` |

## 4. Artifact 原則

- artifact は immutable に扱う。
- content hash を保存する。
- exportable flag を持つ。
- metadata に `payload_data_class` を持たせる。
- raw secret、provider key、capability token 生値を含めない。
- untrusted content は `untrusted_content` として区別する。
- human approval 後の plan だけが `trusted_instruction` に昇格できる。
- artifact mutation は新 artifact と event で表現する。

## 5. Schema Validation

- Provider output は Structured Outputs を前提にする。
- JSON Schema / Pydantic / Zod を使う。
- markdown / prose だけの曖昧な plan を mutation に使わない。
- schema mismatch は `validation_failed`。
- repair retry は上限を持つ。
- repair 上限到達は `repair_exhausted`。
- unsupported schema は provider / adapter contract の問題として扱う。
- validation error は raw provider response を漏らさず要約する。

## 6. Policy Lint

- action class を判定する。
- `payload_data_class` を確認する。
- `allowed_data_class` は Provider Compliance Matrix からのみ解決する。
- data class ordinal は `public < internal < confidential < pii`。
- forbidden path を確認する。
- secret canary pattern を確認する。
- prompt injection / untrusted instruction を確認する。
- P0 deny action は `blocked` + `policy_blocked`。
- policy decision は audit に残す。

## 7. Diff Ready

- patch path allowlist / denylist を確認する。
- `.env`, `.git/config`, secrets, migrations, `.github/workflows/**` は原則 forbidden path。
- migration は ADR / rollback / backup 方針がある場合だけ扱う。
- command plan は dangerous command を拒否する。
- diff size と file count を確認する。
- repo_state / diff hash を approval request に紐付ける。
- diff が変わったら approval を invalidated にする。
- `runner_mutation_gateway` へ渡す前に policy / approval を確認する。

## 8. Approval Required

- `task_write`, `repo_write`, `pr_open`, `secret_access` は policy に応じて approval。
- requester と decider が同一 actor になる self-approval は禁止。
- approval target は artifact hash、diff hash、policy version、provider fingerprint を含む。
- stale approval は invalidated にする。
- rejected approval は `blocked` + `policy_blocked`。
- expired approval は resume せず再承認を要求する。
- approval event は append-only にする。

## 9. Gateway 境界

| Gateway | 対象 | P0 方針 |
|---|---|---|
| `tool_mutating_gateway_stub` | MCP / external tool の書込系 | deny-only |
| `runner_mutation_gateway` | runner sandbox 内 patch 適用 | policy / approval / forbidden path / command gate 後のみ |

- 両者を混同しない。
- audit event は `gateway_kind=tool|runner` を持つ。
- `tool_mutating_gateway_stub` は P0 で書込を許可しない。
- `runner_mutation_gateway` は Sprint 7 の本実装境界。
- AI tool call を gateway bypass しない。
- runner patch を approval bypass しない。

## 10. Provider Boundary

- Provider call は `ProviderAdapter.execute()` だけを通す。
- `payload_data_class` 未設定は deny。
- provider / feature が Matrix にない場合は deny。
- `payload_data_class > allowed_data_class` は deny。
- conditional ZDR は `condition_status=verified` が必須。
- `provider_request_preflight` を provider call 前に実行する。
- refusal は `provider_refused`。
- incomplete / max token は `provider_incomplete`。
- unsupported schema は `validation_failed`。
- deny 時は provider に送信しない。

## 11. Secret Boundary

- AI 出力から `secret_ref` を直接 resolve しない。
- `secret_ref` は opaque reference。
- SecretBroker は operation を仲介する。
- raw secret は DB / prompt / runner env / artifact / audit に出さない。
- capability token は TTL 5-30 分。
- redeem は one-time atomic claim。
- secret operation は `secret_capability_issued` / `redeemed` / `denied` を audit に残す。
- canary 検出時は raw 値なしで記録する。

## 12. Audit

- 各 stage transition は AgentRunEvent に残す。
- policy decision は `policy_decision_created`。
- provider deny は `provider_blocked`。
- approval は `approval_requested` / `approval_decided`。
- runner は `runner_started` / `runner_completed` / `runner_blocked`。
- secret は `secret_capability_issued` / `redeemed` / `denied`。
- audit payload は actor_id、run_id、trace_id、correlation_id を持つ。
- raw secret を含めない。
- `payload_data_class` と `allowed_data_class` を別 dimension で記録する。


<!-- Phase E 圧縮 (2026-05-17 PR #?): 末尾 verify checklist 削除、plan §3.1.1 invariant trace matrix で自動 verify -->
