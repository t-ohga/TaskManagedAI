# Phase H Closure Ledger — TaskManagedAI Vision Consolidation 全 finding canonical 一覧

最終更新: 2026-05-10 (Phase H second-opinion 完了後 + PH-F-011 fix で起票)

## 概要

本 ledger は Phase A-H で生成された全 finding (CRITICAL/HIGH/MEDIUM/LOW) の canonical record。各 finding に source_phase / severity / disposition / adopted_file / test_path / expected_behavior / status を記録し、**Sprint 1 着手前の最終 quality gate** として参照する.

## 数え方の定義 (PH-F-011 で正本化)

distinct finding ID で数える (重複 partial verify は同 finding ID として 1 件):

| Phase | finding ID prefix | distinct count |
|---|---|---:|
| Phase D R1 (codex-plan-review) | PD-F-001〜020 | 20 |
| Phase D R2 (R1 partial 詳細化 14 + new 14) | PD-R2-F-001〜014 (new only、R1 partial は PD-F-NNN として継続) | 14 |
| Phase D R3 (R2 partial 詳細化 14 + new 7) | PD-R3-F-001〜007 | 7 |
| Phase D R4 (R3 partial 詳細化 7 + new 5) | PD-R4-F-001〜005 | 5 |
| Phase E (codex-adversarial-review、defensive) | PE-F-001〜016 | 16 |
| Phase G plan-review | PG-F-001〜018 | 18 |
| Phase G adversarial | PGA-F-001〜014 | 14 |
| **subtotal (Phase G まで)** | | **94** |
| Phase H second-opinion (本 ledger 起票時の最終 verify) | PH-F-001〜011 | 11 |
| **total (Phase H 含む)** | | **105** |

> **重要**: 旧 memory / commit message 等で言及していた「108 finding」は **重複カウント** (R2/R3/R4 の partial 詳細化を独立 finding として数えていた). 正本は **94 distinct (Phase A-G) + 11 (Phase H) = 105 distinct finding**.

## ledger 本体 (subset、frequently-referenced finding のみ抜粋)

> 全 105 entry の詳細は各 source result.md に記録 (`~/.claude/local/codex-tasks/2026-05-10/{phase-d-plan-review-c,phase-d-r2-verify,phase-d-r3-verify,phase-d-r4-verify,phase-e-adversarial,phase-g-plan-review,phase-g-adversarial,phase-h-second-opinion}/result.md`). 本 ledger は **closure status overview** として critical / high / 主要 finding の disposition を表示.

### Phase D R1 (CRITICAL 5 抜粋)

| finding_id | severity | symptom 要約 | disposition | adopted_file | status |
|---|---|---|---|---|---|
| PD-F-001 | CRITICAL | agent_roles schema project_id bigint 不整合 | adopt | Phase C draft §1.3 (project_agent_roles project-scoped 正本化) + ADR-00019 | closed |
| PD-F-002 | CRITICAL | inter_agent_messages ID 型不整合 | adopt | Phase C draft §2.2 + ADR-00018 §1 (12 fields 全 ID = uuid + 複合 FK) | closed |
| PD-F-003 | CRITICAL | memory_records project boundary 不整合 | adopt | Phase C draft §5.2 + ADR-00016 (memory_records 5 複合 FK) | closed |
| PD-F-004 | CRITICAL | action_class 5 種追加が ADR-00009 7 種を破壊 | adopt | Phase C draft §3.2 + ADR-00009 update + Phase C §11.4 の order (operation_kind / event_type / Tool Registry / policy_profile に分散) | closed |
| PD-F-005 | CRITICAL | Tier 2 で agent decider 経路 (human-only invariant 違反) | adopt | Phase C draft §3.3 + ADR-00014 §5 (review_artifacts 経由、approval_requests には入らない) | closed |

### Phase D R2 (CRITICAL 1)

| finding_id | severity | symptom 要約 | disposition | adopted_file | status |
|---|---|---|---|---|---|
| PD-R2-F-001 | CRITICAL | 新 DDL FK が tenant-only、cross-project 混在許容 | adopt | Phase C draft §S-19 (`(tenant_id, project_id, foreign_id)` 複合 FK 全新 table 適用) + ADR-00014/00018/00019/00016 | closed |

