---
id: "SP-PHASE0_local_bootstrap"
type: "heavy"
status: "draft"
sprint_no: 0
created_at: "2026-06-20"
updated_at: "2026-06-20"
target_days: 4
max_days: 7
adr_refs:
  - "[ADR-00058](../adr/00058_local_secret_store_cli_auth_boundary.md)"
  - "[ADR-00059](../adr/00059_host_portable_local_reconciliation_secret_revoke.md)"
planned_adr_refs:
  - "ADR-00011 (update: keyring 依存の supply-chain 記録)"
related_sprints:
  - "SP-001-5_host_portable_amendment"
  - "SP-006_cli_artifact"
risks:
  - "API key の in-process provider.call で env/argv/subprocess に raw を出さない (CRITICAL、Phase 2 実装時に堅持)"
  - "URI backend 5+source drift (fail-open、SECRET_URI_PATTERN 単一定数で構造防止)"
  - "host-ambient CLI 経路が broker 監査外 (user 承認済 trade-off)"
  - "revoke material の crash-window (durable reconciliation + downgrade preflight で source of truth 保護)"
---

# SP-PHASE0 — local 起動基盤 + secret tooling + CLI サブスク認証供給 + host-portable 決着

> 大元計画 (PLAN-10、`docs/実装計画/10_大元計画_ローカル自律AI基盤.md`) Phase 0 の heavy Sprint Pack。完成ゴール C の「初回起動して使い始められる」土台層。Phase 0 詳細設計 workflow (4ストリーム並列設計→境界批評 REFUTE→最終化) の成果を実装に落とす。

## 目的

local Mac で TaskManagedAI を起動し使い始められる土台を作る。具体的には:
1. **secret tooling**: secret (GitHub token 優先、API key 副次) を登録する LocalSecretStore + SecretRef create/rotate/revoke を SecretBroker 抽象に差し込む。SOPS+age は後フェーズ (D-4)。
2. **CLI サブスク認証供給経路**: 主軸の CLI サブスク credential (claude/codex、self-rotating OAuth) を **host-ambient** (SecretBroker 境界外) に分類し、API key (副次・static) のみ broker-managed。raw secret 非保存境界を維持。
3. **ローカル起動**: docker compose dev (postgres/redis/api/frontend) + **host worker** で起動する runbook。
4. **host-portable 決着**: SP-001-5 の tension (loopback bind vs restore 契約) を local scope で loopback 維持に正本化。

## 背景

現状は「記録」は自律で動くが「実行」が構造的に欠落 (大元計画 §1 の 5 大ブロッカー)。Phase 0 はその最下層 = 起動 + secret + CLI 認証供給を固める。実行エンジンは CLI 主 (worker が `claude -p` / `codex exec` をサブスク認証で headless spawn)。Phase 0 設計で **CLI サブスク credential が self-rotating OAuth token** と実機確認され、全 broker-managed (案B) が構造的に不可能 → host-ambient (案C hybrid) を user 承認 (2026-06-20)。境界批評が初期設計を REFUTE (broker が raw を launcher へ forward する seam は SecretBroker §10 違反) し、修正版に到達: **Phase 0 は CLI=host-ambient (host worker file 直読、broker 非経由)**、broker-managed API key は **in-process `provider.call`** (ProviderAdapter HTTP、subprocess なし、env/argv に raw を出さない) で **Phase 2 実装**。さらに plan-review (codex adversarial R1) で URI 文法 (`secret://(sops|local)/...`、`local://` は誤り) と revoke crash-safety (durable reconciliation) を adopt。

## 対象外 (scope_out)

- production AgentRun の駆動 (Phase 2-6)。CLIAgentAdapter 本体 (Phase 2)。
- Provider Compliance Matrix への cli/subscription 行追加 (Phase 2、Phase 0 は interface 合意のみ)。
- SOPS+age 移行 (D-4)、VPS internal-only 化 (D-1)、GitHub App/Draft PR (D-5)、外部 SaaS 連携 (D-3)。
- frontend 変更 (Phase 0 は backend + docs + CLI 中心)。
- host migration drill 実機実施 (D-1)。

## 設計判断 (確定、ADR 正本)

