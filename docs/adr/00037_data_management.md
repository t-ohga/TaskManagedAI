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
