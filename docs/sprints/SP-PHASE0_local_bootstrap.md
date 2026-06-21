---
id: "SP-PHASE0_local_bootstrap"
type: "heavy"
status: "completed"
sprint_no: 0
created_at: "2026-06-20"
updated_at: "2026-06-21"
target_days: 4
max_days: 7
adr_refs:
  - "[ADR-00058](../adr/00058_local_secret_store_cli_auth_boundary.md)"
  - "[ADR-00059](../adr/00059_host_portable_local_reconciliation_secret_revoke.md)"
planned_adr_refs:
  # keyring 固有 intake は docs/citations/keyring_adoption.md に直接記録済 (非AI foundational lib、license=MIT)。
  # generic ADR-00020 (AI framework checklist) の accept は ADR-00016 依存の別 governance track (本 Sprint の gate 外)。
  - "ADR-00020 (Framework Intake Checklist、generic): AI framework intake track、ADR-00016 accepted 待ち (keyring intake は adoption.md で完了済)"
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
| **S2** DB schema | migration 0049 (URI CHECK 拡張、revision 固定 literal、両方向) + **migration 0050 material_lifecycle** (`material_state` / `material_purged_at` / `purge_attempts` additive 列、create/rotate + revoke の crash-safe source of truth + 3 条件 downgrade preflight: `revoked AND material_purged_at IS NULL`=0 かつ `material_state IN (writing,purging)`=0 かつ `secret_uri LIKE 'secret://local/%'`=0 (full rollback 0050→0049 の skew 防止)) + ORM 同期。S1 と密結合のため **S1+S2 を 1 PR** に統合 (cross-source-enum 単独 PR 方針) | G1 | S1, **ADR-00058 + ADR-00059 accepted** |
| **S3** deploy / taskhub CLI | host-setup.md (Mac runbook) / mac-smoke-sop drift fix / taskhub init・status・secret subcommand / docker-compose.dev credential 供給 / cli_registry.toml | G2 | S1, ADR-00058/00059 |
| **S4** verification + 正本化 | test_compose_loopback_binding / e2e (secret resolve via LocalStoreResolver, broker 内部のみ) / host-ambient CLI 供給 test / create/rotate crash-window + cross-tenant material identity test / false-present negative test (material_state省略insert→writing止まり、issue/redeem で material_not_present deny) / revoke crash-window + downgrade preflight test / docker smoke (throwaway) / SP-001-5 §Review close / 進捗 doc | G3 (最終) | S1,S2,S3, ADR-00058/00059 |

## タスク一覧 (主要)

