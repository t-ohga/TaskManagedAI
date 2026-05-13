---
id: "ADR-00011"
title: "GitHub App Permission Matrix: 最小 permission + broker-mediated installation token + merge/deploy deny"
status: "proposed"
date: "2026-05-13"
authors:
  - "claude (sprint8 owner)"
related_sprints:
  - "SP-008_github_app_repoproxy"
acceptance_blocked_by:
  - "Sprint 11 BL-0094: real GitHub App registration + private key SOPS encrypt"
  - "Sprint 11 BL-0095: SecretBroker allowed_operations + capability_token issue flow"
  - "Sprint 11 BL-0097: GitHubAppAdapter httpx wrapper (broker-mediated only)"
  - "Sprint 11 BL-0100: AgentRunEvent repo_pr_opened actual emission"
  - "Sprint 11 BL-0102: AC-KPI-02 time_to_merge endpoint + median calc test"
  - "Sprint 11 BL-0101a: Webhook HMAC SecretBroker-mediated service layer + Redis SETNX replay"
  - "Sprint 11 BL-0096a: RepoProxy 4 整合 binding server-side 再計算 refactor"
  - "Sprint 11.5 BL-Permission-CLI: GitHub API current permissions fetch + CI workflow integration"
supersedes: null
superseded_by: null
---

このテンプレの使い方: ADR Gate Criteria #11 (GitHub App permission 変更) に該当。
Sprint 8 batch 0 で `proposed`、Sprint 11 で `acceptance_blocked_by` 全 8 件
完了後に **accepted** 昇格 (Codex SP8 R1 F-SP8-004 + R2 R2-F-002 adopt、
2026-05-13 status は標準 `proposed` のまま維持し、custom field
`acceptance_blocked_by` で blocking conditions を非標準扱いで記録)。

Sprint 8 では Permission Matrix の最終形を確定し、`config/github_app_permissions.toml`
で hardcode + CLI `--check` で diff check 基盤を整備。

## Status 詳細 (Codex SP8 R1 F-SP8-004 + R2 R2-F-002 adopt)

- **status: proposed**: 標準 ADR lifecycle (`proposed` → `accepted`) を維持
  (rules/sprint-pack-adr-gate.md と ADR template の整合性のため、Codex
  R2 R2-F-002 adopt で custom `proposed_pending_sprint_11` から元に戻し)。
- **acceptance_blocked_by 8 件** (frontmatter 参照): Sprint 11 で全件完了後に
  `accepted` へ昇格する。1 件でも未完了の状態で accepted 化することは ADR
  Gate Criteria #11 違反 (P0 期間中の GitHub App permission を実装で証明
  できないまま採用案確定するのは設計品質上 NG)。

最終更新: 2026-05-13

## 背景

- 決定対象: TaskManagedAI 用 GitHub App の **Repository / Organization / Account permission 一式**、および **installation token を扱う SecretBroker boundary**、**merge / deploy の P0 deny 戦略**
- 関連 Sprint: SP-008_github_app_repoproxy (Sprint 8)
- 前提 / 制約:
  - P0 は Tailscale 閉域、単一 VPS / Mac、Docker Compose (ADR-00007 / ADR-00021)
  - SecretBroker は SOPS + age + FastAPI 内 module、capability token は atomic claim (ADR-00006)
  - AgentRun は 16 状態 + blocked_reason 3 種、event_type 22 + P0.1 で 31 まで拡張 (ADR-00004)
  - action_class 7 種 (`task_write` / `repo_write` / `pr_open` / `secret_access` / `merge` / `deploy` / `provider_call`) は不変 (ADR-00009 / `multi-agent-orchestration.md`)
  - `.github/workflows/**` への AI / runner 書込は forbidden_path で deny (ADR-00008)
  - Hard Gate 7 (AC-HARD-01〜07) + Quality KPI 5 (AC-KPI-01〜05) を満たすこと

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: 最小 permission + broker-mediated token + merge/deploy deny | contents:write + pull_requests:write + metadata:read のみ、installation token は SecretBroker 内 resolve、merge/deploy は 3 層 deny | 攻撃面最小 / 既存 SecretBroker / Policy Engine と整合 / GitHub App permission overreach 防止 | 実装が SecretBroker 拡張 + Permission Matrix toml + 3 層 deny の負担増 |
| B: GitHub Personal Access Token (PAT) | dev user の PAT を SecretBroker に登録、scope=repo / public_repo | 実装簡易 | actor=`github_app` の audit 不可 / PAT scope は granular でない / rotation 困難 / scale で破綻 |
| C: GitHub OAuth App | OAuth flow で installation token 取得 | user 個別の権限 | scope=repo の coarse permission / installation_id 不在 / P0 では 1 user のため利点なし |
| D: 拡張 permission (workflows / actions / packages 込み) | 将来の自動化を見据えて広めに取る | future-proof | permission overreach、Sprint 8 で必要なし、ADR Gate Criteria #11 違反 |

