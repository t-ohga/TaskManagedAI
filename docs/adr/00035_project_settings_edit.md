---
id: "ADR-00035"
title: "プロジェクト設定編集機能 (M-3: name/description + autonomy_level UI)"
status: "accepted"
date: "2026-05-28"
deciders: ["t-ohga"]
adr_gate_criteria: [2, 3, 4, 8]
related_adr:
  - "ADR-00025 (autonomy policy profiles)"
---

# ADR-00035: プロジェクト設定編集機能 (M-3)

## 背景

UI 改善計画 M-3「設定ページ編集機能」を実装する。現状 `/settings` (`frontend/app/(admin)/settings/page.tsx`)
は全て read-only で、Provider Compliance Matrix / policy profile / repository binding を静的表示するのみ。

ユーザーは「プロジェクト基本情報 (name/description) + autonomy_level + policy_profile を編集可能に」を要望。
ただし設定項目の多くは P0 invariant で保護されており、編集可能範囲は限定される。

ADR Gate Criteria #3 (API 契約: 新 project 更新 endpoint) + #4 (AI エージェント権限: autonomy_level の
UI 露出) + #2 (DB schema: projects.description 追加) + #8 (migration) に該当。

**調査済の重要事実 (Codex plan review R1 反映)**: `projects` テーブル / `Project` model には現状
`description` カラムが**存在しない** (columns: id / workspace_id / slug / name / status / policy_profile /
autonomy_level / metadata_)。`ProjectListItem` schema にも description なし。よって description 編集には
nullable column 追加 (A-7 と同じ低リスク pattern) が必要。

## 決定対象

`/settings` ページに以下の編集機能を追加する:

1. **プロジェクト基本情報 (name / description)** — 編集可能。
2. **autonomy_level (L0-L3)** — 編集可能 (既存 backend endpoint を UI に接続)。
3. **policy_profile** — **read-only 導出表示** (autonomy_level から server-resolve、独立編集は不可)。

## 前提 / 制約 (調査済 invariant)

- **policy_profile は 100% server-owned**。`ProjectAutonomySettingsService` が autonomy_level から
  `resolve_autonomy_policy_profile()` で導出し、現状は常に `"default"` (L0-L3 matrix は Policy Engine が
  profile の上に適用)。`ProjectRepository._reject_caller_supplied_policy_controls()` が caller payload の
  `policy_profile` / `autonomy_level` を signature レベルで拒否。
  → **policy_profile を UI から独立選択させる設計は禁止** (server-owned-boundary + rendering.md §6
  「UI は policy override を直接提供しない」)。M-3 では導出値を read-only 表示する。
- **autonomy_level** の更新は既存 endpoint `PATCH /api/v1/me/projects/{project_id}/autonomy`
  (`ProjectAutonomySettingsUpdate`, extra forbid) 経由のみ。`task_write` capability gate + actor/tenant
  解決済。policy_profile は同 service が server-resolve。
- **name** は `ProjectRepository.update()` で更新可 (policy_profile/autonomy_level は reject)。**description は
  カラム未存在** → nullable `description` column を追加してから更新対象にする。汎用 project PATCH の REST
  endpoint は未実装 → 新規追加が必要。
- server-owned-boundary §1: `tenant_id` / `workspace_id` / `created_by` / `policy_profile` /
  `autonomy_level` (generic 経路) は caller 編集不可。`name` / `description` のみ caller 編集可。
- audit: 現状 autonomy_level 変更に audit event なし (gap)。`audit_events.event_type` は free text
  (CHECK なし)。tickets が `ticket_created`/`ticket_updated` を使うのと同様 `config_changed` を使う。
- **audit payload はユーザー自由入力値 (name/description の本文・旧新値) を永続化しない** (Codex plan
  review R1 P2 反映)。既存 ticket 更新 audit が `updated_fields` のみ残し本文値を避ける境界に合わせ、
  `config_changed` payload は `changed_fields` (フィールド名リスト) のみとする。description は秘密情報や
  長文を含みうるため raw 値を audit に残さない (secretbroker-boundary §11 整合)。

## 選択肢

1. **name/description 専用 PATCH endpoint + 既存 autonomy endpoint UI 接続 + policy_profile 導出表示 (採用)**:
   invariant 完全準拠。policy_profile は server-owned のまま、autonomy_level 経由で間接制御。
