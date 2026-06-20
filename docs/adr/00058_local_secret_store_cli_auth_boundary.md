---
id: "ADR-00058"
title: "LocalSecretStore resolver + secret_uri local backend segment 拡張 (secret://local/...) + CLI サブスク認証 vs API token の境界決定"
status: "proposed"
date: "2026-06-20"
authors:
  - "Claude (autonomous, user 承認 scope: 大元計画 Phase 0 + ADR Gate 4 決定 user 確認済)"
related_sprints:
  - "SP-001-5_host_portable_amendment"
  - "PLAN-10 (大元計画 Phase 0)"
supersedes: "ADR-00006 (partial amendment: secret_ref URI を backend=sops|local へ拡張 + storage backend に local 追加。atomic claim / capability token / raw 非保存 / OperationContext fingerprint の中核 invariant は不変・継承)"
superseded_by: null
---

> **正本更新 (supersede scope)**: 本 ADR は ADR-00006 (秘密管理方式) の **secret_ref URI format と secret storage backend の固定** を partial に amend する (中核 invariant は継承)。既存設計コーパスへの影響:
> - **active harness 正本 (本 ADR で同期済、5+source)**: `.claude/rules/secretbroker-boundary.md §2/§4` / `.claude/reference/secretbroker-contract.md §2/§4/§13` / `.claude/rules/core.md` / `.claude/reference/testing.md` / `.claude/agents/taskmanagedai/{code-reviewer,security-specialist}.md` / `docs/基本設計/06_秘密管理設計.md (DD-06)` を backend=`sops|local` (Phase 0 default=`local`、SOPS=D-4) へ更新済。
> - **historical/design 正本 (本 ADR が supersede、個別編集不要)**: PRD-00 / DD-00 / DD-01 / DD-02 / DD-05 / ADR-00006 / ADR-00036 / SP-000 / 計画(仮) 等が示す `secret://sops/<scope>/<name>#<version>` は **`sops` backend の有効な例**として残る (sops は引き続き有効な backend)。「P0 標準は SOPS のみ」を排他的に読む箇所は本 ADR の backend=`sops|local` 決定が優先する。SECRET_URI_PATTERN を runtime の唯一の source of truth とする。

ADR Gate Criteria #6 (Secrets 管理方式) + #2 (DB schema: secret_uri CHECK 拡張 + 5+source 整合 + migration 両方向) に該当。大元計画 (PLAN-10) Phase 0 の中核。実行エンジン = CLI 主 (claude / codex をサブスク認証で headless subprocess 実行) という確定方針に対し、CLI サブスク credential をどう供給するか、raw secret 非保存境界を破らずに正式決定する。**user 確認ゲート: 案C hybrid / host worker / keyring+fallback を user 承認済 (2026-06-20)**。

最終更新: 2026-06-20

> **status: proposed**。Phase 0 詳細設計 workflow (4ストリーム並列設計→境界批評→最終化) の成果。境界批評が初期設計を **REFUTE** (broker が resolve した raw を launcher へ forward する seam は SecretBroker §10「値を返す API ではない」を破る) し、修正版 (CLI=host-ambient で broker 非経由、API key=broker 内 in-process `provider.call` で subprocess/env/argv/temp-file に raw を出さない) に到達。adversarial R1-R7 で計 12 HIGH + 1 MEDIUM を adopt。実装着手直前に codex-plan-review clean + 採否判定 を経て accepted へ昇格 (sprint-pack-adr-gate §12.4)。

## 背景

- 決定対象:
  1. **LocalSecretStore resolver** の新設 (簡易 local secret store、SOPS+age は後フェーズ D-4)。
  2. **secret_ref URI backend segment** を拡張。正本 grammar は `secret://<backend>/<scope>/<name>#v<n>` (scheme は `secret://`、`sops` は backend segment、secretbroker-boundary.md §2)。現状 `secret://sops/...` 固定の backend を `secret://(sops|local)/...` へ additive 拡張する (scheme `secret://` は不変、backend に `local` を追加)。
  3. **CLI サブスク認証 vs API token の境界** (本 ADR の最重要・user 確認ゲート)。
  4. **credential 境界の確定**: CLI credential は host-ambient (CLI が file を自読、broker 非経由)、API key は broker 内 in-process `provider.call` で消費。**subprocess / env / argv / temp-file への raw material serialization は全経路で不可** (境界批評 R6/R7 反映)。