## 採用案

- 採用: **A (最小 permission + broker-mediated token + merge/deploy deny)**
- 理由:
  - GitHub App は per-installation token + actor=`github_app` で audit に紐付け、PAT より granular。
  - 最小 permission で攻撃面を抑え、ADR Gate Criteria #11 の意図 (permission overreach 抑止) に整合。
  - broker-mediated token は raw token を caller (RepoProxy / AI / runner / artifact / log) に渡さず、`docs/基本設計/06_秘密管理設計.md §SecretBroker §10` に整合。
  - `merge` / `deploy` は P0 deny を 3 層で enforce (capability token issue + Policy Engine + UI)、P0 期間中の人間 review を経由しない自動 merge / deploy を物理的に防ぐ。
- 実装 Sprint: SP-008
- 実装対象ファイル:
  - `config/github_app_permissions.toml` (NEW): Permission Matrix hardcode
  - `backend/app/services/repoproxy/permission_matrix.py` (NEW): Matrix loader + differential check
  - `backend/app/services/repoproxy/github_app_adapter.py` (NEW): httpx wrapper (broker 経由のみ token resolve)
  - `backend/app/services/repoproxy/repoproxy.py` (NEW): high-level service (branch / commit / push / Draft PR / status)
  - `backend/app/services/repoproxy/webhook_hmac.py` (NEW): X-Hub-Signature-256 verifier
  - `backend/app/services/secretbroker/operations.py` (修正): `repo.push` / `repo.pr_open` operation 追加
  - `backend/app/services/policy_engine/rules.py` (修正): `merge` / `deploy` P0 deny rule
  - `migrations/versions/00NN_secret_broker_repo_operations.py` (NEW): allowed_operations 追加
  - `migrations/versions/00NN_repo_pr_opened_event.py` (NEW): AgentRunEvent payload schema 拡張
  - `tests/repoproxy/` (NEW 5+ files): permission matrix / broker integration / 4 整合 / merge-deploy deny / webhook HMAC / canary

### Permission Matrix (P0 最小)

```toml
# config/github_app_permissions.toml
[repository_permissions]
contents = "write"         # branch create / commit / push
pull_requests = "write"    # Draft PR open / update
metadata = "read"          # repo info / branch list

[repository_permissions.deny_explicit]
# 以下は明示 deny。CI で diff check し、有効化された場合 fail。
actions = "deny"
workflows = "deny"        # .github/workflows/** への push を二重防御 (forbidden_path + permission)
packages = "deny"
administration = "deny"
issues = "deny"           # P0 では使わない、P0.1 で再評価
checks = "deny"           # CI status fetch は metadata:read で代替

[organization_permissions]
# P0 personal 用途のため organization permission は不要

[account_permissions]
email_addresses = "deny"  # PII 取得経路を deny
```

### broker-mediated installation token