2. policy_profile を UI から直接選択可能にする: server-owned-boundary + rendering.md §6 違反。**却下**。
3. 汎用 PATCH /projects/{id} で name/description/autonomy_level を一括更新: autonomy_level は専用 service
   経由が必須 (ProjectRepository が reject)。一括 endpoint で autonomy を扱うと境界が崩れる。**却下**。

## 採用案

### A0. projects.description カラム追加 (migration)

```sql
ALTER TABLE projects ADD COLUMN description text NULL;
```

- nullable text (既存 row 無影響、backfill 不要、rollback=drop_column)。A-7 と同じ低リスク pattern。
- `Project` model に `description: Mapped[str | None]`、`ProjectListItem` schema に `description: str | None`。

### A. name/description 更新 endpoint (新規)

```
PATCH /api/v1/me/projects/{project_id}/profile
body: { name?: str (min 1), description?: str | null }  # extra="forbid"
```

- `ProjectRepository.update(tenant_id, id, {name?, description?})` 経由。policy_profile/autonomy_level は
  payload に含めない (含めれば repository が reject)。
- 空の更新 (両方 unset) は 400。
- server 側で actor/tenant 解決、commit。
- 成功時 `config_changed` audit event。**event_payload は `changed_fields` (フィールド名のソート済リスト)
  のみ** + project_id + actor。**name/description の本文・旧新値は payload に含めない** (P2 反映)。
- response: 更新後 ProjectListItem (description 含む)。

### B. autonomy_level 編集 UI (既存 endpoint 接続 + audit 追加)

- 既存 `PATCH /api/v1/me/projects/{project_id}/autonomy` を frontend から呼ぶ (L0-L3 selector)。
- **追加**: autonomy endpoint で `config_changed` audit event を emit。autonomy_level は enum (L0-L3) で
  自由入力ではないため、`changed_fields=["autonomy_level"]` + 旧→新 autonomy_level + resolved
  policy_profile + reason_code を payload に残してよい (enum 値は秘密情報でない)。現状の audit gap を埋める。
  audit は **実遷移時のみ** 記録する (previous == new の no-op / retry では記録しない)。row lock
  (`SELECT ... FOR UPDATE`) で旧値取得を直列化し、並行更新でも audit が実遷移と 1:1 対応する。
- UI には L0-L3 の意味 (AI 自律レベル) を明示。policy_profile は導出値として read-only 表示。

### B-1. autonomy_level の compare-and-swap (adversarial review R7-R9 で追加)

