---
id: "ADR-00006"
title: "秘密管理方式: SOPS + age + FastAPI 内 SecretBroker (atomic claim redeem)"
status: "accepted"
date: "2026-05-07"
accepted_at: "2026-05-09"
authors:
  - "t-ohga"
related_sprints:
  - "SP-000_bootstrap"
  - "SP-002_core_data_model"
  - "SP-004_agent_runtime"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-09 (Sprint 4 着手前 ADR Gate で accepted 化、SP-002 で secret_refs/secret_capability_tokens schema 実装済、SP-004 で SecretBroker issue/redeem 本実装の前提)

## 背景

- 決定対象: P0 の secret-at-rest、`secret_ref` URI、SecretBroker、capability token、atomic claim redeem。
- 関連 Sprint: SP-000_bootstrap
- 前提 / 制約: P0 は単一 VPS / 個人運用であり、HashiCorp Vault は過剰。raw secret は DB、AI prompt、runner env、artifact export、audit に保存しない。ADR Gate Criteria #6（Secrets 管理方式）に該当する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: SOPS + age + FastAPI 内 SecretBroker | SOPS encrypted file で保存し、FastAPI 内 `app.secrets.broker` が broker-mediated operation と atomic claim を担う | P0 に十分軽い。Vault 移行境界を残しつつ raw secret 非露出を実装できる | age key 配置、atomic claim 実装、audit redaction を誤ると境界が崩れる |
| B: HashiCorp Vault | centralized secret store / dynamic secret を使う | 商用化や multi-tenant 化に強い | P0 では運用、backup、復旧、policy が過大 |
| C: 環境変数のみ | process env に secret を置く | 実装が最小 | atomic claim、one-time redeem、actor / run binding ができず、runner / log 露出リスクが高い |

## 採用案

- 採用: A: SOPS + age + FastAPI 内 SecretBroker (atomic claim)
- 理由: P0 の軽量運用と、将来 Vault へ移行可能な SecretAdapter 境界を両立できる。secret 値を caller へ返さず、broker が操作単位で必要な外部呼び出しを仲介する。
- 実装 Sprint: SP-000_bootstrap で contract 固定、SP-004 で本実装前に accepted 化
- 実装対象ファイル:
  - `backend/app/secrets/broker.py`
  - `backend/app/models/secret.py`
  - `migrations/versions/*_secret_broker.py`
- 実装ガイダンス:
  - `secret_ref` は `secret://sops/<scope>/<name>#<version>` に固定し、domain model は opaque reference として扱う。
  - capability token は TTL 5-30 分、one-time redeem、token hash only storage、`issued_to_actor_id` / `issued_run_id` / `expected_request_fingerprint` binding を必須にする。
  - **token 発行前検証**: `requested_operation` が `secret_refs.allowed_operations` に含まれること、caller が `secret_refs.allowed_consumers` に含まれること、`secret_refs.status='active'` (rotation.verify 専用は `pending` も許可) を SQL レベルで確認。
  - **OperationContext canonical schema**: broker が以下の必須 field を validated request から組み立てて fingerprint を計算する: `tenant_id`, `actor_id`, `run_id`, `secret_ref_id`, `requested_operation`, `target` (operation-specific canonical 構造)、`payload_hash` (provider.call / repo.push 等の SHA-256)、`approval_id`, `policy_version`, `provider_compliance_matrix_version`。NFC UTF-8 + JCS canonical JSON + SHA-256 で fingerprint。
  - redeem は `check -> execute -> mark used` を禁止し、単一 transaction / conditional UPDATE で atomic claim する。WHERE 節に `status='issued'` AND `used_at is null` AND `expires_at > now()` AND `issued_to_actor_id = :actor_id` AND `issued_run_id is not distinct from :run_id` AND `expected_request_fingerprint = :computed_fingerprint` AND `:requested_operation = any(allowed_operations)` を含める。0 rows RETURNING は deny、1 row RETURNING のみ operation 実行可。
  - **redeem 後の `secret_refs` 再検証**: 同一 transaction 内で `secret_refs` を `for update` し、`status` / `allowed_consumers` / `allowed_operations` / `scope` が capability token の制約と一致することを確認。不一致なら raw secret resolve せず `secret_capability_denied` (理由: secret_ref_revoked / scope_mismatch / consumer_mismatch / operation_mismatch)。
  - request fingerprint は caller が任意入力する hash ではなく、broker が canonical OperationContext から issue / redeem 時に再計算する。
  - `resolve_secret_ref` は broker 内部専用であり、`get_secret_value(secret_ref)` のような raw secret 返却 API は作らない。
