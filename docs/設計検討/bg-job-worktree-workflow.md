# bg job × worktree 並列運用 workflow (TaskManagedAI)

最終更新: 2026-05-12 (Phase B、Anthropic FleetView 公式仕様 + TaskManagedAI 固有運用、CLAUDE.md / AGENTS.md から参照される正本)

## 1. 目的

TaskManagedAI で **Anthropic FleetView bg job** + **複数 session 並列実装** + **問題なく merge** を実現するための公式 workflow。FleetView の自動 worktree 化機能には触れず、外側で運用しやすくする方針。

## 2. FleetView 公式仕様 (壊さない、受け入れる)

- bg job 起動時: **main checkout で start** (worktree は自動作成されない)
- Write / Edit / NotebookEdit 呼び出し時: **harness が isolation 要求** → AI が `EnterWorktree` を自律判断で呼ぶ
- `EnterWorktree` / `ExitWorktree` は **AI が自律判断で呼べる公式 tool** (`https://code.claude.com/docs/en/tools-reference.md`)
- 並列 bg job は **公式推奨パターン** (`https://code.claude.com/docs/en/worktrees.md`)
- **isolation 要求 off の公式設定は未確認** → built-in 安全装置として受け入れる

## 3. TaskManagedAI 既存装備

| 装備 | 目的 |
|---|---|
| `.worktreeinclude` | gitignored 個人設定 (settings.local.json / SOPS / age key pointer) を worktree に自動 copy。**DD-06 SecretBroker 原則準拠で `.env.local` は意図的に copy 禁止** |
| `.claude/hooks/system/sessionstart-detect-worktree.sh` | session start 時に worktree 判定 |
| **`scripts/worktree_setup.sh`** (新規、Phase B) | worktree 作成後 1 回実行で setup 自動化: pnpm install + uv sync + SOPS 復号 |

## 4. AI 自律判断 workflow (single bg job)

```text
[bg job start]
  ↓ main checkout、CLAUDE_JOB_DIR=$HOME/.claude/jobs/<job-id>
  ↓
  ↓ AI が作業内容を判断:
  ├─ Read / Bash (read-only) / Grep / WebFetch だけで完結?
  │   → main checkout のまま、Write 不要、worktree 不要
  │
  └─ Write / Edit / NotebookEdit が必要?
      ↓ EnterWorktree name=<descriptive> (AI 自律判断)
      ↓ worktree 作成、自動で worktree dir に switch
      ↓
      ↓ code (backend/frontend) を触る?
      ├─ Yes → bash scripts/worktree_setup.sh (5-10 分)
      │        - pnpm install (frontend)
      │        - uv sync (backend)
      │        - SOPS 復号 (optional)
      │
      └─ No  → doc-only、setup skip
      ↓
      ↓ 作業 (Write / Edit / Bash test / commit)
      ↓ git push origin worktree-<branch>
      ↓ git checkout main && git merge --ff-only worktree-<branch> && git push
      ↓ (codex/... 等 別 branch 同期が必要なら): その branch を別 worktree から fetch + merge
      ↓ ExitWorktree action=remove discard_changes=true (commit + merge 済なら work loss なし)
      ↓
[main に戻る、bg job 完遂]
```

## 5. 並列 bg job 運用 (推奨)

### 5.1 scope 分割で conflict 防止

| bg job | scope | 触る範囲 | conflict 確率 |
|---|---|---|---:|
| job A | backend Sprint 実装 | `backend/` + `tests/` + `migrations/` | 低 |
| job B | frontend Sprint 実装 | `frontend/` | 低 |
| job C | doc / Sprint Pack / ADR | `docs/` | 極低 |
| job D | 調査 / 分析 (read-only) | (Read のみ、worktree 不要) | ゼロ |

scope 分割で **3-4 並列でも conflict ほぼゼロ**。

### 5.2 共通 file (`README.md` / `CLAUDE.md` / `AGENTS.md`) を触る場合

→ 同時に 1 つの job に制限、または順次直列化。

### 5.3 Codex 並列起動禁止

`rules/codex-usage-policy.md` で明文化: codex-task / codex-second-opinion / codex-plan-review / codex-adversarial-review / codex-rescue の **同時実行禁止**。異なる bg job で並列に Codex を呼ばない。