- 関連 Sprint: PLAN-10 Phase 0 / SP-001-5 (host-portable) / SP-006 (cli_artifact、launcher の env scrub が tension の核)。
- 前提 / 制約:
  - 実行エンジン = CLI 主 + API 切替可 (大元計画 §0 確定)。worker は host で動かす (host worker、ADR-00059 と整合)。
  - **実機事実 (Phase 0 設計で確認)**: CLI サブスク credential は self-rotating OAuth token。claude = `~/.claude/.credentials.json` (accessToken / refreshToken / expiresAt) + macOS Keychain、codex = `~/.codex/auth.json` (tokens.refresh_token / access_token、subscriptionType=max / auth_mode=chatgpt)。**CLI 自身が in-place で自動 refresh** する。
  - SecretBroker 不変条件は維持: raw secret 非保存 (DB/log/artifact/audit/ContextSnapshot/worker process env/argv)、capability token TTL 5-30 分 / one-time atomic claim redeem / actor-run-fingerprint binding、**broker は secret 値を返す API ではない** (broker.py は operation callback に SecretHandle(metadata) のみ渡し raw を即 `del`、secretbroker-boundary.md §10)。
  - enum / 横断不変条件を増やさない。URI scheme 拡張は scheme regex の追加のみ (scope/name/version 構造不変)。

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: 全 host-ambient | CLI も API key も全て SecretBroker 境界外。CLI が credential lifecycle を所有 | 実装最小・最堅牢、refresh 自然動作 | API key (static) も broker の atomic claim / fingerprint 監査を受けられない |
| B: 全 broker-managed | CLI credential も secret_ref 登録→redeem→注入、全 secret を一律 broker 境界へ | 全 secret が一貫した監査経路 | **構造的に不可能**: OAuth を CLI が in-place refresh → broker 注入 token を CLI が上書き → broker material が即 stale → 次 redeem で expired token → 全 run 失敗。rotation 整合不能。raw OAuth を broker 保持で token theft blast radius 拡大 |
| C: hybrid (採用) | CLI サブスク = host-ambient (境界外、CLI 所有)、API key (副次・static) のみ broker-managed | 各 credential の性質 (OAuth=self-rotating vs API key=static) に最適な境界。CLI 主・API 副次 (大元計画 §0) と整合 | 2 経路 (CredentialSupplyMode) の境界を実装/test で分離管理。host-ambient の per-run 監査 trade-off を user 承認が必要 (本 ADR の確認ゲート) |

## 採用案

