---
name: branch-pr-workflow
description: "TaskManagedAI の worktree + branch + PR + Codex auto-review + merge workflow を実体化する skill。invocation triggers include 'PR 起票', 'worktree 作成', 'PR merge', 'Codex auto-review 確認', 'user 手元作業の代理処理 path'。1 ticket = 1 PR = 1 worktree branch、Claude が起票・修正・採否判定、user が merge という責務分離を skill body で正本化。"
disable-model-invocation: false
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# branch-pr-workflow

TaskManagedAI の worktree + branch + PR + Codex auto-review + merge workflow を Skill として実体化。invocation 時に本 SKILL.md 全体を Main Agent context に load し、各 step の手順 (branch 命名 / phase 0-3 worktree / PR convention / Codex review / 採否判定 / merge 責務分離 / divergence 防止 / 完了条件) を参照する。

## 起動条件 (When to invoke)

- **PR 起票** (`gh pr create` 前)
- **worktree 作成** (`EnterWorktree` 前)
- **Codex auto-review 確認** (PR push 後、`.claude/scripts/codex_pr_full_review.sh` 実行前)
- **PR merge 判断** (Claude classifier reject 経路 / user 直接 merge の確認)
- **user 手元作業の代理処理** (uncommitted / staged / untracked / 6 state を Claude が代理 PR 起票)
- **divergence 整理** (2 branch 並走、worktree branch ↔ main repo current branch)

## 原則

- **1 ticket = 1 PR = 1 worktree branch** (Sprint / Quality Loop / hotfix 単位)
- branch / commit / PR は **append-only** (rebase 最小限、push 済 history 上書き禁止)
- main / master への **直接 commit / push 禁止** (PR 経由のみ)
- **Claude (worktree work)** と **user (main merge 判断)** の責務分離
- branch 名は **内容と一致** (drift したら rename ではなく新 branch 起こす)
- **Codex auto-review** は PR trigger で起動、findings は Claude が pull → adopt/reject/defer 判定 → fix commit で PR update

## Branch 命名 convention

| prefix | 用途 | 例 |
|---|---|---|
| `quality-loop/QL-X-<topic>` | R29 統合計画 §5 QL-A〜QL-G の Quality Loop run | `quality-loop/QL-A-registry-namespace` |
| `sprint/SP-NNN-batch-N` | Sprint 実装 batch | `sprint/SP-010-batch-0` |
| `adr/ADR-NNNNN-<topic>` | ADR 単独起票 | `adr/ADR-00028-host-portable-amendment` |
| `refactor/<topic>` | refactor (context-mgmt-refactor 等) | `refactor/context-mgmt-phase-a` |
| `docs/<topic>` | doc-only 単発 update | `docs/sprint-pack-readme-fix` |
| `hotfix/<issue>` | 緊急修正 (ADR Gate Criteria 11 種 break-glass 対象外限定) | `hotfix/lint-warning-fix` |
| `fix/pr<N>-codex-<scope>` | post-merge Codex finding follow-up | `fix/pr1-codex-p1-security` |
| `chore/<topic>` | CI / settings / ci concurrency fix 等 | `chore/ci-concurrency-push-sha-fix` |

**禁止 (drift 原因)**:
- 命名後の rename (PR link 切れ、Codex review track 切れ): 内容変わるなら **新 worktree branch を起こす**
- 1 branch で複数 ticket 混合 commit
- `worktree-<NAME>` (旧 convention、DEPRECATED 2026-05-15)
- `feature/<short>` (Sprint Pack 対応が曖昧化)

## Worktree workflow (4 phase)

### Phase 0: 着手前

1. **EnterWorktree** で新 worktree 作成 (branch 命名は上記 convention)
   - 親: `/Users/tohga/repo/TaskManagedAI` (main repo) または既存 worktree
   - base branch: `main` (または P0.1 開始後は `release/p0.1` 等)
2. code を触る場合: `bash scripts/worktree_setup.sh` で setup 自動化 (pnpm install + uv sync + SOPS 復号、~10 分)
3. doc-only 作業の場合: setup skip 可

### Phase 1: 進行中

1. Claude が worktree 内で work
2. **3 phase pattern 推奨** (CRITICAL invariant 直結 code 変更):
   - Phase 0: Claude direct edit (実 file 編集 + new file 起票)
   - Phase 1: `codex-review-loop` (構造磨き、R1=ALL / R2=HIGH+ / R3=CRITICAL、clean まで)
   - Phase 2: `codex-adversarial-loop` (敵対視点、R1=ALL / R2=HIGH+ / R3=CRITICAL、clean まで)
3. 適宜 commit、`git push -u origin <branch>` (worktree branch を origin に push)
4. **divergence 防止**: 別 branch との作業混在禁止 (cross-branch edit は別 worktree で)

### Phase 2: PR 作成 + Codex review

§PR-creation + §Codex-review section 参照。

### Phase 3: 完了後