- `SecretBroker.allowed_operations` に `repo.push` / `repo.pr_open` を追加。
- `OperationContext` canonical JCS に `(provider="github", repo_full_name, branch, commit_sha, artifact_hash, approval_id, policy_version)` を含め、`expected_request_fingerprint` を server-side 計算 (`server-owned-boundary §1`)。
- `RepoProxy.create_draft_pr(...)` は broker 内で `installation_token` を resolve → httpx で GitHub API 呼出 → response のみ返す。caller に raw token を返さない。
- `installation_token` TTL は GitHub 仕様で 1 hour 固定。redeem ごとに新 token 取得 (`/app/installations/{id}/access_tokens`)。
- raw token / private key は AI / runner / artifact / log / audit に出さない (canary test 必須)。

### merge / deploy P0 deny (3 層)

1. **Capability token issue**: `SecretBroker.allowed_operations` に `merge` / `deploy` を **登録しない** → issue 時点で deny。
2. **Policy Engine**: P0 default policy で action_class `merge` / `deploy` は **always deny**。
3. **UI / API**: GitHub UI から人間が手動で merge する以外の経路を作らない。FastAPI に merge endpoint を作らない。

### 4 整合 binding

ApprovalRequest が `decision=approved` を返すまで RepoProxy は動作しない:
- `artifact_hash`: 生成 patch の sha256
- `policy_version`: approval 時の policy pack version
- `provider_request_fingerprint`: AgentRun の ContextSnapshot にある `provider_request_fingerprint`
- `repo_state_commit_sha`: push 時の HEAD commit sha (push 直前に再 fetch、stale なら invalidate)

1 つでも mismatch なら ApprovalRequest を invalidate → RepoProxy は deny → AgentRun は `blocked` + `policy_blocked`。

### Webhook HMAC

- GitHub webhook receive endpoint: `POST /webhooks/github` (FastAPI、Tailscale 内 IP のみ accessible)
- `X-Hub-Signature-256: sha256=...` を `hmac.compare_digest(expected, actual)` で constant-time 比較
- Webhook shared secret は `secret_ref://sops/p0/github_webhook_hmac#v1` で SecretBroker 経由 resolve
- Invalid signature → 401 + `webhook_hmac_failed` audit
- Replay 防止: webhook payload の `delivery_id` を最近 1 hour 分 Redis に記録、重複なら deny
- Secret rotation 中は新旧 2 secret 並行 verify、`secret_refs.status='deprecated'` の旧 secret は 7 日 grace period

### 実装ガイダンス

- Permission Matrix differential check は CI で実行 (`uv run python -m backend.app.services.repoproxy.permission_matrix --check`)。
- Permission 差分検知時は CI fail で merge block、ADR-00011 update を要求。
- raw token は debug log にも出さない (Sprint 6 redaction module 流用、SHA256 hex 12 byte truncate でも payload 漏れ可能性 → key 名のみ audit)。
- Branch naming `codex/agent-run-{run_id_short}` で衝突回避、existing branch overwrite は deny。
- `.github/workflows/**` は forbidden_path で AI 出力 push を deny + RepoProxy で repository_permissions.workflows=deny で permission 不足で fail (二重防御)。

### テスト指針

- `uv run pytest tests/repoproxy/test_permission_matrix.py -q`: actions / workflows / administration / packages が deny 明示されていることを確認
- `uv run pytest tests/repoproxy/test_github_app_adapter.py -q`: broker-mediated token 経由のみ動作確認
- `uv run pytest tests/repoproxy/test_repoproxy_service.py -q`: 4 整合 binding 1 mismatch deny 確認
- `uv run pytest tests/repoproxy/test_webhook_hmac.py -q`: signature mismatch / replay / timing attack / secret rotation 中の dual-verify を確認
- `uv run pytest tests/repoproxy/test_merge_deploy_deny.py -q`: merge / deploy が capability token + Policy Engine 両方で deny されることを確認
- `uv run pytest tests/repoproxy/test_canary_no_raw_token.py -q`: raw installation token が AI / runner / artifact / log / audit に漏れないことを確認
- `uv run pytest tests/repoproxy/test_branch_naming_collision.py -q`: branch overwrite deny 確認
- `uv run pytest tests/repoproxy/test_forbidden_path_dotgithub.py -q`: `.github/workflows/**` への push deny を確認
- `uv run pytest tests/contracts/test_kpi_time_to_merge.py -q`: AC-KPI-02 median 計算 確認