- 採用: **案C hybrid** (user 承認済 2026-06-20)。
- 理由: 案B は OAuth self-rotating により構造的に不可能 (実機確認)。案A は static API key の broker 監査を捨てる。案C は credential の性質ごとに最適境界を選び、大元計画の CLI 主・API 副次と完全整合する。
- 実装 Sprint: PLAN-10 Phase 0。
- 実装対象ファイル:
  - `backend/app/services/secrets/local_secret_store.py` (新規、LocalSecretStore: macOS Keychain via `keyring` 先行 + cryptography Fernet 暗号化ファイル fallback、DB 非保存。**material key は `tenant_id + secret_ref_id` (DB 上一意な所有者) に束縛** — 例: keychain service=`taskhub:<tenant_id>:<secret_ref_id>` / file=`~/.taskhub/secrets.d/<tenant_id>/<secret_ref_id>.enc` 0o600。name の sha256 だけだと cross-tenant 同名 secret が衝突・誤解決するため不可)
  - `backend/app/services/secrets/secret_registration.py` (新規、SecretRegistrationService: create/rotate で store へ raw 委譲 + secret_refs metadata row を **crash-safe な順序**で調停)
  - `backend/app/repositories/secret_ref.py` (modify、`create()/insert()` 追加、metadata-only、現状 get/list のみ) — **Phase 0**
  - `backend/app/services/secrets/uri_pattern.py` (新規、`SECRET_URI_PATTERN` 単一定数 = `secret://(sops|local)/<scope>/<name>#v<n>` の唯一の source of truth) — **Phase 0**
  - `backend/app/db/models/secret_ref.py` (modify、URI CHECK を `secret://(sops|local)/...` 併許容、`SECRET_URI_PATTERN` を import) — **Phase 0**
  - `migrations/versions/00NN_secret_uri_local_backend.py` (新規、CHECK 拡張、両方向 + downgrade `secret://local/%` row 不在 preflight。**revision 固定 SQL literal を hardcode、`SECRET_URI_PATTERN` を import しない** = migration 不変性、drift guard で current 定数と一致を CI 強制) — **Phase 0**
  - `config/cli_registry.toml` (modify、claude/codex は host-ambient 分類を明記。API transport の API key は CLI に渡さない=`credential_env_mapping` は不要) — **Phase 0 (分類記載)**
  - API key の broker-managed 経路は **既存 SecretBroker `provider.call` operation + ProviderAdapter (in-process HTTP)** を使う (新規 spawn primitive は作らない)。API key は broker 内部の in-process HTTP client でのみ materialize し、**subprocess を起動しない / env・argv・temp-file に raw を出さない** (§10 broker-mediated operation、SP-034 教訓「in-process httpx > subprocess」) — **Phase 2 (real ProviderAdapter 配線時)**
  - `backend/app/services/cli_artifact/launcher.py` (modify、host-ambient は HOME 経由自然参照のみ。launcher に raw secret を注入する経路は作らない、signature 不変) — **Phase 0**
  - `pyproject.toml` (modify、`keyring` 依存追加、cryptography は既存) — **Phase 0**