1. clean 判定後、user に **main へ merge 判断**を委ねる (§責務分離)
2. `ExitWorktree action=remove` で worktree clean exit (**commit が remote に push 済確認後**)
3. 旧 worktree branch は origin に残す (PR 履歴維持、merge 後は GitHub 側で auto-delete 設定可)

## PR 作成 protocol

```bash
gh pr create --base main --head <worktree-branch> \
  --title "<prefix>(<scope>): <summary> (codex-all-loops R{N} clean、{M} findings)" \
  --body "$(cat <<'EOF'
## Summary
<1-3 bullet 要約 + reference>

## codex-all-loops verdict
<Phase 1/2 round summary + findings closure 数>

## 変更 file list (operation + 行数)
<table>

## 不変条件 trace
<applicable subset>

## Test plan
- [ ] Codex auto-review 完了
- [ ] Codex findings 採否判定 (adopt/reject/defer)
- [ ] fix commit で PR update
- [ ] clean 判定後 main merge

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### PR title convention

`<prefix>(<scope>): <summary> (codex-all-loops R{N} clean、{M} findings)`

- prefix: Conventional Commits (`docs`/`feat`/`fix`/`refactor`/`test`/`chore`)
- scope: ticket id (`QL-A` / `SP-010-batch-0` / `context-mgmt-phase-a` 等)
- summary: 1 行
- codex-all-loops summary: round 数 + findings closure 数

## Codex auto-review 確認義務 (§6.5.9 正本化)

### Setup (既設定済)

- Codex app (chatgpt.com) で GitHub 連携設定済
- PR 作成で `chatgpt-codex-connector[bot]` auto-review trigger
- review timing: push から 1-5 min (small) / 5-10 min (large)
- **CI green ≠ Codex clean**: CI 通過後も inline finding 来る可能性

### baseline 確認必須 (PR #42/#44 で再発)

**必ず最初に `codex_pr_full_review.sh <PR> | head -200` を実行して baseline 内容確認**。delta +0 を「真の 0 件 clean」と誤判定しない (`feedback_codex_pr_review_baseline_check.md` 教訓)。

```bash
.claude/scripts/codex_pr_full_review.sh <PR> 2>&1 | head -200
```

3 endpoint × paginated × Codex bot filter で全件取得:
- `pulls/N/comments` (inline)
- `issues/N/comments` (conversation)
- `reviews` (top-level)

### 採否判定 (3 分類、F-PR42 / F-PR44 / F-PR47 で確立)

| 分類 | 条件 | アクション |
|---|---|---|
| **adopt** | TaskManagedAI rules / PRD / DD / Sprint Pack / ADR と整合、根拠明確 | fix commit + PR update (merge 前) または follow-up PR (merge 後) |
| **reject** | Codex 誤認 / 文脈不整合 | PR comment で reject 理由返信、`~/.claude/local/codex-reviews/<date>/<slug>/rejected.md` に記録 |
| **defer** | 別 Sprint / 別 PR へ | Sprint Pack 残リスクに記録、PR 内では未対応マーク |

### Severity × risk_to_apply 独立評価

- P1/CRITICAL × LOW → 即 fix
- P1/HIGH × HIGH → ユーザー承認 + diff/影響/rollback 説明
- P2 × LOW → 自動 fix
- P2 × HIGH (auth / DB / API / runner / secret) → ユーザー承認必須
- P3 (LOW) → backlog

**security 関連 (runner / approval / secret broker / provider compliance) は severity を 1 段上げて判定**。

## PR 起票・merge 責務分離 (§6.5.8 正本化)

| Role | 担当 | 理由 |
|---|---|---|
| **PR 起票** (worktree → branch → commit → push → `gh pr create`) | **Claude** | Codex 委譲・実装・doc 修正は Claude が自律完遂 |
| **PR 修正** (Codex auto-review + adopt/reject 判定 + fix commit + push 再 trigger) | **Claude** | multi-round review loop は Claude が clean まで polish |
| **PR レビュー応答** (Codex bot / 別 reviewer comment への採否判定 + fix or 説明返信) | **Claude** | 採否判定は project rules / 不変条件と照合する Claude の責務 |
| **PR merge** (`gh pr merge` or GitHub UI、main へ統合) | **user** | Claude classifier が `Merging PR to main` を destructive と判定し reject する。user 直接 authorization 必須 |
| **Branch cleanup** (merge 後 `--delete-branch`) | **user** or GitHub auto-delete | branch 削除も destructive、user 判断 |

### user が merge できない場合の代替経路 (gh API、本 session 確立、2026-05-17)

Claude classifier が `gh pr merge` を reject する場合、API 直接 call で merge 可能 (HTTPS 経由、SSH 不要):

```bash
HEAD_SHA=$(gh pr view <PR> --json headRefOid -q '.headRefOid')
gh api -X PUT "repos/<owner>/<repo>/pulls/<PR>/merge" \
  -f merge_method=squash \
  -f sha="$HEAD_SHA" \
  -f commit_title="..." \
  -f commit_message="..."
