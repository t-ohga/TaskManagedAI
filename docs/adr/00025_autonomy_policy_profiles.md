---
id: "ADR-00025"
title: "Autonomy Policy Profiles: L0-L3 4 段階で approval スキップ範囲を切替、`autonomy_level` (caller-visible) と `policy_profile` (server-owned) を概念分離"
status: "accepted"
date: "2026-05-15"
accepted_at: "2026-05-24"
authors:
  - "t-ohga"
related_sprints:
  - "SP-024"
supersedes: null
superseded_by: null
---

最終更新: 2026-05-24 (SP024-T01 readiness gate で accepted 化、`projects.policy_profile` は server-owned DB cache として維持)

## 背景

- 決定対象: `approval 不要で AI が自動実行できる範囲` を 4 段階 (L0/L1/L2/L3) で切替可能にする autonomy policy profiles を定義する。**human-only approval decider invariant (ADR-00009 §self-approval / `.claude/reference/multi-agent-orchestration-draft.md`) は維持**したまま、Policy Engine `effect=allow` で `approval_requests` row を作らない auto-allow path を level ごとに調整する。
- 関連 Sprint: 本 ADR は **SP-024 readiness gate で accepted**。**SP-017 は SP-016 `## P0.1 候補` で AI Society Visualization (board / role icon / dashboard) に予約済のため使用不可** (`docs/sprints/SP-016_ui_cli_parity.md:39+135` で予約)、R29 plan §10.4 「新 SP-017 候補」言及は SP-024 に override 済み。SP024-T02 以降の runtime 実装までは L0 default のみ実 enforce、L1-L3 auto-allow path は disable。
- 前提 / 制約:
  - **不変条件 #2 維持**: approval を要する action では decider は依然 human only。auto-allow path は「approval を skip」であって「agent / orchestrator / service / provider が decider に昇格」ではない (ADR-00009 §Tier 2 準拠)。
  - **caller-not-allowed**: `autonomy_level` (L0-L3 project setting) は caller-visible だが、`policy_profile` (Policy Engine server-resolved effect profile) は **server-owned**、caller 指定不可 (`.claude/rules/server-owned-boundary.md:5-12`)。両者は概念分離。
  - **Phase 5 prerequisite (Critical)**: L1-L3 auto-allow path は **Phase 5 Hook Trust Boundary 完成 + ADR-00012 accepted** が prerequisite。SP-022 Phase 5 completion (PR #80) と ADR-00012 accepted を確認済みのため、本 ADR は SP024-T01 で accepted 化した。ただし runtime effect は SP024-T02+ の regression gate 完了まで default disabled。
  - **ADR Gate Criteria 11 種**: 本 ADR は #4 (AI エージェント権限) を主、#2 (DB schema、`autonomy_level` 列追加時)、#3 (API 契約、settings endpoint)、#5 (MCP/tool 権限、low-risk profile 機械判定)、#10 (Provider 追加 / 切替、auto-allow path の provider 制約) を補助とする trigger。**break-glass 対象外** (`.claude/rules/sprint-pack-adr-gate.md` §11)。
  - **level に関わらず human approval 必須の action_class**: `secret_access` / `merge` / `deploy` / `provider_call` (L0-L3 全 level)。これは ADR-00006 (SecretBroker raw secret 非保存) / ADR-00010 (Provider Matrix) / ADR-00023 候補 (Realtime/Gemini direct 不可) の延長。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A: 4 段階 L0-L3 (採用) | L0 strict default / L1 low_risk / L2 medium_risk / L3 high_autonomy、`autonomy_level` は caller-visible project setting、`policy_profile` は server-owned。auto-allow 適用は low-risk profile (機械判定) 通過時のみ | user 要求「4 段階で設定切替可能」を満たす。human-only decider 不変、auto-allow と decider 委譲を別軸分離。`secret_access`/`merge`/`deploy`/`provider_call` は全 level で human approval 必須を強制可能 | level upgrade で auto-allow scope が drift しやすい → accepted ADR + Sprint Pack + human approval event before effect で gate |
| B: 2 段階 (strict / autonomous) | 既存 ADR-00009 §Tier 2 `low_risk_auto_allow` の on/off 切替のみ | 実装シンプル | user 要求の `4 段階` を満たさない。L1/L2 中間 (個人運用日常) と L3 (Draft PR 自動化) の境界が消える |
| C: action_class 単位の auto-allow on/off | 各 action_class ごとに boolean | 柔軟 | matrix 爆発、user 設定 UI 困難、L3 の `pr_open` 制約 (SecretBroker capability 内包 path 例外) を表現困難 |
| D: 0 段階 (常時 approval 必須) | auto-allow path を実装しない | 実装最も安全 | user 要求の「approval 不要で AI が自動実行」を否定 |

## 採用案

- 採用: A: 4 段階 L0-L3。
- 理由:
  - user 要求「approval 不要で AI が自動実行できる範囲を 4 段階で設定切替可能にする」を満たす。
  - `secret_access` / `merge` / `deploy` / `provider_call` は全 level で human approval 必須を強制可能 (§3.3 不変条件 #1)。
  - low-risk profile (機械判定) 通過時のみ auto-allow を適用する設計で fail-closed 維持。1 軸でも不合格なら approval path に fall back。
  - `autonomy_level` (caller-visible) と `policy_profile` (server-owned) の概念分離で server-owned-boundary 不変 (`.claude/rules/server-owned-boundary.md`) を維持。
  - level upgrade (L0→L3) は **accepted ADR + accepted Sprint Pack + human approval event before effect** 必須で gate。
- 実装 Sprint: 本 ADR は **accepted**。SP-024 (SP024-T02+) で実装する。SP-017 は AI Society Visualization 用に予約済のため使用不可。SP024-T02+ が完了するまでは L0 default のみ実 enforce。
- 実装対象ファイル (SP024-T02+):
  - `backend/app/domain/policy/autonomy_level.py` (新規、Literal L0/L1/L2/L3 + Pydantic enum + frozenset)
  - `backend/app/db/models/project.py` (既存) または `workspace.py` の `autonomy_level` 列追加 (`migrations/versions/00NN_p0_1_autonomy_level.py`)
  - **`projects.policy_profile` compatibility decision (SP024-T01 accepted)**: `projects.policy_profile` は ADR-00009 accepted 実装の server-owned DB cache / FK として維持する。caller-visible write surface は引き続き禁止し、`ProjectCreate` / update API / CLI / UI は `autonomy_level` だけを受け取る。Policy Engine は `autonomy_level` から server-owned `policy_profile` を resolve し、必要な場合のみ server-side に `projects.policy_profile` を更新する。`policy_profiles` / `policy_profile_action_effects` / `policy_decisions_policy_profile_fkey` は削除しない。
  - `backend/app/services/policy/engine.py` (autonomy_level → policy_profile resolve helper、Policy Engine 内部で server-owned 解決、caller 入力経路を signature レベル削除)
  - `backend/app/services/policy/low_risk_profile.py` (新規、機械判定: payload_data_class / diff size / file count / forbidden path / dangerous command / provider_request_preflight / runner_mutation_gateway / ContextSnapshot 10 列 PASS)
  - `frontend/app/(admin)/project-settings/autonomy/` (UI、`policy_profile` 入力 field は削除、`autonomy_level` のみ表示)
  - `taskmanagedai-cli/src/settings/autonomy.ts` (`tmai settings autonomy --level L1`、`policy_profile` 指定経路は CLI からも削除)
  - `tests/policy/test_autonomy_level_enum.py` / `test_autonomy_level_resolve.py` / `test_low_risk_profile.py` / `test_autonomy_upgrade_gate.py` / **`test_autonomy_caller_supplied_policy_profile_reject.py` (caller-supplied `policy_profile` reject 経路 verify)** (5 件最小)
- 実装ガイダンス:
  - `autonomy_level` enum は **5+ source** で整合: DB CHECK / SQLAlchemy CheckConstraint / Python Literal / Pydantic Field validator / pytest EXPECTED constant (`.claude/rules/cross-source-enum-integrity.md`)
  - `policy_profile` は **caller 指定不可**、Policy Engine 内部で `autonomy_level` から解決する server-owned 値 (`.claude/rules/server-owned-boundary.md` §1)。現行 code は `ProjectCreate` で caller-supplied `policy_profile` を拒否済み。SP024-T03 で API / CLI / UI / repository / DB の全 write surface を再確認し、`test_autonomy_caller_supplied_policy_profile_reject.py` で regression 化する。
  - **SP024-T03 resolver safety**: SP024-T03 時点では `resolve_autonomy_policy_profile()` は L0-L3 全 level を server-owned `policy_profile='default'` に解決し、`auto_allow_enabled=False` を返す。既存 `low_risk_auto_allow` は SP-014 semantics で `provider_call` allow row を持つため、ADR-00025 の「provider_call は全 level human approval 必須」不変条件を満たす T05 更新が完了するまで resolver から返してはならない。
  - level matrix:

    | Level | 名称 | auto-allow される action_class (low-risk profile 通過時) | human approval が必須の action_class | 想定用途 |
    |---|---|---|---|---|
    | **L0** | `strict` (default) | (なし、全 mutation で approval) | `task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` | 初回利用、新 provider 切替直後、高リスク環境、新 Sprint 着手直後 |
    | **L1** | `low_risk` | `task_write` (low-risk profile: 単一 ticket comment / acceptance criteria update / labels) | `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` | 個人運用の日常 (TaskManagedAI の P0.1 dogfooding default 想定) |
    | **L2** | `medium_risk` | `task_write` + `repo_write` (low-risk profile: docs only diff / file count <= 3 / forbidden path no-hit / dangerous command no-hit) | `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call` | 慣れた個人運用、TaskManagedAI を dogfooding |
    | **L3** | `high_autonomy` | `task_write` + `repo_write` + `pr_open` (low-risk profile: Draft PR 限定 / 単一 BL / reviewer artifact required / `provider_request_preflight` PASS、**ただし `pr_open` が内部で SecretBroker capability issue/redeem を必要とする場合は別 gate で human approval 必須**) | `secret_access` / `merge` / `deploy` / `provider_call` + **`pr_open` のうち SecretBroker / RepoProxy capability operation を内包する path** | 個人運用、Draft PR まで自動化、merge は依然 human approval |

  - low-risk profile 機械判定軸 (1 軸でも不合格なら approval path に fall back):
    - `payload_data_class <= internal` (confidential/pii は L 問わず approval 必須)
    - diff size <= N lines / file count <= M (level ごとに上限、本 ADR で固定)
    - forbidden path no-hit (`.env`、`.git/config`、secrets、migrations、`.github/workflows/**`)
    - dangerous command no-hit (Runner / CLI 経路の denylist)
    - `provider_request_preflight` PASS (canary、token pattern 検出なし)
    - `runner_mutation_gateway` 通過 (Sprint 7 後の本実装)
    - ContextSnapshot 10 列 PASS + `evidence_set_hash` 既定
  - 不変条件 (level 切替で破ってはならない):
    1. `secret_access` / `merge` / `deploy` / `provider_call` は **全 level で human approval 必須**
    2. `approval_requests.decided_by_actor_id` は **human actor のみ** (DB CHECK + service guard + Pydantic + pytest の 4 重防御)
    3. auto-allow path で実行する action でも **AgentRunEvent + audit event** に `policy_profile` + `policy_version` + `auto_allow_reason` + `effective_action_class` + `applied_level` を必ず残す
    4. low-risk profile の機械判定で **1 軸でも不合格** なら approval path に fall back
    5. level downgrade (L3→L0) はいつでも可能、upgrade (L0→L3) は **accepted ADR + accepted Sprint Pack + human approval event before effect** 必須 (ADR retro は不可、ADR Gate Criteria #4 trigger)
    6. budget exceeded / global kill switch / Provider Matrix row blocked / Tool/MCP Gateway deny のいずれかが発火したら **level 設定を無視して即 `effect=deny` / AgentRun blocked** に切替。approval path 切替は不可、provider/tool 送信を fail-closed で完全停止。復旧は **config change ADR + accepted Sprint Pack** 経由のみ
- テスト指針:
  - autonomy_level enum 5+ source 整合 (`test_autonomy_level_enum.py`)
  - autonomy_level → policy_profile resolve mapping (`test_autonomy_level_resolve.py`、L0/L1/L2/L3 → server-owned policy_profile の expected map)
  - low-risk profile 機械判定 7 軸 (`test_low_risk_profile.py`、各軸不合格 negative + 全 PASS positive)
  - level upgrade gate (`test_autonomy_upgrade_gate.py`、accepted ADR + Sprint Pack + human approval event なし → effect 不可)
  - caller 指定 `policy_profile` reject (`test_autonomy_caller_supplied_policy_profile.py`、signature レベル削除済 contract)
  - L1-L3 で `secret_access` / `merge` / `deploy` / `provider_call` 全件 approval path 通過 (`test_autonomy_human_required_actions.py`)
  - 3 段 kill switch 発火時 level 設定無視 (`test_autonomy_kill_switch_override.py`、BudgetGuard cap zero / Provider Matrix blocked / Tool Gateway deny)
- ADR Gate Criteria 該当: #4 主、#2 (`autonomy_level` 列追加時)、#3 (settings endpoint)、#5 (low-risk profile 機械判定)、#10 (auto-allow path の provider 制約) を補助。

## 却下案

- **B (2 段階)**: user 要求の「4 段階で設定切替可能」を満たさない。L1/L2 中間と L3 (Draft PR 自動化) の境界が消える。
- **C (action_class 単位の boolean)**: matrix 爆発で UI 困難。L3 の `pr_open` 内部 SecretBroker capability 例外 path を表現困難。`autonomy_level` の段階的 upgrade 概念と一致しない。
- **D (0 段階)**: user 要求「approval 不要で AI が自動実行」を否定。dogfooding 段階で実用性が低下。

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|
| L upgrade で auto-allow scope drift | `test_autonomy_upgrade_gate.py` + accepted ADR + Sprint Pack + human approval event before effect | level upgrade は **3 つ全て揃った後** にのみ effect 化、ADR retro 不可。downgrade はいつでも可能 |
| caller-supplied `policy_profile` で server-owned-boundary 破壊 | `test_autonomy_caller_supplied_policy_profile.py` (signature レベル削除確認) | `autonomy_level` のみ caller-visible、`policy_profile` は server resolve 専用、API endpoint signature に存在しない |
| low-risk profile 機械判定漏れで confidential payload が auto-allow | `test_low_risk_profile.py` (各軸不合格 negative test) | 7 軸の **1 軸でも不合格** なら approval path に fall back、fail-closed 設計 |
| L3 `pr_open` で SecretBroker capability 内包 path 漏れ | `test_autonomy_pr_open_secret_capability.py` (内包 path detect) | `pr_open` operation 内で SecretBroker `redeem_capability_token` を呼ぶ場合は **常に approval path**、`pr_open` auto-allow からは除外 |
| `autonomy_level` 列 drift (5+ source) | `tests/cross_source/test_autonomy_level_drift.py` | DB CHECK / SQLAlchemy / Literal / Pydantic / pytest の 5+ source 整合 check |
| Phase 5 prerequisite 未完で L1-L3 effect 化 | `.claude/hooks/` trusted hook 完成確認 (ADR-00012 accepted) | SP-022 Phase 5 completion + ADR-00012 accepted を SP024-T01 で確認。runtime effect は SP024-T02+ gate 完了まで default disabled |
| 3 段 kill switch override 漏れ (level 設定が kill 優先される) | `test_autonomy_kill_switch_override.py` (BudgetGuard zero / Provider blocked / Tool deny で level 無視確認) | kill switch 発火時は **level 設定を完全無視**、`effect=deny` / AgentRun blocked。approval path 切替は不可 |

## rollback 手順

### 運用 rollback (autonomy 設定の問題発見)

**F-PR12-002 P2 adopt 反映**: auto-allow path は `approval_requests` row を作らない invariant のため、`auto_allow_reason` 列を仮定した invalidation step は実装不可能。代わりに AgentRunEvent / audit event / policy_decisions の append-only ledger を trace する設計。

1. 全 `projects.autonomy_level` を L0 (default) に強制 downgrade する settings flag を Policy Engine に追加 (`AUTONOMY_GLOBAL_DOWNGRADE=L0`)。downgrade は accepted ADR + Sprint Pack 不要 (L upgrade と非対称)。
2. **AgentRunEvent + `policy_decisions` の append-only ledger を trace** して過去 auto-allow path で実行された action を identify する: `policy_decisions.reason_code='auto_allow_applied'` (新規 reason_code、ADR-00009 §QL-B update §reason_code 列の延長) + AgentRunEvent metadata `applied_level` 列で `L1` 以上の row を抽出。該当 action に対する rollback / compensation は **新規 ticket 起票 + human approval** 経由 (auto-allow action 自体の DB row は append-only 維持、消去せず)。`approval_requests` row は **作られていないため invalidate 対象なし**。
3. AgentRunEvent / audit event の `applied_level` 列で過去 auto-allow 履歴を trace、不正パターン検出 → `policy_decisions` の `reason_code='autonomy_downgrade'` で記録。
4. UI / In-App Notification で auto-allow path 一時停止 + 過去 auto-allow action の human review 要求を通知する。

### Migration rollback (DB schema 変更時、`autonomy_level` 列追加時)

1. migration 適用前に `pg_dump` で full DB backup を取得し、age で暗号化して別ボリュームに保存する。
2. staging DB で `uv run alembic upgrade head`、`alembic check`、autonomy_level enum 5+ source 整合 test を先行実行する。
3. production migration 後に `projects.autonomy_level` が L0/L1/L2/L3 enum 以外を保存可能、`secret_access`/`merge`/`deploy`/`provider_call` で L3 が auto-allow される、kill switch 発火時に level 無視されない、のいずれかを検出したら rollback trigger とする。
4. `uv run alembic downgrade -1` を実行する。downgrade で data loss / inconsistent state になる場合は forward-fix migration を新規作成し、staging で検証してから production 適用する。最終手段として age 暗号化 backup から restore する。
5. rollback verification は `uv run pytest tests/policy/test_autonomy_level_enum.py tests/policy/test_autonomy_level_resolve.py tests/policy/test_low_risk_profile.py tests/policy/test_autonomy_upgrade_gate.py tests/policy/test_autonomy_caller_supplied_policy_profile.py tests/policy/test_autonomy_human_required_actions.py tests/policy/test_autonomy_kill_switch_override.py -q` で実行して確認する (P0.1 完了後に Sprint Pack 検証手順と合わせて整合確認)。

### ADR-00025 自体の rollback (accepted 後、runtime effect 前)

1. SP024-T02 以降の code / DB schema / API 変更前であれば、`status: superseded` または `rejected` に変更し `superseded_by` に代替 ADR を記録する (例: ADR-00009 §Tier 2 既存 `low_risk_auto_allow` semantics に巻き戻し)。
2. runtime effect 前であれば、DB / API / Policy Engine の rollback は不要。SP-024 を docs-only closeout し、L0 default の現行運用を継続する。
3. runtime 実装後の取下げは、`autonomy_level` 列 migration rollback (上記 Migration rollback) + Policy Engine resolve helper の disable + L0 forced default の 3 step を Sprint Pack で計画した上で実行する。

## 関連 ADR

- ADR-00009 (action_class taxonomy 7 種 + Tier 2 `low_risk_auto_allow` semantics、本 ADR で L0-L3 cross-ref note 追加)
- ADR-00012 (Hook Trust Boundary、本 ADR accepted 化の Phase 5 prerequisite)
- ADR-00014 (Multi-Agent Orchestration、role ⊥ capability authorization invariant、本 ADR の不変条件 #2 と整合)
- ADR-00002 (Data Model、`autonomy_level` 列追加時の ADR Gate Criteria #2 trigger)
- ADR-00006 (SecretBroker raw secret 非保存、本 ADR の `secret_access` 全 level human approval 必須 invariant の延長)
- ADR-00010 (Provider Compliance Matrix、本 ADR の `provider_call` 全 level human approval 必須 invariant の延長)
- ADR-00023 (**QL-H Quality Loop run で proposed 起票予定**、現時点では未起票、本 cross-ref は QL-H 完了後に有効化される。InteractionGateway Realtime intake、本 ADR の Realtime/Gemini direct 不可 invariant と整合)

## 関連資料

- `docs/設計検討/修正まとめ統合計画.md` §10 (R29 clean、本 ADR の source spec)
- `.claude/rules/server-owned-boundary.md` §1 (caller-not-allowed 経路、`policy_profile` は server-owned)
- `.claude/reference/multi-agent-orchestration-draft.md` (decider human-only、role ⊥ capability、orchestrator は requester only)
- `.claude/rules/cross-source-enum-integrity.md` (5+ source 整合、`autonomy_level` enum drift 防止)
- `.claude/rules/sprint-pack-adr-gate.md` §11 (ADR Gate Criteria 11 種 break-glass 対象外、L upgrade は ADR retro 不可)