- 実装ガイダンス:
  - **CredentialSupplyMode** を 2 経路に分離:
    - `host_ambient` (CLI サブスク、**Phase 0 実装**): worker が host で動くため `~/.claude` / `~/.codex` を CLI が直読。**broker を一切介さない** (host worker の HOME 経由)。raw token は worker env/argv/artifact/audit/DB に出ない (CLI が file/keychain 直読、TaskManagedAI が raw に触れない)。per-run 監査は `cli_invocation_started` / `cli_process_completed` event (registry agent / actor / workdir / redaction_hit_count) に記録。**Phase 0 はこの経路のみ** (CLI 実行は host worker が credential file を直読、broker 注入なし)。
  - **【境界批評 R16 finding-1 反映: credential-file 読取境界】** host-ambient は CLI 自身が credential file を読む設計のため、**CLI 配下の AI/tool 層が prompt-injection で `cat ~/.codex/auth.json` / `~/.claude/.credentials.json` を読み exfiltrate するリスク**が残る (env/argv 非露出・stdout redaction では防げない)。Phase 0 mitigation: ① **per-agent-type の専用最小 HOME / credential dir** を用意し、その CLI の auth file のみを置く (他 secret を同居させない、blast radius 最小化) ② cli_artifact launcher の forbidden_path/tool sandbox で credential file path への AI/tool 経由アクセスを deny (CLI 本体の auth 読取は許可、AI tool 層の任意 read は禁止) ③ artifact/stdout の canary scan で CLI 固有 token 形を検出 (exfiltration 試行を Hard Gate failure 化) ④ それでも残る分は **accepted HIGH risk (local 単一 user・AI は user 自身の subscription) として明記し、confidential 以上の payload を扱う自律実行は Phase 2+ の追加封じ込めまで gate**。Phase 0 exit に **credential-file exfiltration negative test** (`cat <credential>` 相当が deny される / raw token が artifact に残らない) を必須化。
    - `broker_managed` (API key、副次、**Phase 2 実装** = API transport): static API key を secret_ref 登録 → **broker-mediated in-process `provider.call` operation** で消費。API transport は ProviderAdapter の **in-process HTTP client** で provider を呼ぶ (subprocess を起動しない)。**self-rotating credential は broker_managed 経路へ登録できない validation を register 時に enforce** (案B の罠を構造防止)。
  - **【境界批評 finding-1 (R6) 反映: API key は subprocess env に出さない】**API transport の broker-managed API key は、**subprocess env/argv/temp-file に一切 serialize しない**。CLI transport は subprocess だが host-ambient (CLI が credential file を自分で読む、TaskManagedAI が raw に触れない)、API transport は subprocess を使わず broker 内部の in-process HTTP client で API key を消費する。よって **どの経路でも raw secret が子 process の env/argv に入らない** (PLAN-10 横断制約「raw secret を CLI subprocess env/argv に出さない」+ SecretBroker §10「runner env への secret 注入禁止」と完全整合)。API key の消費は既存 `redeem_capability_token` + `provider.call` operation の中で broker が in-process に行い、operation_result (provider response) のみを caller に返す (raw key は broker 内部で del/zeroize、§10 SecretHandle-only 不変)。launcher signature は不変。
  - launcher の `assert_no_raw_secret(env)` (caller-influenced env を canary scan) は維持し、host-ambient でも worker env に secret が混入しないことを spawn 前に確認。CLI が stdout/stderr に token を echo した場合に備え capture に canary scan (CLI 固有 token 形 Claude accessToken / Codex refresh_token を pattern 登録)。
  - API transport の provider response も `assert_no_raw_secret` + redaction を通す (in-process でも log/artifact に raw を残さない)。
  - **【境界批評 R7 finding-2 反映: create/rotate material lifecycle + identity】** material は `tenant_id + secret_ref_id` に束縛 (cross-tenant 同名衝突防止)。create/rotate の **crash-safe 順序**: ① secret_refs row を `pending` + `material_state='writing'` で INSERT/commit (DB が material owner の source of truth) → ② store へ raw 書込 (key=tenant_id+secret_ref_id) → ③ row を `material_state='present'` + (create 時) `active` 昇格 commit。途中 crash / store 失敗 / DB 失敗を `material_state` (`writing`/`present`/`purging`/`purged`) + reconciliation で収束: `material_state='writing'` のまま放置された row は `secret gc-orphans` が store の有無を確認し再試行 or rollback (orphan material 削除 + row 破棄)。idempotency key で再実行を冪等化。revoke 側の `material_purged_at` と対称な create 側 durable tracking。**DB default は `material_state='writing'`** (省略 insert が false-present にならない安全側)、migration 0050 は既存 active/deprecated 行を `present` へ backfill。**token issue / redeem の secret_ref 再検証で `material_state='present'` を必須化** (`writing`/`purging`/`purged` は `material_not_present` で deny、boundary §7/§9)。これにより store 未完了の false-present row から token が出ない。
  - **keyring 依存** (user 承認済): macOS Keychain backend。**local Mac (Phase 0 実運用 target) では keyring は must_ship** (Keychain が OS-level に master/material を保護)。cryptography Fernet 暗号化ファイル fallback は **CI Linux headless / Keychain 不在環境専用**。supply-chain audit 対象として uv.lock pin + SBOM 対象化 (ADR-00011 §digest pinning/SBOM 観点)。
  - **【境界批評 R16 finding-2 反映: Fernet fallback master key custody contract】** file-only fallback の Fernet master key は **ciphertext と同居させない**: ① master key は OS keychain (keyring) に格納し、不在環境のみ `~/.taskhub/keyring.d/master.key` に **0o600 + ciphertext (`secrets.d/`) と別ディレクトリ**で保存 ② key 生成は CSPRNG (Fernet.generate_key、32B base64url) ③ file format に version header (`v1`) + per-secret nonce/salt は Fernet が内包 ④ permission 検証 (0o600 でなければ起動時 fail) ⑤ rotation/rekey: 新 master key 生成 → 全 material 再暗号化 → 旧 key 破棄 (taskhub secret rekey) ⑥ backup/restore: master key は backup 対象だが ciphertext と別経路 (同梱しない) ⑦ **紛失時は復号不能 = material loss** を明記し、紛失=該当 secret_ref を `revoked` + 再登録で recovery (rollback=再登録、ADR-00059) ⑧ multi-host 移行は master key + ciphertext の両方を移送 (D-1 で profile 化)。**fallback-only 環境の confidentiality (key 非同居) + recoverability (再登録 path) を exit の negative test で検証**。
  - URI 全体 regex (`secret://(sops|local)/<scope>/<name>#v<n>`、components_match も backend 可変) の current contract は単一定数 `SECRET_URI_PATTERN` (uri_pattern.py)。**runtime sources** = ORM CheckConstraint / resolver dispatch / register validation / test EXPECTED が `SECRET_URI_PATTERN` を import (5+source drift 構造防止)。未知 backend は fail-closed deny。
  - **【境界批評 R4 finding-1 反映: migration 不変性】Alembic migration は `SECRET_URI_PATTERN` を import しない**。migration は **revision 固定の SQL literal** を hardcode で commit する (runtime 定数の後日変更が過去 revision の fresh-DB 適用結果を書き換えると、同 revision 名で既存 DB は旧 CHECK / fresh DB は新 CHECK となり fail-open/fail-closed・downgrade preflight 判定が環境分岐する事故を防ぐ)。**drift guard test は「最新 migration の固定 literal」と current `SECRET_URI_PATTERN` を明示比較**し、両者一致を CI で強制 (定数を変えたら新 migration を追加する規律)。downgrade preflight の `secret://local/%` 判定も migration 内固定 literal を使う。
