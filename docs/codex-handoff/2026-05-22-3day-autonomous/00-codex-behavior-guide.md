# Codex Behavior Guide (autonomous full drive 期間中の行動規範)

本 file は Codex が 3 日間 autonomous で TaskManagedAI 開発を進める際の **絶対遵守 invariant + 振る舞い指示書**。Claude が連続 42 PR merge で確立した品質担保 path を継承する。

## §1 起動 protocol

### 1.1 必読 file (起動時)

順番に Read:

1. `docs/codex-handoff/2026-05-22-3day-autonomous/README.md` (master index)
2. **本 file** (`00-codex-behavior-guide.md`)
3. `01-current-state.md` (現状 snapshot)
4. `02-task-priority-matrix.md` (task 優先順位)
5. 自分が着手する `tasks/task-NN-*.md` (個別 task 指示)
6. 関連 rules (本 file §10 参照、task ファイルから追加 link)

### 1.2 worktree 設定

Codex は **新 worktree で作業** (既存 `.claude/worktrees/sprint-SP-012-batch-7-taskhub-admin-cli` は Claude 用):

```bash
cd /Users/tohga/repo/TaskManagedAI
git worktree add .claude/worktrees/codex-task-<task-name> origin/main
cd .claude/worktrees/codex-task-<task-name>
bash scripts/worktree_setup.sh  # pnpm install + uv sync + SOPS 復号 (5-10 min)
```

並行 task が複数なら **task ごと別 worktree** で衝突回避。

### 1.3 environment

```bash
# host 側 uv run 用 env (Mac local docker compose stack 経由 DB アクセス)
export TASKMANAGEDAI_DATABASE_URL='postgresql+asyncpg://taskmanagedai:taskmanagedai_local_smoke_pwd@127.0.0.1:5432/taskmanagedai'
export TASKMANAGEDAI_REDIS_URL='redis://127.0.0.1:6379/0'
export TASKMANAGEDAI_DEV_LOGIN_COOKIE_SECRET='dummy-host-side-execute-8chars'

# test DB
export TASKMANAGEDAI_DATABASE_URL_TEST='postgresql+asyncpg://taskmanagedai:taskmanagedai_local_smoke_pwd@127.0.0.1:5432/taskmanagedai_test'
export TASKMANAGEDAI_RUN_DB_TESTS=1
```

