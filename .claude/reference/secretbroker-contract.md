# SecretBroker Contract

SecretBroker の `secret_ref`、capability token、atomic claim、one-time redeem、audit event、rotation contract。  
raw secret 禁止を P0 の安全境界として固定する。

## 1. Contract Summary

| 項目 | Contract |
|---|---|
| secret storage | SOPS + age、DB は `secret_ref` のみ |
| raw secret DB 保存 | 禁止 |
| AI への secret 値渡し | 禁止 |
| runner env secret 注入 | 禁止 |
| capability token TTL | 5-30 分 |
| token storage | hash のみ |
| redeem | one-time atomic claim |
| binding | actor_id / run_id / `expected_request_fingerprint` (broker-computed OperationContext fingerprint) / operation |
| audit | issue / redeem / deny |
| rotation | `pending -> active -> deprecated -> revoked` |

## 2. `secret_ref` Format

```text
secret://sops/<scope>/<name>#<version>
```

例:

```text
secret://sops/project/provider-openai#v1
secret://sops/repo/github-app-private-key#v3
secret://sops/p0/tailscale-auth-key#v1
```

- 例は placeholder。
- 実 token / key は書かない。
- URI は opaque reference。
- SecretBroker だけが URI を解釈する。
- `#<version>` は必須。
- version は rotation の単位。

## 3. Scope

| scope | P0 用途 |
|---|---|
| `p0` | dev login token、SOPS age key reference、Tailscale auth key |
| `workspace` | 将来 reserved |
| `project` | provider API key metadata |
| `repo` | GitHub App private key reference |
| `agent_run` | run scoped reserved |
| `provider` | provider scoped reserved |

## 4. Secret Ref Metadata

| key | DB 保存 | 説明 |
|---|---:|---|
| `secret_uri` | yes | URI |
| `scope` | yes | scope |
| `name` | yes | logical name |
| `version` | yes | `v1`, `v2` |
| `status` | yes | lifecycle |
| `runner_injectable` | yes | P0 常に false |
| `allowed_consumers` | yes | caller allowlist |
| `allowed_operations` | yes | operation allowlist |
| `owner_actor_id` | yes | owner |
| `rotated_from_id` | yes | prior version |
| raw secret value | no | 禁止 |

必須 invariant:

```json
{
  "runner_injectable": false
}
```

## 5. Secret Ref Status

| status | 意味 | token 発行 |
|---|---|---|
| `pending` | rotation 中の新 version 候補 | verify operation のみ可 |
| `active` | 現行 version | 可 |
| `deprecated` | 移行後の旧 version | 新規発行不可 |
| `revoked` | 使用不可 | 不可 |

遷移:

```text
pending -> active -> deprecated -> revoked
pending -> revoked
active -> revoked
deprecated -> revoked
```

DB constraint:

- active per `(tenant_id, scope, name)` は最大 1。
- pending per `(tenant_id, scope, name)` は最大 1。

## 6. Capability Token Attributes

| attribute | rule |
|---|---|
| `token_hash` | raw token ではなく hash |
| `secret_ref_id` | 対象 secret metadata |
| `allowed_operations` | operation allowlist |
| `scope_constraint` | repo / provider / resource constraint。OperationContext.target で重複可だが broker が canonical 化 |
| `issued_to_actor_id` | actor binding |
| `issued_run_id` | run binding |
| `expires_at` | TTL 5-30 分 |
| `used_at` | redeem 時刻 |
| `expected_request_fingerprint` | **broker が server 側で計算する canonical OperationContext の SHA-256**。caller-supplied 不可。redeem 時も broker が再計算して比較 |
| `status` | issued / redeeming / used / expired / revoked |

## 6.1 OperationContext Canonical Schema (broker 側計算)

fingerprint は **broker が server 側で計算する canonical 値**。caller が任意 hash を指定する設計は禁止。

| field | 内容 |
|---|---|
| `tenant_id` | tenant 境界 |
| `actor_id` | 発行先 actor |
| `run_id` | AgentRun 関連付け (null 許容) |
| `secret_ref_id` | 対象 secret_ref id |
| `requested_operation` | operation enum |
| `target` | operation-specific target (下表) |
| `payload_hash` | 送信 payload / diff の SHA-256 |
| `approval_id` | approval request id (該当時) |
| `policy_version` | policy pack version |
| `provider_compliance_matrix_version` | Matrix version (provider.call 時) |

