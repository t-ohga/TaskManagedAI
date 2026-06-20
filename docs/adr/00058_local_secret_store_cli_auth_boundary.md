---
id: "ADR-00058"
title: "LocalSecretStore resolver + secret_uri local:// scheme 拡張 + CLI サブスク認証 vs API token の境界決定"
status: "proposed"
date: "2026-06-20"
authors:
  - "Claude (autonomous, user 承認 scope: 大元計画 Phase 0 + ADR Gate 4 決定 user 確認済)"
related_sprints:
  - "SP-001-5_host_portable_amendment"
  - "PLAN-10 (大元計画 Phase 0)"
supersedes: null
superseded_by: null
---

ADR Gate Criteria #6 (Secrets 管理方式) + #2 (DB schema: secret_uri CHECK 拡張 + 5+source 整合 + migration 両方向) に該当。大元計画 (PLAN-10) Phase 0 の中核。実行エンジン = CLI 主 (claude / codex をサブスク認証で headless subprocess 実行) という確定方針に対し、CLI サブスク credential をどう供給するか、raw secret 非保存境界を破らずに正式決定する。**user 確認ゲート: 案C hybrid / host worker / keyring+fallback を user 承認済 (2026-06-20)**。

最終更新: 2026-06-20

> **status: proposed**。Phase 0 詳細設計 workflow (4ストリーム並列設計→境界批評→最終化) の成果。境界批評が初期設計を **REFUTE** (broker が resolve した raw を launcher へ forward する seam は SecretBroker §10「値を返す API ではない」を破る) し、修正版 (broker-mediated operation callback 内 spawn) に到達。実装着手直前に codex-plan-review R1 minimum + 採否判定 を経て accepted へ昇格 (sprint-pack-adr-gate §12.4)。

## 背景

- 決定対象:
  1. **LocalSecretStore resolver** の新設 (簡易 local secret store、SOPS+age は後フェーズ D-4)。
  2. **secret_ref URI scheme** を `sops://` 固定から `local://` 併許容へ additive 拡張。
  3. **CLI サブスク認証 vs API token の境界** (本 ADR の最重要・user 確認ゲート)。
  4. CLI credential を subprocess へ供給する **server-owned 注入経路** の設計 (境界批評 CRITICAL の反映)。
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
  - `backend/app/services/secrets/local_secret_store.py` (新規、LocalSecretStore: macOS Keychain via `keyring` 先行 + cryptography Fernet 暗号化ファイル `~/.taskhub/secrets.d/<sha256>.enc` 0o600 fallback、DB 非保存)
  - `backend/app/services/secrets/secret_registration.py` (新規、SecretRegistrationService: store へ raw 委譲 + secret_refs metadata row INSERT を調停)
  - `backend/app/services/secrets/cli_credential_injection.py` (新規、API key 注入の server-owned seam、後述 CRITICAL 設計)
  - `backend/app/repositories/secret_ref.py` (modify、`create()/insert()` 追加、metadata-only、現状 get/list のみ)
  - `backend/app/db/models/secret_ref.py` (modify、URI CHECK を sops|local 併許容、単一定数 `SECRET_URI_SCHEME_PATTERN` 集約)
  - `migrations/versions/00NN_secret_uri_local_scheme.py` (新規、CHECK 拡張、両方向 + downgrade preflight)
  - `config/cli_registry.toml` (modify、claude/codex は host-ambient 分類を明記、API key 経路のみ `credential_env_mapping`)
  - `backend/app/services/cli_artifact/launcher.py` (modify、host-ambient は HOME 経由自然参照、API key は broker operation callback 内 spawn 注入point。`assert_no_raw_secret(env)` 維持)
  - `pyproject.toml` (modify、`keyring` 依存追加、cryptography は既存)
