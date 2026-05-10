---
id: "ADR-00016"
title: "Hermes-Agent Integration Strategy: pattern adoption only + 48 module 4 分類 + Wave 19-23 ロードマップ + ContextSnapshot 10 列不変保証 + memory_retrieval_artifacts 別 table + sanitizer_policy_versions"
status: "proposed"
date: "2026-05-10"
authors:
  - "t-ohga"
related_sprints:
  - "SP-018_hermes_memory_integration"
  - "SP-020_curator_insights_integration"
related_research:
  - "Phase A-1 hermes 48 module deep dive"
  - "Phase B-1 4 分類最終判定 (brush-up 36 / optimize 3 / skip 9)"
  - "Phase B-2 R-007/008/013/014 + Phase E PE-F-005"
  - "docs/設計検討/harness-v5-wave-19-23-roadmap.md"
acceptance_blocked_by:
  - "ADR-00014 + ADR-00020 accepted"
  - "P0 完了 + ハーネス v5 Wave 19-22 完了"
---

最終更新: 2026-05-10 (proposed 起票)

## 背景

- 決定対象: TaskManagedAI vision の **「user-scope ハーネス v5 = hermes 級 memory + context + curation + cron」** を実現するため、hermes-agent 48 module を **pattern adoption only** で取り込む scope と方針を固定。本 ADR は (1) full embed 禁止、(2) 4 分類判定 (brush-up 36 / optimize 3 / skip 9)、(3) Wave 19-23 ロードマップ、(4) ContextSnapshot 10 列不変保証、(5) memory_retrieval_artifacts 別 table、(6) **sanitizer_policy_versions** (PE-F-005 fix) の 6 点を担保.
- ADR Gate Criteria #4 (AI 権限) + #2 (DB schema) + #5 (MCP/tool 権限、cron) 該当.

## 採用案

### §1: 48 module 4 分類 (Phase A-1 + B-1 確定)

| 分類 | 件数 | 取り込み方針 |
|---|---|---|
| brush-up | 36 | concept 取り込み + TaskManagedAI 境界で再実装 (memory_manager / hermes_state / context_engine / context_compressor / curator / insights / cron / kanban_db.py の board concept / batch_runner / model_tools 等) |
| optimize | 3 | concept 取り込み + 大幅最適化 (acp_adapter / run_agent / hermes_cli) |
| skip | 9 | TUI / Web UI / packaging / I18n / gateway platforms / honcho / mem0 / supermemory cloud / external observability / tinker-atropos |

詳細: `~/.claude/local/codex-tasks/2026-05-10/take-up-classification-b1/result.md`

### §2: Wave 19-23 ロードマップ (`docs/設計検討/harness-v5-wave-19-23-roadmap.md`)

| Wave | タイトル | source | 実装 Sprint |
|---|---|---|---|
| 19 | Memory Core (memory_manager + sessiondb FTS pattern) | hermes agent/memory_manager.py + hermes_state.py | SP-018 |
| 20 | Memory Plugins (provider abstraction、internal 実装のみ) | hermes plugins/memory/ (concept のみ、external API 不使用) | SP-018 |
| 21 | Context Layer (engine + compressor + references) | hermes agent/context_*.py | SP-018 |
| 22 | Knowledge Curation (curator + insights) | hermes agent/curator.py + insights.py | SP-020 |
| 23 | Cron + Routines (scheduled + GitHub webhook + API trigger) | hermes cron/ + gateway concept | P1+ |

### §3: ContextSnapshot 10 列不変保証 (R-013 / PD-F-014 / PE-F-005)

memory backend は ContextSnapshot を **置き換えない/上書きしない**:

| 検証 | 強制 path |
|---|---|
| 10 列 DDL 変更なし | `tests/db/test_schema_introspection.py` で完全一致 assert |
| memory retrieval 別 table | §4 memory_retrieval_artifacts |
| trust_level=untrusted_content 強制 | DB CHECK |
| sanitizer_version 整合 (PE-F-005) | §5 sanitizer_policy_versions |
| secret canary scan | retrieval 時に provider-compliance §8 と同等 |
| tenant/project boundary | (tenant_id, project_id) FK + 複合 FK pattern |

### §4: memory_retrieval_artifacts (PD-F-014 fix、別 table)

DDL は Phase C draft §5.3 参照。raw memory text は AgentRun column / ContextSnapshot column に入れない、artifact store のみ.

### §5: sanitizer_policy_versions (PE-F-005 fix)

```sql
create table sanitizer_policy_versions (
    tenant_id bigint not null default 1 references tenants(id),
    version text not null,                                  -- e.g. 'v1.2.3'
    config_hash text not null,                              -- canonical config の sha256
    activated_at timestamptz not null default now(),
    deprecated_at timestamptz,
    primary key (tenant_id, version)
);

create index ix_sanitizer_policy_active
    on sanitizer_policy_versions (tenant_id)
    where deprecated_at is null;
```

memory_retrieval_artifacts.sanitizer_version は current `sanitizer_policy_versions` (deprecated_at IS NULL) と一致確認:
- 一致: そのまま使用
- 不一致 (deprecated): `stale_sanitizer` deny または re-sanitize (artifact 再生成、新 sanitizer_version で immutable artifact ref 更新)
- provider prompt の memory snippet は **redaction_status='redacted' 原則**、`raw_with_canary_scan_passed` は明示例外 (local debug 等) に閉じる.

### §6: license / persistence / external network 違反防止 (S-10 / PE-F-010)