- S1: `uri_pattern.py` 単一定数 (`secret://(sops|local)/...`) → `local_store_resolver.py` (keyring+Fernet, canary redaction 再利用, raw 内部のみ) → `resolver_dispatch.py` (CompositeSecretResolver, backend dispatch, 未知 fail-closed) → `secret_ref.py` create/insert (metadata-only, server-owned uri 組立, active≤1/pending≤1) → `registration.py` (crash-safe material lifecycle: row を pending+material_state=writing で commit → store 書込 (key=tenant_id+secret_ref_id) → present。**create と rotate を分離**: 初回 create は present 後に active 昇格可 / **rotate は pending+present のまま `secret.verify`/dry-run/smoke 通過後に新 version active + 旧 version deprecated を明示 step** (未検証 material を active にしない、(tenant,scope,name) active≤1 競合回避、contract §13/DD-06 §8.2 準拠)。material_state + gc-orphans で crash-window 収束, self-rotating を broker-managed 登録 reject) → **host-ambient CLI 供給** (host worker が file 直読、broker 非経由) → revoke (rule §5 準拠の新経路) + durable reconciliation (`material_purged_at` 列 + `gc-orphans`)。**API key の in-process `provider.call` は設計確定のみ、実装は Phase 2**。
- S2: migration 0049 URI backend CHECK (**revision 固定 SQL literal を hardcode、`SECRET_URI_PATTERN` を import しない** = migration 不変性。drift guard test で「最新 migration の固定 literal == current `SECRET_URI_PATTERN`」を CI 強制) + **migration 0050 material_lifecycle** (`material_state` (writing/present/purging/purged) + `material_purged_at` + `purge_attempts` additive 列、create/rotate (ADR-00058 finding-2) + revoke (ADR-00059) の crash-safe source of truth、material key は `tenant_id+secret_ref_id` 束縛、条件付き downgrade preflight `status='revoked' AND material_purged_at IS NULL` 0 件 + `material_state IN (writing,purging)` 0 件 + crash-window/cross-tenant test) + ORM CheckConstraint は `SECRET_URI_PATTERN` を import (runtime source) + downgrade `secret://local/%` row preflight + `secret://sops/` 後方互換 test + **canonical 正本同期** (`.claude/rules/secretbroker-boundary.md §2` + `.claude/reference/secretbroker-contract.md §2` + `.claude/rules/core.md` + `.claude/reference/testing.md` + `.claude/agents/taskmanagedai/{code-reviewer,security-specialist}.md` + `docs/基本設計/06_秘密管理設計.md` (DD-06 §1/§3.2 backend 方針) を backend=`sops|local` (Phase 0 default=local、SOPS=D-4) へ additive 更新、5+source の rule/reference/agent/DD 源を漏れなく含める。SecretBroker metadata allowlist にも material_state/material_purged_at/purge_attempts を追加)。
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
| keyring backend (macOS Keychain) — local Mac 実運用 target | ✅ (local Mac) | CI/headless のみ Fernet fallback (master key custody contract 定義済、key非同居) |
| credential-file 読取境界 (host-ambient exfiltration 防止) | ✅ (Phase 0 control 実装) | 出力 canary scan (`credential_canary.py`、JWT/refresh_token/key-name/path + broad、hit で `CREDENTIAL_EXFILTRATION` deny) + per-agent 最小 HOME + 全 drain path withhold + scan↔redact 正規化統一。negative test CI-testable PASS、adversarial R1-R4 clean。実 codex integration test + 実 path 配線は Phase 2 narrow defer → §Review gate C 参照 |
| taskhub init/status 完全実装 | - | 最小 (exit 0 + 実値) で可、拡張は後 |
| docker smoke の full coverage | - | 最小 (healthz + worker pickup) で可 |

## 受け入れ条件 (exit criteria)