- 実装ガイダンス:
  - **CredentialSupplyMode** を 2 経路に分離:
    - `host_ambient` (CLI サブスク): worker が host で動くため `~/.claude` / `~/.codex` を CLI が直読。raw token は worker env/argv/artifact/audit/DB に出ない (CLI が file/keychain 直読)。per-run 監査は `cli_invocation_started` / `cli_process_completed` event (registry agent / actor / workdir / redaction_hit_count) に記録。
    - `broker_managed` (API key、副次): secret_ref→redeem→spawn 直前注入。**self-rotating credential は broker_managed 経路へ登録できない validation を register 時に enforce** (案B の罠を構造防止)。
  - **【境界批評 CRITICAL 反映】broker-managed の注入は「launcher が raw を引数で受ける」方向を反転**。subprocess spawn 自体を `broker.redeem_capability_token(operation=lambda ctx: spawn_with_injected_env(...))` の **operation callback 内**で実行。broker の SecretHandle-only invariant (resolved を `del` し callback に metadata のみ) を維持したまま、operation 内だけ raw を materialize し **caller に一切返さない**。launcher signature `launch_cli_agent(request, registry)` は不変維持 (entry 直渡しは agent allowlist bypass のため不採用)。
  - launcher の `assert_no_raw_secret(env)` (caller-influenced env を canary scan) は維持。broker 注入分も canary scan に通す (bypass しない)。CLI 固有 token 形 (Claude accessToken / Codex refresh_token) を canary pattern 登録。
  - temp-file 経路を使う場合は `finally` + secure unlink で確実削除 (crash/SIGKILL/timeout kill 時の残留防止)。
  - **keyring 依存** (user 承認済): macOS Keychain backend。CI Linux headless / 環境制約時は cryptography Fernet 暗号化ファイル fallback へ degrade (cryptography は既存 dep)。supply-chain audit 対象として uv.lock pin + SBOM 対象化 (ADR-00011 §digest pinning/SBOM 観点)。
  - URI scheme regex は単一定数 `SECRET_URI_SCHEME_PATTERN` に集約し migration / ORM / resolver / register / test が import (5+source drift 構造防止)。未知 scheme は fail-closed deny。
- テスト指針:
  - `tests/secrets/test_local_secret_store.py`: store/resolve/delete round-trip、keychain→暗号化ファイル fallback、0o600 perm、symlink/path traversal reject、URI scheme reject negative。
  - `tests/secrets/test_secret_registration.py`: create で raw が DB/return/audit に出ず metadata row active のみ (`assert_no_raw_secret` PASS)、(tenant,scope,name) active≤1/pending≤1 違反 reject、cross-tenant 分離。
  - `tests/secrets/test_cli_credential_injection.py`: ① host-ambient で CLI が file 直読 (worker env に token 非常駐)、② broker_managed API key が **operation callback 内**で注入され caller に raw 返らない、argv 非露出、③ **self-rotating credential を broker_managed 登録すると reject** (案B 罠の構造防止)、④ caller が credential を直接渡せない (signature 物理削除) negative。
  - migration 両方向 + downgrade preflight (local:// row 不在検証)。
  - 実コード review: credential injection は §14.1 CRITICAL gate → codex-adversarial-review mode=code で findings_zero (CRITICAL=0/HIGH≤2)。

## 却下案

- A (全 host-ambient): static API key の broker 監査 (atomic claim / fingerprint / audit trail) を捨てる。API key は self-rotating でなく broker 管理可能なので、監査を享受しない理由がない → 却下。
- B (全 broker-managed): OAuth self-rotating により構造的に不可能 (実機確認、broker 注入 token を CLI が refresh 上書き → 即 stale → 全 run 失敗) → 却下。raw OAuth を broker 保持する token theft blast radius も劣る。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| host-ambient CLI 経路が broker 監査外 (atomic claim/fingerprint なし) | `cli_invocation_started`/`cli_process_completed` event の actor/run/workdir 記録を test 固定 | per-run 監査を event 必須化。trade-off を本 ADR で user 承認済。CLI=主実行エンジンの credential は CLI 所有が安全 (refresh 整合) |
| CLI が token を stdout/stderr に echo → launcher capture (max 1MB) に raw 混入 | redaction + canary scan (CLI 固有 token pattern 登録) | stdout/stderr redaction を CLI token 形に拡張、canary 検出時 Hard Gate failure |
| broker-managed 注入で raw が caller/env/argv に漏れる | `assert_no_raw_secret`、test_cli_credential_injection negative | spawn を broker operation callback 内に閉じ raw forward を物理排除。signature から credential 引数削除 |
| keyring 新規依存の supply-chain | uv.lock pin + SBOM | ADR-00011 記録。暗号化ファイル fallback で degrade 可 (cryptography 既存) |
| URI scheme 5+source drift (fail-open) | scheme 定数の import 元 grep + cross-source enum test | 単一定数 `SECRET_URI_SCHEME_PATTERN` 集約、未知 scheme fail-closed deny |

## rollback 手順

1. **migration (URI scheme)**: downgrade で `local://` row 存在を preflight (constraint-tightening は legal row preflight 必須の教訓)。`local://` row 不在時のみ旧 `sops://` 固定 CHECK へ revert (lossless)。
2. **CLI=host-ambient 分類**: revert は credential 供給を host worker 自然参照に戻すのみ (DB 変更なし)。broker operation 反転設計は additive (既存 redeem 経路不変) なので revert は注入 seam の no-op 化。
3. **keyring 依存**: 削除 + 暗号化ファイル単独へ degrade (cryptography 既存で依存 0 動作)、uv.lock revert。
4. 検証: 既存 `sops://` secret_ref の redeem が不変であること、CLI 実行が host credential で動くこと、`assert_no_raw_secret` 全 secret test PASS。