operation-specific `target`:

| operation | target |
|---|---|
| `provider.call` | `{provider, api_or_feature, model_resolved}` |
| `repo.push` | `{repo_full_name, branch, commit_sha}` |
| `repo.pr_open` | `{repo_full_name, base_branch, head_branch, draft=true}` |
| `secret.verify` | `{secret_ref_id, version}` |

計算: NFC UTF-8 → JCS canonical JSON → SHA-256。

防げる攻撃:

- operation substitution (token を別 operation で使う)
- target substitution (repo / provider 取り違え)
- payload tampering (approved diff と異なる diff を push)
- approval substitution (別 approval の token を異 operation で使う)
- secret_ref substitution (別 secret_ref 参照を異 secret resolve に使う)

## 7. Issue Flow

1. caller が operation、scope、operation-specific target、payload (該当時) を要求。
2. Policy Engine が action class と approval を確認。
3. SecretBroker が `secret_ref` metadata を確認。
4. `allowed_consumers` に caller があるか確認。
5. `allowed_operations` に operation があるか確認。
6. status が発行可能か確認。
7. TTL が 5-30 分内か確認。
8. raw token を生成。
9. **broker が canonical OperationContext を組み立てて fingerprint を計算**（caller-supplied 値ではなく server 側計算）。
10. token hash + computed `expected_request_fingerprint` を DB 保存（発行時束縛）。
11. raw token を caller に 1 回返す。caller は fingerprint を持つ必要なし（broker が redeem 時に再計算）。
12. `secret_capability_issued` を audit に残す（fingerprint hash も記録）。

## 8. Issue Deny Reasons

| reason_code | 条件 |
|---|---|
| `secret_ref_missing` | URI / metadata 不在 |
| `secret_ref_not_active` | status 不正 |
| `consumer_not_allowed` | caller 不許可 |
| `operation_not_allowed` | operation 不許可 |
| `ttl_out_of_range` | TTL 5-30 分外 |
| `approval_missing` | approval 必要だが未承認 |
| `policy_denied` | policy deny |
| `scope_mismatch` | resource scope 不一致 |
| `fingerprint_unbound` | expected_request_fingerprint が設定されていない (issue 時必須) |

## 9. Atomic Claim SQL (broker 側 fingerprint 再計算 + redeem mismatch deny)

```sql
update secret_capability_tokens
   set status = 'redeeming',
       used_at = now()
 where tenant_id = :tenant_id
   and token_hash = :token_hash
   and status = 'issued'
   and used_at is null
   and expires_at > now()
   and issued_to_actor_id = :actor_id
   and issued_run_id is not distinct from :run_id
   and expected_request_fingerprint = :computed_fingerprint  -- broker が再計算した値
   and :requested_operation = any(<allowed_operations_check>)
returning id, secret_ref_id, allowed_operations, scope_constraint;
```

重要:

- `:computed_fingerprint` は broker が **redeem 時の実 operation request から OperationContext canonical schema (§6.1) で再計算**した値。caller 提供 hash は使わない。
- 0 rows は deny（理由: not_found / expired / actor_mismatch / run_mismatch / **fingerprint_mismatch** / operation_mismatch）。
- 1 row のみ redeem 実行可。
- actor mismatch は deny。
- run mismatch は deny。
- expired は deny。
- already used は deny。
- operation mismatch は deny。
- **fingerprint mismatch は operation substitution / target tampering / payload tampering / approval reuse / secret_ref substitution を防ぐ**（§6.1 後半参照）。

## 10. Redeem Flow (broker 側再計算 + claim 後の secret_refs 再検証)

1. caller が token、operation、actor_id、run_id、operation-specific target、payload (該当時) を渡す。
2. SecretBroker が token hash を計算。
3. **SecretBroker が canonical OperationContext を組み立てて fingerprint を再計算**（§6.1 schema、issue 時と同一アルゴリズム）。
4. atomic claim UPDATE を実行（broker 計算の fingerprint と DB の `expected_request_fingerprint` が一致しないと WHERE 句で 0 rows）。
5. 0 rows -> `secret_capability_denied`（reason_code は §11 参照）。
6. 1 row -> claim success。
7. **同一 transaction 内で `secret_refs` を `for update` lock + 再検証**:
   - `status='active'`（rotation.verify は `pending` も可）
   - `caller ∈ allowed_consumers`
   - `requested_operation ∈ allowed_operations`
   - `scope` が capability token の `scope_constraint` と一致
   - 不一致なら raw secret を resolve せず `secret_capability_denied` を記録