- テスト指針:
  - `tests/secrets/test_local_secret_store.py`: store/resolve/delete round-trip、keychain→暗号化ファイル fallback、0o600 perm、symlink/path traversal reject、URI scheme reject negative。
  - `tests/secrets/test_secret_registration.py`: create で raw が DB/return/audit に出ず metadata row active のみ (`assert_no_raw_secret` PASS)、(tenant,scope,name) active≤1/pending≤1 違反 reject、cross-tenant 分離。**create/rotate crash-window (finding-2)**: ① store 書込成功・DB commit 前 crash → `material_state='writing'` row 残置 → `gc-orphans` が store material を rollback 削除 + row 破棄、② DB `pending+writing` commit 後・store 書込前 crash → `material_state='writing'` + store 空 → reconciliation が再試行 or row 破棄、③ **cross-tenant 同名 secret 2 件** (tenant A/B 同 scope/name) で material が `tenant_id+secret_ref_id` 束縛により衝突・誤解決しない、④ 再実行 idempotent。
  - `tests/secrets/test_cli_credential_host_ambient.py` (**Phase 0**): host-ambient で CLI が file 直読、worker process env に token 非常駐 (spawn 前後 os.environ 差分なし)、argv 非露出、`self-rotating credential を broker_managed 登録すると reject` (案B 罠の構造防止)。
  - `tests/secrets/test_api_key_provider_call.py` (**Phase 2**): broker-mediated `provider.call` で API key が broker 内部の in-process HTTP client でのみ消費され、**subprocess を起動しない / 子 process env・argv・temp-file に raw が出ない**、provider response (operation_result) のみ caller に返り raw key は返さない (broker 内部 del/zeroize)、response/log に `assert_no_raw_secret`、caller が credential を直接渡せない (signature 物理削除) negative。
  - migration 両方向 + downgrade preflight (`secret://local/%` row 不在検証)。
  - 実コード review: API transport の provider.call 経路 (Phase 2) は §14.1 CRITICAL gate → codex-adversarial-review mode=code で findings_zero (CRITICAL=0/HIGH≤2)。Phase 0 の secret tooling (resolver/create/register/revoke/host-ambient 供給) も CRITICAL invariant 直結のため同 gate。