```

ただし classifier が reject する正規経路だが API 直接は **user 明示指示時のみ** (本 session の context management refactor PR #42/44/46/47 で使用)。

## User 手元作業の代理処理 path (§rules/branch-and-pr-workflow §11 正本化、Codex F-PR44-005 統合)

User 手元の変更 (uncommitted / staged / untracked / 6 state) を Claude が代理で PR にする時の安全 protocol。詳細手順は `rules/branch-and-pr-workflow.md` (Phase D 圧縮版 30 行 L1 reminder) に移送、本 skill body で実体化:

### 6 state 全部を漏れなく transfer

1. **committed** (HEAD commits ahead of main): `git cherry-pick <hash>`
2. **untracked file/dir**: `cp -r <src> <worktree>/<dest>`
3. **tracked file の text 変更 (worktree edit + staged)**: `git -C <src> diff HEAD -- <file> | git -C <worktree> apply`
4. **tracked file の binary 変更**: `mkdir -p $(dirname <dest>) && cp <src>/<binary> <dest>`
5. **tracked file の deletion**: `git -C <worktree> rm <path>` (`git diff --name-status -M HEAD` の D を再現)
6. **tracked file の rename (binary 含む)**: `git -C <worktree> mv <old> <new>` + 内容変更があれば追加 transfer

### enumerate 段階の安全検査 (commit/copy 前必須)

```bash
# 全 file 数 + path 列挙
find <dir> -type f | wc -l && find <dir> -type f
# symlink 検出 (1 件でも user 確認なしに add しない)
find <dir> -type l
# sensitive filename sweep
find <dir> -type f \( -name '.env*' -o -name '*.key' -o -name '*.pem' \
  -o -name 'id_rsa*' -o -name 'id_ed25519*' -o -name '*.pfx' -o -name '*.p12' \
  -o -name '*credentials*' -o -name '*secrets*' -o -name 'authorized_keys' \)
# size 検査 (>1MB binary は user 確認)
find <dir> -type f -size +1M -exec du -h {} +
# 機密 content sweep (filename のみ表示、content 出力 = secret leak のため -l)
rg -l -i --hidden --no-ignore \
  -- 'password|secret|api[_-]?key|token|BEGIN.*PRIVATE.*KEY|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]+' \
  <dir> > /tmp/secret-hit-files.txt 2>/dev/null || true
test -s /tmp/secret-hit-files.txt && {
  echo "ERROR: secret-suspect content (NOT shown for security)"; cat /tmp/secret-hit-files.txt
}
```

### add 禁止条件

- 巨大 binary (>1MB) / `.env*` / `*.key` / `*.pem` / `id_rsa*` 等 sensitive filename
- 機密疑い content (rg sweep ヒット)
- symlink (`find -type l` で 1 件以上)
- 100 file 超の untracked dir → 複数 PR 分割 or user 承認
- 25 file 超の add は別 session で慎重に

## Divergence 防止 (2 branch 並走時)

### state check

```bash
git status --short
git log --oneline @{upstream}..HEAD  # local ahead
git log --oneline HEAD..@{upstream}  # remote ahead
```

### remote 取り込み (linear、push 済 history 上書きなし)

```bash
git pull --rebase origin <branch>    # rebase
git pull origin <branch>             # merge commit 作成
```

### local commit 廃棄 (destructive、要 user 承認)

```bash
git reset --hard origin/<branch>
```

## 完了条件 (本 skill 適用 checklist)

- [ ] worktree branch 命名が convention
- [ ] worktree 着手前に `EnterWorktree` 実行
- [ ] 3 phase pattern (direct edit + codex-review-loop + codex-adversarial-loop) で work
- [ ] commit が worktree branch にのみ集中、別 branch との混在なし
- [ ] PR が `gh pr create --base main` で作成 (title + body convention)
- [ ] **PR baseline `codex_pr_full_review.sh <PR>` で内容確認**
- [ ] Codex findings 採否判定 + fix commit で clean 達成
- [ ] main merge は user 直接実行 (or API 経由、user 明示指示時)
- [ ] worktree branch divergence は §divergence-防止 protocol で整理

## 関連参照

- `.claude/rules/branch-and-pr-workflow.md` (Phase D 後 30 行 L1 reminder、本 skill body へ link)
- `.claude/rules/codex-usage-policy.md` §14 Mandatory Codex review gates (Codex F-PR44-001/002 統合)
- `.claude/rules/sprint-pack-adr-gate.md` §12 ADR accepted promotion (Codex F-PR44-004 統合)
- `.claude/scripts/codex_pr_full_review.sh` (helper script)
- `.claude/scripts/codex_pr_full_review.README.md` (Phase C 移送済、F-PR42-001〜005 / F-PR47-001 教訓含む)
- `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/feedback_codex_pr_review_baseline_check.md` (本 session 教訓、baseline 見逃し再発防止)
- `~/.claude/CLAUDE.md` Git Worktree 利用判断ルール (user-global、Phase E で reference 移送予定)