| 違反 path | 防止策 |
|---|---|
| honcho / mem0 / supermemory cloud HTTP 送信 | service layer で external HTTP egress deny |
| AutoGPT autogpt_platform (Polyform Shield) embed | コード embed 完全禁止 + CI で `import autogpt` denylist (PE-F-010) |
| 独自 SQLite (kanban_db.py) embed | CI で `import sqlite3` + `kanban_db` denylist |
| OpenAI API embedding 直接呼び出し | ProviderAdapter 経由のみ + payload_data_class enforcement |
| memory に raw secret 混入 | provider-compliance §8 と同等の canary scan を memory layer で再実装 |

CI script: `scripts/ci/check_framework_intake.sh` (PE-F-010 strengthening)、license string scan + external API endpoint denylist + telemetry endpoint denylist で機械検査.

### §7: ADR-00020 連動

新 module / framework / external library 取り込み時は ADR-00020 framework intake checklist を経て本 ADR に追記.

### §8: 実装 Sprint

- SP-018 (Wave 19-21、memory + context、target 5/max 7 days)
- SP-020 (Wave 22、curator、target 3/max 5 days)
- SP (P1+) Wave 23 (cron/routines)

### §9: テスト指針

- `test_memory_records_schema.py` (12+ 列 enforcement + 5 複合 FK)
- `test_fts5_search.py` (tenant scope、cross-tenant 結果なし、relevance ranking)
- `test_tenant_project_boundary.py` (cross-tenant/project reject)
- `test_secret_canary_scan.py` (store/retrieve 両方で fake API key deny)
- `test_context_supplements_schema.py` (immutable artifact ref + sanitizer_version)
- `test_contextsnapshot_unchanged.py` (10 列完全一致 invariant)
- `test_sanitizer_policy_versions.py` (drift detection + stale_sanitizer deny / re-sanitize)
- `eval/multi_agent/memory_secret_canary/` (R-013 negative)
- `eval/multi_agent/memory_cross_tenant/` (negative)

## リスク / rollback

| リスク | 軽減 |
|---|---|
| ContextSnapshot 暗黙置換 (R-013) | `test_contextsnapshot_unchanged.py` を CI smoke 級 |
| external API 送信 | service layer + network module で external HTTP block + `scripts/ci/check_framework_intake.sh` |
| memory raw secret | secret canary scan + assert_no_raw_secret test helper |
| persistence 二重化 | `import sqlite3` / `kanban_db` CI denylist |
| license 違反 | ADR-00020 checklist + citation 義務化 (`docs/citations/hermes_pattern_adoption.md`) |
| sanitizer_version drift | `test_sanitizer_policy_versions.py` + retrieval 時に deny |

rollback: tenant_config で `memory_enabled=false` / `curator_enabled=false`、systemd `cron disable`、ContextSnapshot 不変なので AgentRun 動作に影響なし.

## 関連

- ADR-00014 / ADR-00020 / Phase C §C-5 + §11.3 PE-F-005, PE-F-010
- `docs/設計検討/harness-v5-wave-19-23-roadmap.md`

---

## Phase G adversarial strengthening update (2026-05-10、PGA-F-010 反映)

ADR-00021 §14.1 (Phase G adversarial Strengthening) の **PGA-F-010 (sanitizer_version drift で stale memory)** mitigation を本 ADR に強化反映:

### sanitizer_policy_versions table を正本化 + config_hash FK 必須

```sql
create table sanitizer_policy_versions (
    tenant_id bigint not null default 1 references tenants(id),
    id uuid primary key default gen_random_uuid(),
    version text not null,                                -- e.g. 'v1.2.3'
    config_hash text not null,                            -- canonical config の sha256 (name 同じでも config_hash 違えば別 version)
    ruleset_hash text not null,                            -- secret canary pattern set の sha256
    created_at timestamptz not null default now(),
    activated_at timestamptz not null default now(),
    deprecated_at timestamptz,
    unique (tenant_id, version),
    unique (tenant_id, config_hash)                       -- config が同じなら version も一意
);
```

`memory_records` / `memory_retrieval_artifacts` を上記に FK 接続 (sanitizer_version は NOT NULL FK):

```sql
alter table memory_records
    add column sanitizer_version_id uuid not null,
    add foreign key (tenant_id, sanitizer_version_id)
        references sanitizer_policy_versions(tenant_id, id);

alter table memory_retrieval_artifacts
    add column sanitizer_version_id uuid not null,
    add foreign key (tenant_id, sanitizer_version_id)
        references sanitizer_policy_versions(tenant_id, id);
```

### restore 後の sanitizer drift 処理

- restore 後 `taskhub verify --integrity --multi-agent` で source meta の `sanitizer_policy_versions.config_hash` と target current config の hash を比較
- config_hash 一致 → そのまま使用
- config_hash mismatch → 以下 3-step 処理:
  1. **retrieval deny**: 該当 sanitizer_version の memory snippet retrieval を全 deny (audit `memory_retrieval_stale_sanitizer_denied`)
  2. **explicit re-sanitize job**: `taskhub re-sanitize --version <id>` を background async で起動、新 config_hash で artifact 再生成
  3. **old snippet quarantine**: 旧 snippet を `~/.taskhub/quarantine/<sanitizer_version_id>/` に移動 + audit `memory_snippet_quarantined`

### 関連

- ADR-00021 §14.1 PGA-F-010
- SP-018 must_ship (sanitizer_policy_versions table + FK + restore drift handling)