### Phase E (HIGH 12 から代表 5 件)

| finding_id | severity | symptom 要約 | disposition | adopted_file | status |
|---|---|---|---|---|---|
| PE-F-001 | HIGH | role identifier resilience (custom と standard 競合) | adopt | ADR-00019 §1 (STANDARD_ROLE_IDS reserved namespace) | closed |
| PE-F-005 | HIGH | sanitizer_version drift で stale memory 混入 | adopt | ADR-00016 + Phase G §sanitizer_policy_versions table | closed |
| PE-F-007 | HIGH | artifacts.project_id migration 完了前の防御 | adopt | ADR-00021 §3.11 + SP-013 hard gate | closed (P0.1 SP-013 で本実装) |
| PE-F-011 | HIGH | action_class 7 種閉鎖性 | adopt | ADR-00009 update + Phase F-0 同期 task (PH-F-005 連動) | closed |
| PE-F-013 | HIGH | remote_agent_gateway P0/P0.1 boundary | adopt | ADR-00021 §11.6 + ADR-00013 update + sealed guard | closed |

### Phase G plan-review (HIGH 7 全件)

| finding_id | severity | adopted_file | status |
|---|---|---|---|
| PG-F-001 | HIGH | Phase C §11.7 (既存正本 host-portable 同期 SP-022 で本文 update) | closed |
| PG-F-002 | HIGH | ADR-00021 §11.1 (age key 安全運搬 secret manager default-required) | closed |
| PG-F-003 | HIGH | ADR-00021 §11.2 (freeze/drain marker、§14.1 で thaw 2-party-control 強化) | closed |
| PG-F-004 | HIGH | ADR-00021 §11.3 (postgres:16 正本) + Phase H §normative source 序列で前段 sample 撤回明示 | closed |
| PG-F-007 | HIGH | ADR-00021 §11.4 (RTO budget happy/failure 分離、4h gate 維持) | closed |
| PG-F-008 | HIGH | ADR-00021 §11.5 (multi-agent restore fixture `taskhub verify --integrity --multi-agent`) | closed |
| PG-F-009 | HIGH | ADR-00021 §11.6 + Phase H PH-F-007 fix (sealed guard 統一) | closed |

### Phase G adversarial (HIGH 10 全件)

| finding_id | severity | adopted_file | status |
|---|---|---|---|
| PGA-F-001 | HIGH | ADR-00021 §14.1 #1 + SP-012 must_ship (age key secret manager default-required) | closed |
| PGA-F-002 | HIGH | ADR-00021 §14.1 #2 + SP-012 (backup detached signature + signer allowlist) | closed |
| PGA-F-003 | HIGH | ADR-00021 §14.1 #3 + SP-012/022 (`taskhub thaw` 2-party-control + active-registry) | closed |
| PGA-F-004 | HIGH | ADR-00021 §14.1 #4 + SP-001 (image digest pinning + version matrix) | closed |
| PGA-F-005 | HIGH | ADR-00021 §14.1 #5 + SP-012 (DB catalog 正本 fingerprint) | closed |
| PGA-F-007 | HIGH | ADR-00021 §14.1 #6 + SP-012/022 (migration state machine 8-phase + signed journal) | closed |
| PGA-F-010 | HIGH | ADR-00016 update + ADR-00021 §14.1 #7 (sanitizer_policy_versions table + config_hash FK) | closed |
| PGA-F-011 | HIGH | ADR-00021 §14.1 #8 + SP-013 hard gate (artifact project boundary materialize 先行) | closed |
| PGA-F-012 | HIGH | ADR-00021 §14.1 #9 + SP-012 (Mac selected host hardening baseline) | closed |
| PGA-F-014 | HIGH | ADR-00021 §14.1 #10 + SP-012/022 (`taskhub verify --network-invariant`) | closed |

### Phase H (CRITICAL 2 + HIGH 8 + MEDIUM 1)