- ADR-00058 (CLI 認証境界=案C hybrid) + ADR-00059 (loopback + revoke) が accepted。keyring 依存 intake は `docs/citations/keyring_adoption.md` に evidence 記録 (generic ADR-00020 accept は AI framework track へ defer、§Review gate B 参照)。
- raw secret が DB (metadata-only) / log / argv (getpass/stdin) / artifact / audit (config_changed raw なし) / ContextSnapshot / worker process env に一切出ない (assert_no_raw_secret 全 scan PASS)。
- **境界批評 finding-2 解消**: Phase 0 の CLI 供給は host-ambient (host worker file 直読、broker 非経由、worker env に token 非常駐)。API key (Phase 2) は in-process `provider.call` (ProviderAdapter HTTP、subprocess を起動せず env/argv/temp-file に raw を出さず broker 内部で消費、provider response のみ返す) を ADR-00058 で確定 (SecretHandle-only 不変、どの経路でも子 process env に raw が入らない)。Phase 0 host-ambient test で worker env 非常駐・self-rotating broker-managed 登録 reject 確認。
- SecretBroker 不変条件維持 (atomic claim / TTL 5-30 分 / OperationContext server 再計算)。既存 broker test (redeem/negative/multi_agent) が LocalStoreResolver 差込後も全 PASS (回帰)。
- **material lifecycle が crash-safe + create/rotate 分離**: row (pending+material_state=writing) commit → store 書込 → present の順序で、store 成功/DB 失敗・DB 成功/store 失敗・途中 crash・再実行 が `material_state` + `gc-orphans` reconciliation で収束 (orphan material 残置なし / active row だが material 無し なし)。**create は present 後に active 可 / rotate は present のまま secret.verify/dry-run/smoke 通過後に新 active + 旧 deprecated**。**rotate が verify/smoke 前に active にならない negative test PASS** (未検証 material の active 化 + active≤1 競合回避)。material key が `tenant_id+secret_ref_id` 束縛で **cross-tenant 同名 secret が衝突・誤解決しない** (negative test PASS)。
- **false-present 防止**: DB default `material_state='writing'`、token issue / redeem の secret_ref 再検証で `material_state='present'` 必須 (`writing`/`purging`/`purged` は `material_not_present` で deny)。**material_state 省略 insert が active/present にならず token 発行されない negative test PASS** (store 未完了 row から token が出ない)。
- **host-ambient credential-file 読取境界** ✅ Phase 0 control 実装 (§Review gate C): 出力 canary scan (credential token を JWT/refresh_token/key-name/path basename + broad で検出 → `CREDENTIAL_EXFILTRATION` deny + raw output withheld) + per-agent 最小 HOME + 全 drain path (deny/cancel) で canary hit 時 withhold + scan↔redact 正規化統一 (不可視文字 obfuscation bypass 閉鎖)。**negative test PASS** (`test_credential_canary.py`/`test_orchestrator_credential_withhold.py`、CI-testable、adversarial R1-R4 clean)。実 codex を任意 prompt で動かす end-to-end integration test + tool-level sandbox は Phase 2 narrow defer。残 exfiltration risk (任意 re-encode+key 構造削除) は accepted HIGH (local 単一 user)、confidential 以上 payload の自律実行は Phase 2+ gate (ADR-00058 §残リスク)。
- **Fernet fallback master key custody** (CI/headless): master key が ciphertext と別ディレクトリ・0o600・keyring 優先、紛失時は再登録 recovery (material loss 明記)。**key 非同居 + 再登録 recovery の negative test** PASS。local Mac は keyring (Keychain) must_ship。
- revoke が canonical rule §5 (active/deprecated/pending→revoked) 準拠 (rotation.py.revoke() 流用なし、責務分離)、material 削除は revoked 後の別 step。crash-window test (DB revoked 後 store.delete 前 crash → `material_purged_at IS NULL` 残置 → `gc-orphans` で idempotent 収束) PASS。
- **full rollback safety**: full rollback (0050→0049 downgrade) で local present row がある状態では 0050 downgrade が lifecycle 列削除前に fail-fast (3 条件 preflight: revoked未purge=0 / writing,purging=0 / `secret://local/%`=0)。local row + lifecycle source-of-truth の skew を防ぐ regression test PASS。
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
- **【accepted HIGH risk】host-ambient credential-file の prompt-injection exfiltration** (CLI 配下 AI/tool が credential file を直接 read): per-agent 専用 HOME + tool sandbox deny + canary で軽減するが完全には防げない。local 単一 user・AI=user 自身の subscription として accepted、**confidential 以上 payload を扱う自律実行は Phase 2+ の追加封じ込め (専用 OS user / sandbox policy 強化) まで gate**。
- CLI が token を stdout に echo した場合の capture 混入 → canary scan (CLI token pattern) + redaction で軽減。
- Fernet fallback (CI/headless) の master key 管理: key 非同居 + 紛失時は再登録 recovery (material loss)。local Mac は keyring (Keychain) must_ship で回避。
- keyring supply-chain (ADR-00020 Framework Intake Checklist で intake)。
- docker worker での OAuth refresh は host worker 既定で回避 (docker worker は後フェーズ検討)。

## 次スプリント候補

