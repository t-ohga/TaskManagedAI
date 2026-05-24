---
id: "ADR-00024"
title: "Project Auto-Discovery + Memory Boundary: cross-project retrieval deny-by-default + ContextSnapshot 10 列 を memory が上書きしない invariant"
status: "accepted"
date: "2026-05-15"
updated_at: "2026-05-24"
accepted_at: "2026-05-24"
authors:
  - "t-ohga"
related_sprints:
  - "SP-016_ui_cli_parity"
  - "SP-018_hermes_memory_integration"
supersedes: null
superseded_by: null
acceptance_history:
  - "2026-05-15: proposed during QL-G Quality Loop run as the project auto-discovery + memory boundary ADR."
  - "2026-05-24: accepted at SP018-T01 ADR readiness gate. SP-016 CLI context safety is completed, SP-018 plan-only gate exists, and the schema guidance was reconciled to artifact-bound storage (`content_artifact_ref` + `content_hash`) instead of raw `redacted_content` JSONB."
---

最終更新: 2026-05-24 (SP018-T01 ADR readiness gate で accepted promotion、`content_artifact_ref` 正本へ drift 修正)

## 背景

- 決定対象: CLI ContextResolver による project auto-discovery (`docs/cli/README.md §3` state machine) と memory backend (history / preference / cache / retrieval) の **boundary 物理分離** を定義する。**cross-project retrieval を deny-by-default** + **ContextSnapshot 10 列を memory が上書きしない** 2 invariant を本 ADR で固定。
- 関連 Sprint: SP-016_ui_cli_parity で CLI context safety の placeholder marker を解決済み。SP-018_hermes_memory_integration で memory backend を実装する。本 ADR の accepted は boundary decision の確定であり、DB/API/runtime 実装完了を意味しない。
- 前提 / 制約:
  - **`.claude/CLAUDE.md §2 #10` invariant 維持**: tenant/project boundary を memory cross-project retrieval で破らない (deny-by-default)
  - **`.claude/CLAUDE.md §2 #9` invariant 維持**: ContextSnapshot 必須 10 列 を memory/realtime/provider continuation で上書きしない、supplement は別 metadata
  - **ADR Gate Criteria 11 種**: 本 ADR は #2 (DB schema、memory_records table)、#3 (API 契約、memory retrieval endpoint)、#4 (AI agent 権限、memory-derived prompt input は untrusted)、#9 (広範囲 refactor) を trigger。**break-glass 対象外** (`.claude/rules/sprint-pack-adr-gate.md` §11)
  - **R29 plan §3.2 P-07 + §3.3 D-08 統合**: P-07 (project auto-discovery + memory boundary) + D-08 (memory bank / always-on memory P0.1+ defer) を本 ADR で 1 statement に統合、U-07 確定後の implementation Sprint Pack で本 ADR と SP-018 を cross-reference

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: deny-by-default + 別 metadata (採用) | cross-project retrieval deny-by-default、ContextSnapshot 10 列を memory が上書きしない、memory-derived prompt input は untrusted_content trust_level、memory backend は別 table + 別 API | tenant/project boundary 不変 + ContextSnapshot 不変、memory 経由の AI 出力直結 (`.claude/CLAUDE.md §2 #1`) も遮断 | memory retrieval 単独で AI prompt enrichment できない (boundary check 必要)、user 設定で per-project / per-repo memory enable は別 API call が必要 |
| B: project_id ベース admit list | memory retrieval を project_id ベース admit list で許可 (denylist より緩い) | 柔軟、user 設定で project 間 memory 共有可 | cross-project boundary 違反のリスク高、admin が誤って 全 project admit すると cross-tenant leakage 可能性 |
| C: ContextSnapshot overlay | ContextSnapshot 10 列を memory が override / extend、AI run 中の context が dynamic に拡張 | retrieval 経由で AI 性能向上 | ContextSnapshot 10 列 invariant 違反、`.claude/CLAUDE.md §2 #9` 不変条件 違反、再現性 contract 破綻 |
| D: 完全 reject (memory backend 実装しない) | memory 機能を P1+ で完全 reject、CLI context safety のみ ADR-00015 + docs/cli/README.md で扱う | ADR 起票コストゼロ | user 要求 (history / preference / 簡易 cache) を満たさない、CLI 経由の `~/.taskmanagedai/profile.yaml` 等は CLI 内部実装で扱う必要 |