## 却下案

- A (全 host-ambient): static API key の broker 監査 (atomic claim / fingerprint / audit trail) を捨てる。API key は self-rotating でなく broker 管理可能なので、監査を享受しない理由がない → 却下。
- B (全 broker-managed): OAuth self-rotating により構造的に不可能 (実機確認、broker 注入 token を CLI が refresh 上書き → 即 stale → 全 run 失敗) → 却下。raw OAuth を broker 保持する token theft blast radius も劣る。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| host-ambient CLI 経路が broker 監査外 (atomic claim/fingerprint なし) | `cli_invocation_started`/`cli_process_completed` event の actor/run/workdir 記録を test 固定 | per-run 監査を event 必須化。trade-off を本 ADR で user 承認済。CLI=主実行エンジンの credential は CLI 所有が安全 (refresh 整合) |
| **host-ambient credential-file の prompt-injection exfiltration** (CLI 配下 AI/tool が `cat ~/.codex/auth.json` で読取、accepted HIGH risk) | credential-file exfiltration negative test (cat deny / canary 検出) + canary scan | per-agent 専用最小 HOME (他 secret 非同居) + launcher tool sandbox で credential path の AI/tool read を deny + artifact canary。**残分は accepted HIGH (local 単一 user)、confidential 以上 payload の自律実行は Phase 2+ 追加封じ込めまで gate** |
| Fernet fallback master key の同居/紛失 (CI/headless) | key 非同居 + 0o600 permission 検証 + 再登録 recovery negative test | master key を keyring 優先・不在時のみ ciphertext と別 dir 0o600、紛失時は revoked+再登録 (material loss 明記)。local Mac は keyring must_ship |
| CLI が token を stdout/stderr に echo → launcher capture (max 1MB) に raw 混入 | redaction + canary scan (CLI 固有 token pattern 登録) | stdout/stderr redaction を CLI token 形に拡張、canary 検出時 Hard Gate failure |
| broker-managed API key が caller/env/argv/subprocess に漏れる (Phase 2) | `assert_no_raw_secret`、test_api_key_provider_call negative | API transport は **in-process `provider.call` (subprocess なし)**、API key は broker 内部 HTTP client でのみ消費し env/argv/temp-file に出さない。provider response のみ返す (raw key は broker 内部 del/zeroize)。signature から credential 引数削除 |
| keyring 新規依存の supply-chain | uv.lock pin + SBOM | ADR-00011 記録。暗号化ファイル fallback で degrade 可 (cryptography 既存) |
| URI backend 5+source drift (fail-open) | `SECRET_URI_PATTERN` の import 元 grep + cross-source enum test | 単一定数 `SECRET_URI_PATTERN` 集約、未知 backend fail-closed deny |

## rollback 手順

1. **migration (URI backend)**: downgrade で `secret://local/%` row 存在を preflight (constraint-tightening は legal row preflight 必須の教訓)。`secret://local/%` row 不在時のみ旧 `secret://sops/` 固定 CHECK へ revert (lossless)。
2. **CLI=host-ambient 分類**: revert は credential 供給を host worker 自然参照に戻すのみ (DB 変更なし、Phase 0 は元々 host-ambient のみ)。API key の in-process `provider.call` (Phase 2) は additive (既存 redeem + provider.call operation 不変) なので revert は real ProviderAdapter の未配線化。
3. **keyring 依存**: 削除 + 暗号化ファイル単独へ degrade (cryptography 既存で依存 0 動作)、uv.lock revert。
4. 検証: 既存 `secret://sops/` secret_ref の redeem が不変であること、CLI 実行が host credential で動くこと、`assert_no_raw_secret` 全 secret test PASS。