autonomy_level は AI 権限制御 (Gate #4) であり、stale な baseline からの **re-escalation** を防ぐため
optimistic concurrency (compare-and-swap) を **必須** で追加する:

- `ProjectAutonomySettingsUpdate.expected_autonomy_level: AutonomyLevel` を **required** にする。caller が
  「編集の基にした現在値」を宣言する concurrency token (If-Match 相当)。**authority 値ではない** ため
  server-owned-boundary に反しない (server が実値を所有し、caller は期待値を申告するのみ)。required に
  することで「expected を省略して CAS をすり抜ける」経路 (R8: CLI / 旧 client) を塞ぐ。
- CAS は **実際の mutation 境界である `ProjectAutonomySettingsService.update_autonomy_level` で強制** する
  (R9)。service は `expected_autonomy_level` を必須引数に持ち、row lock (`FOR UPDATE`) 後の current と
  比較して不一致なら `AutonomyExpectationMismatch` を raise する。endpoint はこの単一 CAS writer に委譲し、
  例外を **409 Conflict**、None を 404 に写像する。endpoint 側に CAS を二重実装せず、内部 caller (将来の
  MCP / job) が service を直接使っても CAS をすり抜けられない (no-CAS writer を production path から排除)。
- service は実遷移有無を `changed` で返し、endpoint は **実遷移時のみ** `config_changed` audit を記録する
  (no-op / retry では残さない)。AI 権限の audit は実遷移と 1:1 対応する。
- frontend: autonomy selector を controlled state にし、server 値 (prop) が変わったら state を同期して
  未保存の stale 選択を破棄する (refresh / 別タブ更新後の stale DOM 再送を client 側でも防ぐ)。hidden field
  で baseline (expected) を常に送る。CLI は `--expected-level` を必須フラグにする。基本情報フォーム
  (name / description) も touched-field のみ送信し、未編集 field で他方の更新を巻き戻す lost update を防ぐ。

### C. frontend

- `/settings` に「プロジェクト基本情報」編集フォーム (name/description) を追加 (Server Action 経由、
  FastAPI endpoint へ)。
- autonomy_level の L0-L3 selector + 現在値表示 + 導出 policy_profile の read-only 表示。
- `frontend/lib/api/` に projects settings client (read + update) を追加。
- 既存 hardcoded `POLICY_PROFILES` (sprint9-admin-ui) は backend enum (default / low_risk_auto_allow) と
  drift しているため、policy_profile 表示は backend 由来の実値に寄せる。

## 却下案

- policy_profile UI 直接選択 (選択肢 2): invariant 違反。
- 汎用一括 PATCH (選択肢 3): autonomy_level 専用 service 境界を壊す。

## リスク

- MEDIUM-HIGH (autonomy_level は AI 権限制御、ADR Gate #4)。
- autonomy_level を UI から変更可能にすることで、ユーザーが AI 自律レベルを self-service で変更できる。
  P0 は個人専用 (owner = user) のため self-service は許容。ただし変更は必ず `config_changed` audit に残す。
- policy_profile を誤って編集可能にすると policy enforcement を迂回する重大リスク → read-only 導出に限定し
  signature レベルで caller 入力を排除 (既存 ProjectRepository reject + ProjectAutonomySettingsUpdate
  extra forbid を維持)。
- name/description は低リスク (表示用メタデータ)。
- audit gap 解消により autonomy 変更の traceability が向上。

## rollback 手順

1. frontend: /settings の編集フォーム / selector を revert (read-only に戻す)。
2. backend: 新規 `PATCH .../profile` endpoint を削除。autonomy endpoint の audit 追加分を revert。
   `Project` model / `ProjectListItem` schema の `description` 参照を revert。
3. DB: `uv run alembic downgrade -1` で migration `0038_*` を戻す (`drop_column projects.description`)。
   description は nullable 追加カラムのため data loss は description 値のみ (他カラム・他テーブル無影響)。

## 実装対象ファイル

- `migrations/versions/0038_*.py`: projects.description nullable column 追加 (revision ID ≤ 30 chars)。
- `backend/app/db/models/project.py`: `description: Mapped[str | None]`。
- `backend/app/api/me.py`: ProjectListItem に description 追加 + name/description PATCH endpoint 追加 +
  autonomy endpoint に audit 追加。
- backend: `config_changed` audit emit (name/description = changed_fields のみ、autonomy = 値含む)。
- `frontend/lib/api/projects.ts` (新規 or 既存): settings read + update client。
- `frontend/app/(admin)/settings/page.tsx` + `_components`: 編集フォーム + autonomy selector + policy_profile
  read-only 表示。
- `frontend/app/(admin)/settings/actions.ts` (新規): Server Action。
- tests: migration round-trip + backend endpoint contract (name/description update + audit changed_fields
  のみ + caller-supplied reject negative + autonomy audit) + frontend vitest (form / selector /
  policy_profile read-only)。

## テスト指針

- name/description PATCH 成功 + 更新後値検証 + `config_changed` audit 記録。
- caller が policy_profile / autonomy_level を name/description endpoint に smuggle → reject (negative)。
- autonomy_level 変更で policy_profile が server-resolve され、audit に旧→新が残る。
- cross-tenant / cross-project の負例 (project boundary)。
- frontend: 編集フォームの送信 → Server Action → API、policy_profile が read-only (編集 UI を持たない) こと。
- raw secret が audit payload に出ないこと (assert_no_raw_secret 相当)。

## DoD

- [ ] name/description 編集が動作し audit に残る。
- [ ] autonomy_level 編集が既存 service 経由で動作し audit に残る。
- [ ] policy_profile は read-only 導出表示で、編集経路が UI/API に存在しない。
- [ ] server-owned-boundary negative test pass。
- [ ] backend ruff/mypy/pytest + frontend tsc/eslint/vitest pass (A-7 同様、pre-existing 債務は除く)。
