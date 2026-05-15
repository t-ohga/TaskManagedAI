---
id: "ADR-00002"
title: "DB schema 基礎: tenant_id + project boundary + actors / principals + RLS-ready (P0 single-tenant、multi-tenant 移行余地維持)"
status: "accepted"
date: "2026-05-08"
accepted_at: "2026-05-08"
authors:
  - "t-ohga"
related_sprints:
  - "SP-002_core_data_model"
  - "SP-004_agent_runtime"
  - "SP-005-5_output_validator"
  - "SP-010_research_evidence"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-13 (Sprint 10 prep で Research/Evidence schema 延長 section を追加。Sprint 5.5 prep で status drift fix: proposed → accepted。Sprint 2 完了 commit 74b67cf 経由で de facto accepted 化済みだったが file 上の status field が proposed のまま残存していた drift を修正。Sprint 5.5 では artifacts.trust_level 列追加 (additive only) を本 ADR の延長として扱う。**Sprint 10 では research_tasks / claims / evidence_sources / evidence_items の 4 table 追加 + evidence_set_hash invariant 確立を本 ADR の延長として扱う、§7 参照**)

## 背景

- 決定対象: P0 DB schema の `tenant_id` 不変条件、project boundary、actors / principals 分離、RLS-ready metadata、複合 FK、`app_role` repository contract、Sprint 2 実装 table と Sprint 4 / Sprint 10 follow-up の境界。
- 関連 Sprint: SP-002 Core Data Model、SP-004 Agent Runtime (`agent_runs.parent_run_id` cross-project 制約 BL-0029b)、SP-010 Research Evidence (`research_tasks` cross-project 制約 BL-0029c)。
- 前提 / 制約: P0 は個人 1 user (`tenant_id=1`) だが schema は multi-tenant-ready にする。Sprint 2 では RLS を有効化せず、`metadata.rls_ready=true` と policy 草案を維持する。DB schema は ADR Gate Criteria #2 に該当し、break-glass 先行不可のため実装前に proposed 化する。`app_role` と repository layer は tenant 条件抜けを contract test で reject する。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: `tenant_id NOT NULL DEFAULT 1` + 複合 FK + RLS-ready metadata + `app_role` | DD-02 §5.1 準拠。project boundary を `(tenant_id, project_id, id)` 複合 FK で閉じる | P0 個人運用と P1 multi-tenant 移行を両立し、cross-tenant / cross-project 越境を DB と app 層で防げる | actors / principals / project の複合 FK が複雑。Sprint 4 / Sprint 10 follow-up が必要 |
| B: 単一 tenant 固定 (`tenant_id` 列なし) | P0 個人専用に最適化する | schema が簡素 | P1 multi-tenant 化が destructive migration になり、監査主体表現も弱い |
| C: フル multi-tenant + RLS 有効化 | PostgreSQL RLS を Sprint 2 から有効にする | DB engine が tenant 境界を enforce する | migration / superuser / bypass case の運用負荷が P0 で過剰 |

## 採用案

- 採用: **A: `tenant_id NOT NULL DEFAULT 1` + 複合 FK + RLS-ready metadata + `app_role`**。
- 理由: P0 の単純さを保ちながら P1 migration cost を抑える。複合 FK で DB レベルの越境を防ぎ、repository contract test で SELECT / UPDATE / DELETE の `tenant_id` WHERE を強制する。Sprint 2 の project boundary は `tickets` / `repositories` / `ticket_relations` に限定し、`agent_runs.parent_run_id` は BL-0029b、`research_tasks` は BL-0029c へ分離する。
- 実装 Sprint: Sprint 2 は `tenants` / `actors` / `principals` / `workspaces` / `projects` / `repositories` / `tickets` / `acceptance_criteria` / `ticket_relations` / `audit_events` / `notification_events` / `secret_refs` / `secret_capability_tokens`。Sprint 4 は Agent Runtime、Sprint 10 は Research Evidence。
- 実装対象ファイル:
  - `migrations/versions/0002_*.py`
  - `backend/app/db/models/`
  - `backend/app/repositories/`
  - `backend/app/db/app_role.py`
  - `eval/security/tenant_isolation/`
- 実装ガイダンス:
  - 全主要 table に `tenant_id bigint NOT NULL DEFAULT 1` を持たせ、親子参照は `(tenant_id, ...)` または `(tenant_id, project_id, ...)` の複合 FK にする。`id` 単独 FKは禁止。
  - `tickets` / `repositories` / `ticket_relations` は `unique (tenant_id, project_id, id)` と同一 project 内 FK を持つ。
  - `metadata.rls_ready=true` を JSONB column または table comment に残す。P0 は RLS 無効、policy 草案維持。
  - `secret_refs` / `secret_capability_tokens` は ADR-00006 に従い raw secret / raw token 列を持たない。`runner_injectable=false`、`token_hash` unique、`expected_request_fingerprint text not null` を必須にする。