8. 再検証 PASS の場合のみ broker 内部で secret を resolve。
9. broker-mediated operation を実行。
10. token を `used` に確定。
11. `secret_capability_redeemed` を audit（fingerprint hash + secret_ref_id + operation のみ、raw 値なし）。
12. operation 失敗時も token 再利用はしない。
13. retry は新 token を発行する。

## 11. Broker-Mediated Operations

| operation | 説明 |
|---|---|
| `provider.call` | provider key を broker 内部で扱い ProviderAdapter と連携 |
| `repo.push` | GitHub installation token を RepoProxy 内部で扱う |
| `repo.pr_open` | Draft PR open |
| `secret.verify` | secret_ref metadata の存在検証 |
| `rotation.read_old` | 旧 version internal read |
| `rotation.read_new` | 新 version internal read |

禁止 operation:

- `get_secret_value`
- `inject_runner_env`
- `expand_secret_into_prompt`
- `export_secret_artifact`
- `log_secret_value`

## 12. Audit Events

| event_type | when |
|---|---|
| `secret_capability_issued` | issue success |
| `secret_capability_redeemed` | redeem success |
| `secret_capability_denied` | issue / redeem deny |
| `config_changed` | metadata / rotation change |
| `secret_canary_detected` | canary hit |

必須 payload:

- `tenant_id`
- `actor_id`
- `run_id`
- `secret_ref_id`
- `operation`
- `reason_code`
- `expected_request_fingerprint_hash` (broker-computed canonical OperationContext fingerprint の SHA-256 hash のみ。caller-supplied fingerprint は audit 不可)
- `trace_id`
- `correlation_id`
- `timestamp`

禁止 payload:

- raw token。
- raw secret。
- private key。
- caller-supplied fingerprint (設計違反)。
- raw OperationContext 内訳 (target / payload / approval_id 等の plaintext)。fingerprint hash で参照する。
- canary raw value。

## 13. Rotation

手順:

1. SOPS file に新 version を追加。
2. `secret_refs` に `pending` version を登録。
3. SecretBroker dry-run verify。
4. policy / provider / RepoProxy の参照先を新 version に切替。
5. smoke test。
6. 新 version を `active`。
7. 旧 version を `deprecated`。
8. capability token TTL expiration を待つ。
9. 旧 version を `revoked`。
10. `config_changed` と rotation audit event。
11. Sprint Review に記録。

## 14. Rotation Drill

Sprint 11.5 で確認:

- SOPS version switch。
- capability token TTL。
- one-time redeem。
- provider key rotation mock。
- GitHub App private key rotation mock。
- Tailscale auth key handling。
- audit event。
- rollback。

## 15. Canary Contract

canary format example:

```text
TMAI_CANARY_FAKE_PROVIDER_KEY_<fixture_id>_<checksum>
```

- 実 token ではない。
- external API に送信しない。
- provider request body に入る前に preflight で止める。
- runner stdout / stderr、artifact、audit payload に raw canary を残さない。
- AC-HARD-02 `secret_canary_no_leak` と連動する。

## 16. Failure Handling

| failure | handling |
|---|---|
| token expired | deny、再発行は policy check から |
| token reused | deny、audit |
| actor mismatch | deny、audit |
| run mismatch | deny、audit |
| fingerprint mismatch | deny、audit |
| operation mismatch | deny、token revoke 検討 |
| secret_ref missing | config_error、AgentRun `blocked` or `failed` |
| SOPS decrypt failed | config_error、rotation / key placement 確認 |
| raw secret in artifact | Hard Gate failure、quarantine |

## 17. Contract Tests

- [ ] raw secret DB 保存なし。
- [ ] `secret_ref` URI validation。
- [ ] `runner_injectable=false`。
- [ ] active / pending unique index。
- [ ] issue allowed_consumers / allowed_operations。
- [ ] TTL 5-30 分。
- [ ] token hash 保存。
- [ ] atomic claim 0 / 1 rows。
- [ ] actor / run / fingerprint binding。
- [ ] one-time concurrent redeem。
- [ ] operation failure consumes token。
- [ ] audit payload has no raw secret。
- [ ] rotation status transitions。
- [ ] canary no leak。
