# SecretBroker Boundary

SecretBroker、`secret_ref`、capability token、atomic claim、one-time redeem の常時ルール。  
raw secret は DB、AI、runner、artifact、audit に保存・展開しない。

## 1. 原則

- secret storage backend は `sops` (SOPS+age) | `local` (LocalSecretStore: OS keychain / 暗号化ファイル) の 2 種 (ADR-00058)。**Phase 0 (local Mac first) は `local` backend 先行、SOPS+age 移行は D-4**。いずれも FastAPI 内 SecretBroker 経由で、raw secret 非保存・broker-mediated operation の境界は不変。
- DB には raw secret を保存しない。
- DB には `secret_ref` URI と metadata のみ保存する。
- AI prompt に secret 値を入れない。
- runner env に provider key / GitHub token / SOPS key を入れない。
- artifact export に secret 値を含めない。
- audit event に raw secret を含めない。
- SecretBroker は secret 値を返す API ではない。
- SecretBroker は broker-mediated operation を実行する境界。

## 2. `secret_ref` URI

形式:

```text
secret://<backend>/<scope>/<name>#<version>
```

`<backend>` は `sops` | `local` (ADR-00058 で `local` を additive 追加。`sops` は不変・後方互換)。正規表現は単一定数 `SECRET_URI_PATTERN` に集約し DB CHECK / ORM / resolver dispatch (CompositeSecretResolver) / register validation / test が import する (5+source drift 構造防止)。未知 backend は fail-closed deny。

例:

```text
secret://sops/project/provider-openai#v1
secret://sops/repo/github-app-private-key#v3
secret://local/project/github-token#v1
```

- `sops` backend: SOPS + age (既存・後方互換 backend、DD-06)。`local` backend: LocalSecretStore (OS keychain / 暗号化ファイル、ADR-00058)。**Phase 0 (local Mac first) の default は `local`、SOPS+age 移行は D-4**。
- 実 token / key 値は文書に書かない。
- `#<version>` は rotation のため必須。
- Domain model は `secret_ref` を opaque reference として扱う。
- URI 解釈は SecretAdapter / SecretBroker / CompositeSecretResolver (backend dispatch) に閉じる。

## 3. Scope

| scope | 用途 |
|---|---|
| `p0` | P0 全体の secret metadata |
| `workspace` | 将来 workspace 単位 |
| `project` | provider API key など project 単位 |
| `repo` | GitHub App private key reference など |
| `agent_run` | schema 上の将来予約 / run scoped reference |
| `provider` | schema 上の将来予約 / provider scoped reference |

- DD-06 の P0 primary scope は `p0`, `workspace`, `project`, `repo`。
- DD-02 schema は `agent_run`, `provider` も予約する。
- P0 実装で使う scope は Sprint Pack に明記する。

## 4. Metadata

DB 保存可:

- `secret_uri`
- `scope`
- `name`
- `version`
- `status`
- `runner_injectable=false`
- `allowed_consumers`
- `allowed_operations`
- `owner_actor_id`
- `rotated_from_id`
- `created_at`
- `deprecated_at`
- `revoked_at`
- `material_state` (non-secret lifecycle: `writing`/`present`/`purging`/`purged`、ADR-00058/00059 crash-safe source of truth)
- `material_purged_at` (non-secret: revoke 後 material purge 完了時刻、NULL=未 purge)
- `purge_attempts` (non-secret: purge 再試行回数、reconciliation)
- non-secret metadata

DB 保存禁止:

- API key 生値。
- private key 生値。
- auth token 生値。
- capability token 生値。
- SOPS age key 生値。
- canary raw value。

## 5. Status

`secret_refs.status`:

- `pending`
- `active`
- `deprecated`
- `revoked`

遷移:

```text
pending -> active -> deprecated -> revoked
pending -> revoked
active -> revoked
deprecated -> revoked
```

- `(tenant_id, scope, name)` で active は最大 1。
- `(tenant_id, scope, name)` で pending は最大 1。
- `deprecated` から新規 token 発行しない。
- `revoked` から token 発行しない。
- rotation verify 専用 operation は `pending` を許可できるが ADR / Sprint Pack に明記する。

## 6. Capability Token

必須属性:

| 属性 | ルール |
|---|---|
| TTL | 5-30 分 |
| one-time redeem | 必須 |
| storage | token 生値は DB 保存禁止、hash のみ |
| actor binding | `issued_to_actor_id` 必須 |
| run binding | `issued_run_id` を使う |
| operation | `allowed_operations` から選ぶ |
| audience | SecretBroker |
| audit | issue / redeem / deny |

- token 生値を返すのは issue 時 1 回のみ。
- token を log / artifact / audit に書かない。
- token は bearer 盗難対策として actor / run / fingerprint と binding する。

## 7. Issue Invariant

token 発行前に必ず確認し、**期待 fingerprint を発行時に束縛する**。**fingerprint は caller が宣言する任意の hash ではなく、broker が validated / approved request から canonical な OperationContext を組み立てて計算する server-owned 値**。

- requested operation が `secret_refs.allowed_operations` に含まれる。
- caller が `secret_refs.allowed_consumers` に含まれる。
- 通常 operation は `secret_refs.status='active'` のみ。
- rotation verify 専用 operation だけ `pending` を許可可能。
- `deprecated` / `revoked` は発行禁止。
- TTL は 5-30 分。
- Policy Engine / approval が必要なら済んでいる。
- **broker が canonical な OperationContext から fingerprint を計算**（後述 §7.1）し `expected_request_fingerprint` として保存。caller が任意 hash を指定する設計は禁止。
- `secret_capability_issued` を raw 値なしで audit（fingerprint hash も記録）。

### 7.1 OperationContext canonical schema

broker が **server 側で再計算可能な canonical schema** を定義し、issue 時 / redeem 時の両方で同じアルゴリズムで fingerprint を計算する。

`OperationContext` 必須 fields (operation 種別ごとの可変は後述):

| field | 内容 |
|---|---|
| `tenant_id` | tenant 境界 |
| `actor_id` | 発行先 actor |
| `run_id` | AgentRun 関連付け (null 許容) |
| `secret_ref_id` | 対象 secret_ref id (UUID) |
| `requested_operation` | operation enum (例: `provider.call`, `repo.push`, `repo.pr_open`) |
| `target` | operation-specific canonical target |
| `payload_hash` | 送信 payload / diff の SHA-256 (provider.call, repo.push 等) |
| `approval_id` | approval request id (該当時、null 許容) |
| `policy_version` | policy pack version |
| `provider_compliance_matrix_version` | Matrix version (provider.call 時) |

operation-specific `target` の例:

| operation | target 構造 |
|---|---|
| `provider.call` | `{provider, api_or_feature, model_resolved}` |
| `repo.push` | `{repo_full_name, branch, commit_sha}` |
| `repo.pr_open` | `{repo_full_name, base_branch, head_branch, draft=true}` |
| `secret.verify` | `{secret_ref_id, version}` |

fingerprint 計算: NFC UTF-8 + JCS canonical JSON + SHA-256。schema 違反は issue / redeem 両方で deny。

### 7.2 Fingerprint 不一致が防ぐ攻撃

- operation substitution: token が `provider.call` 用なのに `repo.push` で使う試行 → operation mismatch + fingerprint mismatch
- cross-target attack: token が repo A 用なのに repo B に push する試行 → target mismatch
- payload tampering: approval された diff と異なる diff を push する試行 → payload_hash mismatch
- approval reuse: 別 approval の token で異 operation を実行 → approval_id mismatch

## 8. Redeem Atomic Claim

逐次処理は禁止:

```text
check -> execute -> mark used
```

必須は atomic claim UPDATE。**redeem 時も broker が実 operation request から OperationContext を再計算し、fingerprint を SQL に渡す**。caller が任意の fingerprint を渡せない設計。

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

- `:computed_fingerprint` は broker が **redeem 時の実 operation request から OperationContext canonical schema で再計算**した値。caller が任意 hash を渡せない。
- 0 rows RETURNING は deny（理由: not_found / expired / actor_mismatch / run_mismatch / **fingerprint_mismatch** / operation_mismatch のいずれか）。
- 1 row RETURNING だけ operation 実行可。
- actor / run mismatch は token 値が正しくても deny。
- operation mismatch は deny。
- 並行 redeem は DB row lock + conditional update で線形化する。

### 8.1 Negative Test 必須項目

OperationContext 設計の効果を検証する fixture:

- operation substitution: provider.call 用 token を repo.push で使う → 全件 deny
- target substitution: repo A 用 token を repo B で使う → 全件 deny
- payload substitution: approved diff と異なる diff を push 試行 → 全件 deny
- approval substitution: 別 approval の token を異 operation で使う → 全件 deny
- secret_ref substitution: 別 secret_ref 参照の token を異 secret resolve に使う → 全件 deny

### 8.2 Multi-Agent Negative Test 必須項目 (SP-014 PE-F-014)

Multi-agent 文脈では、SecretBroker は actor / run 属性を caller 申告ではなく
DB から解決し、以下 6 case を個別 reason_code で deny する:

| negative case | reason_code |
|---|---|
| orchestrator / agent decider 試行 | `agent_decider_forbidden` |
| Tier 2 auto-allow profile から approval decider 経路へ escape | `tier_2_agent_decider_attempt` |
| expected actor_type と DB 上の Actor.actor_type が一致しない | `actor_type_mismatch` |
| expected role_id と DB 上の AgentRun.role_id が一致しない | `role_id_mismatch` |
| lease expired 状態で secret access | `lease_expired_no_secret_access` |
| progress lease 違反 run の secret access | `progress_lease_violated` |

## 9. Redeem 後検証 + 後処理

claim 成功後、**同一 transaction 内で `secret_refs` を再検証**してから operation を実行する。

```sql
-- 同一 transaction 内で secret_refs を lock + 再検証
select status, allowed_consumers, allowed_operations, scope
  from secret_refs
 where tenant_id = :tenant_id
   and id = :secret_ref_id
   for update;
-- status='active' (rotation.verify は status='pending' も可)
-- caller ∈ allowed_consumers
-- requested_operation ∈ allowed_operations
-- scope が capability token の scope_constraint と一致
-- いずれか不一致なら raw secret を resolve せず secret_capability_denied
```

- 再検証で revoked / deprecated / scope mismatch を検出したら raw secret を resolve しない。`secret_capability_denied` を記録（理由: secret_ref_revoked / scope_mismatch / consumer_mismatch / operation_mismatch）。
- 再検証 PASS の場合のみ broker 内部で secret を resolve する。
- caller へ secret 値を返さない。
- broker-mediated operation を実行する。
- operation 成功後 `status='used'`。
- operation 失敗時も原則 token は消費済み。
- retry は policy check から新 token を発行する。
- broker crash で `redeeming` のままなら expires_at 経過で expire / manual revoke。
- `secret_capability_redeemed` を raw 値なしで audit（fingerprint hash + secret_ref_id + operation のみ）。
- deny は `secret_capability_denied`。

## 10. Broker-Mediated Operation

許可される方向:

- `provider.call`: ProviderAdapter と連携して provider key を broker 内部で扱う。
- `repo.push`: RepoProxy と連携して installation token を broker 内部で扱う。
- `repo.pr_open`: Draft PR 作成を broker / RepoProxy 境界で扱う。
- `secret.verify`: secret_ref 存在と metadata だけ検証する。
- `rotation.read_old`: rotation 中の旧 version を broker 内部参照。
- `rotation.read_new`: rotation 中の新 version を broker 内部参照。

禁止:

- `get_secret_value(secret_ref)`。
- runner env への secret 注入。
- AI prompt への secret 展開。
- artifact export への secret 展開。
- raw secret を audit payload に入れる。

## 11. Audit

| event_type | 内容 |
|---|---|
| `secret_capability_issued` | token 発行 |
| `secret_capability_redeemed` | redeem 成功 |
| `secret_capability_denied` | issue / redeem deny |
| `config_changed` | rotation / metadata 変更 |
| `secret_canary_detected` | canary 検出 |

必須 payload:

- `tenant_id`
- `actor_id`
- `run_id`
- `secret_ref_id`
- `operation`
- `reason_code`
- `expected_request_fingerprint_hash` (broker-computed fingerprint の SHA-256 hash のみ。caller-supplied fingerprint は audit 不可)
- `trace_id`
- `correlation_id`
- `timestamp`

禁止 payload:

- raw token。
- raw secret。
- private key。
- provider request body の未 redacted 内容。
- caller-supplied fingerprint (設計違反)。
- raw OperationContext 内訳 (target / payload / approval_id 等の plaintext)。fingerprint hash で参照する。


<!-- Phase E 圧縮 (2026-05-17 PR #?): 末尾 verify checklist 削除、plan §3.1.1 invariant trace matrix で自動 verify -->
