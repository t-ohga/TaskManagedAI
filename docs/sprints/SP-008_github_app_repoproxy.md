---
id: "SP-008_github_app_repoproxy"
type: "heavy"
status: "partial_skeleton"
sprint_no: 8
created_at: "2026-05-13"
updated_at: "2026-05-24"
review_summary: "2026-05-24 reconciliation + Batch A/A2/B/C/D/E: Permission Matrix / MockRepoProxy / low-level HMAC / SecretBroker repo operation primitives / repo_pr_opened enum / orchestrator KPI proxy rollup / server-owned Draft PR binding guard / DB-backed ApprovalRequest+ContextSnapshot resolver / broker-mediated GitHubAppAdapter boundary / webhook service boundary with replay protocol / repo_pr_opened event writer / agent_runs KPI endpoint are present. Real GitHub httpx transport, live Git ref re-fetch, concrete SecretBroker+Redis webhook adapters and route wiring, and RepoProxy runtime call-site wiring remain residual. Keep status partial_skeleton."
target_days: 5
max_days: 7
adr_refs:
  - "[ADR-00006](../adr/00006_secrets_management.md) # accepted、installation token を SecretBroker capability token 経由で扱う"
  - "[ADR-00007](../adr/00007_external_exposure.md) # accepted、GitHub webhook は Tailscale 内 endpoint のみ受信、Funnel/Cloudflare 不使用"
  - "[ADR-00009](../adr/00009_action_class_taxonomy.md) # accepted、repo_write / pr_open / merge / deploy action_class enforcement"
  - "[ADR-00011](../adr/00011_github_app_permission_matrix.md) # accepted、Criteria #11 GitHub App permission 変更"
  - "[ADR-00003](../adr/00003_api_contract.md) # accepted、Draft PR / webhook API contract (Criteria #3)"
planned_adr_refs: []
related_sprints:
  - "SP-007_runner_sandbox # 実在、runner_mutation_gateway → RepoProxy 経由 push"
  - "SP-009_p0_ui_pack # 実在、Approval Inbox + AI Runs で repo_write/pr_open 表示"
upstream_sprints:
  - "SP-001_project_foundation"
  - "SP-002_core_data_model"
  - "SP-003_policy_approval"
  - "SP-004_agent_runtime"
  - "SP-006_cli_artifact"
  - "SP-007_runner_sandbox"
downstream_sprints:
  - "SP-009_p0_ui_pack"
  - "SP-012_p0_acceptance"
risks:
  - "github_app_permission_overreach"
  - "installation_token_leak"
  - "webhook_hmac_bypass"
  - "draft_pr_self_approval"
  - "deny_list_drift"
---

このテンプレの使い方: 権限 / 実行 / 外部連携など ADR Gate Criteria に該当する Sprint に使う。実装前に ADR-00011 を proposed 化 → P0 deny を維持しつつ Draft PR flow + RepoProxy + SecretBroker integration を確立する。

最終更新: 2026-05-13

## 目的

- GitHub App を **read-only metadata + contents:write (Draft PR / branch / commit)** の最小 permission で登録し、AgentRun 生成 patch を **runner_mutation_gateway → RepoProxy** 経由でのみ branch push + Draft PR 作成できる回路を完成する。
- installation token は **SecretBroker capability token** 経由で broker-mediated に発行 / redeem し、AI / runner / artifact / log / audit に raw token を渡さない (ADR-00006 §10 broker-mediated operation `repo.push` / `repo.pr_open` を実装)。
- **`merge` / `deploy` は P0 で deny-only**、Draft PR は **human approval 必須** + 4 整合 (artifact_hash / policy_version / provider_request_fingerprint / repo_state_commit_sha) で stale invalidate。
- webhook (Pull Request / Push / Check Suite) を Tailscale 内 endpoint で受信し、**HMAC SHA-256 verification + actor binding** + AgentRunEvent append-only に統合する。
- AI Runs timeline で `repo_pr_opened` event (Sprint 4 で予約済 agent_run_event_type) を表示できるよう RepoProxy → AgentRun integration を最終確立。

## 背景

- Sprint 7 で `runner_mutation_gateway` + forbidden_path / dangerous_command が完成 (commit `dc573cc`)、runner sandbox 内で patch を生成可能。
- Sprint 8 は **生成 patch を GitHub repo に届ける** 唯一の経路を確立する Sprint。`docs/基本設計/03_AIオーケストレーション設計.md §RepoProxy` + `docs/設計検討/計画(仮).md §Sprint 8` で定義された境界を実装。
- GitHub App は本物の App を P0 開発期に作成する必要がある。**actor=`github_app`** で audit に紐付け、installation token は短命 (1 hour TTL) + scope=`installation` で SecretBroker 管理。
- `.github/workflows/**` への AI / runner 書込は **AI Output Boundary §forbidden_path で deny** (Sprint 7 で確立)、本 Sprint で repo push 経路でも redundant deny (二重防御)。
- Draft PR flow は AC-KPI-02 `time_to_merge` の計測元 (`docs/要件定義/01_P0要求定義.md §AC-KPI-02`)、本 Sprint で `pr_opened_at` / `pr_ready_for_review_at` を AgentRunEvent に記録。

