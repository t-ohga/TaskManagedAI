# Server-Owned Boundary Rules

Sprint 1-4 で確立した caller-supplied 経路禁止 + signature レベル物理削除 + approval validation 4 整合 pattern。`reference_review_observations.md §3` (project memory archived) からの恒久化。

## 1. Caller-supplied 経路の禁止 invariant

以下は **caller (API endpoint / service layer / external client) が直接指定する経路を signature レベルで物理削除**:

- `expected_request_fingerprint` (SecretBroker capability token redeem): broker 内部で OperationContext canonical schema から再計算
- `allowed_data_class` (ProviderAdapter): Provider Compliance Matrix からのみ resolve
- `payload_data_class` (ProviderAdapter): request / artifact metadata から事前算出 (caller 入力ではない)
- `approval_target_diff_hash` (ApprovalRequest): server 側で diff から再計算

## 2. Signature レベル削除

caller が「うっかり指定できる」経路を残さない invariant:

```python
# ❌ 禁止 (caller-supplied 経路)
def redeem_token(token_hash: str, expected_fingerprint: str) -> Result: ...

# ✅ OK (server-owned)
def redeem_token(token_hash: str, operation_context: OperationContext) -> Result:
    expected_fingerprint = compute_fingerprint(operation_context)  # broker 内部
    ...
```

`expected_fingerprint` parameter は **signature から削除**、`OperationContext` のみ受け取り、内部で再計算。

## 3. Approval validation 4 整合

Sprint 3 で確立した ApprovalRequest validation の 4 整合 pattern:

1. **artifact_hash binding**: approval target artifact (e.g., diff / patch / SQL) の sha256
2. **policy_version**: approval 時の policy pack version
3. **provider_request_fingerprint**: provider call 時の OperationContext canonical fingerprint
4. **action_class**: enum (`task_write` / `repo_write` / `pr_open` / `secret_access`)

4 整合の **いずれか 1 つでも mismatch なら invalidated**。stale approval は resume せず再承認を要求。

## 4. Self-approval 禁止

ApprovalRequest の `requester` と `decider` が同一 actor の場合は reject (DB CHECK constraint + service layer guard)。

AI / worker が requester の場合、`decider` は human actor のみ許可。

## 5. Action class enum

`action_class` は次の固定 enum:

- `task_write` (Sprint Pack / Ticket 編集)
- `repo_write` (RepoProxy 経由 push / PR 開始)
- `pr_open` (Draft PR 作成)
- `secret_access` (SecretBroker capability token redeem)
- (P0 deny) `merge` / `deploy`

## 6. Defense-in-Depth (4 layer 防御、§cross-source-enum-integrity §2 と連動)

各 caller-supplied 経路禁止は 4 layer で enforce:

1. API endpoint Pydantic schema (caller field 削除)
2. Service layer signature (parameter 削除)
3. ORM model (column 削除 or computed)
4. DB CHECK constraint (validation)

突破経路を残さない。

## 関連

- source memory: `reference_review_observations.md §3` (project memory、Wave 18 archived)
- 移送先 agent: `caller-supplied-boundary-auditor` (Wave 18) で signature レベル check
- 関連 rules: `cross-source-enum-integrity.md` (4 重防御) / `secretbroker-boundary.md` (atomic claim) / `provider-compliance.md` (data class boundary)
- Wave 18 BL-WP018-004