- テスト指針:
  - atomic claim race condition: 同一 token の並行 redeem で成功が 1 件だけになる。
  - TTL 切れ: expired token は `secret_capability_denied` になり raw secret を返さない。
  - actor mismatch / run mismatch: token 値が正しくても deny される。
  - fingerprint mismatch: approved request と異なる operation / payload / target で deny される。
  - **operation substitution**: `provider.call` 用 token を `repo.push` で使用 → 全件 deny (operation mismatch + fingerprint mismatch)。
  - **target substitution**: repo A 用 token を repo B で使用 → deny (target mismatch)。
  - **payload substitution**: approved diff と異なる diff を push 試行 → deny (payload_hash mismatch)。
  - **approval substitution**: 別 approval の token で異 operation 実行 → deny (approval_id mismatch)。
  - **secret_ref substitution**: 別 secret_ref の token で異 secret resolve 試行 → deny。
  - audit redaction: token 生値、raw secret、canary raw value が audit / log / artifact に残らない。

## 却下案

- B: HashiCorp Vault: P1 以降の secrets 管理方式変更として ADR 対象に残す。P0 では operational burden が大きい。
- C: 環境変数のみ: atomic claim、capability token TTL、actor / run / `expected_request_fingerprint` (broker-computed) binding を実現できず、SecretBroker boundary を満たさないため却下する。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| atomic claim 実装が race を許す | 並行 redeem test、DB transaction test | conditional UPDATE + row lock、0 rows deny を contract test 化 |
| raw secret が log / artifact に混入する | secret canary fixture、redaction test | broker-mediated operation のみに限定し、audit payload allowlist を使う |
| age key の配置が単一障害点になる | backup / restore rehearsal、key access review | SOPS key placement を Sprint 0 Open Questions で固定し、復旧手順を文書化 |
| token が `redeeming` のまま残る | expired token monitor、audit review | expires_at 後の expire / manual revoke を運用手順に含める |

## rollback 手順

### 運用 rollback (secret rotation / token 漏えい対応)

1. redeem 競合、raw secret 露出、token 漏えい疑いを検知したら、新規 capability token 発行を停止し、該当 `secret_refs` を `revoked` または `deprecated` にする。
2. 未使用 token を失効し、直前の `secret_ref` version へ戻す。SOPS file の新 version に問題がある場合は pending から削除し、旧 active version を維持する。
3. `secret_capability_issued` / `secret_capability_redeemed` / `secret_capability_denied` を確認し、raw secret 非露出、actor / run / fingerprint binding、one-time redeem が復旧後も成立することを検証する。

### Migration rollback (DB schema 変更時)

`migrations/versions/*_secret_broker.py` を含む schema 変更の場合:

4. **migration 適用前**: `pg_dump` で full DB backup を取り、age で暗号化して別ボリューム / 別ホストに保存する。backup file 自体は restore drill で復号できることを事前確認する。
5. **migration 適用**: Alembic upgrade を staging DB で先行実行し、`alembic check` と以下の contract test を確認する:
   - `secret_capability_tokens`: status enum (`issued|redeeming|used|expired|revoked`) / `token_hash` unique / `expires_at` index / atomic claim WHERE 節 (status / used_at / expires_at / actor / run / fingerprint / requested_operation)
   - `secret_refs`: status enum (`pending|active|deprecated|revoked`) / partial unique constraint `(tenant_id, scope, name)` で `status='active'` 1 件のみ + `status='pending'` 1 件のみ / `allowed_consumers` / `allowed_operations` / `runner_injectable=false` 強制
6. **rollback trigger**: production migration 後に redeem race / atomic claim 失敗 / unique constraint 違反 / status enum mismatch / fingerprint binding 漏れが検出された場合。
7. **rollback step**: Alembic downgrade を実行できる場合は downgrade。downgrade で data loss / inconsistent state になる場合は forward-fix migration を新規作成し、staging で検証してから production 適用する。最終手段として age 暗号化 backup から restore (RPO ≤24h を許容できる場合のみ)。
8. **rollback verification**: restore 後に以下を `pytest tests/contract/test_secret_broker.py` で確認:
   - `secret_capability_tokens`: row count / status enum 分布 / `token_hash` 重複なし / atomic claim contract / negative test (actor mismatch / run mismatch / fingerprint mismatch / expired / replay)
   - `secret_refs`: row count / status enum 分布 / `(tenant_id, scope, name, status='active')` partial unique 1 件保証 / `allowed_consumers` / `allowed_operations` / `runner_injectable` 強制