## 対象外

- **GitHub App marketplace 公開** (P1 以降)
- **`merge` の自動化** (P0 deny、人間が GitHub UI で手動 merge)
- **`deploy` / GitHub Deployments API** (P0 deny、Deployment は ADR-00021 §host-portable で別経路)
- **branch protection rule の自動設定** (P1、本 Sprint では手動設定前提)
- **CodeQL / Dependabot 連携** (P1 以降、Sprint 11.5 observability で扱う)
- **webhook UX 強化** (defer_if_over_budget、AgentRun UI 反映の自動 toast 等)

## 設計判断

- **broker-mediated `repo.push`**: SecretBroker capability token で operation=`repo.push` を発行、RepoProxy は SecretBroker 経由でのみ token を間接取得。raw `installation_token` を caller に返さず、broker 内で `httpx` request を実行して response のみ返す (`docs/基本設計/06_秘密管理設計.md §SecretBroker §10`)。
- **4 整合 binding**: Draft PR 作成時の ApprovalRequest と SecretBroker capability token に `artifact_hash` (生成 patch sha256) + `policy_version` + `provider_request_fingerprint` + `repo_state_commit_sha` を expected_request_fingerprint で server-side 計算 (`server-owned-boundary §3`)。1 つでも mismatch なら invalidate。
- **`merge` / `deploy` deny**: `action_class` enum に `merge` / `deploy` は登録済 (ADR-00009)、Policy Engine の P0 default deny で enforcement、capability token issue 経路でも deny。Sprint 8 で `merge_*` event_type は **追加しない** (P0 期間中は使わない)。
- **webhook HMAC**: GitHub からの webhook は `X-Hub-Signature-256: sha256=...` を `hmac.compare_digest` で constant-time 比較、shared secret は SecretBroker から resolve (`secret_ref://sops/p0/github_webhook_hmac#v1`)。invalid signature は 401 + `webhook_hmac_failed` audit。
- **`actor.type=github_app`** で全 GitHub App 操作 (push / pr_open / webhook receive) を audit、`github_app_installation_id` を actor metadata に保存。
- **branch naming convention**: AgentRun が作る branch は `codex/agent-run-{run_id_short}` (8 桁 prefix) で衝突回避、existing branch overwrite は deny。

## 実装チケット

- **BL-0094**: GitHub App 登録 + private key を SOPS で encrypt + `secret_ref://sops/p0/github_app_private_key#v1` で参照
- **BL-0095**: SecretBroker に `provider=github` / `operation=repo.push,repo.pr_open` を追加、`installation_token` を broker 内 resolve、capability token の `expected_request_fingerprint` に `(repo_full_name, branch, commit_sha, artifact_hash)` 束縛
- **BL-0096**: `RepoProxy` service module (FastAPI 内、Worker からも呼出可) - branch create / commit / push / Draft PR open / status check の高レベル interface
- **BL-0097**: `GitHubAppAdapter` - low-level httpx wrapper (broker 経由のみ token 取得、retries / rate limit handling、`api_version`=`2022-11-28`)
- **BL-0098**: Permission Matrix (`config/github_app_permissions.toml`) - 必須 contents:write / pull_requests:write / metadata:read のみ、actions / workflows / packages / administration は明示 deny
- **BL-0099**: Webhook HMAC verifier (FastAPI route `/webhooks/github` Tailscale 内のみ accessible、Webhook secret SecretBroker 経由 resolve)
- **BL-0100**: AgentRunEvent integration - `repo_pr_opened` event を RepoProxy から append、payload に `pr_number` / `branch` / `head_sha` / `draft=true` / `created_at`
- **BL-0101**: `merge` / `deploy` deny test (capability token issue 経路で deny 確認、Policy Engine deny 確認、HARD test)
- **BL-0102**: AC-KPI-02 `time_to_merge` 計測 helper (2026-05-24 Batch E で `/api/v1/agent_runs/{run_id}/kpi` endpoint を追加。現 P0 source は `repo_pr_opened` first event → `agent_runs.completed_at` proxy、median 集計は Eval / orchestrator rollup 側で扱う)

## タスク一覧

- [ ] **batch 0**: ADR-00011 起票 (proposed)、Permission Matrix draft。2026-05-24 reconciliation 以降は ADR-00011 を design decision accepted とし、implementation closeout は本 Pack の residual batches で判定する。
- [ ] **batch 1**: BL-0094 (GitHub App 登録) + BL-0095 (SecretBroker integration) + Codex multi-round review
- [ ] **batch 2**: BL-0096 (RepoProxy) + BL-0097 (GitHubAppAdapter) + Codex multi-round review
- [ ] **batch 3**: BL-0098 (Permission Matrix) + BL-0101 (merge/deploy deny test) + Codex multi-round review
- [ ] **batch 4**: BL-0099 (Webhook HMAC verifier) + Codex multi-round review
- [ ] **batch 5**: BL-0100 (AgentRunEvent integration) + BL-0102 (AC-KPI-02 計測) + Codex multi-round review
- [ ] **Sprint Exit**: SP-008 ## Review 章 + main merge。ADR-00011 の accepted status だけでは Exit 不可; residual batches A-E の実装証跡が必要。
- [ ] **Hard Gate 接続**: AC-HARD-03 tenant isolation の repo permission 越境 test 追加