- **CLI 認証境界 = 案C hybrid** (ADR-00058): CLI サブスク = host-ambient (CLI が OAuth 所有・refresh、per-run 監査は cli_invocation event)、API key = broker-managed。
- **credential 供給** (ADR-00058、境界批評 finding-2 反映): **Phase 0 は CLI=host-ambient のみ** (host worker が `~/.claude`/`~/.codex` 直読、broker 非経由)。broker-managed (static API key) は **in-process broker-mediated `provider.call`** (ProviderAdapter の in-process HTTP、subprocess を起動せず API key を env/argv/temp-file に出さず broker 内部で消費、provider response のみ返す、SecretHandle-only invariant 不変) で **Phase 2 (real ProviderAdapter 配線時)**。**どの経路でも raw secret が子 process env に入らない**。Phase 0 は設計確定のみ。
- **URI backend 拡張** (ADR-00058): 正本 grammar `secret://<backend>/<scope>/<name>#v<n>` の backend を `secret://(sops|local)/...` へ拡張 (scheme `secret://` 不変)。単一定数 `SECRET_URI_PATTERN` (uri_pattern.py) を DB CHECK/ORM/resolver/register/test が import (5+source drift 構造防止)、未知 backend fail-closed。
- **secret backend** (ADR-00058): macOS Keychain (keyring) 先行 + cryptography Fernet 暗号化ファイル fallback。
- **host worker** (ADR-00059 と整合): worker は docker 外・host で動かす (OAuth refresh 自然動作、~/.claude 直読)。docker は postgres/redis/api/frontend。
- **loopback bind 維持** (ADR-00059): 127.0.0.1:5432/6379、restore preflight と整合。ports 撤回禁止 (過去 R2 revert 済地雷)。
- **secret revoke** (ADR-00059、adversarial R1/R2 反映): **canonical rule §5 準拠の新 revoke 経路** (`active`/`deprecated`/`pending` → `revoked` を許容、rotation.py.revoke() は rotation 専用で流用せず)、material 削除は status=revoked 後の別 step。**crash-safe**: `material_purged_at`/`purge_attempts` 列で durable に追跡し、`status='revoked' AND material_purged_at IS NULL` を idempotent purge する `secret gc-orphans` reconciliation。migration downgrade は未 purge revoked 0 件を preflight (source of truth 保護)。「revoked=削除済」は material_purged_at non-NULL で初めて真。rollback=再登録、DESTRUCTIVE approval gate。

## 実装チケット (4 stream)

| stream | 内容 | group | depends_on |
|---|---|---|---|
| **S1** secret tooling コア | uri_pattern.py 単一定数 / LocalStoreResolver / CompositeSecretResolver / SecretRefRepository.create / SecretRegistrationService / host-ambient CLI 供給 (broker 非経由) / revoke (rule §5: active/deprecated/pending→revoked) + durable reconciliation (material_reconciliation + gc-orphans)。API key の in-process provider.call は設計のみ (Phase 2 実装) | G1 (先行) | **ADR-00058 + ADR-00059 accepted** (revoke/material は ADR-00059 gate) |
| **S2** DB schema | migration 0049 (URI CHECK 拡張、revision 固定 literal、両方向) + **migration 0050 material_purge_tracking** (`material_purged_at` / `purge_attempts` additive 列 + 条件付き downgrade preflight `status='revoked' AND material_purged_at IS NULL` 0 件) + ORM 同期。S1 と密結合のため **S1+S2 を 1 PR** に統合 (cross-source-enum 単独 PR 方針) | G1 | S1, **ADR-00058 + ADR-00059 accepted** |
| **S3** deploy / taskhub CLI | host-setup.md (Mac runbook) / mac-smoke-sop drift fix / taskhub init・status・secret subcommand / docker-compose.dev credential 供給 / cli_registry.toml | G2 | S1, ADR-00058/00059 |
| **S4** verification + 正本化 | test_compose_loopback_binding / e2e (secret resolve via LocalStoreResolver, broker 内部のみ) / host-ambient CLI 供給 test / create/rotate crash-window + cross-tenant material identity test / revoke crash-window + downgrade preflight test / docker smoke (throwaway) / SP-001-5 §Review close / 進捗 doc | G3 (最終) | S1,S2,S3, ADR-00058/00059 |

## タスク一覧 (主要)