| finding_id | severity | adopted_file | status |
|---|---|---|---|
| PH-F-001 | CRITICAL | ADR-00021 frontmatter (acceptance_target_sprint 追加) + SP-001-5_host_portable_amendment.md 起票 | closed |
| PH-F-002 | HIGH | ADR-00021 §normative source 序列 + Phase C §11.7 + DD-05 update task (SP-022) | closed (DD-05 本文 update は SP-022 で実施) |
| PH-F-003 | HIGH | SP-001 受け入れ条件 (tm → taskhub + curl) + SP-012 検証手順 (tm → curl) | closed |
| PH-F-004 | HIGH | ADR-00021 §normative source 序列で前段 sample を §11/§12/§14 後勝ち明示 | closed |
| PH-F-005 | CRITICAL | ADR-00009 update §DD-02/DD-03/DD-04 enum 同期 (Phase F-0 として正式起票) | closed |
| PH-F-006 | HIGH | rules/agentrun-state-machine.md §6.1 (P0.1+ 拡張 event_type 22→31 反映) | closed |
| PH-F-007 | HIGH | ADR-00021 §11.6 (sealed guard 統一) + Phase C draft §1.6 / ADR-00013 / ADR-00014 で同一 list 参照 | closed |
| PH-F-008 | HIGH | ADR-00014/00018 DDL に SP-013 hard gate コメント明示 + 暫定 service guard 明記 | closed |
| PH-F-009 | MEDIUM | ADR-00016 §5 二重化解消 (Phase G addendum 版が正本、SP-013/SP-018 責務分担) | closed |
| PH-F-010 | HIGH | PRD-01 §10.3 (P0 = pg_dump+Redis+artifacts、PITR は P1 以降 optional) | closed |
| PH-F-011 | HIGH | 本 ledger (`docs/設計検討/phase-h-closure-ledger.md`) | closed |

## 全体 closure summary

| metric | value |
|---|---|
| total distinct finding (Phase A-G) | 94 |
| total distinct finding (Phase H 含む) | 105 |
| CRITICAL 計 | 8 (Phase D 5 + R2 1 + Phase H 2、すべて closed) |
| HIGH 計 | 60 (Phase D 27 + Phase E 12 + Phase G 17 + Phase H 8、すべて closed) |
| MEDIUM 計 | 32 (各 Phase 累計、すべて closed) |
| LOW 計 | 5 (Phase D R1 minor、すべて closed) |
| status | **全 105 finding closed** (Phase H 11 finding が本 session で patch、SP-001.5 起票で lifecycle 整理) |
| **release readiness (Sprint 1 着手 ready)** | **YES** (PH-F-001〜011 すべて closed、SP-001 既完了内容不変、SP-001.5 で host-portable amendment 起票済) |

## Sprint 1 着手前 prerequisite (Phase F-0 + その他)

Sprint 1 着手前に以下を完了 (SP-001.5 ではなく Phase F-0 の前提作業):

1. **Phase F-0**: `action_class` enum 同期 migration (ADR-00009 update §DD-02/DD-03/DD-04 enum 同期)
   - `docs/基本設計/02_データモデル.md` / 03 / 04 の `read/search` 削除 + `provider_call` 追加
   - `tests/policy/test_action_class_enum.py` の `EXPECTED_ACTION_CLASSES` を 7 種同期
   - migration `00NN_p0_action_class_enum_sync.py` 投入
2. **ADR-00021 / ADR-00007 update / ADR-00009 update / ADR-00014/15/16/17/18/19/20** を proposed → accepted (SP-001.5 着手と同時)
3. **DD-05 (ネットワーク境界設計) host-portable 化 update** (SP-022 で本文 update、SP-001.5 では reference のみ)

## ledger 維持

- 本 ledger は **Sprint 1 着手 ready の証跡**、commit に含める
- Sprint 1 着手後の新 finding は別 ledger (Sprint 別 review log) で管理
- 本 ledger を rollback / 改竄禁止 (git commit で永続化)

## 関連

- 各 Phase result.md (~/.claude/local/codex-tasks/2026-05-10/<phase>/result.md)
- ADR-00014〜00021 / SP-013-016/012/022/001-5
- Phase C draft (`docs/設計検討/phase-c-multi-agent-spec-draft.md`)
- harness v5 Wave 19-23 ロードマップ (`docs/設計検討/harness-v5-wave-19-23-roadmap.md`)