## must_ship / defer_if_over_budget 対応表

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 8 | 5 | 7 | GitHub App / RepoProxy / Permission Matrix / Draft PR 作成 / CI 取得 / webhook HMAC / merge+deploy deny / AC-KPI-02 計測 | webhook UX 強化、auto PR description 生成、branch protection rule auto-set、CodeQL 連携 |

## 受け入れ条件

- [ ] `config/github_app_permissions.toml` に最小 permission のみ列挙され、`actions`, `workflows`, `packages`, `administration` は明示 deny。
- [ ] SecretBroker に `repo.push` / `repo.pr_open` operation 追加、capability token redeem は atomic claim UPDATE + `expected_request_fingerprint` (sha256 over OperationContext canonical JCS) で binding。
- [ ] `RepoProxy.create_draft_pr()` は ApprovalRequest が `decision=approved` + 4 整合 (artifact_hash / policy_version / provider_request_fingerprint / repo_state_commit_sha) を server-side 検証して通過した時のみ動作。
- [ ] `merge` / `deploy` action_class は capability token issue + Policy Engine + UI の 3 層で deny、negative test がある。
- [ ] webhook endpoint は Tailscale 内 (`100.64.0.0/10`) からのみ受信、HMAC SHA-256 検証失敗は `webhook_hmac_failed` audit + 401 response。
- [ ] AI / runner / artifact / log / audit に **raw installation token** が出現しない (canary test)。
- [ ] AgentRunEvent `repo_pr_opened` が `pr_number`, `branch`, `head_sha`, `draft=true` を payload に持つ。
- [ ] `actor.type='github_app'` で全 push / pr_open / webhook receive event が audit に記録される。
- [ ] AC-KPI-02 `time_to_merge` の計測 endpoint が動作、median 計算ロジックが test カバー。
- [ ] `.github/workflows/**` への push は **forbidden_path** + RepoProxy の二重 deny。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-008_github_app_repoproxy.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ls docs/adr/00011_github_app_permission_matrix.md` で planned ADR が存在することを確認する。
- [ ] `uv run pytest tests/repoproxy/test_github_app_adapter.py -q` で broker-mediated token 経由のみ動作することを確認。
- [ ] `uv run pytest tests/repoproxy/test_repoproxy_service.py -q` で 4 整合 binding が 1 つでも mismatch なら deny されることを確認。
- [ ] `uv run pytest tests/repoproxy/test_permission_matrix.py -q` で actions / workflows / administration が deny 明示されていることを確認。
- [ ] `uv run pytest tests/repoproxy/test_webhook_hmac.py tests/repoproxy/test_webhook_service.py -q` で signature mismatch / replay / rotation status / timing attack に対応していることを確認。
- [ ] `uv run pytest tests/repoproxy/test_merge_deploy_deny.py -q` で merge / deploy が capability token / Policy Engine 両方で deny されることを確認。
- [ ] `uv run pytest tests/repoproxy/test_repo_pr_opened_event.py -q` で AgentRunEvent integration を確認。
- [ ] `uv run pytest tests/repoproxy/test_canary_no_raw_token.py -q` で raw installation token が AI / runner / artifact / log / audit に漏れないことを確認。
- [ ] `uv run pytest tests/repoproxy/test_branch_naming_collision.py -q` で `codex/agent-run-*` branch overwrite が deny されることを確認。
- [ ] `uv run pytest tests/repoproxy/test_forbidden_path_dotgithub.py -q` で `.github/workflows/**` への push が forbidden_path + RepoProxy で二重 deny されることを確認。
- [ ] `uv run pytest tests/contracts/test_kpi_time_to_merge.py -q` で AC-KPI-02 median 計算が正しいことを確認。
- [ ] `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/metrics/test_agent_run_kpi.py -q` と `uv run pytest tests/api/test_agent_runs_kpi.py -q` で AgentRun KPI endpoint exposure を確認。
- [ ] `rg -n "installation_token|GITHUB_TOKEN|GITHUB_INSTALLATION_TOKEN" backend tests --glob '!**/test_*' --glob '!**/env_scrub.py'` で raw token を保存する経路がないことを review する。

## レビュー観点

