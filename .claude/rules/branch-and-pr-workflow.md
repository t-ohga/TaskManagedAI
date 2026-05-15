# Branch + PR Workflow

worktree + Codex auto-review を含む branch / PR workflow の常時 rule。
本 rule は 2026-05-15 QL-A セッションで発生した「worktree branch 名 ↔ 内容乖離」「2 branch 並走 divergence」「PR 経路未確立」を防ぐために制定。

## 1. 原則

- **1 ticket = 1 PR = 1 worktree branch** (Sprint / Quality Loop / hotfix の単位)
- branch / commit / PR は **append-only** (rebase は最小限、push 済 history の上書き禁止)
- main / master への **直接 commit / push 禁止** (PR 経由のみ)
- **Claude (worktree work)** と **user (main merge 判断)** の責務分離
- branch 名は **内容と一致** (drift したら rename ではなく新 branch 起こす)
- **Codex auto-review** は PR trigger で起動、findings は私 (Claude) が pull → adopt/reject/defer 判定 → fix commit で PR update

## 2. Branch 命名 convention

| prefix | 用途 | 例 |
|---|---|---|
| `quality-loop/QL-X-<topic>` | R29 統合計画 §5 QL-A〜QL-G の Quality Loop run | `quality-loop/QL-A-registry-namespace` |
| `sprint/SP-NNN-batch-N` | Sprint 実装 batch (P0 Exit Master Plan の Sprint 10/11/11.5/12 等) | `sprint/SP-010-batch-0` |
| `adr/ADR-NNNNN-<topic>` | ADR 単独起票 (Sprint Pack を伴わない場合) | `adr/ADR-00028-host-portable-amendment` |
| `docs/<topic>` | doc-only 単発 update (rule / reference / README) | `docs/sprint-pack-readme-fix` |
| `hotfix/<issue>` | 緊急修正 (ADR Gate Criteria 11 種 break-glass 対象外限定) | `hotfix/lint-warning-fix` |
| `codex/...` | Codex 用 reserved (Claude 新規作成禁止) | (Codex 側で管理) |
| `worktree-<NAME>` | **DEPRECATED**: 2026-05-15 までの旧 convention、新規作成禁止 (内容ドリフトの原因) | - |

**禁止 (drift 原因)**:
- `worktree-<old-name>` を意味と乖離する用途で再利用 (本セッション 2026-05-15 で発生)
- `feature/<short>` (Sprint Pack 対応が曖昧化)
- 1 branch で複数 ticket を混合 commit
- 命名後の rename (PR link 切れ、Codex review track 切れ): 内容が変わるなら **新 worktree branch を起こす**

## 3. Worktree workflow (4 phase)

### Phase 0: 着手前

1. **EnterWorktree** で新 worktree 作成 (branch 命名は §2 convention)
   - 親: `/Users/tohga/repo/TaskManagedAI` (main repo) または既存 worktree
   - base branch: `main` (または P0.1 開始後は `release/p0.1` 等)
2. code を触る場合: `bash scripts/worktree_setup.sh` で setup 自動化 (pnpm install + uv sync + SOPS 復号、~10 分)
3. doc-only 作業の場合: setup skip 可

### Phase 1: 進行中

1. Claude が worktree 内で work
2. **3 phase pattern 推奨** (R29 QL-A で確立、37 findings closure):
   - Phase 0: Claude direct edit (実 file 編集 + new file 起票)
   - Phase 1: `codex-review-loop` (構造磨き、R1=ALL / R2=HIGH+ / R3=CRITICAL、clean まで)
   - Phase 2: `codex-adversarial-loop` (敵対視点、R1=ALL / R2=HIGH+ / R3=CRITICAL、clean まで)
3. 適宜 commit、`git push -u origin <branch>` (worktree branch を origin に push)
4. **divergence 防止**: 別 branch との作業混在禁止 (cross-branch edit は別 worktree で)

