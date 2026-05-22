---
id: "SP-002_core_data_model"
type: "heavy"
status: "completed"
sprint_no: 2
created_at: "2026-05-08"
updated_at: "2026-05-22"
# F-PR100-R1-002 audit fix (PR #101): frontmatter drift 訂正、tenant_id boundary + actors / principals
# / secret_refs schema + AC-HARD-03 fixture loader 実装は完了済 (master plan §1.1).
# 本 訂正 PR で frontmatter status を draft → completed に同期更新.
target_days: 6.5
max_days: 8
adr_refs:
  - "[ADR-00006](../adr/00006_secrets_management.md)"
planned_adr_refs:
  - "[ADR-00002](../adr/00002_db_schema.md) # Sprint 2 で proposed 化、project 境界 invariant + actors/principals + complex FK"
related_sprints:
  - "SP-001_project_foundation"
  - "SP-003_policy_approval"
  - "SP-004_agent_runtime"
risks:
  - "tenant_id 複合 FK の漏れによる cross-tenant / cross-project 越境"
  - "agent_runs.parent_run_id の cross-project 制約は Sprint 4 follow-up に分離"
  - "research_tasks の cross-project 制約は Sprint 10 follow-up に分離"
---

このテンプレの使い方: Sprint 2 の Core Data Model で、tenant invariant、project 境界 invariant、actors / principals、SecretBroker 永続化裏側、AC-HARD-03 fixture skeleton を実装するための heavy Sprint Pack。ADR Gate Criteria #2 DB schema、#6 Secrets 管理方式、#8 migration に該当するため、ADR-00002 を proposed 化し、ADR-00006 の schema 部分に従う。

最終更新: 2026-05-08

## 目的

- TaskManagedAI P0 の Task Core DDL を実装し、Sprint 3 以降の Policy / Approval、Sprint 4 以降の Agent Runtime、Sprint 8 の Repo Integration が依存できる DB 境界を作る。
- 全主要テーブルに `tenant_id bigint NOT NULL DEFAULT 1` を持たせ、親子参照は `tenant_id` を含む複合 FK で閉じる。
- Sprint 2 内に存在する `tickets` / `repositories` / `ticket_relations` は `(tenant_id, project_id, id)` 複合 FK で project 境界を閉じ、同一 tenant・別 project の cross-project 参照を拒否する。
- actors / principals schema を作り、`human`、`service`、`agent`、`provider`、`github_app` を監査主体として扱えるようにする。
- `secret_refs` / `secret_capability_tokens` の基礎 migration を作る。ただし atomic claim redeem の実装は Sprint 4 に分離し、この Sprint では schema と contract test placeholder までに止める。
- AC-HARD-03 `tenant_isolation_negative_pass` の fixture skeleton を `eval/security/tenant_isolation/` に作る。

## 背景

- DD-02 は、P0 は個人 1 user でも schema を tenant-aware にし、主要テーブルに `tenant_id`、複合 FK、一意制約、`metadata.rls_ready=true`、app_role repository layer を持たせる方針を定義している。
- Sprint 1 は起動可能な基盤、dev login、`human:default` request context、Alembic、seed skeleton を用意する。Sprint 2 はそれを正式な Core Data Model に接続する。
- PRD-01 AC-HARD-03 は、越境 SELECT / INSERT / UPDATE / DELETE が DB 制約、複合 FK、app_role により全件失敗することを P0 Hard Gate として要求している。
- DD-02 §5.1 は tenant 境界に加え、同一 tenant 内の project 境界も DB レベルで防ぐことを要求している。
- ADR-00006 は `secret_ref` URI、`secret_refs`、`secret_capability_tokens`、raw secret 非保存、token hash only、capability token lifecycle を定義している。Sprint 2 では永続化 schema のみを作り、issue / redeem service と atomic claim WHERE 節は Sprint 4 に送る。

## 対象外

- カスタムフィールド、Ticket template、workflow template。P1 以降へ送る。
- `agent_runs`、`agent_run_events`、artifacts、ContextSnapshot 10 カラム。Sprint 4 で扱う。
- `agent_runs.parent_run_id` cross-project 制約。Sprint 4 BL-0029b follow-up で扱う。
- `research_tasks`、claims、evidence_sources、evidence_items。Sprint 10 で扱う。
- `research_tasks` cross-project 制約。Sprint 10 BL-0029c follow-up で扱う。
- SecretBroker issue / redeem service、atomic claim UPDATE、本物の broker-mediated operation。Sprint 4 で扱う。
- RLS 有効化。P0 では無効のまま、`metadata.rls_ready=true` と policy 草案、app_role contract test を維持する。
- Ticket CRUD API と Acceptance Criteria API の本実装。Core schema 完了後の後続 slice で扱う。

## 設計判断