## 却下案

- **B: PAT**: actor=`github_app` で audit 不可、PAT scope は granular でない (`repo` scope は contents + pull_requests + workflows + actions すべて含む)、rotation が UI 手動操作、organization scale で破綻。P0 personal でも GitHub App の方が運用整合性高い。
- **C: OAuth App**: scope=repo の coarse permission、`installation_id` がないため `actor.github_app_installation_id` binding 不可、P0 personal では OAuth flow の利点なし。
- **D: 拡張 permission**: workflows / actions / packages を取ると、P0 で `.github/workflows/**` 直接書込が permission レベルで可能になる (forbidden_path だけが防御)。Defense-in-depth 弱体化、ADR Gate Criteria #11 の意図に反する。Sprint 11.5 以降で CI 自動化が必要になった時点で別 ADR で拡張。

## リスク

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| permission overreach (CRITICAL) | CI で current permission vs Matrix diff check | 差分検知時 CI fail + ADR update 必須、月次 audit (Sprint 11.5) |
| installation token leak (CRITICAL) | canary test (fake token を SecretBroker に登録 → 各経路で漏れた瞬間検出) | broker-mediated operation 経由のみ token resolve、AC-HARD-02 fixture と統合 |
| HMAC bypass (HIGH) | unit test (timing / replay / rotation) | `hmac.compare_digest` + replay detection (Redis nonce) + dual-secret rotation window |
| Draft PR self-approval (HIGH) | negative test (AgentRun が自分の PR を approval する経路) | `decider != requester` constraint で deny、`human_only=True` action_class enforcement |
| Permission Matrix drift (MEDIUM) | GitHub API permission 仕様変更で Matrix が陳腐化 | Sprint 11.5 で月次 audit、API version pin (`api_version=2022-11-28`) |
| Webhook DoS (MEDIUM) | request rate monitoring | per-installation rate limit (Sprint 11.5)、queue buffering |
| Token rotation window race (MEDIUM) | rotation 中の 2 secret 並行検証 | grace period 7 日 + Redis nonce で replay 防止 |
| Branch name collision (LOW) | branch overwrite test | run_id prefix 8-char → collision 検出時 12-char 伸長 |

## rollback 手順

1. **rollback trigger**:
   - GitHub App permission overreach 発覚 (CI fail / audit log で予想外 API call)
   - installation token leak 検出 (canary test FAIL / artifact / log で raw token 発見)
   - webhook HMAC bypass 確認 (invalid signature が verified として処理された痕跡)
   - merge / deploy が P0 期間中に発火 (Policy Engine bypass / 3 層 deny の 1 つでも穴)

2. **rollback step**:
   - GitHub App permission を UI で revert (`actions=write` を `none` 等、Permission Matrix toml の状態に戻す)
   - `installation_token` を即時 revoke (`/app/installations/{id}/access_tokens` DELETE)、SecretBroker `secret_refs.status='revoked'` に変更
   - webhook secret を rotate (`secret_refs.status='deprecated'` → 新 v2 を `pending` → `active`)
   - merge/deploy 発火 PR を git revert + force-push `--force-with-lease`、actor=`github_app` の audit log で blast radius 確認
   - `.github/workflows/**` への push 履歴を確認、AI 出力起因なら全 affected commit を revert

3. **verification after rollback**:
   - `uv run pytest tests/repoproxy/ -q` 全 pass
   - canary test (raw token leak detection) で 0 hit
   - `uv run pytest tests/eval/test_ac_hard_02_secret_canary.py -q` AC-HARD-02 PASS
   - GitHub App permission を `gh api repos/owner/repo/installation` で確認、Matrix と一致
   - SecretBroker `secret_refs` の `status='revoked'` row 数を audit、rotation 完遂確認