- テスト指針: schema introspection で全 table の `tenant_id`、複合 FK、`id` 単独 FK 不在を検査する。cross-tenant / cross-project SELECT / INSERT / UPDATE / DELETE negative は ValueError または constraint violation として扱い、`app_role` contract、AC-HARD-03 fixture skeleton (`eval/security/tenant_isolation/`) を作る。
- ADR Gate Criteria 該当: **#2 DB schema** が主、**#8 破壊的操作 / migration** が補。Sprint 2 は新規 table 追加を原則とし destructive migration は避ける。

## 却下案

- B: `tenant_id` 列なしでは P1 multi-tenant 化が destructive になり、ADR-00001 から接続する actors / principals の監査境界も弱いため却下する。
- C: RLS 有効化は将来方針として保持するが、P0 では bypass case と migration 運用が重すぎるため却下する。RLS-ready metadata と `app_role` contract で移行余地を残す。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| `tenant_id` 複合 FK 漏れによる cross-tenant 越境 | schema introspection、repository contract、AC-HARD-03 fixture | 全 table の `tenant_id` と複合 FK を contract test 化し、`id` 単独 FK を reject |
| project boundary 漏れによる cross-project 越境 | cross-project negative fixture | Sprint 2 対象を `tickets` / `repositories` / `ticket_relations` に限定し、Sprint 4 / Sprint 10 follow-up を明示 |
| `app_role` contract と repository 実装の drift | tenant WHERE contract test | CI smoke に昇格し manual SQL に頼らない |
| secret schema と Sprint 4 atomic claim 実装の drift | ADR-00006 / DD-02 / migration 整合 review | Sprint 4 着手時に ADR-00006 accepted 化を gate にする |
| RLS 未有効化が P0 脆弱性になる | `metadata.rls_ready=true` lint | metadata 不在を CI でブロックし、policy 草案を維持 |
| migration rollback の data loss | staging 先行、backup / restore drill | destructive migration を避け、必要時は forward-fix migration を用意 |

## 既知の限界 / Future Work

### 5.2 Sprint 2 P0 limitation: tenant_id / project_id immutability

Sprint 2 では tenant_id および project_id の immutability を以下で強制:

- **Repository layer**: `TicketRepository.update_in_project` 等で payload に `tenant_id` / `project_id` が含まれる場合、repository instance の引数と不一致なら ValueError reject (R26 で実装)
- **DB layer FK**: `(tenant_id, project_id, repository_id)` 等の複合 FK で部分的な cross-tenant / cross-project UPDATE は IntegrityError reject

**DB layer の限界**:

1. **tenant_id coordinated move**: tenant_id + project_id + 全関連 actor_id を一斉に更新する coordinated UPDATE は、DB FK のみでは通過する (test `test_db_coordinated_move_p0_limitation_documents_repository_layer_enforcement` で documenting)。Repository layer 強制で防いでいる。
2. **project_id isolated / coordinated move**: 同一 tenant 内で repository_id=NULL かつ child row (acceptance_criteria / ticket_relations) が無い ticket については、project_id-only UPDATE が DB FK のみでは通過する (test `test_isolated_ticket_project_id_change_succeeds_documents_p0_limitation` で documenting)。Repository layer の payload project_id check で防いでいる。

**Future Work (Sprint 4)**:

- `tenant_id` immutability BEFORE UPDATE trigger を migration で追加し、DB layer でも cross-tenant move を完全 reject する
- `project_id` immutability BEFORE UPDATE trigger も同等に追加検討。child row がない ticket でも project_id 変更を拒否することで AC-HARD-03 + project boundary invariant を DB layer で完全 fail-closed にする
- 両 trigger の効果を検証する negative test を `tests/security/test_*_isolation_negative.py` に追加

## rollback 手順