- ADR-00002 を proposed 化してから migration に入る: Sprint 2 は DB schema、tenant_id、project boundary、複合 FK、app_role に触れるため、ADR Gate Criteria #2 に該当する。
- `tenant_id` は全主要テーブルで `bigint NOT NULL DEFAULT 1` とする: P0 の個人運用を単純にしつつ、将来 tenant 分離へ移行できるようにする。
- 親子参照は `(tenant_id, id)` または `(tenant_id, project_id, id)` の複合 FK を使う: `id` 単独 FK は cross-tenant / cross-project 越境を許すため禁止する。
- Sprint 2 の project 境界対象は `tickets` / `repositories` / `ticket_relations` に限定する: `agent_runs.parent_run_id` は agent_runs table が Sprint 4 対象のため follow-up、`research_tasks` は Sprint 10 対象のため follow-up にする。
- `ticket_relations` は `project_id` を持つ: cross-project relation は別モデルで分離し、P0 では同一 project 内 relation のみ許可する。
- actors と principals を分離する: actor は監査主体、principal は session / api_token / capability_token / installation / worker の認証手段として扱う。
- `secret_refs` は raw secret を持たない: DB には `secret_uri`、scope、name、version、status、allowed_consumers、allowed_operations、owner_actor_id、metadata のみを保存する。
- `secret_capability_tokens` は raw token を保存しない: `token_hash` と constraint metadata のみを持ち、atomic claim 実装は Sprint 4 の SecretBroker service に送る。
- `secret_capability_tokens` の run 参照は Sprint 2 では nullable + FK 後付け前提にする: `agent_runs` が未作成のため、`issued_run_id` / `agent_run_id` の FK は Sprint 4 の migration follow-up で閉じる。
- app_role は owner 権限を持たない: SELECT / UPDATE / DELETE は repository layer の tenant WHERE contract test、INSERT は DB 複合 FK negative test で越境を失敗させる。
- rollback は migration 単位で設計する: destructive migration は避け、適用前に dev backup、staging upgrade、contract test、downgrade または forward-fix の判断点を残す。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 DD ファイル |
|---|---|---|---:|---|---|---|
| BL-0022 | tenants table + RLS-ready metadata | F-003,NF-008 | 0.6 | BL-0021 | tenants migration、`metadata.rls_ready=true`、base seed | `docs/基本設計/02_データモデル.md` |
| BL-0023 | actors / principals schema (actor_type / principal_type) | F-002,F-003,NF-008 | 0.6 | BL-0022 | users、actors、principals、`auth_context_hash`、複合 FK | `docs/基本設計/02_データモデル.md` |
| BL-0024 | workspaces / projects / repositories migration | F-003,NF-008 | 0.5 | BL-0022,BL-0023 | workspace / project / repository DDL、project FK | `docs/基本設計/02_データモデル.md` |
| BL-0025 | tickets / acceptance_criteria / ticket_relations + project boundary | F-004,F-005,AC-HARD-03 | 0.8 | BL-0024 | Ticket core DDL、`(tenant_id, project_id, id)` constraints | `docs/基本設計/02_データモデル.md` |
| BL-0026 | audit_events / notification_events (append-only) | F-007,NF-005 | 0.4 | BL-0023 | append-only audit / notification base tables | `docs/基本設計/02_データモデル.md` |
| BL-0027 | secret_refs / secret_capability_tokens 基礎 migration | NF-003,NF-008 | 1.0 | BL-0004,BL-0023,ADR-00006 | secret registry、token hash storage、FK 後付け TODO | `docs/基本設計/02_データモデル.md`, `docs/adr/00006_secrets_management.md` |
| BL-0028 | app_role repository layer (PostgreSQL ROLE + repository contract test) | AC-HARD-03,NF-001 | 0.7 | BL-0022,BL-0024 | app_role、migration role 分離、tenant WHERE contract | `docs/基本設計/02_データモデル.md` |
| BL-0029a | tenant boundary cross-tenant negative test | AC-HARD-03,NF-008 | 0.6 | BL-0025,BL-0028 | SELECT / INSERT / UPDATE / DELETE 越境 negative | `docs/基本設計/02_データモデル.md` |
| BL-0029ab | project boundary cross-project negative test | AC-HARD-03,NF-008 | 0.8 | BL-0025,BL-0028 | `tickets` / `repositories` / `ticket_relations` cross-project negative | `docs/基本設計/02_データモデル.md` |
| BL-0030 | AC-HARD-03 fixture skeleton (`eval/security/tenant_isolation/`) | F-019,AC-HARD-03 | 0.5 | BL-0029a,BL-0029ab | fixture manifest、loader placeholder、expected result schema | `docs/要件定義/01_P0要求定義.md`, `docs/基本設計/02_データモデル.md` |

## タスク一覧