- S1: `uri_pattern.py` 単一定数 (`secret://(sops|local)/...`) → `local_store_resolver.py` (keyring+Fernet, canary redaction 再利用, raw 内部のみ) → `resolver_dispatch.py` (CompositeSecretResolver, backend dispatch, 未知 fail-closed) → `secret_ref.py` create/insert (metadata-only, server-owned uri 組立, active≤1/pending≤1) → `registration.py` (create/rotate crash-safe 順序: secret_refs row を pending+material_state=writing で commit → store へ raw 書込 (key=tenant_id+secret_ref_id) → present+active 昇格 commit。material_state + gc-orphans で crash-window 収束, self-rotating を broker-managed 登録 reject) → **host-ambient CLI 供給** (host worker が file 直読、broker 非経由) → revoke (rule §5 準拠の新経路) + durable reconciliation (`material_purged_at` 列 + `gc-orphans`)。**API key の in-process `provider.call` は設計確定のみ、実装は Phase 2**。
- S2: migration 0049 URI backend CHECK (**revision 固定 SQL literal を hardcode、`SECRET_URI_PATTERN` を import しない** = migration 不変性。drift guard test で「最新 migration の固定 literal == current `SECRET_URI_PATTERN`」を CI 強制) + **migration 0050 material_lifecycle** (`material_state` (writing/present/purging/purged) + `material_purged_at` + `purge_attempts` additive 列、create/rotate (ADR-00058 finding-2) + revoke (ADR-00059) の crash-safe source of truth、material key は `tenant_id+secret_ref_id` 束縛、条件付き downgrade preflight `status='revoked' AND material_purged_at IS NULL` 0 件 + `material_state IN (writing,purging)` 0 件 + crash-window/cross-tenant test) + ORM CheckConstraint は `SECRET_URI_PATTERN` を import (runtime source) + downgrade `secret://local/%` row preflight + `secret://sops/` 後方互換 test + **canonical 正本同期** (`.claude/rules/secretbroker-boundary.md §2` + `.claude/reference/secretbroker-contract.md §2` + `.claude/rules/core.md` + `.claude/reference/testing.md` + `.claude/agents/taskmanagedai/{code-reviewer,security-specialist}.md` を `secret://(sops|local)/...` へ additive 更新、5+source の rule/reference/agent 源を漏れなく含める)。
- S3: host-setup.md Mac section (固定 migration head 非記載, port は compose 実値) + mac-smoke-sop drift fix (3000→3900, stale head 撤廃) + taskhub init/status 最小実装 + secret subparser (getpass/stdin, argv 物理排除) + DESTRUCTIVE_SUBCOMMANDS に secret-revoke + docker-compose.dev credential 供給 + cli_registry.toml host-ambient 分類。
- S4: test_compose_loopback_binding (ports 撤回 regression guard) + e2e DB-gated (secret create→issue→redeem→LocalStoreResolver resolve が broker 内部のみ、negative: actor/run/fingerprint mismatch) + host-ambient CLI 供給 test (host worker file 直読、worker env に token 非常駐、self-rotating を broker-managed 登録 reject) + revoke crash-window test (DB revoked 後 store.delete 前 crash → gc-orphans で idempotent 収束) + docker smoke (専用 project/port/throwaway volume, 実運用 volume 非汚染) + SP-001-5 §Review close (status in_progress 維持) + 進捗 doc。

## must_ship / defer_if_over_budget 対応表

| 項目 | must_ship | defer_if_over_budget |
|---|---|---|
| LocalSecretStore + SecretRefRepository.create + URI scheme 拡張 | ✅ | - |
| host-ambient CLI 供給 (host worker file 直読、broker 非経由) | ✅ | - |
| API key の in-process provider.call (設計確定、subprocess env 注入なし) | ✅ (設計) | 実装は Phase 2 |
| docker compose dev + host worker でローカル起動 (/healthz green) | ✅ | - |
| loopback bind 正本化 + regression guard | ✅ | - |
| taskhub secret create/rotate/revoke | ✅ | - |
| host-setup.md Mac runbook | ✅ | - |
| keyring backend (macOS Keychain) | - | 暗号化ファイル単独へ degrade 可 |
| taskhub init/status 完全実装 | - | 最小 (exit 0 + 実値) で可、拡張は後 |
| docker smoke の full coverage | - | 最小 (healthz + worker pickup) で可 |

## 受け入れ条件 (exit criteria)