### Phase 2: PR 作成 + Codex review

§4-§6 参照。

### Phase 3: 完了後

1. clean 判定後、user に **main へ merge 判断**を委ねる (§7)
2. `ExitWorktree action=remove` で worktree clean exit (**commit が remote に push 済確認後**)
3. 旧 worktree branch は origin に残す (PR 履歴維持、merge 後は GitHub 側で auto-delete 設定可)

## 4. PR 作成 protocol

### 4.1 PR 作成コマンド

```bash
gh pr create --base main --head <worktree-branch> \
  --title "<prefix>(<scope>): <summary> (codex-all-loops R{N} clean、{M} findings)" \
  --body "$(cat <<'EOF'
## Summary
<1-3 bullet 要約 + R29/master plan reference>

## codex-all-loops verdict
<Phase 1/2 round summary + findings closure 数>

## 変更 file list (operation + 行数)
<table>

## 不変条件 #1〜#18 trace
<applicable subset、特に #14 doc-only gate 遵守確認>

## Test plan
- [ ] Codex auto-review 完了
- [ ] Codex findings 採否判定 (adopt/reject/defer)
- [ ] fix commit で PR update
- [ ] clean 判定後 main merge

## 関連資料
- INTEGRATED-REPORT: ~/.claude/local/codex-reviews/<date>/<slug>/INTEGRATED-REPORT.md
- Codex artifacts: 同 dir

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### 4.2 PR title convention

`<prefix>(<scope>): <summary> (codex-all-loops R{N} clean、{M} findings)`

- prefix: `docs` / `feat` / `fix` / `refactor` / `test` / `chore` (Conventional Commits)
- scope: `QL-A` / `SP-010-batch-0` / `ADR-00027` 等
- summary: 1 行で内容
- codex-all-loops summary: round 数 + findings closure 数 (Phase 1 + Phase 2)

例: `docs(QL-A): registry + SP-0045 + ADR-00027 + BL-0140 三分割 (codex-all-loops R6 clean、37 findings)`

### 4.3 base branch

- **P0 期間中**: `main` (sealed CI guard 含む)
- **P0.1 開始後**: `release/p0.1` (multi-agent feature branch、sealed guard 解除後)

## 5. Codex auto-review 連携

### 5.1 setup (user 側、既設定済)

- Codex app (chat.openai.com) で GitHub 連携設定済 (2026-05-15 user 確認)
- PR 作成で auto-review trigger、PR comment に finding 投稿

### 5.2 Codex review 取得

```bash
gh pr view <PR-NUMBER> --comments | head -200
# または
gh api repos/<owner>/<repo>/pulls/<PR-NUMBER>/comments | jq '.[] | {user: .user.login, body: .body, path: .path, line: .line}'
```

### 5.3 review 結果の構造

Codex review は通常 1 round (long-loop ではない)。findings は:
- severity (CRITICAL / HIGH / MEDIUM / LOW)
- category
- file path + line number
- 修正提案

私の判定では `.claude/rules/codex-usage-policy.md` §8-§9 (採否判定 3 分類 + Checklist) を適用。

## 6. 採否判定 + fix commit loop

### 6.1 採否判定 (3 分類)

| 判定 | 条件 | アクション |
|---|---|---|
| **adopt** | TaskManagedAI rules / PRD / DD / Sprint Pack / ADR と整合、根拠明確 | fix commit、PR update |
| **reject** | Codex 誤認、context 不整合、堂々巡り | PR comment で reject 理由を返信、`~/.claude/local/codex-reviews/<date>/<slug>/rejected.md` に記録 |
| **defer** | 追加情報必要、別 Sprint へ | Sprint Pack 残リスクに記録、PR 内では未対応マーク |

### 6.2 fix commit

```bash
# worktree 内で fix
git add <files>
git commit -m "fix(<scope>): adopt Codex F-CRA-NNN (<summary>)"
git push origin <branch>
# PR は自動 update
```

### 6.3 clean 判定

- Codex auto-review が再 trigger される設定なら、push で自動再 review
- 自動再 review なしの場合は私が Codex review コマンド (`codex-adversarial-review` skill 等) を別途起動
- CRITICAL = 0 AND HIGH ≤ 2 で **READY** 判定 (`.claude/rules/codex-usage-policy.md` §9 同等)

## 7. Main へ merge 判断 (user 直接)

- **Claude classifier は main merge を reject する可能性が高い** (long autonomous chain 後)
- main merge は **user 直接実行**:
  ```bash
  gh pr merge <PR-NUMBER> --squash --delete-branch
  # または ff merge
  gh pr merge <PR-NUMBER> --rebase
  ```
- merge 前に user が PR diff + Codex review + Claude 採否判定 record を確認
- ADR Gate Criteria 11 種該当 PR は **ADR accepted 必須** (sprint-pack-adr-gate.md §10 break-glass 対象外)

## 8. Divergence 防止 (2 branch 並走時)

### 8.1 並走容認 case

- worktree branch (work) と main repo current branch (review) を同時に持つ
- 別 worktree で別 ticket を並行進行 (scope を物理分離)

### 8.2 divergence 発生 → 整理 protocol

```bash
# state check
git status --short
git log --oneline @{upstream}..HEAD  # local ahead
git log --oneline HEAD..@{upstream}  # remote ahead