- [ ] ADR-00002 を `docs/adr/00002_db_schema.md` として proposed 化し、tenant invariant、project boundary、actors / principals、複合 FK、migration rollback、negative test 方針を記録する。
- [ ] ADR-00006 の Sprint 2 対象を schema のみに限定し、atomic claim redeem service は Sprint 4 で実装することを Pack と migration comment に明記する。
- [ ] tenants table を作り、P0 seed として `tenant_id=1` を作成する。
- [ ] users、actors、principals を作り、actor_type は `human` / `service` / `agent` / `provider` / `github_app`、principal_type は `session` / `api_token` / `capability_token` / `installation` / `worker` を制約する。
- [ ] `actors.actor_id`、`actors.impersonated_by`、`principals.principal_type`、`auth_context_hash`、`tenant_id` 付き複合 FK を migration と test acceptance に含める。
- [ ] workspaces、projects、repositories を作り、repository は project に所属し、`unique (tenant_id, project_id, id)` を持つ。
- [ ] tickets、acceptance_criteria、ticket_relations を作り、ticket と repository、acceptance_criteria と ticket、ticket_relations の source / target が tenant と project 境界内に閉じるようにする。
- [ ] ticket_relations に `project_id` を持たせ、別 project の ticket 同士を結ぶ INSERT が複合 FK で失敗する fixture を作る。
- [ ] audit_events と notification_events を append-only 前提で作り、raw secret や raw token を payload に入れない column / test 方針を残す。
- [ ] `secret_refs` を作り、`secret_uri`、scope、name、version、status、`runner_injectable=false`、allowed_consumers、allowed_operations、owner_actor_id、rotation metadata を持たせる。
- [ ] `secret_capability_tokens` を作り、`token_hash` unique、allowed_operations、scope_constraint、issued_to_actor_id、nullable run id、expires_at、used_at、expected_request_fingerprint、status を持たせる。
- [ ] `secret_capability_tokens` には raw token を保存せず、agent run FK は Sprint 4 follow-up として migration TODO を残す。
- [ ] PostgreSQL `app_role` と migration role を分け、app が owner 権限で動かないことを contract test にする。
- [ ] repository layer は `tenant_id = current_tenant_id` を全 SELECT / UPDATE / DELETE に含める contract test を作る。
- [ ] cross-tenant negative fixture で SELECT / INSERT / UPDATE / DELETE が失敗することを確認する。
- [ ] cross-project negative fixture で `tickets` / `repositories` / `ticket_relations` の別 project 参照が失敗することを確認する。
- [ ] AC-HARD-03 fixture skeleton を `eval/security/tenant_isolation/` に作り、Sprint 11 の loader 接続予定を manifest に書く。
- [ ] `agent_runs.parent_run_id` と `research_tasks` の cross-project 制約がこの Sprint から漏れているのではなく、後続 Sprint follow-up として明示されていることを確認する。

## must_ship / defer_if_over_budget 対応表

### ロードマップ §94 正本 (verbatim quote)

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 2 | 6.5 | 8 | tenant_id invariant + 複合 FK + **project 境界 invariant** (`(tenant_id, project_id, id)` 複合 FK で当 Sprint 内に存在するテーブル `tickets` / `repositories` / `ticket_relations` を閉じる、DD-02 §5.1) + 越境 + cross-project negative test + actors/principals schema + `secret_refs` / `secret_capability_tokens` 基礎 migration。`agent_runs.parent_run_id` cross-project 制約は Sprint 4 follow-up (BL-0029b)、`research_tasks` cross-project 制約は Sprint 10 follow-up (BL-0029c) に分離 | カスタムフィールド、テンプレート |

### Sprint Pack 内詳細 trace

ロードマップ正本の must_ship を Sprint Pack 内で詳細化したもの:

| 項目 | ロードマップ → Sprint Pack trace |
|---|---|
| tenant_id invariant | 実装チケット BL-0022, BL-0028, BL-0029a |
| 複合 FK | 実装チケット BL-0023, BL-0024, BL-0025, BL-0027, BL-0028 |
| **project 境界 invariant** (`(tenant_id, project_id, id)` 複合 FK で当 Sprint 内に存在するテーブル `tickets` / `repositories` / `ticket_relations` を閉じる、DD-02 §5.1) | 実装チケット BL-0025, BL-0029ab |
| 越境 | 実装チケット BL-0029a |
| cross-project negative test | 実装チケット BL-0029ab |
| actors/principals schema | 実装チケット BL-0023 |
| `secret_refs` / `secret_capability_tokens` 基礎 migration | 実装チケット BL-0027 |
| `agent_runs.parent_run_id` cross-project 制約は Sprint 4 follow-up (BL-0029b) | SP-004 実装チケット BL-0029b |
| `research_tasks` cross-project 制約は Sprint 10 follow-up (BL-0029c) | SP-010 follow-up BL-0029c |

## 受け入れ条件