- [ ] ADR-00011 は design decision として accepted。SP-008 completion は ADR status ではなく、2026-05-24 residual reconciliation で列挙した implementation evidence の完了で判定する。
- [ ] GitHub App permission は最小 (contents:write + pull_requests:write + metadata:read のみ)、actions / workflows / packages / administration は明示 deny。
- [ ] installation token は SecretBroker 内でのみ resolve、RepoProxy は broker-mediated operation 経由でのみ httpx request を投げる。
- [ ] 4 整合 binding が all-or-nothing (1 mismatch でも invalidate)、`expected_request_fingerprint` は OperationContext canonical JCS で server-side 計算 (`server-owned-boundary §1` 違反なし)。
- [ ] `merge` / `deploy` deny が capability token issue / Policy Engine / UI の 3 層で enforced (defense-in-depth)。
- [ ] webhook HMAC は `hmac.compare_digest` で timing-attack safe、shared secret は SecretBroker から resolve、Tailscale 内 endpoint のみ受信。
- [ ] AgentRunEvent `repo_pr_opened` payload に raw token / raw response body を含めない、PR URL は redacted form。
- [ ] `actor.type='github_app'` の actor instance が `github_app_installation_id` を binding 持つ、self-approval 禁止 (decider != requester) は GitHub App actor でも適用。
- [ ] AC-KPI-02 計測ロジックが PR-flow source のみ (RepoProxy 経由)、parent + children の重複計測なし (`multi-agent-orchestration.md §10`)。
- [ ] `.github/workflows/**` への AI / runner 書込が forbidden_path で deny + RepoProxy で二重 deny。
- [ ] branch naming `codex/agent-run-{run_id_short}` の衝突 (existing branch) が deny される。

## 残リスク

- **GitHub App permission overreach (CRITICAL)**: P0 admin が誤って actions / workflows / administration permission を有効化する可能性。Permission Matrix を toml で hardcode + CI で differential check (現状 permission vs Matrix)、unexpected diff は CI fail で block。Sprint 11.5 で permission audit log を Loki 統合。
- **installation token leak (CRITICAL)**: SecretBroker bypass / log debug / artifact export 経路で raw token が漏れるリスク。canary test (fake token を本物として SecretBroker に登録 → 各経路で漏れた瞬間検出)、AC-HARD-02 fixture と統合。
- **webhook HMAC bypass (HIGH)**: timing attack / signature replay / secret rotation 中の dual-secret window。`hmac.compare_digest` + nonce 検証 + secret rotation 中は新旧両方の secret を verify、stale signature reject。
- **Draft PR self-approval (HIGH)**: AgentRun が自分の PR を approval する経路 (decider==requester) が `human_only` constraint で deny されるか negative test 必須。
- **deny list drift (MEDIUM)**: Permission Matrix の deny list が GitHub 仕様変更で陳腐化。Sprint 11.5 で月次 audit、ADR-00011 §rollback で対応。
- **branch collision (LOW)**: `codex/agent-run-{8-char}` が同 prefix collision (確率 1/4B/8-char = ~1/4B、運用上ほぼ 0)。collision detect 時は run_id 12-char prefix へ伸長 (Sprint 11)。
- **PR description prompt injection (HIGH)**: AI 生成の PR title / description に injection が混入する可能性。`docs/設計検討/harness-residual-risks.md PH4-F-XXX` で recorded、artifact validation + redaction で対応 (Sprint 7 batch 1 と同 redaction module 流用)。
- **webhook DOS (MEDIUM)**: Tailscale 内 endpoint でも GitHub から大量 webhook で DoS 可能。rate limit (per installation_id) + queue buffering で対応、Sprint 11.5 で深掘り。

## 次スプリント候補

- **Sprint 9 (P0 UI Pack)**: Approval Inbox + AI Runs timeline で `repo_pr_opened` / `repo_push` event を表示、Draft PR URL hyperlink + commit SHA copy。
- **Sprint 11 (Eval Harness)**: AC-HARD-03 tenant isolation の repo permission 越境 fixture を追加 (Tenant A の AgentRun が Tenant B の repo に push 試行 → deny)。
- **Sprint 11.5 (Operational Hardening)**: GitHub App permission audit log + webhook rate limit + Permission Matrix differential CI。
- **Sprint 12 (P0 Acceptance)**: Draft PR flow を gold flow に接続、AC-KPI-02 final 判定。
- **P0.1 / P1**: branch protection rule auto-set / CodeQL 連携 / `merge` automation (human review 必須は維持) / GitHub App marketplace 公開。

## 関連 ADR

