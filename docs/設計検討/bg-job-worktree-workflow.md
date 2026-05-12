# bg job × worktree 並列運用 workflow (TaskManagedAI 固有事情)

最終更新: 2026-05-12 (Phase B-2、user-global Git Worktree 利用判断ルールを正本化、project 側は TaskManagedAI 固有事情のみ保持)

## 1. 正本の階層

| 層 | 場所 | 役割 |
|---|---|---|
| **判断フロー / 使う・使わない判断軸** | `~/.claude/CLAUDE.md` §「Git Worktree 利用判断ルール（全プロジェクトで厳守、bg job 含む）」 | **正本**。判断 4 step、main 作業時の注意、bg job での挙動 |
| **TaskManagedAI 固有事情** (本 doc) | `docs/設計検討/bg-job-worktree-workflow.md` | setup script / `.worktreeinclude` / scope 分割 / 回避策 |
| **AI 用 memory** | `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/reference_fleetview_worktree_workflow.md` | next session で AI が context 復元 |

判断フローは user-global を必ず参照し、TaskManagedAI 固有部分のみ本 doc に従う。

## 2. TaskManagedAI 固有装備

### 2.1 `scripts/worktree_setup.sh`

worktree を「使う」と判断 + code (backend / frontend) を触る場合に 1 回実行:

- `pnpm install --frozen-lockfile` (frontend dependencies、約 5-10 分)
- `uv sync --locked` (backend Python dependencies、約 1-2 分)
- SOPS 復号 (`config/local/env.local.enc` 等 → `.env.local`、任意)
- `.worktreeinclude` で copy された個人設定の verify

doc-only 作業なら skip 可。

### 2.2 `.worktreeinclude`

gitignored 個人設定の自動 copy 定義:

- `.claude/settings.local.json` / `.codex/config.local.toml` (Claude / Codex 個人許可)
- `.sops.yaml` / age key path pointer (SOPS 復号設定)
- `config/local/secret-refs.env` / `config/local/age-key-path` (TaskManagedAI 固有 secret 参照)

**DD-06 SecretBroker 原則準拠で `.env.local` は意図的に copy 禁止**。各 worktree で SOPS 経由 (setup script 内) で生成する。

## 3. 並列 bg job の scope 分割 (TaskManagedAI 推奨)

| bg job | scope | 触る範囲 | conflict 確率 |
|---|---|---|---:|
| job A | backend Sprint 実装 | `backend/` + `tests/` + `migrations/` | 低 |
| job B | frontend Sprint 実装 | `frontend/` | 低 |
| job C | doc / Sprint Pack / ADR | `docs/` | 極低 |
| job D | 調査 / 分析 (read-only) | (Read のみ、worktree 不要) | ゼロ |

scope 分割で **3-4 並列でも conflict ほぼゼロ**。

### 共通 file (1 job に制限)

`CLAUDE.md` / `AGENTS.md` / `README.md` / `.worktreeinclude` を触る job は同時に 1 つに制限、または直列化。

### Codex 並列起動禁止

`.claude/rules/codex-usage-policy.md` で明文化済み。異なる bg job で並列に Codex を呼ばない。

## 4. branch / merge 戦略 (TaskManagedAI 固有)

### branch 命名

- worktree branch: `worktree-<scope>-<feature>` (例: `worktree-phase-a-external-concept-integration`)
- 既存 branch (`main`, `codex/...`) に直接 commit しない、必ず worktree branch 経由

### merge 順序

1. worktree branch → main (fast-forward)
2. main → 関連 branch (`codex/...` 等) (fast-forward が可能ならそれ、無理なら 3-way)
3. worktree branch 削除 (`ExitWorktree action=remove discard_changes=true`)

### 同じ branch を 2 worktree で checkout する場合の回避 (2026-05-12 Phase A 実演済)

**症状**: `fatal: '<branch>' is already used by worktree at '<path>'`

**回避**:

```bash
# worktree 側で push
git push origin worktree-<branch>

# 別 worktree (main / codex/... checkout 中) で
git fetch origin
git merge --ff-only origin/main   # main から取り込む場合
git push origin codex/...
```

## 5. ExitWorktree の判断 (TaskManagedAI 推奨)

| 条件 | action | discard_changes |
|---|---|---|
| commit + push + main merge 全部済 | `remove` | `true` (work loss なし) |
| commit 済 + push 済、merge 未 (後で再開) | `keep` | n/a |
| uncommit あり | まず commit、または stash、その後再判定 | - |
| 作業中で session 切替 | `keep` (次 session で再開) | n/a |

## 6. 失敗時のリカバリ (TaskManagedAI 固有)

| 症状 | 原因 | 解決 |
|---|---|---|
| `fatal: 'branch' is already used by worktree` | 同 branch を 2 worktree で checkout | §4 fetch + merge --ff-only |
| pnpm install が遅い | content-addressable store 未活用 | `pnpm config set store-dir ~/.local/share/pnpm/store` で main / worktree 共有 |
| uv sync が毎 worktree で遅い | venv project-local | P0.1+ で `UV_PROJECT_ENVIRONMENT=$HOME/.venvs/taskmanagedai` 検討 |
| SOPS 復号失敗 | age key 不在 / path 違い | `~/.sops-age-key` 確認、または `config/local/age-key-path` の pointer file 確認 |
| ExitWorktree が「N commits will discard」 | commit が main に未 merge | まず main へ merge + push、その後 `discard_changes=true` |
| 並列 job で merge conflict | scope 分割不足 | conflicting job を 1 つに止め、もう片方を待たせる |
| worktree 削除し忘れで `.claude/worktrees/` 膨らむ | ExitWorktree 呼び忘れ | `git worktree list` で確認、`git worktree prune` で cleanup |

## 7. CI / 品質 gate との接続

- worktree branch は **完成してから 1 回 push** (途中 push を避けて CI runner 枠を節約)
- main merge 後の CI green は必須 (Sprint Exit 条件)
- `gh run watch` で確認、`fix(ci)` commit を worktree で作って main へ merge する flow

## 8. /goal コマンドとの連携

`/goal <condition>` で AI が user-global 判断ルールに従って自律的に worktree workflow を実施可能。ゴール条件に「main + 関連 branch に merge + push 済まで」を含めれば、AI は判断 4 step に従って自主判断で完遂する。

## 9. 改訂履歴

- 2026-05-12 初版 (Phase B、FleetView 公式仕様 + TaskManagedAI 固有運用)
- 2026-05-12 Phase B-2: user-global 判断ルールが追加されたため、project 側は固有事情のみに縮小 (159 行 → ~95 行)

## 10. references

- **判断ルール正本**: `~/.claude/CLAUDE.md` §「Git Worktree 利用判断ルール」
- Anthropic Claude Code Worktrees: `https://code.claude.com/docs/en/worktrees.md`
- Anthropic Claude Code Tools Reference: `https://code.claude.com/docs/en/tools-reference.md`
- TaskManagedAI `.worktreeinclude` (DD-06 SecretBroker 原則準拠)
- TaskManagedAI `scripts/worktree_setup.sh`
- `.claude/rules/codex-usage-policy.md` (Codex 並列禁止)
- AI 用 memory: `~/.claude/projects/-Users-tohga-repo-TaskManagedAI/memory/reference_fleetview_worktree_workflow.md`