- [ ] ADR-00002 が proposed 状態で存在し、DB schema、tenant invariant、project boundary、actors / principals、migration rollback、negative test 方針を含む。
- [ ] 全主要テーブルが `tenant_id bigint NOT NULL DEFAULT 1` を持ち、親子 FK は `tenant_id` を含む複合 FK で閉じている。
- [ ] P0 で RLS は有効化しないが、対象テーブルに `metadata.rls_ready=true` が入り、RLS policy 草案または follow-up が残っている。
- [ ] users、actors、principals が作成され、actors は `human` / `service` / `agent` / `provider` / `github_app`、principals は `session` / `api_token` / `capability_token` / `installation` / `worker` を許可する。
- [ ] `actors.actor_id`、`actors.impersonated_by`、`principals.principal_type`、`auth_context_hash` が migration と test の acceptance に含まれている。
- [ ] workspaces、projects、repositories、tickets、acceptance_criteria、ticket_relations が作成され、slug / seq / relation uniqueness は tenant または tenant + project を含む。
- [ ] `tickets` / `repositories` / `ticket_relations` は `(tenant_id, project_id, id)` の複合 unique / FK で同一 project 内に閉じている。
- [ ] 同一 tenant・別 project の repository を ticket に紐付ける INSERT / UPDATE が失敗する。
- [ ] 同一 tenant・別 project の ticket 同士を `ticket_relations` で結ぶ INSERT が失敗する。
- [ ] cross-tenant SELECT / INSERT / UPDATE / DELETE が app_role、repository layer、複合 FK により全件失敗する。
- [ ] `secret_refs` は raw secret を保存せず、`secret_uri` と metadata のみを持つ。`runner_injectable=false` が DB 制約で強制される。
- [ ] `secret_capability_tokens` は raw token を保存せず、`token_hash` unique、expires_at index、status enum、expected_request_fingerprint、allowed_operations を持つ。
- [ ] `secret_capability_tokens` の atomic claim WHERE 節と issue / redeem service は Sprint 4 に defer され、この Sprint では schema と contract placeholder に限定されている。
- [ ] `secret_capability_tokens` の run 参照は nullable で、`agent_runs` FK 後付けが Sprint 4 follow-up として明示されている。
- [ ] audit_events / notification_events は append-only 前提で、raw secret / raw token を payload に含めない。
- [ ] AC-HARD-03 `tenant_isolation_negative_pass` fixture skeleton が `eval/security/tenant_isolation/` にあり、expected result と Sprint 11 loader 接続予定を持つ。
- [ ] Provider Compliance Matrix、`payload_data_class` / `allowed_data_class`、`provider_request_preflight`、`tool_mutating_gateway_stub`、`runner_mutation_gateway`、AgentRun 16 状態、ContextSnapshot 10 カラムの contract を変更しない。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-002_core_data_model.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ruby -e 'text=File.read("docs/sprints/SP-002_core_data_model.md"); missing=%w[BL-0022 BL-0023 BL-0024 BL-0025 BL-0026 BL-0027 BL-0028 BL-0029a BL-0029ab BL-0030].reject { |id| text.include?(id) }; abort("missing: #{missing.join(",")}") unless missing.empty?'` で 10 チケットが揃っていることを確認する。
- [ ] `ls docs/adr/00002_db_schema.md docs/adr/00006_secrets_management.md` で ADR-00002 と ADR-00006 の参照が存在することを確認する。
- [ ] `uv run alembic upgrade head` を dev DB で実行し、Core Data Model migration が通ることを確認する。
- [ ] `uv run alembic downgrade -1 && uv run alembic upgrade head` で直近 migration の downgrade / upgrade が成立することを確認する。
- [ ] `uv run pytest tests/db/test_schema_introspection.py -q` で全主要テーブルの `tenant_id NOT NULL DEFAULT 1`、複合 FK、tenant を含む unique 制約を確認する。
- [ ] `uv run pytest tests/db/test_actor_principal_constraints.py -q` で actor_type / principal_type / `auth_context_hash` / impersonation FK の acceptance を確認する。
- [ ] `uv run pytest tests/db/test_ticket_project_boundary.py -q` で `tickets` / `repositories` / `ticket_relations` の `(tenant_id, project_id, id)` 制約を確認する。
- [ ] `uv run pytest tests/security/test_tenant_isolation_negative.py -q` で cross-tenant SELECT / INSERT / UPDATE / DELETE の negative fixture が全件失敗することを確認する。
- [ ] `uv run pytest tests/security/test_project_isolation_negative.py -q` で同一 tenant・別 project の repository / ticket_relations 越境が失敗することを確認する。
- [ ] `uv run pytest tests/db/test_app_role.py tests/contract/test_app_role_contract.py -q` で app_role が owner 権限を持たず、repository layer が tenant WHERE を必ず含め、payload tenant_id/project_id 越境を ValueError reject することを確認する。
- [ ] `uv run pytest tests/db/test_secret_schema.py tests/db/test_secret_constraints.py -q` で `secret_refs` / `secret_capability_tokens` が raw secret / raw token を保存せず、`runner_injectable=false`、`token_hash` unique、expires_at index、status enum、metadata raw_secret CHECK、TTL bounds、SHA-256 hex format を満たすことを確認する。
- [ ] `uv run pytest tests/eval/test_tenant_isolation_loader.py -q` で AC-HARD-03 fixture loader (Public/Redacted 分離、6 anti-gaming rules、jsonschema validation、fixture_immutable_index、JSON strict parser 等 23 種の defense-in-depth invariant) が機能することを確認する。
- [ ] `rg -n "get_secret_value|runner_injectable\s*=\s*true" backend migrations tests --glob '!**/*.md'` で raw secret 返却 API や runner 注入許可が実装に混入していないことを確認する (実装対象限定、Markdown 除外)。
- [ ] `rg -n "sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|AGE-SECRET-KEY-[A-Z0-9]{20,}" docs --glob '!docs/sprints/**' --glob '!docs/adr/**' --glob '!docs/設計検討/**'` で docs に実値らしい secret / API key / age key 値がないことを確認する (共通 token regex set)。
- [ ] `find eval/security/tenant_isolation -maxdepth 2 -type f | sort` で AC-HARD-03 fixture skeleton、manifest、expected result schema が存在することを確認する。
- [ ] `ruby -e 'paths=["docs/sprints/SP-002_core_data_model.md","docs/実装計画/P0_バックログ.md"].select { |p| File.exist?(p) }; text=paths.map { |p| File.read(p) }.join("\n"); missing=%w[agent_runs.parent_run_id research_tasks BL-0029b BL-0029c].reject { |s| text.include?(s) }; abort("missing follow-up trace: #{missing.join(",")}") unless missing.empty?'` で両 follow-up が Sprint 4 / Sprint 10 に分離されていることを確認する。

### Migration rollback DoD (必須)

DB schema 変更 (Alembic migration) を伴う場合、以下を必ず満たす:

1. **migration 適用前**: `pg_dump` で full DB backup を取り、age で暗号化して別ボリュームに保存。restore drill で復号確認
2. **staging 先行**: `uv run alembic upgrade head` を staging DB で実行し、`alembic check` + Core Data Model contract test (`tenant_id NOT NULL DEFAULT 1`、複合 FK、project boundary、actor/principal enum、secret schema、app_role) が PASS
3. **rollback trigger**: production migration 後に `id` 単独 FK、`tenant_id` 欠落、`tickets` / `repositories` / `ticket_relations` の cross-project 参照成功、raw secret / raw token 保存、app_role owner 権限、または `secret_capability_tokens` の raw token 混入が検出された場合
4. **rollback step**: `uv run alembic downgrade -1` で 1 step downgrade。downgrade で data loss / inconsistent state になる場合は forward-fix migration を新規作成し、staging で検証してから production 適用
5. **rollback verification**: restore 後に Core Data Model contract test を `uv run pytest tests/db/test_schema_introspection.py tests/db/test_actor_principal_constraints.py tests/db/test_ticket_project_boundary.py tests/db/test_app_role.py tests/contract/test_app_role_contract.py tests/db/test_secret_schema.py tests/db/test_secret_constraints.py tests/security/test_tenant_isolation_negative.py tests/security/test_project_isolation_negative.py tests/eval/test_tenant_isolation_loader.py -q` で確認

## レビュー観点

- [ ] tenant invariant が全主要テーブルに入っており、`id` 単独 FK が混入していない。
- [ ] project boundary は Sprint 2 対象の `tickets` / `repositories` / `ticket_relations` で DB 制約として閉じている。
- [ ] cross-project negative test は同一 tenant・別 project ケースを含み、tenant isolation だけで満足していない。
- [ ] `agent_runs.parent_run_id` と `research_tasks` の cross-project 制約を誤って未実装 risk とせず、後続 Sprint follow-up として明示している。
- [ ] actors / principals は将来の IdP 置換、GitHub App、provider、agent、worker を受けられるが、P0 の `human:default` と衝突しない。
- [ ] app_role と migration role が分離され、app が owner 権限で migration や越境操作を実行できない。
- [ ] audit_events / notification_events は append-only の正本として扱われ、raw secret や raw token を payload に含めない。
- [ ] `secret_refs` / `secret_capability_tokens` は ADR-00006 の schema 方針に沿い、raw secret 非保存、token hash only、`runner_injectable=false` を満たす。
- [ ] atomic claim redeem は Sprint 4 に defer されており、中途半端な issue / redeem service を Sprint 2 に入れていない。
- [ ] migration rollback、backup、forward-fix 判断点が現実的で、destructive operation がない。
- [ ] Migration rollback DoD の `pg_dump` / staging / `alembic check` / downgrade / forward-fix / contract test が実行手順として具体化されている。
- [ ] AC-HARD-03 fixture skeleton が Sprint 11 loader、Sprint 12 final 判定へ trace できる。
- [ ] Provider / Tool / Runner / AgentRun / ContextSnapshot の contract を先行変更していない。

## 残リスク

- tenant_id 複合 FK の漏れによる cross-tenant 越境: schema introspection test と repository contract test で全 table / FK を列挙し、`id` 単独 FK を reject する。
- project boundary の漏れによる cross-project 越境: Sprint 2 対象を `tickets` / `repositories` / `ticket_relations` に限定して negative fixture を必須化する。
- `agent_runs.parent_run_id` cross-project 制約の未実装: agent_runs は Sprint 4 対象のため、SP-004 の BL-0029b follow-up に移し、Sprint 2 の Review で未実装理由を残す。
- `research_tasks` cross-project 制約の未実装: research_tasks は Sprint 10 対象のため、SP-010 の BL-0029c follow-up に移し、Sprint 2 の Review で未実装理由を残す。
- `secret_capability_tokens` の FK 後付け忘れ: Sprint 2 migration comment、ADR-00006、SP-004 の実装チケットで `issued_run_id` / `agent_run_id` FK follow-up を明示する。
- app_role contract が repository 実装と drift する: repository layer の tenant WHERE contract test を CI smoke に昇格し、manual SQL だけに頼らない。
- migration rollback が data loss を伴う: Sprint 2 は destructive migration を避け、downgrade 不可能な変更は forward-fix migration と backup restore 条件を Migration rollback DoD / Review に残す。

## 次スプリント候補

- Sprint 3: Policy And Approval。actors / principals を使って requester / decider、self-approval 禁止、action class 7 種、policy_rules、approval_requests、policy_decisions を実装する。
- Sprint 4: Agent Runtime。agent_runs、agent_run_events、artifacts、ContextSnapshot 10 カラム、BudgetGuard、SecretBroker issue / redeem、`secret_capability_tokens` の run FK follow-up を実装する。
- Sprint 4 follow-up: `agent_runs.parent_run_id` cross-project negative fixture を追加し、BL-0029b の最終判定を更新する。
- Sprint 10 follow-up: `research_tasks` cross-project negative fixture を追加し、BL-0029c の最終判定を更新する。
- Sprint 11: AC-HARD-03 fixture loader を Eval Harness に接続し、public_regression / private_holdout / adversarial_new の dataset version に載せる。
- Sprint 12: `tenant_isolation_negative_pass` final 判定を P0 Acceptance Test に接続する。

## 関連 ADR

- [ADR-00006](../adr/00006_secrets_management.md): `secret_ref` URI、SOPS + age、FastAPI 内 SecretBroker、`secret_refs`、`secret_capability_tokens`、raw secret 非保存、token hash only、atomic claim redeem contract を定義する。Sprint 2 は schema のみ実装し、atomic claim は Sprint 4 へ送る。
- [ADR-00002](../adr/00002_db_schema.md): Sprint 2 で proposed 化する。tenant invariant、project 境界 invariant、actors / principals、複合 FK、app_role、negative test、migration rollback を扱う。
- ADR-00001 は Sprint 1 の dev login / `human:default` actor binding から継続参照する。Sprint 2 では actors / principals schema に接続する。
- ADR-00008 は destructive migration が必要になった場合のみ作成または参照する。Sprint 2 の初期方針は destructive migration を避ける。
- ADR-00010 は変更しない。Provider Compliance Matrix、`payload_data_class`、`allowed_data_class`、`provider_request_preflight` は Sprint 5 以降の対象である。

## Review

完了日: 2026-05-08
累計 round: 81 round (Batch 1: 4 / Batch 2: 4 / Batch 3: 11 / Batch 4: 37、ADR-00002 proposed 化を含む)
累計 findings adopted: 71 件 (Batch 1: 11 / Batch 2: 14 / Batch 3: 15 / Batch 4: 38)

### changed

**Batch 1 (R4 clean)** — tenants / actors / principals / workspaces / projects / repositories schema:
- `migrations/versions/0002_tenants_actors_principals.py` (6 table、複合 FK、`tenant_id NOT NULL DEFAULT 1`、actor_type/principal_type CHECK、`actors.actor_id` text + `auth_context_hash`、`principals_uq_tenant_actor_principal_id`)
- `backend/app/db/models/{tenant,actor,principal,workspace,project,repository}.py` (SQLAlchemy 2.x async + `Mapped[T]`)
- `backend/app/db/app_role.py` (`set_tenant_context` / `get_tenant_context` / `assert_tenant_context` skeleton)
- `backend/app/repositories/base.py` (BaseRepository[ModelT] + tenant_id required)
- `backend/app/seeds/initial.py` (1 tenant + 1 actor `human:default` + 1 principal + 1 workspace + 1 project + 1 repository)
- `tests/db/test_schema_introspection.py` / `test_actor_principal_constraints.py` / `test_repository_layer.py` / `test_app_role.py`

**Batch 2 (R4 clean)** — tickets / acceptance_criteria / ticket_relations + audit_events / notification_events:
- `migrations/versions/0003_tickets_acceptance_audit.py` (5 table、project boundary 複合 FK `(tenant_id, project_id, ticket_id) → tickets`、self-loop check、actor-principal 複合 FK `(tenant_id, actor_id, principal_id) → principals`)
- `backend/app/db/models/{ticket,acceptance_criteria,ticket_relation,audit_event,notification_event}.py`
- `backend/app/repositories/{ticket,acceptance_criteria,ticket_relation,audit_event,notification_event}.py` (3 project-scoped repository で `get/list/update/delete` + `statement_for_*` を NotImplementedError、`*_in_project` / `*_in_ticket` 経路のみ提供で boundary bypass 防止)
- `tests/db/test_ticket_project_boundary.py` / `test_acceptance_criteria.py` / `test_ticket_relations.py` / `test_audit_events.py` / `test_notification_events.py`

**Batch 3 (R11 clean)** — secret_refs / secret_capability_tokens 基礎 migration:
- `migrations/versions/0004_secret_refs_capability_tokens.py` (2 table、22 種の DB-level invariant: raw secret 列不在 / `runner_injectable=false` CHECK / partial unique active 1 + pending 1 / `(tenant_id, secret_uri)` unique / `(tenant_id, scope, name, version)` unique / secret_uri format CHECK + components match CHECK / status enum / allowlist 構造 + active 非空 + string element / token_hash + expected_request_fingerprint SHA-256 64-hex / TTL 5-30 分 bounds / used_at 双方向 lifecycle / `(tenant_id, token_hash)` per-tenant unique / expires_at WHERE status='issued' partial index / `metadata` jsonb_path_exists で nested 含む 13 raw secret keys reject / agent_runs FK は Sprint 4 follow-up TODO)
- `backend/app/db/models/{secret_ref,secret_capability_token}.py` (Literal type alias、Mapped[T])
- `backend/app/repositories/{secret_ref,secret_capability_token}.py` (read-only skeleton、`atomic_claim` は `NotImplementedError("Implemented in Sprint 4 SecretBroker service")`)
- `tests/db/test_secret_schema.py` / `test_secret_constraints.py` (33 test)

**Batch 4 (R37 clean)** — app_role + cross-tenant/cross-project negative test + AC-HARD-03 fixture loader:
- `tests/security/test_tenant_isolation_negative.py` (cross-tenant SELECT/INSERT/UPDATE/DELETE 全 4 種カバー、coordinated UPDATE P0 limitation documenting)
- `tests/security/test_project_isolation_negative.py` (cross-project ticket/repository/acceptance_criteria/ticket_relations + isolated ticket P0 limitation documenting)
- `tests/contract/test_app_role_contract.py` (app_role + statement_for_*_in_project の tenant_id/project_id predicate contract)
- `eval/security/tenant_isolation/loader.py` + `manifest.json` (23 種の defense-in-depth invariant: PublicFixture/RedactedFixture 型分離、6 anti-gaming common rules 全強制、jsonschema Draft7 + FormatChecker、fixture_immutable_index sha256 双方向検証 + entry allowlist + ASCII created_at + calendar valid、JSON strict parser duplicate key + NaN reject、metadata raw_secret nested 検出、PublicFixture spoof reject、RedactedFixture post-load nested leak、tuple/non-string key TypeError、unknown top-level key reject、split path containment、expected_schema canonical filename strict)
- `tests/eval/test_tenant_isolation_loader.py` (97 test、parametrize 含む)
- `backend/app/repositories/ticket.py` (`update_in_project` の payload tenant_id/project_id reject 追加)
- `pyproject.toml` + `uv.lock` (jsonschema>=4.0,<5.0 追加、`uv lock` で 4.26.0 + transitive deps)

**ADR / Sprint Pack 整合**:
- `docs/adr/00002_db_schema.md` proposed 化 (R36 fix で 9 round / accepted 化準備済) + §5.2 Sprint 2 P0 limitation: tenant_id / project_id immutability (Sprint 4 で trigger 検討)
- SP-002 Sprint Pack の test path / ADR ref / rg コマンド drift 完全 cleared

### verified

**Hard Gates 7 への trace**:
- **AC-HARD-03 `tenant_isolation_negative_pass`**: Batch 4 で fixture loader scaffold + 23 invariant fail-closed 完成 (Sprint 11 で eval harness loader 接続予定)。fixture skeleton: `eval/security/tenant_isolation/{manifest.json, expected_schema.json, public_regression/sample.json}` + `loader.py`。cross-tenant SELECT/INSERT/UPDATE/DELETE 全 4 種は repository layer + DB FK + ADR-00002 §5.2 P0 limitation で fail-closed
- **AC-HARD-04 `backup_restore_rpo_rto`**: Sprint 2 では Migration rollback DoD として `pg_dump` / staging 先行 / Alembic downgrade / forward-fix migration / restore drill 手順を規定 (実 drill は Sprint 12 P0 Acceptance)
- **AC-HARD-05/06/07** は Sprint 7 (runner sandbox) / Sprint 11 (prompt injection adversarial) で対象外
- **AC-HARD-01 `policy_block_recall` / AC-HARD-02 `secret_canary_no_leak`**: Sprint 3 (policy/approval) / Sprint 4 (SecretBroker atomic claim) で対象

**Quality KPIs 5**: Sprint 2 では DB schema 整備のみで KPI 計測対象外。Sprint 4 (`approval_wait_ms`) / Sprint 5 (`acceptance_pass_rate`) / Sprint 8 (`time_to_merge`) / Sprint 10 (`citation_coverage`) / Sprint 11.5 (`cost_per_completed_task`) で計測開始。

**検証コマンド** (SP-002 §155-§168 で実行可能):
- `uv run alembic upgrade head` / `downgrade -1 && upgrade head`
- `uv run pytest tests/db/test_schema_introspection.py tests/db/test_actor_principal_constraints.py tests/db/test_ticket_project_boundary.py tests/db/test_app_role.py tests/contract/test_app_role_contract.py tests/db/test_secret_schema.py tests/db/test_secret_constraints.py tests/security/test_tenant_isolation_negative.py tests/security/test_project_isolation_negative.py tests/eval/test_tenant_isolation_loader.py -q`
- `rg -n "get_secret_value|runner_injectable\s*=\s*true" backend migrations tests --glob '!**/*.md'` (false positive cleared)
- `rg -n "<token regex set>" docs --glob '!docs/sprints/**' --glob '!docs/adr/**' --glob '!docs/設計検討/**'` (raw secret 値不在)
- `find eval/security/tenant_isolation -maxdepth 2 -type f | sort` (fixture skeleton 存在)
- `ls docs/adr/00002_db_schema.md docs/adr/00006_secrets_management.md` (ADR 参照存在)

**Sprint Exit gate に対する readiness**: Codex multi-round review で `findings: []` (clean) を達成。VPS deploy smoke は Sprint 11.5 (private staging CI/E2E) で実施予定。

### deferred

- **AgentRun schema / ContextSnapshot 10 カラム**: Sprint 4 (Agent Runtime) で実装。Sprint Pack §47 「対象外」に明記。
- **SecretBroker atomic claim service / issue / redeem 本実装**: Sprint 4 で実装、ADR-00006 accepted 化と同時。Sprint 2 では schema + repository read-only skeleton のみ (`atomic_claim` は `NotImplementedError`)。
- **`agent_runs.parent_run_id` cross-project 制約**: Sprint 4 BL-0029b follow-up に分離 (agent_runs table が Sprint 4 対象)。Sprint Pack §49 / §128 で明示。
- **`research_tasks` cross-project 制約**: Sprint 10 (Research Evidence) BL-0029c follow-up に分離。Sprint Pack §51 / §129 で明示。
- **tenant_id / project_id immutability BEFORE UPDATE trigger**: ADR-00002 §5.2 で Sprint 4 follow-up として明記。Sprint 2 では repository layer の payload tenant_id/project_id reject + DB FK で coordinated UPDATE bypass を P0 limitation として documenting test で記録。
- **AC-HARD-03 fixture loader と EvalRun/EvalResult table の接続**: Sprint 11 (Eval Harness) で実装。Sprint 2 では loader scaffold + 23 invariant の fail-closed のみ。
- **RLS 有効化**: P0 では無効のまま、`metadata.rls_ready=true` と policy 草案、app_role contract test を維持。Sprint 11.5 / P1 で検討。
- **カスタムフィールド / Ticket template / workflow template**: P1 以降 (Sprint Pack §47)。

### risks

- **複合 FK 漏れ → cross-tenant 越境**:
  - 検知: `tests/db/test_schema_introspection.py` で全 table の `tenant_id` 列 + 複合 FK + `id` 単独 FK 不在を assertion
  - 軽減: schema introspection contract test を CI smoke 級で必須化、新 table 追加時は同 contract test pattern を踏襲

- **cross-project fixture 漏れ → P0 limitation 拡大**:
  - 検知: `tests/security/test_project_isolation_negative.py` で repository_id NULL ticket の coordinated UPDATE P0 limitation を documenting
  - 軽減: ADR-00002 §5.2 で Sprint 4 で project_id immutability trigger 検討、Sprint Pack で limitation を明示

- **`agent_runs.parent_run_id` cross-project 制約の Sprint 4 follow-up 漏れ**:
  - 検知: SP-002 §167 の `ruby` 検証コマンドで `BL-0029b` / `BL-0029c` trace 存在確認
  - 軽減: Sprint 4 SP-004 Sprint Pack に BL-0029b を組み込み済 (実装計画/P0_バックログ.md で trace)

- **app_role contract drift → repository が tenant_id WHERE を抜く**:
  - 検知: `tests/contract/test_app_role_contract.py` で statement_for_list/update/delete + statement_for_*_in_project の tenant_id/project_id predicate を SQLAlchemy compile で assert
  - 軽減: Sprint 4 で `app_role` PostgreSQL ROLE 分離本実装時に同 contract test を引き続き維持

- **migration rollback の data loss / inconsistent state**:
  - 検知: SP-002 Migration rollback DoD で `pg_dump` + staging 先行 + `alembic check` + 10 件の contract test 通過 (R36 fix で path 整合)
  - 軽減: Sprint 2 では destructive migration を避け、forward-fix migration を優先する設計を ADR-00002 で明記

- **AC-HARD-03 fixture loader の anti-gaming bypass**:
  - 検知: 97 件の test で 23 種の defense-in-depth invariant を fail-closed 検証 (PublicFixture/RedactedFixture 型分離 + nested expectation leak + jsonschema fail-closed + fixture_immutable_index sha256 双方向 + JSON strict parser + post-load constructed bypass + tuple/non-string key TypeError + unknown top-level key + split path containment + canonical filename + raw secret keys denylist)
  - 軽減: Sprint 11 で eval harness 接続時に CI hook で fixture 改変を block、月次 append-only refresh を git history check で強制