1. **migration 適用前**: `pg_dump` で full DB backup を取り、age で暗号化して別ボリュームへ保存する。restore drill で復号を確認する。
2. **staging 先行**: `uv run alembic upgrade head` を staging DB で実行し、`alembic check` と table contract test (status enum / unique constraint / index / FK) を PASS させる。
3. **rollback trigger**: production migration 後に cross-tenant / cross-project negative、複合 FK、`app_role` contract、`metadata.rls_ready` lint のいずれかが失敗した場合。
4. **rollback step**: `uv run alembic downgrade -1` で 1 step 戻す。downgrade が data loss / inconsistent state になる場合は forward-fix migration を作り、staging 検証後に production 適用する。最終手段は age 暗号化 backup から restore する (RPO <= 24h を許容できる場合のみ)。
5. **rollback verification**: 全 table の `tenant_id`、複合 FK、`metadata.rls_ready=true`、cross-tenant / cross-project negative、`secret_capability_tokens` の status enum / `token_hash` unique / `expected_request_fingerprint not null`、`secret_refs` の partial unique `(tenant_id, scope, name, status='active')` 1 件、`runner_injectable=false` を確認する。
   - `tests/db/test_repository_layer.py` で repository layer contract (tenant WHERE, payload tenant_id/project_id reject) を確認
   - `tests/contract/test_app_role_contract.py` で app_role + statement_for_* contract を確認

## 7. Sprint 10 Research / Evidence schema 延長 (2026-05-13 update proposed)

本 section は **本 ADR の延長として扱う追加 schema** であり、Sprint 10 で proposed → accepted 化する。base ADR (採用案 A: `tenant_id` + 複合 FK + RLS-ready) と同じ invariant を Research / Evidence 4 table に適用する。

### 7.1 追加 table と複合 FK 設計

| table | tenant_id | project FK 経路 | unique 制約 |
|---|---|---|---|
| `research_tasks` | NOT NULL DEFAULT 1 | `(tenant_id, project_id) references projects(tenant_id, id)` | `unique (tenant_id, project_id, id)` |
| `claims` | NOT NULL DEFAULT 1 | `(tenant_id, project_id, research_task_id) references research_tasks(tenant_id, project_id, id)` | `unique (tenant_id, project_id, id)` |
| `evidence_sources` | NOT NULL DEFAULT 1 | project boundary なし (URL based source は tenant 全体共有可、ただし `canonical_url` + tenant 単位 unique) | `unique (tenant_id, canonical_url)` |
| `evidence_items` | NOT NULL DEFAULT 1 | `(tenant_id, project_id, claim_id) references claims(tenant_id, project_id, id)` + `(tenant_id, evidence_source_id) references evidence_sources(tenant_id, id)` | `unique (tenant_id, project_id, claim_id, evidence_source_id, locator)` |

### 7.2 evidence_set_hash invariant (ContextSnapshot 10 列の 1 つ)

- `evidence_set_hash` は **server-owned** で caller-supplied 経路を持たない (`.claude/rules/server-owned-boundary.md` §1)
- 算出: `sha256(NFC-UTF8(JCS-canonical-JSON({"claims": [<claim_id 昇順>], "sources": [<source_id 昇順>], "prov_bundle_hash": <PROV W3C minimal subset hash>}))` の 16-char hex prefix
- ContextSnapshot.evidence_set_hash は Sprint 4 で nullable 確保済、Sprint 10 着手後の新 AgentRun では必須 (BL-0117 で結線)
- 既存 (Sprint 1-9) AgentRun は `evidence_set_hash IS NULL` を許容 (null = "Research/Evidence 未関連付け" semantics)

### 7.3 provenance_json schema (W3C PROV-DM minimal subset)

- 5 relation: `wasGeneratedBy` / `used` / `wasAttributedTo` / `wasInformedBy` / `wasDerivedFrom`
- Pydantic schema で validation (BL-0116)
- caller-supplied 経路は禁止 (server-side で W3C subset 適合 verify、不一致なら reject)

### 7.4 cross-project negative (BL-0029c)

Sprint 2 で deferred の `research_tasks` cross-project negative fixture を Sprint 10 で完成 (BL-0029c)。`(tenant_id, project_id, research_task_id)` の cross-project SELECT / INSERT / UPDATE / DELETE が全件 reject される invariant を fixture で verify。

### 7.5 ADR Gate Criteria 該当

- **#2 DB schema** (新規 4 table 追加)、**#3 API contract** (Research-to-Ticket adapter API、ADR-00003 update で扱う)
- base ADR (採用案 A) と同じ invariant 適用のため、新規 ADR 起票ではなく **本 ADR 延長で proposed → accepted**
- Sprint 10 完了で `status` 維持 (既に accepted)、`最終更新` date を更新

### 7.6 rollback (Sprint 10 schema)

1. migration revision を 1 件 down で revert (`alembic downgrade -1`)
2. ContextSnapshot.evidence_set_hash を nullable に戻し、既存 AgentRun を保護
3. BL-0118 Research-to-Ticket adapter コード削除 (DB 変更なし、service layer のみ)
4. BL-0029c fixture file 削除、SP-002 BL-0029 fallback で Sprint 12 AC-HARD-03 final verify 時に再評価