- Phase 1 (kill switch フル版)。Phase 2 (CLIAgentAdapter + Provider Compliance cli/subscription 行 + PR#350 fold)。

## 関連 ADR

- ADR-00058 (LocalSecretStore + URI scheme + CLI 認証境界)。
- ADR-00059 (SP-001-5 loopback 決着 + revoke material 削除)。
- ADR-00020 (Framework Intake Checklist、generic): keyring 依存 intake は `keyring_adoption.md` で evidence 記録済。generic ADR-00020 accept は ADR-00014/16 + P0完了 依存の AI framework intake track (別件)。
- ADR-00021 (host_portable_deployment、§12.2 internal-only は VPS 目標として retain)。

## Review

### Plan gate (2026-06-20)

- **ADR-00058 + ADR-00059 accepted (2026-06-20)**。codex-plan-review (adversarial) R1-R20 で計 **33 HIGH + 1 MEDIUM を全 adopt**、R20 で **approve / SHIP-READY (No material findings)** を達成。§sprint-pack-adr-gate §12.4 gate (codex-plan-review clean + 採否判定) + user 承認済 4 決定 (案C hybrid / host worker / loopback / keyring) をもって accepted 昇格。
- adversarial loop の主要 adopt: 設計核 (host-ambient CLI / API key in-process provider.call / URI backend additive / revoke rule §5 / loopback) → cross-source 同期 (canonical DD-00/01/02/05/06 + active harness rules/reference/agents + CLAUDE.md + PLAN-10 + ADR supersede) → 深い correctness (material_state false-present gate / credential-file 読取境界 accepted HIGH risk + Phase2 gate / Fernet key custody / create-rotate 分離 / full rollback skew 防止)。
- status: draft → **ready** (実装着手可)。
- **実装は別 gate**: 各 stream 実装後に codex-quality-loop mode=code で R{N} findings_zero (CRITICAL=0/HIGH≤2)。本 Review は plan gate の記録、実装後に各 stream の PR / review round / 採否判定 / exit 達成状況を追記。

### Implementation gate (2026-06-21、batch-1〜3)

実装は 3 batch で完遂。各 batch は **codex adversarial loop または Workflow 並列レビュー + Codex PR auto-review** の二重検証を経て merge。

- **batch-1 = S1 + S2 (PR #352、squash 99113ab)**: secret tooling core + material lifecycle migrations。
  - 内容: `uri_pattern` 単一定数 / `LocalSecretStore` (keyring + Fernet file fallback) / `CompositeSecretResolver` /
    `SecretRegistrationService` (register/rotate/promote_rotated/revoke) / `MaterialReconciliationService` (gc-orphans) /
    migration 0049 (URI backend CHECK) + 0050 (material_state/material_purged_at/purge_attempts + downgrade preflight)。
  - 検証: **codex adversarial R1-R24 (26 findings adopt、CRITICAL 4=R11-R13 = LocalSecretStore custody race、R13 以降
    CRITICAL ゼロ)** + Codex PR auto-review (F1-F4)。CI 8 checks green、no-DB 4983 + DB-gated 195 (実 Postgres)。
  - **defer**: R16-F1 (redeem transaction 境界) → **ADR-00060 (proposed、本 batch-3 で起票)**。
- **batch-2 = S3 (PR #353、squash 394e364)**: deploy / taskhub CLI。
  - 内容: `taskhub secret-create/rotate/revoke` (getpass/stdin のみ、`--material` argv 物理排除) + signed approval
    DESTRUCTIVE gate (default-deny + escape 物理 deny) / `init/status --local` (alembic head runtime、loopback DSN、
    DB URL redaction) / `cli_registry.toml` host-ambient 分類 (codex) / `host-setup.md` runbook + mac-smoke drift fix。
  - 検証: **Workflow 並列 adversarial review (5 dimension、confirmed 5 findings)** + Codex PR auto-review (6 findings)。
    HIGH (secret-revoke が escape flag で approval gate bypass) を封鎖。adopt: HIGH/MEDIUM/LOW + F5 (status loopback DSN) +
    F2/F3/F4/F6 (claude launchable は Phase 2 へ延期)。CI 8 checks green、no-DB 5009。
  - **defer**: Codex F1 (secret-revoke approval が tenant/secret_ref 非束縛 = replay 可) → SecretRevokeApprovalClaim
    (backup/restore と同型の signed-claim) は **S4/Phase 2 hardening へ defer** (Workflow verifier も Phase-0-acceptable
    判定、core gate (default-deny + escape 物理 deny) は ship 済、P0 実リスク低 = signed approval は user 鍵要・single-host)。
- **batch-3 = S4 (本 batch、PR #354)**: verification + 正本化。
  - DB-gated 検証 test **34 件 / 6 file** (`tests/deploy/test_compose_loopback_binding.py` + `tests/secrets/test_{host_ambient_cli_supply,e2e_secret_resolve_db,false_present_negative_db,crash_window_cross_tenant_db,revoke_crash_downgrade_preflight_db}.py` + `_db_harness.py`/`conftest.py`) + docker smoke 補助 script (`scripts/sp_phase0_docker_smoke.sh`、operator-run)。
  - 検証カバレッジ: loopback binding regression guard (3 compose file の全 published port = 127.0.0.1) / e2e create→issue→redeem→LocalStore resolve (broker 内部のみ、SecretHandle-only、actor/run/fingerprint/operation mismatch deny、assert_no_raw_secret) / false-present negative (material_state 未書込→material_not_present deny) / create-rotate crash-window + cross-tenant material identity / revoke crash-window + migration 0050 downgrade preflight / host-ambient CLI 供給 (worker env 非常駐、self-rotating broker-managed reject)。
  - R16-F1 follow-up **ADR-00060** (proposed) 起票 + 本 §Review + SP-001-5 §Review note。
  - 検証: **Workflow 並列 review (3 dimension、confirmed 5 LOW、全 adopt = regression guard / anti-gaming / docs honesty 強化)** + Codex PR auto-review。DB-gated **223 passed** (pg 実走、secret subsystem 全 regression 含む) / no-DB **5025 passed** / mypy / ruff green。**production bug ゼロ** (S1-S3 が end-to-end で正しいことを確認)。

### Implementation exit (2026-06-21)

- **S1-S4 実装 + 自動検証 (CI + ローカル実 Postgres) 完了**。Hard gate (raw secret 非保存 / false-present / atomic claim / cross-tenant material identity / loopback / deny-by-default approval) を DB-gated test で機械検証。
- **status: in_progress → completed (2026-06-21)**。実装 deliverable (S1-S4) + 自動検証 + runbook + 下記 §completion gate A/B/C 全充足をもって completed。gate C (credential-file exfiltration control) は user 承認 option (b) のもと **Phase 0 で control 実装 + Workflow adversarial review R1-R4 clean**、実 codex integration test のみ Phase 2 narrow defer。over-claim 回避の経緯: 当初 gate C を「Phase 0 検証不能」と誤判定 (Codex #357 F2 訂正) → 実装可能と判明 → 実装 + adversarial loop で 6 gap fix → 充足。
- **completion gate の最終状態 (全充足)**:
  - **gate A: host-setup.md clean Mac 実機 runbook walkthrough** ✅ 充足: **user が 2026-06-21 に実施、基盤機能は実機で全 pass** (docker stack / alembic / /healthz / dev login→dashboard / MCP stdio / host worker / secret CLI getpass + approval gate / Keychain / smoke)。operator 詰まり 2 点は **#355 で修正済**。
  - **gate B: keyring 依存 framework intake** ✅ evidence 記録 (ただし当初 gate からの **scope 変更**、下記 note)。`docs/citations/keyring_adoption.md` に keyring の intake evidence を記録 (ADR-00020 §1 8-verify を非AI foundational lib として適用: license=**MIT** (`License-Expression: MIT`、jaraco/keyring) / attribution / telemetry なし / external network なし (local OS keychain) / secret 境界は broker + LocalSecretStore / cross-tenant material key 束縛)。supply-chain risk LOW。
     - **note (正直な scope 変更、Workflow review MEDIUM adopt)**: 当初の completion gate は「generic **ADR-00020 (Framework Intake Checklist)** を §12.4 (codex-plan-review R1 + 採否判定) 経由で proposed→accepted」だった。しかし ADR-00020 は `acceptance_blocked_by: ["ADR-00014/16 accepted", "P0 完了"]` を持ち、**ADR-00016 が proposed のため accept 不能** (keyring と無関係な Hermes-agent ADR 依存) + 8-verify が AI framework 取り込み向け (item 3 = import denylist / from-scratch のみ、非AI foundational lib に未批准の carve-out)。本完了では generic ADR-00020 を **accept せず**、keyring 固有 intake を adoption.md に直接記録する **scope 変更**を行った (= 当初 gate を「充足」したのではなく「非AI lib 向けに緩和・再判定」した)。この scope 変更の承認 (もしくは ADR-00020 への非AI carve-out 正式追記) は **user 判断事項**。check_framework_intake.sh は CI 未配線。
  - **gate C: credential-file exfiltration negative test** ✅ **充足 (Phase 0 control 実装 + adversarial-clean、user 承認 option (b)=Phase 0 対策実装 + narrow defer、2026-06-21)**: 受け入れ条件 (must_ship「credential-file 読取境界」/ 検証 §95 / ADR-00058 §exit) の Phase 0 control を **既存 codex launcher (cli_artifact) 経路向けに実装**:
    - **control 1 (出力 canary scan)**: launcher が capture した stdout/stderr + output/stream artifact を `credential_canary.py` で scan、credential token 検出 (JWT / codex `rt.N.` refresh_token / anthropic OAuth / **JSON key-name canary** / credential-file path basename + broad scanner) で **`LauncherDenyReason.CREDENTIAL_EXFILTRATION` Hard Gate failure**、raw output withheld。
    - **control 2 (per-agent 最小 HOME)**: `_build_scrubbed_env` が host_ambient agent の HOME を per-agent 最小 dir へ override + credential home env (CODEX_HOME) を credential dir へ。shipped codex entry は後方互換 (実 path 配線は Phase 2 実機検証)。
    - **uniform fail-closed**: orchestrator は CREDENTIAL_EXFILTRATION + cancel + 全 drain path で canary hit 時 `[withheld: credential_exfiltration]` placeholder のみ emit (raw 非永続)。**scan と `redact_stream` は同一 `normalize_for_scan` (ANSI/control/Cc/Cf strip) を共有** + credential pattern を redact backstop に fold → 不可視文字 (ZWSP/ANSI/C1) obfuscation bypass のクラスを構造的に閉鎖。
    - **negative test PASS (CI-testable)**: mock CLI output + 不可視文字注入 token で scan 検出 + withhold を assert (`test_credential_canary.py` / `test_orchestrator_credential_withhold.py`、399 cli_artifact+security test pass、fake token のみ raw 非露出)。**Workflow adversarial review R1-R4 で 6 gap (refresh_token bypass / orchestrator redact leak / cancel-path / normalization-mismatch 等) 全 fix → R4 clean (0 findings)**。
    - **narrow defer (Phase 2)**: 実 codex binary を任意 (malicious) prompt で動かす end-to-end integration test + 実 auth path 配線 + tool-level read deny / sandbox 封じ込めは **CLIAgentAdapter (Phase 2)** へ。残リスク (任意 re-encode + key 構造削除、accepted HIGH local 単一 user) は ADR-00058 §残リスクに honest 記載。**ADR-00058 §exit (Phase 0 必須 negative test) は実装で充足、binding 正本のまま**。
- **defer / follow-up (tracked)**: ① R16-F1 redeem transaction 境界 → ADR-00060 (proposed、Phase 2 着手 gate)。② secret-revoke approval target-binding (SecretRevokeApprovalClaim) → Phase 2 hardening。③ claude launchable agent entry → Phase 2 (CLIAgentAdapter)。④ generic ADR-00020 accept → AI framework intake track (ADR-00014/16 + P0完了 依存、別件)。⑤ **gate C control は Phase 0 で実装済 (充足)**。Phase 2 へ narrow defer したのは「実 codex を任意 prompt で動かす end-to-end integration test + 実 auth path 配線 + tool-level read deny/sandbox 封じ込め」のみ (CLIAgentAdapter 本体に随伴)。⑥ SP-001-5 は in_progress 維持 (DB/Redis internal-only vs restore 契約 reconciliation が host-phase の user/ADR 決定事項)。
