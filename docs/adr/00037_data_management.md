---
id: "ADR-00037"
title: "データ管理 (Q-2 一括インポート / Q-3 一括 soft-delete / Q-4 プロジェクトアーカイブ)"
status: "accepted"
date: "2026-05-29"
deciders: ["t-ohga"]
adr_gate_criteria: [2, 3, 8]
related_adr:
  - "ADR-00035 (プロジェクト設定編集)"
  - "ADR-00036 (secret_refs インベントリ)"
related_dd:
  - "DD-02 (データモデル)"
  - "DD-04 (セキュリティ_権限_監査)"
---

# ADR-00037: データ管理 (Q-2 / Q-3 / Q-4)

## 背景

UI 改善計画 Q-2〜Q-4 (データ管理、Tier 4「design approval 必須」) を設計する。3 機能はいずれも
**破壊的操作 (ADR Gate #8)** に該当し、P0 の「destructive action は原則 deny、必要なら ADR + 確認 UI
必須」(rendering.md §7) + 「soft delete + 認可 + 監査 + 復元手順 必須」(実装計画 A-3 教訓) を満たす設計が必要。

調査済の現状:
- `projects.status` は `Literal["active","archived"]` + CHECK 済 → **Q-4 archive は status の soft toggle**
  (reversible) で実装できる。最も低リスク。
- tickets/projects に **soft-delete 基盤 (deleted_at) が無い** → Q-3 は新 schema (nullable `deleted_at`) が必要。
- 「テストデータ」を区別する schema marker が無い (is_test/seed flag なし)。
- import 形式/source は未定義。imported data は untrusted_content であり ai-output-boundary に従う必要がある。
- 既存: tickets API は list/get/create/update のみ (delete は Tier 4 へ移動済)。

## 設計上の前提・assumption (★ user 確認事項)

3 機能の欠落仕様について、本 ADR は以下の P0 準拠 assumption を採用する。**design approval 時に確認・補正**:

- ★ **Q-3「テストデータ」の定義**: schema marker が無いため、対象を「**owner が明示選択した 1 project 内の
  全 ticket**」とし、**hard delete ではなく soft delete (`tickets.deleted_at`)** + 復元 (restore) とする。
  「テストデータ」= project 単位のデータクリーンアップ。任意 entity の hard delete は P0 deny。
- ★ **Q-2 import の形式/source**: **structured JSON (ticket array)** を owner が貼付/アップロードし、
  schema validation (Pydantic/Zod) を通して current project に ticket 作成。外部 URL / 自動取込はしない。
  imported data は untrusted_content として扱い、artifact → schema_validated を経る。
- ★ **Q-4 archive の可視性 + 凍結**: archived project は一覧で badge 表示 (default で除外はしない)。
  **archived = child write 凍結 (read-only)**: archived project への ticket create/update/import/bulk-delete/
  restore は 409 で reject し、unarchive を要求する (Codex plan R1 #3、後述)。

## 破壊的操作の追加 invariant (Codex plan review R1 で強化)

実装が DoD を満たしつつ deleted data 漏洩 / 不安全 restore / 不整合 state を生む余地を塞ぐため、以下を必須とする:

1. **soft-delete は repository-level active scope** (R1 #1): list だけでなく **全 default read path**
   (list / get / count / project summary / dashboard / KPI 集計) が `deleted_at IS NULL` を強制する。
   `TicketRepository` に active-scope helper を設け全 read で経由。`include_deleted=True` は restore 専用 path
   のみ opt-in。get/count/summary も含む contract test 必須。
2. **deletion batch + batch 単位 restore + 所有境界 + 冪等性** (R1 #2 / R2 #1): soft-delete は
   **deletion batch (run id)** を発行し、各 ticket に `deleted_batch_id` / `deleted_by_actor_id` /
   `deleted_at` を記録。restore は **特定 batch を対象** とし、project 内の全 `deleted_at` を盲目的に
   clear しない。restore の UPDATE は **`WHERE tenant_id=? AND project_id=? AND deleted_batch_id=? AND
   deleted_at IS NOT NULL`** で batch 所有を tenant + project の両方で検証する (batch_id は UUID だが、
   推測/漏れによる別 project の削除行復活を防ぐ、R2 #1)。再 restore / 空 batch / 並行 restore は **0 rows →
   idempotent 200 (`restored_count=0`)** とする (二重復元で件数 inflation しない)。restore も owner gate +
   確認 + audit (batch_id + restored_count)。cross-project batch_id 指定 → 0 rows (越境復活しない) の
   contract test 必須。
3. **archive child-write 凍結 (全 mutation 境界で enforce)** (R1 #3 / R5 #2): archived project への ticket
   create / update / import / bulk-delete / restore は **fail-closed (409)**。unarchive (active 化) を要求。
   guard は HTTP endpoint だけでなく **全 ticket mutation が通る共有境界 (`TicketRepository` の
   create/update/create_in_project 等) に置く**。HTTP endpoint だけに置くと **非 HTTP 経路**
   (`backend/app/mcp/api_bridge.py` の ticket create/update、`backend/app/services/research/research_to_ticket.py`
   の `TicketRepository.create_in_project` 直呼び) が archived project に書けてしまう (R5 #2)。これらを
   実装対象 + negative test 対象に明示する (M-3 R9 / R-3 と同じ「単一 entrypoint でなく境界で enforce」)。
4. **import は all-or-nothing transactional + DB-level slug uniqueness** (R1 #4 / R2 #2): 全 row を先に
   validate し、1 件でも不正なら import 全体を reject (partial write なし)。**in-payload の slug 重複** と
   **既存 slug との衝突** はいずれも import を reject (衝突 slug を error に列挙)。dry-run preview を提供。
   app-level の pre-validation **だけに依存せず**、既存の **`tickets_uq_tenant_project_slug` UNIQUE
   (tenant_id, project_id, slug、全行)** を DB-level の最終防衛とする: 並行 import で双方が pre-validation を
   通っても、insert は単一 transaction で行い、一方が unique violation で **transaction 全体 rollback** する
   (重複生成を DB が止める)。migration は `deleted_at` 追加時に **この slug unique を partial 化しない**
   (= soft-deleted 行も slug を予約。delete 済 slug の再利用は reject = 「deleted との衝突 reject」と整合。
   slug 再利用は hard delete 相当で P0 out)。既存 data の重複は当該制約により存在しない (precheck 不要)。
   並行 import の片方が constraint violation で全 rollback する contract test 必須。response/audit に
   validation 結果 + 件数を含める (本文値は残さない)。

## 決定対象

| # | 機能 | 操作 | リスク |
|---|---|---|---|
| Q-4 | プロジェクトアーカイブ | `projects.status` active↔archived (soft、reversible) | LOW-MEDIUM |
| Q-3 | ticket 一括 soft-delete | `tickets.deleted_at` set/clear (soft、復元可) | MEDIUM-HIGH (破壊的) |
| Q-2 | ticket 一括インポート | validated JSON → ticket 作成 (untrusted→validation) | MEDIUM-HIGH (破壊的 write) |

## 前提 / 制約 (P0 invariant)

- **destructive は soft + reversible**: hard delete しない。Q-3 は `deleted_at`、Q-4 は status。復元経路を持つ。
- **owner-only + 確認 UI**: 破壊的操作は ADR-00036 と同じ owner gate (authenticated + human + 構成済み
  owner) で enforce。UI は二段階確認 (destructive は誤操作防止)。
- **監査必須**: 全操作を audit event に残す (Q-4: `config_changed` / Q-3: soft-delete・restore event /
  Q-2: import event)。raw secret なし、件数・対象 id・actor を記録。
- **import の untrusted boundary** (ai-output-boundary): imported ticket は untrusted_content。
  schema validation (title/slug 形式・status enum・project boundary) を必須。AI 出力直結禁止と同様、
  検証なしの一括書込はしない。slug 重複は reject か skip を明示。
- **tenant/project boundary**: 全操作 `tenant_id` (+ Q-2/Q-3 は project_id) filter。cross-tenant/project
  negative test 必須。
- **bounded**: Q-2 import は件数上限 (例: 1 回 100 件) + payload size 上限。Q-3 は対象 project の確認必須。

## 採用案 (設計案、実装は design approval 後)

### Q-4 プロジェクトアーカイブ

- `PATCH /api/v1/me/projects/{id}/archive` body `{archived: bool, expected_status: "active"|"archived"}`。
  CAS (expected_status、M-3 autonomy と同パターン) で stale toggle を防ぐ。owner gate + 確認 dialog。
- status を active↔archived に切替。`config_changed` audit (previous/new status)。
- **child-write 凍結 (共有境界で enforce)**: archived project への ticket create/update/import/bulk-delete/
  restore は 409。「project.status == active」guard を **`TicketRepository` の mutation メソッド
  (create / update / create_in_project)** に置き、HTTP endpoint・MCP bridge・research-to-ticket promotion の
  全経路で fail-closed にする (endpoint だけに置かない)。unarchive で解除。
- frontend: archive/unarchive ボタン + 確認 dialog。archived は badge 表示 + child 操作 UI を disable。

### Q-3 ticket 一括 soft-delete (+ batch restore)

- migration: `tickets` に `deleted_at timestamptz NULL` / `deleted_batch_id uuid NULL` /
  `deleted_by_actor_id uuid NULL` 追加 (nullable、既存行無影響、rollback=drop_column)。
- **repository-level active scope**: `TicketRepository` に active-scope (`deleted_at IS NULL`) helper を設け、
  **list / get / count / project summary / dashboard / KPI 集計の全 default read path** が経由する。
  `include_deleted=True` は restore path 専用 opt-in。
- `POST /api/v1/me/projects/{id}/tickets/bulk-soft-delete` body `{expected_active_count}` → 新 deletion batch
  (run id) を発行し、対象 project の active 全 ticket に deleted_at / deleted_batch_id / deleted_by set。
  owner gate + 二段階確認 + expected_active_count CAS (件数 mismatch なら 409)。`tickets_bulk_soft_deleted`
  audit (batch_id + 件数 + project_id)。
- `POST .../tickets/restore` body `{deleted_batch_id}` → `UPDATE ... SET deleted_at=null, deleted_batch_id=null
  WHERE tenant_id=? AND project_id=? AND deleted_batch_id=? AND deleted_at IS NOT NULL` で **特定 batch のみ**
  復元 (tenant + project で batch 所有検証、越境復活防止)。owner gate + 確認 + audit (batch_id + restored_count)。
  再 restore / 別 project の batch_id / 空 batch は 0 rows → idempotent 200 (`restored_count=0`)。
- ★ delete scope は「project 内 active 全 ticket」固定 (任意選択削除は P0 では out)。

### Q-2 ticket 一括インポート

- `POST /api/v1/me/projects/{id}/tickets/import` body `{tickets: [{slug,title,status?,priority?,description?}...],
  dry_run?: bool}`。
- **all-or-nothing transactional**: 全 row を先に schema validation (untrusted boundary、title/slug 形式 /
  status enum / project boundary)。1 件でも不正、または **in-payload slug 重複**、または **既存 active/deleted
  ticket との slug 衝突** があれば import 全体を reject し、原因 (invalid rows / 衝突 slug) を response に列挙。
  検証通過時のみ単一 transaction で全件 insert (partial write なし)。並行 import が pre-validation をすり抜けても
  既存 `tickets_uq_tenant_project_slug` UNIQUE で一方が rollback する (DB-level 最終防衛)。
- 件数上限 100 + payload size 上限。`dry_run=true` で validation 結果のみ返す (insert しない、preview 用)。
- owner gate + archived project は 409。`tickets_imported` audit (件数 + project_id、本文値は残さない)。
- frontend: JSON 貼付 → dry-run preview (validation 結果 + 衝突) → 確認 → import。AI 出力直結はしない。

## 却下案

- 任意 entity の hard delete (Q-3): P0 deny (復元不可、ADR Gate #8 違反)。
- 外部 URL / 自動 import (Q-2): untrusted source の自動取込は AI output boundary 違反。
- archive を hard delete で代替: data loss、reversible でない。却下。

## リスク

- HIGH (3 破壊的機能、ADR Gate #8)。誤操作・越境・untrusted import・soft-deleted 漏洩が主リスク。
- soft delete により hard data loss を回避。batch restore + 二段階確認 + owner gate + audit + CAS で多層防御。
- import の untrusted boundary: 全件 schema validation + all-or-nothing transactional + 件数/size 上限 +
  in-payload/既存 slug 衝突 reject + dry-run。
- **soft-deleted 漏洩リスク** (R1 #1): list 以外の get/count/summary/dashboard/KPI に filter 漏れがあると
  削除済が露出 → repository-level active scope + 全 read path の contract test で塞ぐ。
- **誤 restore リスク** (R1 #2): batch 単位 restore で古い削除/import の誤復活を防ぐ。
- **archived project への write リスク** (R1 #3): 全 child mutation に active guard + test。
- **競合リスク** (実装 adversarial R1): archive freeze / bulk-delete CAS は非ロック read だと competing
  transaction で破れる → `TicketRepository._lock_project_status()` で project row を FOR UPDATE lock し、
  archive toggle と全 ticket mutation (create/update/import/bulk-delete/restore) を直列化。bulk-delete の
  CAS は repository の atomic 操作内 (lock 保持下 count→CAS→update) で enforce する。
- **MCP active scope 漏洩** (実装 adversarial R2 #2): cross-project `bridge_ticket_list_all` /
  `bridge_ticket_search` に `deleted_at IS NULL` を追加し、soft-deleted を MCP read からも除外。
- **archive freeze は project child write 全体に適用** (実装 adversarial R10 #1): archived = read-only
  child-write freeze は ticket だけでなく **全 project child write** に及ぶ。共通 dependency
  `require_active_project` (`api/dependencies/project_active_guard.py`) を HTTP child-write endpoint
  (claims `create_claim` / evidence_items `create_evidence_item`) に適用し、archived なら 409
  fail-closed。evidence_sources / research_tasks は read-only (GET のみ) で write 経路なし。
  **残リスク (defer、Codex App PR review #1)**: `MemoryRetrievalService.retrieve()` (memory API、GET
  `/api/v1/projects/{project_id}/memory/retrievals`) は **write-on-read** で Artifact + MemoryRetrievalArtifact
  行を作る child write だが `require_active_project` 未適用。ただし `memory_api_enabled` は **default False**
  (config.py、`require_memory_api_enabled` gate) のため **P0 default config では到達不能** (P0-active でない、
  別 feature)。memory feature を有効化する際は本 endpoint (および write-on-read を行う memory insight 系) に
  `require_active_project` を適用する follow-up が必須。新規 project child-write endpoint 追加時も同 dependency
  適用を必須とする運用 (根本解は前述 DB-level enforcement)。
- **delegation_review run guard** (実装 adversarial R10 #2): `bridge_delegation_review` も R6 の
  `_assert_run_ticket_actionable` を通し、削除済 ticket / archived project の run に review
  (approval_decided) event を記録しない。
- **run-transition guard** (実装 adversarial R6 → R12 で server-owned column 化): bulk soft-delete / archive
  **前**に作成済みの既存 run も、削除/凍結後は進行させない。`bridge_run_update` / `bridge_delegation_accept` /
  `bridge_delegation_submit` / `bridge_delegation_review` / `bridge_run_cost` が `_assert_run_ticket_actionable`
  を通し、削除/凍結した作業の AI 実行・コスト・結果公開を防ぐ (進行は cancel のみ許可)。
  **R12 改善**: 当初は `run_queued` event payload から ticket_id を解決していたが (event 改ざん / payload 欠落
  時に fail-open リスク)、`agent_runs.ticket_id` server-owned column (migration 0040、`bridge_run_create` が
  `UUID(ticket_id)` で書込) を直接読む方式へ変更。ticket-less run は NULL → `assert_project_active` のみ適用。
  **R13 改善**: server-owned 権威列が **cross-project / cross-tenant / 存在しない ticket** を指さないことを
  DB で強制する複合 FK `agent_runs(tenant_id, project_id, ticket_id) -> tickets(tenant_id, project_id, id)`
  (`ondelete=RESTRICT`、ticket_id IS NULL は MATCH SIMPLE で未強制) を追加 (core.md §8「親子参照は tenant_id を
  含む複合 FK で閉じる」+「project 境界をまたぐ参照禁止」)。migration 0040 backfill も **event payload を
  untrusted 扱い**し、run と同一 (tenant_id, project_id) の tickets 行に実在一致する場合のみ ticket_id を設定
  (cross-project / 不正 binding は NULL のまま fail-closed、複合 FK 作成を破綻させない)。negative test
  `test_run_ticket_fk_enforces_same_project_binding` (cross-project insert → IntegrityError) で検証。
  **残リスク (defer、Codex adversarial R24 で再確認)**: P0 に queued run を auto-execute する worker は無く
  (worker は cancel propagation のみ)、進行は MCP 手動経路 (`bridge_run_update` / `bridge_run_cost` /
  delegation 系) に限られるため上記 guard で **P0-active 経路は全閉塞**。`AgentRuntimeOrchestrator.execute_provider_step`
  (services/agent_runtime/orchestrator.py) は **provider call + cost 記録 + status/event 遷移** を直接行うが、
  **P0 では production caller を持たない** (R24 検証: 呼出は `tests/runtime/test_orchestrator_pure_helpers.py`
  のみ、API endpoint / arq worker / main 配線ゼロ。orchestrator scope コメント=「arq worker は future、
  Sprint 9 UI は future、本 batch は unit test」)。よって soft-delete/archive 後に provider work が継続する
  経路は **P0 では到達不能**。**P0.1 follow-up (必須)**: arq worker / UI で orchestrator を P0-active 配線する際は、
  `execute_provider_step` の中央 mutation 境界 (provider call 前 / usage 記録前 / status・event 更新前) に
  `assert_agent_run_actionable_locked` 相当 (project row FOR UPDATE lock + ticket-bound run は ticket active /
  ticketless run は project active 検証、bulk_soft_delete / archive と直列化) を必ず追加し、soft-delete/archive 後の
  `execute_provider_step` で provider call・cost/token・status/event が発生しない negative test を入れる
  (ADR-00014/00021 P0.1 orchestrator Sprint scope)。bulk-delete/archive 時の non-terminal run 一括 cancel
  (cascade) も同 Sprint follow-up。**この defer は P0 sealed scope boundary に整合** (P0.1 multi-agent runtime を
  P0 data-management PR で実装しない)。
- **全 run read path active-scope** (実装 adversarial R12 → R13 漏れ補完 → R15 で全 read path 網羅 +
  共通 helper 化): soft-delete した ticket に紐づく run が **default read path** (集計 + 一覧 + 詳細) に
  混入/露出する漏れ (write guard は塞いでも read は別 path) を `agent_runs.ticket_id` JOIN で塞ぐ。
  共通 predicate **`soft_deleted_ticket_run_exclusion()`** (`domain/agent_runtime/active_scope.py`、
  `NOT EXISTS (tickets t WHERE t.tenant_id/project_id/id = agent_runs.* AND t.deleted_at IS NOT NULL)`、
  複合 FK 境界と一致) を次へ適用:
  - 集計: `cost_summary_endpoint` (api/agent_runs.py) / MCP `kpi_show` (mcp/server.py) / MCP
    `bridge_workflow_status` (mcp/api_bridge.py、total_runs/active/completed/failed/success_rate)。
  - 一覧/詳細 (**R15 で追加**): HTTP `list_agent_runs_endpoint` / `get_agent_run_endpoint` (削除済→404) /
    MCP `bridge_run_list` / `bridge_run_show` (削除済→not_found)。
  - nested/recursive (**R16 で追加**): MCP `bridge_run_show` の **children** query (削除済 child を親経由で
    列挙させない) / MCP `bridge_delegation_tree` の **再帰 CTE** (seed=root と recursive=child の両方に
    `NOT EXISTS deleted ticket`、削除済 root→not_found / 削除済 child→tree 除外)。
  ticket_id=NULL の run は含む (削除対象でない)、restore で再び現れる。regression test
  `test_workflow_status_excludes_soft_deleted_ticket_runs` / `test_run_read_paths_exclude_soft_deleted_ticket_runs`
  / `test_run_show_children_exclude_soft_deleted_ticket_runs` / `test_delegation_tree_excludes_soft_deleted_ticket_runs`。
  なお `bridge_run_show` の `ticket_id` 表示も event payload から server-owned column (`run.ticket_id`) 直読みへ変更。
  **残リスク (defer)**:
  - HTTP `get_agent_run_kpi_endpoint` (AC-KPI-02 単一 run point-read) は `agent_run_kpi.py` の SQL に
    active-scope を入れる必要があり、**AC-KPI-02 Hard Gate fixture 整合の確認を伴う**ため defer
    (Codex は agent_run_kpi を aggregation-scope 外として carve-out 済、default run 露出は detail/list で active-scope 化済)。
  - 他の KPI/aggregation service (P0.1 orchestrator KPI 等) への同 scope 適用は follow-up。
  - 根本解は前述 DB-level enforcement (active-scope を全 read path に強制)。
- **work-initiation guard** (実装 adversarial R3): 削除済 ticket / archived project への作業開始
  (AgentRun / approval / delegation / dispatch) を `TicketRepository.assert_ticket_actionable` で拒否
  (soft-deleted → `TicketNotActionableError`、archived → `ProjectArchivedError`)。`bridge_run_create`
  (run/delegation/dispatch の chokepoint) と `bridge_approval_request_create` で enforce し、削除/凍結
  した作業が AI 実行・承認・コスト発生へ進むのを防ぐ。
- **delegation parent-run guard** (実装 adversarial R16 #2 → R17 #1 で chokepoint へ集約): `parent_run_id` を
  指定する run は parent run **自体** が actionable (active ticket + active project) であることを必須にする。
  当初は `bridge_delegation_create` に置いたが、**`bridge_run_create` が parent_run_id を直接受け取り persist
  する真の chokepoint** (MCP `run_create` tool が parent_run_id を直接公開) のため、R17 で `bridge_run_create`
  に集約 (削除済 ticket parent → `TicketNotActionableError`、archived → `ProjectArchivedError`、不在 →
  `ValueError`/`parent not found`、いずれも MCP wrapper が dict 化)。これで `run_create` 直呼びでの parent
  迂回も塞ぐ。`bridge_delegation_create` の二重 guard は撤去し single-source 化。negative test
  `test_run_create_rejects_deleted_ticket_parent` / `test_delegation_create_rejects_deleted_ticket_parent`
  (child run / inter_agent_message 双方の非生成)。
- **approval trust boundary active-scope** (実装 adversarial R18、**P0-active ship-block**): `bridge_approval_request_create`
  は作成時のみ ticket actionable を検証し、bulk soft-delete / archive **後** に残る既存 pending approval を
  invalidate しなかった。decision chokepoint (`ApprovalDecisionService.approve` → POST `/api/v1/approvals/{id}/decide`)
  は id/status のみで pending→approved 遷移するため、「ticket X の approval 作成 → bulk soft-delete → decide」で
  **削除済 work へ human authorization を付与できた** (P0-active HTTP 経路)。shared helper
  `approval_active_scope.py` (`resource_ref='ticket:<uuid>'` を parse、bound ticket の deleted_at / project archived
  を判定) を新設し:
  - **decide guard (security 中核)**: `ApprovalDecisionService.approve` が承認前に bound ticket の active-scope を
    再検証、削除済/archived なら raise (endpoint が 409)。**reject は cleanup のため許可** (approve のみ block)。
  - **read path**: `list_pending_approvals` (stale approval を一覧から除外) / `get_approval_detail` (削除済→404)。
  - soft-delete は **可逆** なので status は変えず (`invalidated` 化しない)、restore で再び承認可能 (動的 filter)。
    `resource_ref` が実在 ticket を指さない (synthetic / 非 ticket / legacy) approval は管轄外で block しない
    (Q-3 soft-delete は行を物理削除しないため、対象は「行が残り deleted_at セット」case に限る)。
  negative test `test_approval_decide_rejects_soft_deleted_ticket` (approve→409 + pending 維持 + restore で actionable
  復帰) / `test_approval_list_detail_hide_soft_deleted_ticket` (list 除外 + detail 404 + restore で再表示)。
  **R19 改善 (Codex adversarial、P0-active)**:
  - **TOCTOU lock**: decide guard を非ロック SELECT から **locking guard** (`assert_approval_target_actionable_locked`、
    bound ticket の project row を `TicketRepository.assert_ticket_actionable` 経由で FOR UPDATE lock) へ変更。
    READ COMMITTED 下で「guard が active と読む→concurrent bulk_soft_delete/archive commit→approve UPDATE」の
    競合を、bulk_soft_delete / archive と同じ project lock で直列化 (lock は approval UPDATE commit まで保持)。
    read path (list/detail/MCP) は表示用途で eventual consistency 可のため非ロック helper のまま。test
    `test_approve_guard_acquires_project_lock` (別 session が project lock 保持中は guard が block)。
  - **MCP read path**: HTTP inbox だけでなく P0-active な MCP tool (`bridge_approval_list` / `bridge_approval_show`)
    にも同 active-scope を適用 (stale approval を AI agent から隠す、list 除外 + show not_found、restore で再表示)。
    test `test_mcp_approval_list_show_hide_soft_deleted_ticket`。併せて両関数の pre-existing AttributeError
    (`created_at` / `requester_actor_id` / `decider_actor_id` は ApprovalRequest に存在せず `requested_at` /
    `requested_by_actor_id` / `decided_by_actor_id` が正) を修正 (mypy error 7→3)。
  **残リスク (defer)**: run_id bound (resource_ref 非 ticket) approval への active-scope、approval の
  proactive invalidation (status 遷移) は follow-up。根本解は DB-level enforcement。
- **delegation inbox / accept active-scope** (実装 adversarial R17 #2): parent ticket が delegation_create
  **後**・accept **前** に soft-delete された timing 漏れ (child ticket は active なので従来 accept できた) を塞ぐ。
  `bridge_delegation_inbox` は message の `parent_run_id` / `sender_run_id` が soft-deleted ticket bound の場合
  その message を一覧から除外 (`NOT EXISTS deleted ticket` 相関、static SQL)。`bridge_delegation_accept` は
  consume **前** に message の parent/sender run を fetch し `_assert_run_ticket_actionable` で検証、不一致は
  reject (message 未消費・child は queued のまま)。negative test
  `test_delegation_inbox_accept_reject_deleted_parent`。
  **R22 改善 (Codex adversarial、P0-active)**: R17 の inbox filter は soft-deleted ticket (`deleted_at`) のみ見ており、
  **archived project** (Q-4、`project.status<>'active'`、archive は ticket を soft-delete しない別 state) の
  delegation を除外できず、active で作成後に archive すると stale queued message (artifact_ref / parent_run_id /
  sender_run_id) が inbox に露出して archive freeze invariant を破っていた。`inter_agent_messages.project_id` を
  直接参照する project-active 条件 (`NOT EXISTS projects WHERE status<>'active'`) を inbox SQL に追加 (accept は
  元々 archived guard で reject)。negative test `test_delegation_inbox_accept_excludes_archived_project`
  (archive 後 inbox total=0 + accept ProjectArchivedError + message 未消費)。
  **R23 改善 (Codex adversarial、P0-active)**: R17/R22 の inbox filter は archived project + parent/sender run の
  soft-deleted ticket を見ていたが、inbox の宛先である **child (receiver) run 自体** の ticket soft-delete を
  見ておらず、parent が active (または ticketless) なら child ticket 削除後も stale message が露出していた。
  child_run_id の run→ticket を `agent_runs` + `tickets.deleted_at IS NOT NULL` で除外する NOT EXISTS を inbox SQL に
  追加。negative test `test_delegation_inbox_accept_reject_deleted_child` (child ticket だけ削除 → inbox total=0 +
  accept TicketNotActionableError + message 未消費)。これで inbox active-scope は archived project + parent/sender/
  child の soft-delete を網羅。
- **残リスク (defer): InterAgentPublisherService の run active-scope** (実装 adversarial R17 #3): P0.1
  inter-agent 通信 service (ADR-00018) の `_assert_run_boundary` は tenant/project membership + parent-child
  shape のみ検証し、`soft_deleted_ticket_run_exclusion` / `_assert_run_ticket_actionable` を適用しない。ただし
  本 service は **P0-active な production caller を持たず** (現状 `__init__` export のみ、P0.1 multi-agent
  orchestrator / 専用 test 用)、P0 期間中の delegation P0-active 経路は MCP bridge (R16/R17 で guard 済) に
  限られる。P0.1 で本 service を multi-agent flow へ配線する際に、parent/sender/child run へ同 active-scope
  guard (shared service-level helper) を適用する follow-up。根本解は DB-level enforcement。
- **0040 downgrade fail-closed** (実装 adversarial R14 #2): server-owned `agent_runs.ticket_id` は
  `run_queued` event payload と乖離し得る (column が正本、payload は untrusted)。無条件 drop すると
  rollback→re-upgrade で backfill が event payload しか見ないため、payload 欠落/改ざん/cross-project だった
  run が ticket-less 化し、soft-deleted ticket bound run が集計・操作へ復活する silent resurrection に
  なり得る。よって 0040 downgrade は 0039 と同じ思想で **ACCESS EXCLUSIVE lock 後に全 non-NULL ticket_id が
  canonical run_queued event payload と lossless 一致するか検査** し、1 件でも不一致/欠損があれば
  `RuntimeError` で中断 (column 保持)。**R15 で TOCTOU を補強**: preflight が読む `agent_run_events` も
  `agent_runs` と同一 transaction 内で ACCESS EXCLUSIVE lock し、preflight 通過〜drop_column 間の
  event_payload 差し替え/欠落 (column 喪失 + 改変後 payload からの誤復元) を排除する。migration test
  `test_0040_*` で clean round-trip と乖離時 fail-closed を検証。**残リスク (defer)**: 乖離検出時の
  自動 reconcile / export は手動運用 (drop 前に reconcile or export)。
- **0040 upgrade fail-closed** (実装 adversarial R21、**P0-active**): backfill は canonical run_queued event の
  ticket_id が UUID 形式かつ同一 project ticket に解決できる場合のみ `agent_runs.ticket_id` を設定し、それ以外は
  NULL のまま残す。だが active-scope predicate / run guard は `ticket_id IS NULL` を **ticket-less (可視・進行可)**
  と扱うため、run_queued payload が binding を主張する (UUID 形式) のに cross-project / 不在 / hard-delete で
  解決できなかった run は、soft-delete 後も list/detail/KPI/transition guard から除外されず migration 時点で
  silent resurrection する。downgrade fail-closed と対称に、**upgrade も backfill 後に「binding 主張・復元不能」
  run を count し 1 件でもあれば `RuntimeError` で中断** (alembic transaction rollback で column も付かない)、
  operator に reconcile / export を要求する。payload に ticket_id を持たない genuinely ticket-less run は対象外で
  migration を妨げない。test `test_0040_upgrade_fails_closed_on_unresolvable_binding`。
- **delegation_review reviewer project 境界** (実装 adversarial R14 #1、bounded adopt): `bridge_delegation_review`
  の reviewer lookup を `tenant_id + id` のみから **`tenant_id + project_id (= 対象 run の project) + id`** に
  絞り、cross-project reviewer (同一 tenant 別 project) を `reviewer_not_found` で拒否する (core.md §8 project
  境界、agent_runs は同一 project 内に閉じる)。negative test `test_delegation_review_rejects_cross_project_reviewer`
  で approval_decided event 捏造の不在を検証。**R15 #3 で soft-delete 境界の漏れも補完**: reviewer run **自体**が
  soft-deleted ticket / archived project に bind されていれば `_assert_run_ticket_actionable` で reject する
  (active-scope 外の reviewer identity で approval_decided を捏造させない。例: reviewer run 作成後に bulk
  soft-delete し、新 active ticket/run を立てて古い deleted-ticket-bound reviewer を指定する経路)。negative test
  `test_delegation_review_rejects_deleted_ticket_reviewer`。**残リスク (defer)**: reviewer の **role/scope 検証・
  delegation tree 帰属・requester/implementer との不一致 (self-approval 強化)** は P0.1 multi-agent の
  approval-boundary design (ADR Gate Criteria #4 AI エージェント権限) に該当するため、専用 ADR で設計する
  follow-up。P0 期間中 delegation review は MCP 手動経路に限られ、project 境界 + reviewer actionable +
  self (run_id 一致) guard で最小防御は確保する。
- **delegation_create transaction 直列化** (実装 adversarial R20、**P0-active**): `bridge_delegation_create` は
  `bridge_run_create` で child run を作った後 `inter_agent_messages` を INSERT するが、`bridge_run_create` が
  内部 commit すると `assert_ticket_actionable` の取得した **project FOR UPDATE lock が message INSERT 前に
  解放**され、その隙に concurrent な bulk_soft_delete / archive が割り込んで stale な前提で message を作れる
  TOCTOU (approve guard R19 と同型)。`bridge_run_create` に `commit: bool=True` を追加し、
  `bridge_delegation_create` は `commit=False` で呼んで **child run 作成と message INSERT を同一 transaction・
  同一 project lock 下** で行い、本関数末尾の 1 commit に集約する (lock は commit まで保持、bulk_soft_delete /
  archive と直列化、message 作成失敗時は child run も rollback で orphan を残さない)。lock-contention test
  `test_delegation_create_serializes_under_project_lock` (別 session が project lock 保持中は delegation_create
  が block、解放後は child run + message が atomic に commit)。
- **dogfooding seed CLI の archive/soft-delete 整合** (実装 adversarial R9): `dogfooding_seed.py` は
  直書き (`Ticket(...)` + ORM 直接更新) で repository guard を通らなかった。bounded fix を適用:
  (1) `_query_existing_dogfooding_tickets` に `deleted_at IS NULL` (soft-deleted を「既存 active」扱い
  しない)、(2) apply 時に `assert_project_active(DEFAULT_PROJECT_ID)` で archived なら fail-closed。
  **残リスク (defer)**: seed の create/update を全面的に `TicketRepository` 経由へ寄せる refactor と、
  acceptance_criteria / evidence 等の他 child mutation・他 dev CLI を含む **全 write path の網羅的
  enforcement** は follow-up。根本解は DB-level enforcement (trigger / RLS で archived project への
  child write 拒否 + soft-delete scope を全経路に強制) で、別 ADR で設計する。
- **残リスク (defer): hard-delete primitive** (実装 adversarial R2 #1): `TicketRepository.delete_in_project`
  は soft-delete/audit 契約を bypass する物理削除。現状 production endpoint へ未配線で caller は
  tenant/project boundary 検証用 security/contract test のみ。archive freeze guard は適用済だが、soft-delete
  モデルへの完全統合 (hard delete 撤去 or maintenance-only gate 化) は pre-existing security/contract test に
  依存するため follow-up Sprint へ defer。production endpoint へ配線しないこと。

## rollback 手順 (operation-level fail-closed、Codex plan R3/R4 HIGH)

silent resurrection は `drop_column` 単体だけでなく **rollback の順序** でも起こる (active-scope filter を
先に revert すると、DB downgrade 前の window で soft-deleted が default read path に露出する)。よって
**operation-level で fail-closed** にし、順序と locking を固定する:

1. **maintenance / read-only mode に入る** (child write = ticket create/update/import/bulk-delete を停止)。
   active-scope filter / soft-delete column を消す前に書込を止め、check↔drop 間の race を排除する。
2. **preflight**: `SELECT count(*) FROM tickets WHERE deleted_at IS NOT NULL`。**1 件でも soft-deleted 行が
   あれば rollback 全体を中断**。先に対象 batch を restore (削除意図を解消) するか、運用判断で復活を明示承認
   してから再実行する。**active-scope filter は deleted 行が解消されるか locked downgrade 完了まで live に
   保つ** (filter を先に revert しない)。
3. **migration downgrade は ACCESS EXCLUSIVE lock を取得してから count → drop** (Codex plan R5 HIGH):
   通常 transaction だけでは concurrent UPDATE を排他できないため、**必ず lock-before-count** とする:

   ```sql
   BEGIN;
   LOCK TABLE tickets IN ACCESS EXCLUSIVE MODE;   -- count の前に排他 lock
   -- SELECT count(*) FROM tickets WHERE deleted_at IS NOT NULL; が 0 の場合のみ ↓
   ALTER TABLE tickets DROP COLUMN deleted_at, DROP COLUMN deleted_batch_id, DROP COLUMN deleted_by_actor_id;
   COMMIT;   -- nonzero なら ROLLBACK して中断 (silent resurrection しない)
   ```

   lock 取得後に count するため count↔drop 間に soft-delete が commit されない (TOCTOU 排除)。
   「単一 transaction だけで可」とは読まない。soft-deleted 行が無ければ hard data loss なし。
   migration round-trip テストで **lock 後 count** が実行されることを検証する。
4. downgrade 完了後に backend (active-scope helper / archive guard / endpoint) と frontend を revert、
   maintenance mode 解除。
5. frontend: archive/import/bulk-delete/restore UI を revert (downgrade 後)。

## 実装対象ファイル (design approval 後)

- migration: `tickets` に `deleted_at` / `deleted_batch_id` / `deleted_by_actor_id` nullable column。
- `backend/app/db/models/ticket.py`: 上記 column。
- `backend/app/repositories/ticket.py`: **active-scope helper (全 read path 経由)** + bulk soft-delete (batch) +
  batch restore + import transactional insert。
- `backend/app/api/me.py` or `tickets.py`: archive / bulk-soft-delete / restore / import endpoint +
  全 read path の active scope 適用。
- `backend/app/repositories/ticket.py`: **archived guard を mutation メソッド (create/update/create_in_project)
  に配置** (HTTP / MCP / research promotion の全経路で fail-closed)。
- **非 HTTP mutation 経路の追随**: `backend/app/mcp/api_bridge.py` (ticket create/update)、
  `backend/app/services/research/research_to_ticket.py` (create_in_project) が repository guard 経由で
  archived project を 409 にすることを確認 (実装対象 + test 対象)。
- frontend: 確認 dialog (二段階) + import dry-run preview + archive ボタン + session.ts client。
- tests: 各 endpoint contract + owner gate + tenant/project negative + **全 read path (list/get/count/summary)
  の deleted 除外** + batch restore + import validation/transactional/衝突 + archived guard
  (**HTTP + MCP bridge + research promotion の全経路**) + audit。

## テスト指針

- Q-4: archive/unarchive + CAS mismatch 409 + audit + owner gate + **archived project への child write が 409**。
- Q-3: bulk-soft-delete が batch 発行 + deleted_at set + **list/get/count/summary 全てから除外** +
  batch restore で当該 batch のみ復活 (他 batch 不変) + **cross-project batch_id → 0 rows (越境復活なし)** +
  **再 restore → restored_count=0 (idempotent)** + 二段階確認 + audit (batch_id/件数/project_id、本文なし)。
- Q-2: 全件 validation (不正 1 件で全体 reject) + in-payload slug 重複 reject + 既存 (active/deleted) slug
  衝突 reject + 件数上限 + dry-run が insert しない + transactional (partial write なし) +
  **並行 import の片方が unique violation で全 rollback (DB-level)** + project boundary + audit。
- 全機能 owner gate (authenticated + human + owner)、非 owner/service/agent/provider/github_app → 403。

## DoD (design approval 後の実装で満たす)

- [ ] 全操作が soft / reversible (hard delete なし)。
- [ ] owner gate + 二段階確認 + audit (全破壊的操作)。
- [ ] soft-deleted ticket が **全 default read path (list/get/count/summary/dashboard/KPI)** から漏れない
      (repository-level active scope + 各 path の contract test)。
- [ ] restore は batch 単位 (project 全 deleted の盲目 clear をしない)。
- [ ] archived project への child write (create/update/import/bulk-delete/restore) が 409 で reject。
      guard は `TicketRepository` mutation 境界に置き、**HTTP + MCP bridge + research-to-ticket promotion の
      全経路**が fail-closed (非 HTTP 経路の negative test 含む)。
- [ ] migration downgrade は **LOCK TABLE tickets IN ACCESS EXCLUSIVE MODE の後に count → 0 なら drop**
      (lock-before-count、TOCTOU 排除)。
- [ ] import は全件 validation + all-or-nothing transactional + in-payload/既存 slug 衝突 reject + dry-run +
      件数/size 上限 + 並行 import の片方が DB unique violation で全 rollback。
- [ ] rollback が **operation-level fail-closed**: maintenance/read-only → preflight count (nonzero で中断) →
      lock 下で count 再確認 + drop の順。active-scope filter を deleted 解消/downgrade 完了まで先に revert
      しない (rollback window でも silent resurrection しない)。
- [ ] tenant/project negative test pass。
- [ ] backend ruff/mypy/pytest + frontend tsc/eslint/vitest + migration round-trip。
- [ ] Codex adversarial review clean (CRITICAL=0 / HIGH≤2)。
