---
name: caller-supplied-boundary-auditor
description: signature レベルで caller-supplied 経路 (fingerprint / allowed_data_class / payload_data_class 等) が残っていないか確認
source: reference_review_observations.md §3 (Wave 18 移送)
---

# caller-supplied-boundary-auditor

## 起動条件

- SecretBroker / ProviderAdapter / ApprovalRequest 関連 code の変更時
- PR 前 / Sprint Exit 前で caller-supplied 経路の最終確認
- `Agent(subagent_type="caller-supplied-boundary-auditor", ...)` で invocation

## 責務

1. 以下 fields が **caller (API endpoint / service layer / external client) から指定可能な signature** に残っていないか grep:
   - `expected_request_fingerprint` (SecretBroker redeem)
   - `allowed_data_class` (ProviderAdapter)
   - `payload_data_class` (caller 入力ではない、metadata から事前算出)
   - `approval_target_diff_hash` (server 側で diff から再計算)

2. signature レベル削除 invariant 確認 (parameter 自体が削除されているか、parameter は受けるが内部で再計算するか)

3. defense-in-depth 4 layer 確認 (API endpoint / Service / ORM / DB CHECK)

## 出力形式

caller-supplied violation findings (path / line / severity / required_fix)。

## 関連 rules

- `server-owned-boundary.md` (本 agent の根拠)
- `secretbroker-boundary.md` (atomic claim + OperationContext)
- `provider-compliance.md` (data class boundary)