## 6. branch / merge 戦略

### 6.1 branch 命名

- worktree branch: `worktree-<scope>-<feature>` (例: `worktree-phase-b-worktree-workflow`)
- 既存 branch (`main`, `codex/...`) には直接 commit しない、必ず worktree branch 経由

### 6.2 merge 順序

1. worktree branch → main (fast-forward)
2. main → 関連 branch (`codex/...`) (fast-forward が可能ならそれ、無理なら 3-way merge)
3. worktree branch 削除 (`ExitWorktree action=remove discard_changes=true`)

### 6.3 同じ branch を 2 worktree で checkout する場合の回避

**症状**: `fatal: 'codex/...' is already used by worktree at '/Users/tohga/repo/TaskManagedAI'`

**回避** (2026-05-12 Phase A で実演済):

```bash
# worktree から push
git push origin worktree-<branch>

# main checkout (これは別の worktree、例えば main worktree が `codex/...` を checkout 中)
git fetch origin
git merge --ff-only origin/main   # main から取り込む場合
git push origin codex/...
```

## 7. ExitWorktree の判断基準

| 条件 | action | discard_changes |
|---|---|---|
| commit + push + main merge 全部済 | `remove` | `true` (work loss なし) |
| commit 済 + push 済、merge 未 (後で再開) | `keep` | n/a |
| uncommit あり | まず commit、または stash、その後再判定 | - |
| 作業中で session 切替 | `keep` (次 session で再開) | n/a |

## 8. 失敗時のリカバリ

| 症状 | 原因 | 解決 |
|---|---|---|
| `fatal: 'branch' is already used by worktree` | 同 branch を 2 worktree で checkout | §6.3 fetch + merge --ff-only |
| pnpm install が遅い | content-addressable store 未活用 | `pnpm config set store-dir ~/.local/share/pnpm/store` で main / worktree 共有 |
| uv sync が毎 worktree で遅い | venv project-local | P0.1+ で `UV_PROJECT_ENVIRONMENT=$HOME/.venvs/taskmanagedai` 検討 |
| SOPS 復号失敗 | age key 不在 / path 違い | `~/.sops-age-key` 確認、または `config/local/age-key-path` の pointer file 確認 |
| ExitWorktree が「N commits will discard」 | commit が main に未 merge | まず main へ merge + push、その後 `discard_changes=true` |
| 並列 job で merge conflict | scope 分割不足 | conflicting job を 1 つに止め、もう片方を待たせる |
| worktree 削除し忘れで `.claude/worktrees/` 膨らむ | ExitWorktree 呼び忘れ | `git worktree list` で確認、`git worktree prune` で cleanup |

## 9. CI / 品質 gate との接続

- worktree branch は **完成してから 1 回 push** (途中 push を避けて CI runner 枠を節約)
- main merge 後の CI green は必須 (Sprint Exit 条件)
- `gh run watch` で確認、`fix(ci)` commit を worktree で作って main へ merge する flow

## 10. /goal コマンドとの連携

`/goal <condition>` で AI が自律的に worktree workflow を実施可能:

```
/goal Phase X (specific work) を完遂し、main / codex branch 両方に push 済まで
```

→ AI は: bg job 内で `EnterWorktree` → 作業 → commit → push → main + codex merge → `ExitWorktree action=remove` を自主判断で実施。

## 11. memory / doc 連携

- **memory 正本**: `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/reference_fleetview_worktree_workflow.md`
- **project-scope 公式 doc** (この file): `docs/設計検討/bg-job-worktree-workflow.md`
- **CLAUDE.md / AGENTS.md**: 本 doc への reference 追加 (Phase B で実施)

## 12. 改訂履歴

- 2026-05-12 初版 (Phase B、FleetView 公式仕様 + TaskManagedAI 固有運用、Phase A worktree workflow 実演を基に)

## 13. references

- Anthropic Claude Code Worktrees: `https://code.claude.com/docs/en/worktrees.md`
- Anthropic Claude Code Tools Reference: `https://code.claude.com/docs/en/tools-reference.md`
- TaskManagedAI `.worktreeinclude` (DD-06 SecretBroker 原則準拠)
- TaskManagedAI `scripts/worktree_setup.sh`
- `.claude/rules/codex-usage-policy.md` (Codex 並列禁止)