# remote 取り込み (linear、push 済 history 上書きなし)
git pull --rebase origin <branch>

# remote 取り込み (merge commit 作成、複数人開発の場合)
git pull origin <branch>  # default = merge

# local commit 廃棄 (destructive、要 user 承認)
git reset --hard origin/<branch>
```

### 8.3 untracked / modified ファイルの扱い

- **`?5` (untracked 5 file)**: intentional な手元作業の可能性、`git status --short` で内容確認後 user に判断委ねる
- **`!1` (modified 1 file)**: 編集中の作業、commit 前に内容確認
- どちらも **Claude が勝手に `git add` / `git stash` / `git clean` しない** (user 承認必須)

## 9. 完了条件 (本 rule 適用 checklist)

- [ ] worktree branch 命名が §2 convention
- [ ] worktree 着手前に `EnterWorktree` 実行
- [ ] 3 phase pattern (direct edit + codex-review-loop + codex-adversarial-loop) で work
- [ ] commit が worktree branch にのみ集中、別 branch との混在なし
- [ ] PR が `gh pr create --base main` で作成 (title + body convention)
- [ ] Codex auto-review trigger 確認
- [ ] findings 採否判定 + fix commit で clean 達成
- [ ] main merge は user 直接実行
- [ ] worktree branch divergence は §8 protocol で整理

## 10. 過去事例 (drift 学習)

### 2026-05-15 QL-A セッションで発生した混乱

**問題**:
- worktree branch `worktree-sprint6-batch1-cli-artifact` (元 Sprint 6 batch 1 work 用) を QL-A の場として再利用 → 命名と内容が乖離
- main repo の `codex/phase-d-g-multi-agent-vision-host-protable` branch と 2 branch 並走 → user 困惑 (⇣3 ⇡1 意味不明状態)
- main merge 直接 push を試行 → classifier denied

**改善 (本 rule 制定)**:
- branch 命名 §2 convention で再利用禁止 + 内容と一致
- 2 branch 並走時の整理 §8 protocol 明文化
- main merge は user 直接実行 §7
- PR + Codex auto-review workflow §4-§6 確立

### 学習: 次回 Quality Loop (QL-C 以降) からの適用

- 新 worktree branch 命名: `quality-loop/QL-C-research-eval-pack` 等
- 旧 `worktree-sprint6-batch1-cli-artifact` は QL-A の PR merge 後 GitHub 側で auto-delete
- PR-based workflow で divergence を physical 防止
