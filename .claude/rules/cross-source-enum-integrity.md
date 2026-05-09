# Cross-Source Enum Integrity Rules

Sprint 1-4 で確立した cross-source enum drift 防止 + 4 重防御 pattern。`feedback_taskmanagedai_invariants.md §1-2` (project memory archived) からの恒久化。

## 1. 5+ source 整合 invariant

Enum (e.g., AgentRun 16 状態 / blocked_reason 3 種 / 22 event types / Provider Compliance reason_code 13 種) は次の **5+ source** で完全整合:

1. DB CHECK constraint (migration / DDL)
2. SQLAlchemy ORM `CheckConstraint`
3. Python Literal type (`from typing import Literal`)
4. Pydantic Field validator
5. pytest test fixture (`EXPECTED_*` constants)
6. (option) frontend TypeScript enum (Sprint 9+)

**drift 発生時の挙動**: 全 source で正しい enum を **exact name set** 比較 (`set(actual) == set(expected)`)、超過 / 不足とも reject。

## 2. Defense-in-Depth 4 重防御

Sprint 4 Batch 3 で確立した 4 重防御 pattern (AgentRun state transition で適用):

```
Layer 1: API endpoint Pydantic validator (request body)
Layer 2: service layer (transition function with business logic)
Layer 3: ORM CheckConstraint (DB level)
Layer 4: DB CHECK constraint (migration level)
```

各 layer で同 enum を独立 enforce、いずれか 1 つ突破されても他 layer で reject。

## 3. Atomic claim pattern (SecretBroker)

SecretBroker `redeem_capability_token` は **逐次処理禁止** (check → execute → mark used 不可)。

```sql
update secret_capability_tokens
   set status = 'redeeming', used_at = now()
 where tenant_id = :tenant_id
   and token_hash = :token_hash
   and status = 'issued'
   and used_at is null
   and expires_at > now()
   and issued_to_actor_id = :actor_id
   and issued_run_id is not distinct from :run_id
   and expected_request_fingerprint = :computed_fingerprint
returning id, secret_ref_id, allowed_operations, scope_constraint;
```

0 rows RETURNING は deny (理由: not_found / expired / actor_mismatch / run_mismatch / fingerprint_mismatch / operation_mismatch)。

## 4. OperationContext fingerprint pattern

`expected_request_fingerprint` は **caller-supplied 禁止**、broker 内部で `OperationContext` canonical schema から server 側で再計算:

```
fingerprint = SHA-256(NFC-UTF8(JCS-canonical-JSON(OperationContext)))
```

OperationContext fields: tenant_id / actor_id / run_id / secret_ref_id / requested_operation / target / payload_hash / approval_id / policy_version / provider_compliance_matrix_version。

Issue 時 / redeem 時で同 algorithm で再計算、mismatch なら deny (caller 任意 fingerprint 入力経路を signature レベルで物理削除)。

## 5. 23 invariant fixture pattern

Sprint 2 Batch 4 / Sprint 3 Batch 4 / Sprint 4 Batch 4 で確立した 23 invariant fixture loader pattern:

- AC-HARD-01 (policy_block_recall): policy deny 全件 fixture
- AC-HARD-02 (secret_canary_no_leak): fake API key fixture
- AC-HARD-03 (tenant_isolation_negative_pass): cross-tenant negative test
- AC-KPI-03 / AC-KPI-04 / AC-KPI-05: respective fixture loader
- 全 fixture は parametrized test + `EXPECTED_*` constants で 5+ source 整合

## 6. Audit assert_no_raw_secret

Audit event payload は **raw secret を含まない invariant**:

- pattern hit 種別 (e.g., `'github_token'`, `'tailscale_authkey'`)
- hash / digest (sha256_prefix_8)
- reason_code (13 種 enum)
- raw value 含めず

Test: `assert_no_raw_secret(audit_event)` を全 secret 関連 test で必須実行。

## 関連

- source memory: `feedback_taskmanagedai_invariants.md` (project memory、Wave 18 archived)
- 移送先 skill: `cross-source-enum-audit` (Wave 18) で任意 enum drift detection
- 移送先 hook: `cross-source-enum-drift-check.sh` (Wave 18) で WARN
- Wave 18 BL-WP018-004