Mac local stack は **継続起動中** (Claude が PR #100-#141 で構築)、`docker compose up` 不要。

## §2 計画必須判定

### 2.1 計画必須 (実装前に **§3.1 Self-Plan-Review** 必須)

以下のいずれかに該当する task:

1. **heavy Sprint Pack** (本 handoff の task-01 / task-02)
2. **新規 ADR が必要** (ADR Gate Criteria 11 種該当)
3. **3 file 横断以上の実装変更**
4. **新規 migration を含む** (Alembic 追加)
5. **CRITICAL invariant 直結変更** (AgentRun 16 状態 / ContextSnapshot 10 列 / Provider Compliance 13 reason_code / SecretBroker raw secret 非保存 / Tenant boundary / actor / principal / approval 4 整合 / runner_mutation_gateway / tool_mutating_gateway_stub / PostgreSQL CHECK / 複合 FK)
6. **複数 backend route + frontend wiring 同時** (task-04 等)

### 2.2 計画必須 task の手順 (Self-Review Protocol、§3 詳細)

Step 1: **§3.1 Self-Plan-Review** = Round 1 (構造論点) + Round 2 (敵対視点) を Codex 自身が 1 session 内で直列 self-execute。findings.md に列挙 + 採否判定 (adopt/reject/defer) + plan file 修正反映。

Step 2: **Readiness Gate 自己判定** = 残存 CRITICAL=0 / HIGH≤2 で `READY`、それ以外は `BLOCKED` → `STOPPED.md` 起票。

Step 3: **§3.2 Self-Impl-Review** = batch 実装 → 直後に Self-Adversarial-Review 1 round → Readiness Gate (CRITICAL=0) → local verify → PR 起票。

`codex-all-loops` (Claude Code skill、`~/.claude/skills/codex-all-loops/SKILL.md`) は Codex CLI から呼べない (§3.0)。Claude verification 戻り時に Claude が deeper round を実施 (§3.4)。

### 2.3 計画不要 (直接実装可)

- 1-2 file / 30 行未満の minor fix
- typo / コメント修正 / frontmatter 更新
- 既存 pattern 適用の定型作業 (import 追加 / type cast 等)
- Codex finding fix で 1 行 commit (commit 抜け追加等)

## §3 Self-Review Protocol (Codex 自身で同等観点を確保)

### 3.0 重要: codex-all-loops は Codex CLI から呼べない

`codex-all-loops` / `codex-review-loop` / `codex-impl-loop` / `codex-adversarial-loop` / `codex-plan-review` は **Claude Code の Skill** (`~/.claude/skills/codex-*/SKILL.md`)。Codex CLI / Codex session からは **直接 invoke 不可**。

さらに `AGENTS.md` / `.claude/rules/codex-usage-policy.md` §1 で **「Codex chain の並列起動禁止」+「Codex 自身がさらに Codex を呼ぶ chain を作らない」** が invariant (再帰禁止)。

→ Codex は **自身の 1 session 内で plan-review / impl / adversarial-review を直列に self-execute** + **Readiness Gate 自己判定** で同等観点を確保する。Claude verification 戻り時に Claude が `codex-all-loops` skill で deeper round を実施 (品質担保の補強)。

### 3.1 Self-Plan-Review (計画必須 task の代替経路)

**目的**: codex-all-loops mode=plan の代替。Codex 自身が 1-2 round で plan を review + adversarial 観点で深掘り + Readiness Gate 自己判定。

#### Round 1 (構造 review): plan file + 関連 Sprint Pack + ADR + rules を Read

- 計画書 (`tasks/task-NN-*.md` + `docs/sprints/SP-NNN-*.md`) を全文 Read
- 関連 ADR / rules / 過去類似 PR を Read (各 task ファイル §関連参照 に列挙済)
- 以下を network 構造論点として列挙:
  - 抜け漏れ: 必要 step / 考慮事項 / エッジケース
  - 整合性: 既存 code / docs / 公式仕様との矛盾
  - 曖昧さ: 複数解釈 / 判断迷う点
  - 依存関係: ticket 順序 / migration 順序
  - 5+ source enum drift / cascade pattern リスク

→ findings.md に finding-schema (id / severity / category / symptom / recommendation) で列挙。

#### Round 2 (敵対視点 review): Round 1 finding ベース + 新規 adversarial 観点

- assumption 違反 (前提が崩れる scenario)
- race condition (並行 transaction / lease)
- boundary edge case (DB CHECK 抜け / Pydantic extra forbid 抜け / signature レベル漏れ)
- security boundary (caller-supplied 経路 / raw secret / actor 偽装)
- regression test cover 不足

→ findings.md に追記。Round 1 findings と重複は除外 (堂々巡り防止)。

#### Readiness Gate (Codex 自己判定)

- 全 finding を severity (CRITICAL / HIGH / MEDIUM / LOW) で分類
- 採否判定 (adopt / reject / defer) を実施し plan file に反映 (Edit ツールで直接修正)
- adopt 後の **残存 CRITICAL = 0 AND 残存 HIGH ≤ 2** で `READY` (実装着手可能)
- それ以外は `BLOCKED` → `STOPPED.md` 起票 + Claude verification 待ち
- findings.md + Readiness Gate 結果は PR description §self-review-verdict に貼り付け

#### `codex` CLI の `review` サブコマンド活用 (option)

Codex CLI 自体に `codex exec review` がある場合、本 self-review の structured 出力に活用可:

```bash
codex exec review --target docs/sprints/SP-014_orchestrator_agent.md \
  -c model_reasoning_effort=xhigh \
  --json
```

ただし **このコマンドの実行は「Codex 1 session 内の sub-step」であり、Codex chain (再帰) ではない**。AGENTS.md invariant 「Codex から Codex skill を呼ぶ chain 禁止」とは別概念 (chain = 別 session を spawn する pattern を指す)。

### 3.2 Self-Impl-Review (実装 task の代替経路)

**目的**: codex-all-loops mode=code の代替。Codex 自身が batch 実装 + 直後に self-review (敵対視点) + Readiness Gate 自己判定。

#### Step 1: batch 実装 (5-10 file / 1500-3000 行)

- task ファイル §4 実装 phase の batch 分割に従い、1 batch 単位で実装
- 各 file を Read → Edit / Write で実装
- 既存 pattern 確認 (PR #133-#140 / PR #128-#131 等の最近の merge PR を `git log -p` で参照)

#### Step 2: 実装後 Self-Adversarial-Review (1 round)

実装完了直後、別 「new conversation context」のつもりで自身の diff を re-read + 敵対視点で review:

- **invariant 観点** (本 file §7 + §8 全項目を 1 つずつ check)
  - server-owned-boundary §1: caller-supplied 経路 signature レベル削除?
  - 5+ source enum integrity: Literal + frozenset + Pydantic + pytest + DB CHECK?
  - raw secret 非保存: DB / log / artifact / audit / ContextSnapshot 漏れなし?
  - cascade pattern: matrix-based logic で全 case 明示 enforce?
- **regression test** が case ごと別 test function で追加されている?
- **boundary edge case** (concurrent / null / negative / overflow / unicode)
- **error path** (exception 握りつぶし / 弱い assertion / fallback 不適切)

→ findings を列挙 + 即 adopt fix (commit に重ねる) or defer (TODO + Sprint Pack 残リスク)。

#### Step 3: Readiness Gate (Codex 自己判定)

- 残存 CRITICAL = 0 で `READY` (PR 起票可能)
- それ以外 → 追加 fix or `STOPPED.md`

#### Step 4: local verify

§4.3 admin bypass merge 6 条件のうち §4.3 #1 を満たす:

```bash
# Backend 変更時
uv run ruff check backend tests
uv run mypy backend
uv run pytest tests/<関連 dir>/ -q

# Frontend 変更時
cd frontend
pnpm typecheck
pnpm lint
pnpm vitest run

# Migration 含む時
uv run alembic check
uv run alembic upgrade head
# downgrade テスト
uv run alembic downgrade -1 && uv run alembic upgrade head
```

### 3.3 PR 起票後 Codex auto-review baseline 確認 (`§6` で詳細)

PR push 後、**GitHub の Codex bot が PR trigger で auto-review** を実施する (Codex 自身が呼ぶ chain ではない、external trigger)。

```bash
sleep 60  # Codex auto-review trigger 待ち
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -200
```

baseline 内容確認 (delta +0 = 真の 0 件 ≠ baseline 見逃し、PR #42/#44/#47 教訓) + 採否判定 + adopt fix commit。

これは **Codex 自身が起動する chain ではなく**、GitHub Codex App が PR webhook で起動する独立 service なので AGENTS.md invariant に違反しない。

### 3.4 Claude verification 戻り時に codex-all-loops で deeper round (品質担保補強)

3 日間後に Claude が戻ったとき (`03-claude-verification-checklist.md`)、Claude が本 worktree から `codex-all-loops` skill を起動して deeper round を実施可能:

```
Skill(skill="codex-all-loops", args="docs/sprints/SP-014_orchestrator_agent.md --mode=plan --max-rounds=8")
```

これは Claude Code main session 内の Skill 起動であり、Codex chain ではない (AGENTS.md 整合)。

→ Codex 側は self-review で **CRITICAL 0** を達成する責務、Claude 側で deeper adversarial round で品質担保補強。

## §4 PR 起票 protocol

### 4.1 branch 命名

| prefix | 用途 | 例 |
|---|---|---|
| `feat/sp014-batch-0-*` | SP-014 batch 実装 | `feat/sp014-batch-0a-orchestrator-lease-manager-2026-05-23` |
| `feat/sp012-8-batch-*` | UI i18n batch | `feat/sp012-8-batch-1-navigation-japanese-2026-05-23` |
| `feat/sp022-1-*` | scripts hardening | `feat/sp022-1-pg-dump-flag-fix-2026-05-24` |
| `fix/prNN-codex-*` | post-merge Codex finding fix | `fix/pr142-codex-p1-lease-race-2026-05-23` |

### 4.2 PR description format

```markdown
## Summary

<1-3 bullet 要約 + 関連 Sprint Pack + ADR>

## self-review verdict (§3 Self-Review Protocol)

<Round 1 (構造) + Round 2 (敵対) の findings 採否判定 + Readiness Gate 結果 + local verify 結果>

## changes (files / 行数)

| file | operation | 行数 |
|---|---|---|
| ... | ... | ... |

## verification

- ruff check: clean / failures
- mypy backend: clean / failures
- pytest tests/multi_agent/: N PASS / N FAIL
- pnpm typecheck + lint + test: ... (frontend 時)
- alembic upgrade Mac local: 成功 / 失敗 (migration 時)

## invariant 遵守

- server-owned-boundary §1: ✅ caller-supplied 経路なし
- 5+ source enum integrity: ✅ Literal / frozenset / DB CHECK / pytest / (mirror table)
- (CRITICAL invariant trace は task ファイル §invariant の項目を copy)

## ADR Gate

[非該当 (理由) / 該当 (ADR-NNNNN 起票必要)]

🤖 Generated with Claude Code (Codex 委譲、Claude verification pending)

Co-Authored-By: Codex <noreply@openai.com>
```

### 4.3 admin bypass merge 条件 (CI billing-blocked 状態)

全て満たす PR のみ admin bypass merge OK:

1. **local verify 全件 clean** (ruff + mypy + pytest [DB test 含む TASKMANAGEDAI_RUN_DB_TESTS=1] + typecheck + lint + Vitest)
2. **既存 contract test regression なし** (multi_agent 30 件 + tickets 8 件 + dogfooding seed 24 件 + 累計 70+ vitest)
3. **migration 含む場合は Mac local DB に upgrade head 確認済** + downgrade 動作確認
4. **invariant trace** が PR description に記載
5. **Codex auto-review baseline 自己確認後** (本 file §6)
6. **ADR Gate 非該当** (該当時は Claude による ADR 起票 + accepted promotion が先決、本 handoff scope 外)

### 4.4 admin bypass merge コマンド

```bash
PR_NUM=$(gh pr list --head <branch> --json number -q '.[0].number')
HEAD_SHA=$(gh pr view "$PR_NUM" --json headRefOid -q '.headRefOid')
gh api -X PUT "repos/t-ohga/TaskManagedAI/pulls/$PR_NUM/merge" \
  -f merge_method=squash \
  -f sha="$HEAD_SHA" \
  -f commit_title="<title> (#$PR_NUM)" \
  -f commit_message="<commit message>"
```

## §5 branch 衝突回避戦略

並行 task で同一 file を編集する可能性:

| file | task |
|---|---|
| `frontend/app/(admin)/*/page.tsx` | task-02 i18n / task-04 wiring |
| `backend/app/api/tickets.py` | task-04 wiring (ApprovalRequest auto trigger 除く) |
| `backend/app/cli/dogfooding_seed.py` | task-03 hardening (sanitizer ruleset) / 別 task |

回避策:

1. **task ごと別 worktree + 別 branch** で並行作業
2. 同 file 修正が必要なら **時系列で順次** (前 task の merge 後に次 task 着手)
3. 衝突発生時は `git pull --rebase origin main` で linear history 維持
4. **同 file 複数 task は 1 PR にまとめる** (例: tickets.py の Approval auto trigger + audit_event 詳細化 は SP-014 と一緒に)

## §6 Codex auto-review 確認義務

### 6.1 必須 trigger

**code change PR 起票後** (push + `gh pr create` 後)、admin bypass merge 前 or 直後に baseline 確認:

```bash
sleep 60  # Codex auto-review trigger 待ち
.claude/scripts/codex_pr_full_review.sh <PR_NUM> 2>&1 | head -200
```

### 6.2 baseline 内容確認必須 (PR #42/#44/#47 で再発)

- **`head -200` で head 行確認** (delta +0 を「真の 0 件 clean」と誤判定しない、`feedback_codex_review_must_use_full_helper.md` 教訓)
- inline + conversation + reviews 3 endpoint 全件取得 確認
- Codex bot filter (`chatgpt-codex-connector[bot]`) 経由

### 6.3 採否判定 (3 分類)

| 判定 | 条件 | アクション |
|---|---|---|
| **adopt** | TaskManagedAI rules / PRD / DD / Sprint Pack / ADR と整合、根拠明確、真の bug or invariant 違反 | fix commit + PR update (merge 前) または follow-up `fix/prNN-codex-*` PR (merge 後) |
| **reject** | Codex 誤認 / 文脈不整合 / 既存 pattern と意図的に異なる設計 | PR comment で reject 理由返信、`~/.claude/local/codex-reviews/<date>/<slug>/rejected.md` に記録 |
| **defer** | 別 Sprint / 別 PR へ (scope 大 or multi-actor 化後等) | TODO comment + Sprint Pack 残リスクに記録 |

### 6.4 cascade pattern 防止 (Claude 教訓、PR #133→#135→#137)

**1 fix で 1 invariant 修正 + 別 invariant に regression** = cascade 発生。

**回避**:
- invariant fix は **matrix-based logic** で全 case (例: 7 cases × 3 dimensions) を明示 enforce
- shallow `if a and b` ではなく、`if scope == X: if not condition: raise` の **branch separation** で全 case 確実 cover
- regression test を **case ごと別 test function** で追加 (1 case 1 test)

## §7 5+ source enum integrity

新規 enum 導入時、以下 5+ source で完全一致:

1. **Python Literal** (`backend/app/domain/.../taxonomy.py` 等)
2. **Python Final frozenset** (constant、runtime 比較用)
3. **Pydantic Field validator** (request/response schema)
4. **pytest fixture** (`EXPECTED_*` constant、parametrize)
5. **DB CHECK constraint** (migration)
6. **(option) DB mirror table** (immutable seed、PE-F-012 mitigation pattern)
7. **(option) frontend TypeScript enum** (UI 表示用、Sprint 9+)

**drift 検出**:
- import-time `assert frozenset(get_args(Literal)) == STANDARD_*` で early detection
- pytest contract test で `exact name set` 比較 (`assert set(actual) == set(expected)`)
- migration ast parse + CHECK constraint 値抽出 (Claude `test_action_class_enum.py` pattern 流用)

## §8 server-owned-boundary §1 invariant

caller-supplied 経路を **signature レベルで物理削除**:

| field | source |
|---|---|
| `tenant_id` | session (Depends) |
| `project_id` | session 経由 (`/api/v1/me/current_project`) |
| `actor_id` | session (Depends(get_current_actor_id)) |
| `created_by_actor_id` | server resolve、payload に含めない |
| `payload_data_class` | request / artifact metadata から事前算出 |
| `allowed_data_class` | Matrix からのみ resolve |
| `expected_request_fingerprint` | broker 内部 canonical OperationContext から再計算 |

Pydantic schema は `extra="forbid"` で caller-supplied 経路を完全排除。

## §9 migration 規律

### 9.1 必須 invariant

- **revision id ≤ 30 chars** (project convention、`.claude/rules/testing.md` §12)
- **down_revision 連続** (linear history)
- **downgrade 実装必須** (rollback 可能性確保)
- **Mac local DB に upgrade head 確認** (PR merge 前)
- **既存 constraint との重複追加禁止** (Claude PR #136 反省、既存 `agent_runs_uq_tenant_project_id` を見落として重複追加した過去あり)

### 9.2 trigger / function 変更

`CREATE OR REPLACE FUNCTION` で前 migration の trigger を replace 可能 (Claude PR #140 pattern)。downgrade では旧 version を `CREATE OR REPLACE` で restore。

## §10 既存 rules 参照

絶対遵守:

- `.claude/rules/codex-usage-policy.md` (§14 mandatory Codex review gates)
- `.claude/rules/server-owned-boundary.md`
- `.claude/rules/cross-source-enum-integrity.md`
- `.claude/rules/sprint-pack-adr-gate.md`
- `.claude/rules/agentrun-state-machine.md`
- `.claude/rules/provider-compliance.md`
- `.claude/rules/secretbroker-boundary.md`
- `.claude/rules/ai-output-boundary.md`

参照推奨 (task により):

- `.claude/rules/rendering.md` (frontend task)
- `.claude/rules/testing.md` (test 追加時)
- `.claude/rules/instincts.md` (Edge case 事故予防)
- `.claude/rules/branch-and-pr-workflow.md` (PR 起票)

## §11 完了報告 protocol

3 日間終了時 (or 個別 task 完了時) に Codex は:

### 11.1 task 単位完了報告

`docs/codex-handoff/2026-05-22-3day-autonomous/completion/task-NN-completed.md` を新規起票:

```markdown
# task-NN 完了報告 (YYYY-MM-DD)

## summary

- task: SP-NNN batch X
- start: 2026-05-23 09:00 JST
- end: 2026-05-24 18:00 JST (~28h)
- 完了 BL: BL-XXX / BL-XXX
- 累計 PR: #142 / #143 / #144

## PR list

| PR | merge SHA | scope | Codex finding |
|---|---|---|---|
| #142 | abc1234 | ... | adopt 2 (PR #145 で fix) |
| #143 | def5678 | ... | clean (0 findings) |

## Codex finding 採否判定

| PR | finding | severity | judgment | follow-up PR |
|---|---|---|---|---|
| #142 | <内容> | P1 | adopt | #145 |
| ... | ... | ... | ... | ... |

## defer / carry-over

- BL-XXX-NNN: <理由>、移送先: SP-NNN-N (新規起票 or 既存追記)
- defer 全件は新 Sprint Pack 起票 or 既存 Sprint Pack の `## Review` §deferred で carry-over 記載

## blocker (if any)

- ...

## Claude verification 依頼項目

1. `<file>` 中 `<function>` の invariant <description>
2. ...
```

### 11.2 3 日間総括報告

`docs/codex-handoff/2026-05-22-3day-autonomous/COMPLETION_REPORT.md` を新規起票:

```markdown
# Codex 3-day Autonomous Completion Report (2026-05-22 → 2026-05-25)

## summary
- 完了 task: task-01 / task-02 / task-03 / task-04 (4 / 4)
- 累計 PR merge: 47 PR
- Codex finding: P1×3 + P2×5 = 8 件 (全件 close)
- multi_agent test PASS: 45 件 (累計 30 + 新 15)
- carry-over Sprint Pack: SP-014-1 / SP-012-8-1 (2 件新規起票)

## next session entry (Claude verification)
- 03-claude-verification-checklist.md の checklist を Read
- 必要時 fix PR 起票
- 完了 task の Sprint Pack frontmatter 確認
```

### 11.3 handoff memory

`~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/project_session_2026_05_25_codex_3day_complete.md` を起票:

- 本 file の Claude rehydrate base、auto-compact 後も読める
- `MEMORY.md` index に 1 行追加

## §12 緊急停止

以下を検知したら **`STOPPED.md` を新規起票** + 即座に停止 (Claude が起動して確認するまで再開禁止):

- Codex 3 連続失敗
- spec 衝突 (handoff file 内、または既存 rules / Sprint Pack)
- ADR Gate Criteria 11 種該当変更が必要 (本 handoff scope 外)
- Mac local stack 不可逆破壊リスク
- 想定 effort 大幅超過 (3 day で完遂不可能)

```markdown
# STOPPED.md

## stopped at
2026-05-NN HH:MM:SS JST

## task
task-NN

## reason
<具体的内容>

## Claude action 必要
<Claude が戻ったときに何をすべきか>

## state preserved
- 現在の branch: ...
- 既 merge PR: ...
- 未 merge PR: ...
- Mac local stack alembic head: ...
```

## §13 全体 invariant

- **autonomous full drive 期間中** = AskUserQuestion 不可、判断は本 handoff file + 既存 rules で完結
- **admin bypass merge OK** だが §4.3 6 条件全件 必須
- **Codex 自身がさらに Codex 委譲は禁止** (再帰禁止、Anthropic 公式制約と整合)
- **品質担保 path 復元 invariant** 維持: code change PR で codex_pr_full_review.sh baseline 確認必須 (本 file §6)
- **本 handoff file 修正禁止** (Claude 起動後の retroactive 修正は不可、blocker は §12 STOPPED.md で対応)