- [ADR-00006](../adr/00006_secrets_management.md): accepted。installation token を SecretBroker capability token 経由で扱う前提。本 Sprint で `provider=github` / `operation=repo.push,repo.pr_open` を allowed_operations に追加。
- [ADR-00007](../adr/00007_external_exposure.md): accepted。webhook endpoint を Tailscale 内 (`100.64.0.0/10`) のみ受信、Funnel/Cloudflare 不使用。
- [ADR-00009](../adr/00009_action_class_taxonomy.md): accepted。action_class `repo_write` / `pr_open` / `merge` / `deploy` の enforcement 経路を本 Sprint で確立 (merge / deploy は P0 deny)。
- [ADR-00011](../adr/00011_github_app_permission_matrix.md): design decision accepted。2026-05-24 reconciliation で過去の implementation completion claim を補正済み。Criteria #11 GitHub App permission 変更の正本。
- [ADR-00003](../adr/00003_api_contract.md): Sprint 8 batch 5 で proposed 化、Draft PR / webhook API endpoint contract (Criteria #3)。

## Review

### batch 1 完了 (2026-05-13、commit `5f2ec28`)

#### changed (batch 1: BL-0098)

- `config/github_app_permissions.toml`: ADR-00011 §採用案 を hardcode 正本化
  (repository_permissions = contents:write + pull_requests:write +
  metadata:read のみ、actions / workflows / packages / administration /
  issues / checks の 6 種を明示 deny、webhooks HMAC SHA-256 + secret_ref 経由、
  merge / deploy = p0_deny、branch_naming = ^codex/agent-run-[a-f0-9]{8}$)
- `backend/app/services/repoproxy/permission_matrix.py`: GitHubAppPermissionMatrix
  frozen + tomllib load + check_no_dangerous_permissions (CI diff check)
- `tests/repoproxy/test_permission_matrix.py`: 12 件 (minimum permission 確認 +
  dangerous permission deny + organization empty + account email deny +
  webhook HMAC config + merge/deploy p0_deny + branch naming + 3 negative
  cases)

#### verified (batch 1)

- `uv run pytest tests/repoproxy/ -q`: 12 件 pass
- 2152 full test pass / mypy clean / ruff clean

### batch 2-4 完了 (2026-05-13、commit `b8e07aa`)

#### changed (batches 2-4: BL-0096 + BL-0099 + BL-0101)

- `backend/app/services/repoproxy/repoproxy.py`: RepoProxy ABC +
  DraftPRRequest (server-owned 9 fields: repo_full_name + base_branch +
  head_branch + commit_sha + artifact_hash + policy_version +
  provider_request_fingerprint + repo_state_commit_sha + approval_id) +
  RepoProxyDenyReason (10 enum) + validate_draft_pr_request (branch pattern
  ^codex/agent-run-[a-f0-9]{8}$) + MockRepoProxy (in-memory test backend)
- `backend/app/services/repoproxy/webhook_hmac.py`:
  verify_github_webhook_signature (HMAC SHA-256 + hmac.compare_digest で
  timing attack 防御) + verify_with_rotation (rotation 7 日 grace window) +
  WebhookVerificationResult enum (6 種)
- `tests/repoproxy/test_webhook_hmac.py`: 12 件
- `tests/repoproxy/test_repoproxy_mock.py`: 13 件 (P0 merge/deploy always
  deny + branch overwrite deny + RepoProxyDenyReason 10 enum 5+ source
  verify)

#### verified (batches 2-4)

- `uv run pytest tests/repoproxy/ -q`: 37 件 pass (累計 batch 1+2-4)
- 2177 full test pass / mypy clean / ruff clean
- ADR-00011 §採用案 (3 層 P0 deny + 4 整合 binding + branch naming +
  webhook HMAC constant-time compare) を Mock backend で verify

### batches 5 deferred (別 session で実装)

- BL-0094: 実 GitHub App 登録 (P0 personal scope では admin が手動登録、
  Sprint 8 内では skip)
- BL-0095: SecretBroker repo.push / repo.pr_open allowed_operations 追加
  (既存 RequestedOperation Literal で予約済、actual capability_token issue
  flow は Sprint 11 で結線)
- BL-0097: GitHubAppAdapter (httpx wrapper、Sprint 11 で `GitHubAppRepoProxy`
  と一緒に実装、Mock を本実装に置換)
- BL-0100: AgentRunEvent `repo_pr_opened` actual emission (Sprint 11
  AgentRuntime integration 時に Mock → 本実装結線)
- BL-0102: AC-KPI-02 time_to_merge 計測 endpoint (Sprint 11 で KPI
  collector 整備時に追加)

### Sprint 8 status (Codex audit F-005 adopt で訂正、2026-05-13)

- target_days: 5
- max_days: 7
- actual (本 session): 1 day (Pack + ADR-00011 proposed + batches 1-4
  partial_skeleton + Mock backend)
- **must_ship 未達 (Codex audit F-005 adopt で正直化)**:
  - GitHub App 登録 (BL-0094): admin 手動操作、未実施
  - SecretBroker repo.push / repo.pr_open allowed_operations 追加 (BL-0095):
    RequestedOperation Literal で予約済だが、`secret_refs.allowed_operations` 配列
    + capability_token issue flow との結線は未実装
  - GitHubAppAdapter httpx wrapper (BL-0097): 2026-05-13 audit 時点では boundary absent
  - AgentRunEvent `repo_pr_opened` actual emission (BL-0100): MockRepoProxy
    から AgentRuntime への結線なし、未実装
  - AC-KPI-02 time_to_merge 計測 helper / endpoint (BL-0102): KPI collector
    実装なし、未実装
- **partial_skeleton 達成**:
  - Permission Matrix toml hardcode + check_no_dangerous_permissions (BL-0098): ✅
  - RepoProxy ABC + MockRepoProxy + DraftPRRequest server-owned-boundary
    pending (Codex F-002 で当時の 4 整合 binding 欠落を指摘、Sprint 11 で
    refactor): ✅ interface のみ
  - Webhook HMAC low-level pure helper (BL-0099): ✅ helper のみ、
    SecretBroker mediated service layer は Sprint 11
  - merge/deploy P0 deny test (BL-0101): ✅ Mock レベル
- **defer (Sprint 11 へ、明示 5 件)**: BL-0094 / BL-0095 / BL-0097 / BL-0100 /
  BL-0102

### Codex audit (2026-05-13, sp7-8-9-final-audit, R1)

- F-002 (HIGH): RepoProxy server-owned-boundary §1/§3 4 整合未実装 → adopt、
  Sprint 11 で signature refactor + DB 再計算実装 (本 Sprint で docstring 文書化)
- F-003 (HIGH): Webhook HMAC が SecretBroker-mediated / replay / rotation
  policy 未実装 → adopt、本 Sprint で low-level helper 明示 + Sprint 11 で
  service layer 実装
- F-005 (MEDIUM): must_ship 表記と Review 達成判定不整合 → adopt、status を
  `partial_skeleton` に訂正 + 5 BL 未達リスト明記 (本 commit)

### Codex review (Sprint 8)

batches 2-4 module は Mock backend / interface skeleton で security
boundary 影響は minimal (Mock は実 GitHub API を呼ばない、HMAC verifier は
標準的 constant-time compare pattern)。本 Sprint では Codex multi-round
review を skip し、test カバレッジ (37 件) + ADR-00011 §採用案 invariant
verify で品質確認。

### main branch ff merge は user 確認待ち

本 worktree branch を main へ ff merge する操作は user 直接実行を待つ
(CLAUDE.md §6.7 destructive operation policy)。本 commit push 済、PR 作成
または ff merge は user 判断。

### 2026-05-24 residual reconciliation (post-SP024 Codex)

#### verified present in current tree

- `config/github_app_permissions.toml` + `backend/app/services/repoproxy/permission_matrix.py`: minimal permission matrix, explicit deny list, and static/differential checks.
- `backend/app/services/repoproxy/repoproxy.py`: `RepoProxy` ABC, `MockRepoProxy`, branch pattern validation, branch overwrite deny, merge/deploy deny stubs.
- `backend/app/services/repoproxy/webhook_hmac.py`: low-level HMAC SHA-256 helper with constant-time compare and rotation helper.
- `backend/app/domain/agent_runtime/operation_context.py`: `repo.push` / `repo.pr_open` target schema, including `commit_sha` and `repo_state_commit_sha`.
- `backend/app/services/secrets/broker.py`: `repo.push` / `repo.pr_open` action-class mapping, approval binding, allowed operation validation, and atomic claim fingerprint checks.
- `backend/app/domain/agent_runtime/event_type.py`: `repo_pr_opened` event type exists.
- `backend/app/services/metrics/orchestrator_kpi_rollup.py`: reads existing `repo_pr_opened` events for orchestrator-level proxy rollup.
- `backend/app/services/metrics/agent_run_kpi.py` + `backend/app/api/agent_runs.py`: expose `GET /api/v1/agent_runs/{run_id}/kpi` for one tenant-scoped run without returning raw event payloads.

#### not verified / still residual

- `backend/app/services/repoproxy/github_app_adapter.py` exists as a broker-mediated adapter boundary with no raw installation token exposure to transport. Real GitHub httpx transport and live Git ref re-fetch remain pending.
- `RepoProxy.create_draft_pr()` now accepts only `DraftPRBinding`; the DB-backed resolver loads ApprovalRequest + latest ContextSnapshot and passes the internal `DraftPRRequest` to the transport. Live Git ref re-fetch remains pending for GitHubAppAdapter.
- `GitHubWebhookVerifier` service boundary with SecretBroker resolver protocol, Redis SETNX replay protocol, rotation status validation, and redacted audit payload is present. Concrete SecretBroker resolver, concrete Redis adapter, and FastAPI route wiring remain pending.
- `RepoPROpenedEventWriter` persists append-only `repo_pr_opened` AgentRunEvent payloads from successful Draft PR results. Automatic RepoProxy runtime call-site wiring remains pending.
- Real GitHub App admin registration / private key SOPS metadata cannot be verified from repo files and remains an operator setup item unless a secret metadata fixture is added.

#### next implementation batches

1. Batch A/A2: service-level RepoProxy server-owned binding refactor (`approval_id`, `agent_run_id`) + negative tests for each mismatch. **Completed 2026-05-24**: public signature now takes only `DraftPRBinding`, pure server-owned state builder exists, and DB-backed resolver loads ApprovalRequest + latest ContextSnapshot. Live Git ref re-fetch remains for Batch B transport integration.
2. Batch B: `GitHubAppAdapter` broker-mediated boundary with raw-token non-exposure tests. **Partially completed 2026-05-24**: adapter boundary + tests exist; real httpx transport, retries/rate limit, and live Git ref re-fetch remain.
3. Batch C: webhook service layer with SecretBroker resolution, Redis replay guard, rotation status validation, and audit payload redaction. **Completed 2026-05-24 at service boundary level**; concrete SecretBroker resolver / Redis adapter / FastAPI route wiring remain.
4. Batch D: actual `repo_pr_opened` emission from the runtime path. **Partially completed 2026-05-24**: append-only event writer + DB persistence tests exist; automatic RepoProxy runtime call-site wiring remains.
5. Batch E: `/api/v1/agent_runs/{run_id}/kpi` endpoint. **Completed 2026-05-24**: per-run AC-KPI-02 source endpoint + service tests exist. Final SP-008 status closeout waits for remaining transport/webhook/call-site residuals.

### 2026-05-24 Batch A implementation (RepoProxy binding guard)

#### changed

- `backend/app/services/repoproxy/repoproxy.py`: `RepoProxy.create_draft_pr()` now accepts only `DraftPRBinding` (`tenant_id`, `approval_id`, `agent_run_id`), not a caller-supplied `DraftPRRequest`.
- Added `DraftPRApprovalState` / `DraftPRSnapshotState` projections and `build_draft_pr_request_from_server_state()` for server-owned 4-binding validation.
- `MockRepoProxy` now fail-closes without a resolver and uses `StaticDraftPRRequestResolver` in tests.
- Added regression tests for signature-level deletion, approved-only PR open, action class guard, run mismatch, policy mismatch, diff hash mismatch, provider fingerprint mismatch, repo state mismatch, invalid branch, unknown binding, and resolver-less fail-closed behavior.

#### verified

- `uv run pytest tests/repoproxy -q`
- pending final PR gate: ruff + mypy + docs frontmatter + diff check.

#### deferred

- Real GitHub httpx transport, retries/rate limit handling, and broker-owned installation token use.
- Live Git ref re-fetch immediately before GitHub push / Draft PR creation.
- Automatic call-site wiring from the final RepoProxy Draft PR execution path to `RepoPROpenedEventWriter`.

### 2026-05-24 Batch C implementation (Webhook service boundary)

#### changed

- `backend/app/services/repoproxy/webhook_service.py`: added `GitHubWebhookVerifier`, `WebhookSecretResolver`, `WebhookReplayStore`, and redacted audit result payloads.
- The service verifies current active secret first, then previous deprecated secret during rotation, and denies any previous secret with an invalid status.
- Replay nonce is claimed only after HMAC validation succeeds, using a tenant + installation + delivery hash key and a 3600 second TTL.
- Audit payload records hashes and metadata only; raw signature header, delivery id, and HMAC secret are not emitted.
- `backend/app/services/repoproxy/webhook_hmac.py`: updated module contract to keep it as the low-level pure helper behind the service boundary.
- `tests/repoproxy/test_webhook_service.py`: added 11 focused tests for current/previous secret acceptance, mismatch no-replay, replay duplicate deny, status validation, missing delivery id, audit redaction, JSON serializability, and replay TTL validation.

#### verified

- `uv run pytest tests/repoproxy/test_webhook_service.py -q`

#### deferred

- Concrete SecretBroker-backed secret resolver for webhook HMAC secret material.
- Concrete Redis SETNX replay adapter.
- FastAPI `/webhooks/github` route with Tailscale-only ingress check.
- Automatic call-site wiring from the final RepoProxy Draft PR execution path to `RepoPROpenedEventWriter`.

### 2026-05-24 Batch D implementation (repo_pr_opened event writer)

#### changed

- `backend/app/services/repoproxy/repo_pr_event.py`: added `RepoPROpenedEventWriter`, `build_repo_pr_opened_payload()`, and `append_repo_pr_opened_event()`.
- `DraftPRResult` now carries safe server-owned `repo_full_name`, `branch`, and `head_sha` fields for downstream event emission.
- `MockRepoProxy` and `GitHubAppAdapter` populate those safe result fields from the internal resolved `DraftPRRequest`.
- Event payloads are rebuilt into canonical `https://github.com/{owner}/{repo}/pull/{number}` URLs, so a bad transport-provided URL cannot leak raw tokens.
- Event writer uses `AgentRunEventRepository.append_event()` with `event_type='repo_pr_opened'` and idempotency key `repoproxy:repo_pr_opened:{run_id}:{pr_number}`.
- `tests/repoproxy/test_repo_pr_opened_event.py`: added unit tests for payload redaction, deny paths, idempotency key calls, and a DB integration test for append-only persistence.

#### verified

- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/repoproxy/test_repo_pr_opened_event.py -q`

#### deferred

- Automatic call-site wiring from the final RepoProxy Draft PR execution path to `RepoPROpenedEventWriter`.

### 2026-05-24 Batch E implementation (AgentRun KPI endpoint)

#### changed

- `backend/app/services/metrics/agent_run_kpi.py`: added `AgentRunKpiService` and `AgentRunKpi` for one tenant-scoped AgentRun.
- The service dedupes `repo_pr_opened` events by `(run_id, seq_no)`, uses the first PR-opened event timestamp as the source, and emits a `time_to_merge_proxy_ms` sample only when the run is `completed` and `completed_at >= first_repo_pr_opened_at`.
- `backend/app/api/agent_runs.py`: added `GET /api/v1/agent_runs/{run_id}/kpi`.
- The endpoint returns ids, status, timestamps, counts, sample count, and proxy value only. It does not return raw `agent_run_events.event_payload`.
- `tests/metrics/test_agent_run_kpi.py`: added DB integration tests for first-event selection, running-run no-sample, negative temporal sample rejection, and tenant/missing-run scoping.
- `tests/api/test_agent_runs_kpi.py`: added route/response/404 tests and asserted raw payload keys are absent from API output.
- `tests/api/test_sp012_9_ui_wiring_routes.py`: added route registration coverage.

#### verified

- `uv run ruff check backend/app/services/metrics/agent_run_kpi.py backend/app/services/metrics/__init__.py backend/app/api/agent_runs.py tests/metrics/test_agent_run_kpi.py tests/api/test_agent_runs_kpi.py tests/api/test_sp012_9_ui_wiring_routes.py`
- `PYTHONPATH=cli uv run mypy backend/app/services/metrics/agent_run_kpi.py backend/app/api/agent_runs.py tests/metrics/test_agent_run_kpi.py tests/api/test_agent_runs_kpi.py`
- `uv run pytest tests/api/test_agent_runs_kpi.py tests/api/test_sp012_9_ui_wiring_routes.py -q`
- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/metrics/test_agent_run_kpi.py -q`

#### deferred

- True PR merged timestamp source (`repo_pr_merged` / GitHub merge event) remains future work; current P0 source is explicitly a `repo_pr_opened` to AgentRun completion proxy.
- Automatic call-site wiring from final RepoProxy Draft PR execution to `RepoPROpenedEventWriter`.

### 2026-05-24 Batch A2 implementation (DB-backed Draft PR resolver)

#### changed

- `backend/app/services/repoproxy/draft_pr_resolver.py`: added `DbDraftPRRequestResolver` that tenant-scopes `ApprovalRequest` and latest `ContextSnapshot` lookup from `DraftPRBinding`.
- Resolver delegates all 4-binding validation to `build_draft_pr_request_from_server_state()`.
- Approved approvals are invalidated on stale artifact/policy/provider/repo-state deny reasons before returning fail-closed.
- Added DB integration tests for latest snapshot selection, missing approval, tenant/run scoping, missing snapshot invalidation, repo-state mismatch invalidation, and pending approval no-mutation behavior.

#### verified

- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/repoproxy/test_repoproxy_db_resolver.py -q`

#### deferred

- Real GitHub httpx transport, retries/rate limit handling, and broker-owned installation token use.
- Live Git ref re-fetch immediately before GitHub push / Draft PR creation.
- Automatic call-site wiring from the final RepoProxy Draft PR execution path to `RepoPROpenedEventWriter`.

### 2026-05-24 Batch B implementation (GitHubAppAdapter boundary)

#### changed

- `backend/app/services/repoproxy/github_app_adapter.py`: added `GitHubAppAdapter`, `GitHubBrokeredTransport`, `GitHubDraftPRResponse`, and pinned `GITHUB_API_VERSION = "2022-11-28"`.
- Adapter redeems only SecretBroker capability tokens for `repo.pr_open`; it never accepts or passes a raw GitHub installation token.
- Transport receives `BrokerOperationContext.secret_handle` + internal `DraftPRRequest`, keeping raw installation token resolution inside SecretBroker / broker-owned transport internals.
- Added tests for broker redeem arguments, pinned API version, broker-denial fail-closed behavior, invalid approval ID no-broker-call behavior, and no installation token exposure to transport.

#### verified

- `uv run pytest tests/repoproxy/test_github_app_adapter.py -q`
- `TASKMANAGEDAI_RUN_DB_TESTS=1 TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai@127.0.0.1:55434/taskmanagedai_test' uv run pytest tests/repoproxy -q`

#### deferred

- Real GitHub httpx transport, retries/rate limit handling, and broker-owned installation token use.
- Live Git ref re-fetch immediately before GitHub push / Draft PR creation.
- Automatic call-site wiring from the final RepoProxy Draft PR execution path to `RepoPROpenedEventWriter`.

## QL-B cross-reference (R29 §5 QL-B、2026-05-15 doc-only、F-PR12-004 P2 adopt)

本 Pack の acceptance spec として、QL-B Quality Loop run で記録された future implementation gate を以下の通り cross-reference する:

- `docs/基本設計/06_秘密管理設計.md §13.1` OperationContext canonical schema `repo.pr_open` target = `{repo_full_name, base_branch, head_branch, draft=true, commit_sha, repo_state_commit_sha}` (本 Pack で実装済の broker validator `backend/app/services/secrets/broker.py:681-698` の正本、F-PR12-010 反映)
- `docs/基本設計/03_AIオーケストレーション設計.md §13.1` PolicyDecision must-precede (`pr_open` / `repo_write` action 実行前に outbox pattern で policy_decisions row 記録、external GitHub API 呼出と DB transaction を同一 scope にしない)
- `docs/基本設計/04_セキュリティ_権限_監査設計.md §13.1` action_class 7 種 (`pr_open` Draft PR 作成のみ、merge は P0 deny)
- `docs/adr/00025_autonomy_policy_profiles.md` (proposed) §10.2 L3 `pr_open` auto-allow 例外 (SecretBroker capability issue/redeem を内包する path は別 gate で human approval 必須)