## 採用案

- 採用: **A: deny-by-default + 別 metadata**。
- 理由:
  - `.claude/CLAUDE.md §2 #10` invariant (cross-project deny-by-default) を本 ADR で memory 経路にも明示適用
  - `.claude/CLAUDE.md §2 #9` invariant (ContextSnapshot 10 列を memory が上書きしない) を本 ADR で明示固定
  - memory-derived prompt input を `untrusted_content` trust_level (ADR-00014 §11 / `.claude/rules/ai-output-boundary.md` 準拠) として扱い、`.claude/CLAUDE.md §2 #1` (AI 出力直結禁止) も遮断
  - memory backend を **別 table + 別 API + 別 retrieval pipeline** で物理分離、CLI ContextResolver (docs/cli/README.md §3) と memory backend は **CLI context resolution complete 後にのみ memory retrieval が走る** 順序を enforce
- 実装 Sprint: SP-018_hermes_memory_integration。SP018-T01 で本 ADR を accepted 化し、runtime 実装は SP-018 T02+ の別 PR で行う。
- 実装対象ファイル (SP-018 T02+ implementation batch):
  - `backend/app/db/models/memory_record.py` (新規、memory_records table)
  - `backend/app/services/memory/retrieval.py` (新規、retrieval pipeline + cross-project deny check)
  - `backend/app/services/memory/context_snapshot_overlay_guard.py` (新規、ContextSnapshot 10 列 read-only enforcement)
  - `backend/app/api/memory.py` (新規、memory retrieval endpoint)
  - `migrations/versions/00NN_p0_1_memory_records.py` (ADR Gate Criteria #2 trigger)
  - `frontend/app/(admin)/memory-settings/` (per-project memory enable/disable UI)
  - `taskmanagedai-cli/src/memory/profile.ts` (CLI profile cache、project boundary 維持)
  - `tests/memory/test_cross_project_retrieval_deny.py` (negative test、本 ADR §不変条件 #1)
  - `tests/memory/test_context_snapshot_overlay_guard.py` (negative test、本 ADR §不変条件 #2)
- 実装ガイダンス:
  - memory_records schema (P0.1 SP-018 で実装):
    ```yaml
    memory_record:
      memory_record_id: uuid
      tenant_id: bigint NOT NULL DEFAULT 1
      project_id: uuid NOT NULL  # cross-project deny の DB level enforce
      record_kind: enum {manual_user, manual_agent, auto_completion, auto_failure, auto_review_finding}
      content_artifact_ref: string  # redacted memory content artifact reference
      content_hash: string  # sha256 of redacted artifact content
      data_class: enum {public, internal, confidential, pii}
      redaction_status: enum {redacted, raw_with_canary_scan_passed}
      sanitizer_version_id: uuid  # FK to sanitizer_policy_versions
      created_at: timestamp
      archived_at: timestamp | null
      retention_until: timestamp  # retention policy enforcement
      trust_level: enum {untrusted_content, validated_artifact}  # default untrusted_content; self-promotion forbidden
      
    # 複合 FK で project boundary を物理 enforce
    foreign key (tenant_id, project_id) references projects(tenant_id, id)
    ```
  - retrieval pipeline:
    ```
    Entry: CLI command or AI agent retrieval request
    
    Step 1: CLI ContextResolver で project_id 確定 (docs/cli/README.md §3 state machine)
    Step 2: project_id を retrieval filter として WHERE 句に enforce (`WHERE project_id = :resolved_project_id`)
    Step 3: cross-project query 試行は service layer で reject (project_id list mismatch detection)
    Step 4: retrieved content は untrusted_content trust_level で AI prompt input に inject (validated_artifact 昇格は human approval 経由のみ)
    Step 5: ContextSnapshot 10 列は read-only、memory retrieval は別 metadata (supplement_metadata) として記録、overlay 不可
    ```
  - 不変条件:
    1. **cross-project retrieval deny-by-default**: project_id mismatch を service layer + DB level (RLS-ready) + Pydantic validator + pytest negative test の 4 重防御で reject (`.claude/rules/cross-source-enum-integrity.md §2` 5+ source pattern)
    2. **ContextSnapshot 10 列 read-only**: memory retrieval が ContextSnapshot 10 列 (`prompt_pack_version` / `prompt_pack_lock` / `policy_version` / `policy_pack_lock` / `repo_state` / `tool_manifest` / `evidence_set_hash` / `provider_continuation_ref` / `provider_request_fingerprint` / `snapshot_kind`) を override しない、supplement は `context_snapshot_supplement_metadata` 別 jsonb 列
    3. **memory-derived prompt input は untrusted_content**: ADR-00014 §11 trust_level taxonomy + `.claude/rules/ai-output-boundary.md` §5 Input Trust Layer と整合、`validated_artifact` 昇格は human approval 経由のみ
    4. **CLI ContextResolver 完了後にのみ memory retrieval**: docs/cli/README.md §3 state machine の resolve_complete 後にのみ memory retrieval を invoke、fail-closed 経路 (ambiguous project) では memory retrieval も deny
    5. **retention policy**: memory_records.retention_until 経過後は scheduled deletion (P0.1 SP-018 で実装)、tenant/project boundary 維持して deletion
- テスト指針:
  - cross-project retrieval deny 4 重防御 (service layer reject / DB level WHERE filter / Pydantic project_id mismatch reject / pytest negative test)
  - ContextSnapshot 10 列 read-only enforcement (memory retrieval が overlay 試行 → reject)
  - memory-derived prompt input の trust_level enforcement (untrusted_content default、validated_artifact 昇格は human approval 経由のみ)
  - CLI ContextResolver fail-closed → memory retrieval も deny (順序 invariant)
  - retention_until 経過後の scheduled deletion (tenant/project boundary 維持)
- ADR Gate Criteria 該当: #2 (DB schema) 主、#3 (API endpoint) + #4 (AI agent 権限、untrusted_content) + #9 (広範囲 refactor) を補助。

## 却下案

- **B (project_id ベース admit list)**: cross-project boundary 違反のリスク高、admin 誤設定で cross-tenant leakage 可能性。`.claude/CLAUDE.md §2 #10` invariant 違反。
- **C (ContextSnapshot overlay)**: `.claude/CLAUDE.md §2 #9` invariant (ContextSnapshot 10 列 不変) 違反、再現性 contract 破綻。
- **D (memory backend 完全 reject)**: user 要求 (history / preference / 簡易 cache) を満たさない、SP-018 (Hermes/memory sprint、R29 plan §10.4/§12 予約済) と矛盾。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| cross-project retrieval が service layer bypass で発生 | `tests/memory/test_cross_project_retrieval_deny.py` 4 重防御 negative test | service layer (Pydantic project_id mismatch reject) + DB level (WHERE project_id filter + 複合 FK) + RLS-ready metadata + pytest negative test の 4 重防御 |
| ContextSnapshot 10 列が memory overlay で上書き | `tests/memory/test_context_snapshot_overlay_guard.py` negative test | memory retrieval は `context_snapshot_supplement_metadata` 別 jsonb 列のみ書き込み、10 列への direct write は service layer で reject |
| memory-derived prompt input が AI agent で trusted_instruction として扱われ AI 出力直結 | `tests/policy/test_trust_level_promotion.py` (既存) | memory retrieval 経由 input は `trust_level=untrusted_content` default、`validated_artifact` 昇格は human approval 経由のみ (ADR-00014 §11 + .claude/rules/ai-output-boundary.md §5) |
| CLI ContextResolver ambiguous + memory retrieval が fall-through 実行 | `tests/cli/test_memory_retrieval_context_dependency.py` | CLI ContextResolver fail-closed (ambiguous / unresolved) なら memory retrieval も deny、docs/cli/README.md §3 state machine の resolve_complete check を retrieval pipeline 起動条件にする |
| retention_until 経過後 deletion が cross-tenant に波及 | `tests/memory/test_retention_deletion_boundary.py` | scheduled deletion job は tenant_id + project_id filter で実行、cross-tenant deletion path は存在しない (DB level + service layer 2 重防御) |
| Hermes (SP-018) との integration で memory backend 重複 | SP-018 + 本 ADR cross-reference | 本 ADR は memory_records schema + retrieval pipeline + boundary invariant を定義、Hermes integration は SP-018 implementation で別 ADR (ADR-00016 既存) と統合 |
| ADR accepted が runtime wiring 完了と誤読される | SP-018 Review / acceptance_history / implementation PR gate | 本 ADR の accepted は boundary decision のみ。DDL/API/runtime は SP-018 T02+ の別 PR で、migration round-trip + negative tests PASS 後に進める |

## rollback 手順

### 運用 rollback (memory backend の問題発見、P0.1+ accepted 後)

1. 全 `memory_records.retention_until` を `now() + interval '0 seconds'` に強制 update → scheduled deletion job が全 record 削除 (ただし audit_events table の memory_retrieval_event は append-only 維持、historical record は残る)
2. memory retrieval endpoint を `feature_flag=disabled` で immediate disable、CLI memory commands も同 flag で disable
3. AgentRun 中の memory-derived prompt input は trust_level=untrusted_content default なので、disable 後の新 AgentRun は memory なし状態で続行可能 (既存 AgentRun は ContextSnapshot から再 build)

### Migration rollback (DB schema 変更時、`memory_records` table 追加時)

1. migration 適用前に `pg_dump` で full DB backup を取得、age で暗号化して別ボリュームに保存
2. staging DB で `uv run alembic upgrade head`、`alembic check`、cross-project deny + ContextSnapshot read-only invariant の 4 重防御 test を先行実行
3. production migration 後に cross-project query が deny されない / ContextSnapshot 10 列が overlay 可能 / trust_level default が `untrusted_content` 以外、のいずれかを検出したら rollback trigger
4. `uv run alembic downgrade -1` で memory_records table drop、または forward-fix migration で boundary invariant を enforce してから production 適用
5. rollback verification: `uv run pytest tests/memory/test_cross_project_retrieval_deny.py tests/memory/test_context_snapshot_overlay_guard.py tests/memory/test_retention_deletion_boundary.py -q`

### ADR-00024 自体の rollback (accepted → superseded / rejected)

本 ADR の accepted boundary を取り下げる場合 (例: memory 機能を P1+ scope 外と決定):

1. `status: rejected` に変更、`superseded_by` に代替 ADR を記録 (例: ADR-00030 候補 memory P1+ defer)
2. SP-018_hermes_memory_integration を P1+ 全面 defer
3. SP-016 `<!-- ADR-00024 placeholder -->` marker を「ADR-00024 rejected、memory backend は P1+」と更新
4. docs/cli/README.md §1 #5 + §9 placeholder reference を rejected 状態に更新

## 関連 ADR

- ADR-00014 (Multi-Agent Orchestration、accepted): 本 ADR の memory-derived prompt input の trust_level taxonomy (untrusted_content / validated_artifact / trusted_instruction) は ADR-00014 §11 と整合
- ADR-00016 (Hermes integration、accepted): 本 ADR は memory_records schema + retrieval pipeline + boundary invariant を定義、Hermes integration は ADR-00016 と統合 (SP-018 で実装)
- ADR-00015 (UI/CLI parity、accepted) + QL-F update: 本 ADR の CLI ContextResolver 順序 invariant (resolve_complete 後にのみ memory retrieval) と整合
- SP-016_ui_cli_parity: 本 ADR で `<!-- ADR-00024 placeholder -->` marker を解決
- SP-018_hermes_memory_integration: 本 ADR accepted 後の memory backend 実装先

## 関連資料

- `docs/設計検討/修正まとめ統合計画.md §5 QL-G` (R29 plan、本 ADR の source spec)
- `docs/設計検討/修正まとめ統合計画.md §3.2 P-07` (Project auto-discovery + memory boundary)
- `docs/設計検討/修正まとめ統合計画.md §3.3 D-08` (memory bank / always-on memory P0.1+ defer、本 ADR で統合)
- `docs/設計検討/修正まとめ統合計画.md §2 #9` (ContextSnapshot 10 列 不変)
- `docs/設計検討/修正まとめ統合計画.md §2 #10` (tenant/project boundary deny-by-default)
- `.claude/rules/cross-source-enum-integrity.md` (4 重防御 + 5+ source 整合 pattern)
- `.claude/rules/ai-output-boundary.md §5` (Input Trust Layer、untrusted_content default)
- `docs/cli/README.md §3` (CLI ContextResolver state machine、本 ADR §採用案 retrieval pipeline の prerequisite)