- ADR-00058 (CLI 認証境界=案C hybrid) + ADR-00059 (loopback + revoke) が accepted、ADR-00011 に keyring 記録。
- raw secret が DB (metadata-only) / log / argv (getpass/stdin) / artifact / audit (config_changed raw なし) / ContextSnapshot / worker process env に一切出ない (assert_no_raw_secret 全 scan PASS)。
- **境界批評 finding-2 解消**: Phase 0 の CLI 供給は host-ambient (host worker file 直読、broker 非経由、worker env に token 非常駐)。API key (Phase 2) は in-process `provider.call` (ProviderAdapter HTTP、subprocess を起動せず env/argv/temp-file に raw を出さず broker 内部で消費、provider response のみ返す) を ADR-00058 で確定 (SecretHandle-only 不変、どの経路でも子 process env に raw が入らない)。Phase 0 host-ambient test で worker env 非常駐・self-rotating broker-managed 登録 reject 確認。
- SecretBroker 不変条件維持 (atomic claim / TTL 5-30 分 / OperationContext server 再計算)。既存 broker test (redeem/negative/multi_agent) が LocalStoreResolver 差込後も全 PASS (回帰)。
- **create/rotate の material lifecycle が crash-safe**: secret_refs row (pending+material_state=writing) commit → store 書込 → present+active の順序で、store 成功/DB 失敗・DB 成功/store 失敗・途中 crash・再実行 が `material_state` + `gc-orphans` reconciliation で収束 (orphan material 残置なし / active row だが material 無し なし)。material key が `tenant_id+secret_ref_id` 束縛で **cross-tenant 同名 secret が衝突・誤解決しない** (negative test PASS)。
- revoke が canonical rule §5 (active/deprecated/pending→revoked) 準拠 (rotation.py.revoke() 流用なし、責務分離)、material 削除は revoked 後の別 step。crash-window test (DB revoked 後 store.delete 前 crash → `material_purged_at IS NULL` 残置 → `gc-orphans` で idempotent 収束) PASS。
- URI backend 5+source 整合: drift guard test で **「最新 migration の固定 literal == current `SECRET_URI_PATTERN`」** + runtime sources (ORM/resolver/register/test) の exact 一致。**active harness 正本も全て同期済** (`rules/secretbroker-boundary.md §2` + `reference/secretbroker-contract.md §2` + `rules/core.md` + `reference/testing.md` + `agents/taskmanagedai/{code-reviewer,security-specialist}.md`、二重正本なし)。migration は revision 固定 literal で不変性保持 (`SECRET_URI_PATTERN` を import しない)。未知 backend fail-closed、既存 `secret://sops/` 後方互換。migration 0049 両方向 (downgrade `secret://local/%` row preflight、alembic check PASS)。
- self-rotating credential を broker-managed 登録 reject (案B 罠の構造防止)。
- loopback bind 維持 (compose config 全 host_ip=127.0.0.1)、verify_target_binding_consistency 整合、ports 撤回 CI regression guard。
- taskhub init/status が exit 0 + 実値、taskhub secret 一式動作 (revoke は approval gate)。
- host-setup.md で clean Mac から up→alembic→seed→/healthz green→MCP stdio→worker 起動が再現可 (固定 head 非記載、port は compose 実値)。
- 本番非汚染 (seed_golden_flow_fixtures は environment==test gate、docker smoke は throwaway volume)。
- tenant/project boundary 強制 + cross-tenant 分離 negative。
- 全 stream で mypy + ruff + 該当 pytest PASS、ci-smoke backend-quality (postgres+RUN_DB_TESTS=1) green、CRITICAL 直結 PR は codex-quality-loop mode=code R{N} findings_zero (CRITICAL=0/HIGH≤2)。

## 検証手順

- `uv run mypy backend` / `uv run ruff check backend tests`。
- `TASKMANAGEDAI_RUN_DB_TESTS=1 uv run pytest tests/secrets/ tests/deploy/ backend/tests/migrations/test_secret_uri_local_scheme.py -v`。
- 既存 broker 回帰: `... pytest tests/runtime/test_secret_broker_redeem*.py tests/security/test_secretbroker_multi_agent_negative.py`。
- `alembic check` 両方向 (0049 up/down)。
- docker smoke (throwaway project/port/volume) → /healthz green → worker job pickup → down -v (検証 project のみ)。
- host-setup.md 実機検証は **user 実施** (clean Mac で full runbook、別途依頼)。

## レビュー観点

- credential injection: broker から raw forward しない / canary scan bypass しない / launcher signature 不変 (agent allowlist) / self-rotating を broker-managed 登録不可。
- raw secret 非保存全経路。atomic claim / OperationContext server 再計算の不変。
- URI scheme 5+source exact set。migration downgrade lossless。
- loopback bind regression。revoke は rule §5 準拠経路 + durable reconciliation (material_purged_at + gc-orphans、crash-window、downgrade preflight)。
- over-claim 警戒: SP-001-5 を completed 化しない (host-setup 雛形 + 実機検証は D-1 defer)。

## 残リスク

- host-ambient CLI 経路が broker 監査外 (user 承認済 trade-off、per-run 監査は cli_invocation event 依存)。
- CLI が token を stdout に echo した場合の capture 混入 → canary scan (CLI token pattern) + redaction で軽減。
- keyring supply-chain (ADR-00011 記録、暗号化ファイル fallback で degrade 可)。
- docker worker での OAuth refresh は host worker 既定で回避 (docker worker は後フェーズ検討)。

## 次スプリント候補

- Phase 1 (kill switch フル版)。Phase 2 (CLIAgentAdapter + Provider Compliance cli/subscription 行 + PR#350 fold)。

## 関連 ADR

- ADR-00058 (LocalSecretStore + URI scheme + CLI 認証境界)。
- ADR-00059 (SP-001-5 loopback 決着 + revoke material 削除)。
- ADR-00011 (keyring 依存 supply-chain、update)。
- ADR-00021 (host_portable_deployment、§12.2 internal-only は VPS 目標として retain)。

## Review

(実装後追記。各 stream の PR / Codex review round / 採否判定 / accepted 化日時 / exit 達成状況を記録。)
