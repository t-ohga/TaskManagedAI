# User Preferences (TaskManagedAI、2026-05-15 確立)

本 file は **ユーザーがこれまで明示・暗黙に求めてきた preference / workflow / 品質基準を集約** したもの。各 session 開始時に Claude が参照し、要望の繰り返し説明を不要にする。CLAUDE.md §6.5.9 + `.claude/rules/codex-pr-review-checklist.md` と相互参照。

## 1. 品質 vs 速度: **品質優先 (絶対教訓)**

> 「急がなくていい。それぞれ品質重視で codex をしっかり使い完璧にお願いします。時間よりも品質です。」 (2026-05-13 明示)

- 焦って Claude 単独実装で済ますより、**Codex 委譲して時間をかけてでも完璧に**
- batch 1 件ずつでも品質維持を優先 (work-in-progress を merge しない)
- 「とりあえず動く」レベルで止めない、Codex multi-round で round=clean まで polish

## 2. Codex の使い方

- **Sprint 実装 / リファクタ / 計画レビュー / コミット前 / 同じ問題 2 回失敗時**は Codex 委譲必須
- 単純編集 / 1 行 typo は Claude 単独 OK
- ChatGPT Plus rate limit に当たったら時間を空ける (API 従量に逃げない)
- **Codex 指摘は鵜呑みにせず Claude が adopt/reject/defer 判定** (3 分類)
- inline review (`gh api .../pulls/N/comments`) は必ず全件確認 (本 session の事故再発防止、§6.5.9)

## 3. PR 起票・merge 責務分離

> 「基本私はプルリクエストをあなたが出したものをマージする役としていたい」 (2026-05-15 明示)

- **Claude**: PR 起票・Codex review 採否・fix push・branch state 管理
- **User**: PR merge (squash + delete branch)・git push --delete (destructive)・branch 物理 cleanup
- Claude classifier reject 経路 (merge / force push / branch delete) は user 直接実行
- 詳細: CLAUDE.md §6.5.8

## 4. Branch & worktree 戦略

- **EnterWorktree 利用判断は user-global rule (~/.claude/CLAUDE.md)** に従う、本 project 固有事情は §6.5.7
- doc-only PR は main 直編集も OK (worktree 不要、品質ゲート維持)
- code 変更は worktree 推奨 (parallel bg job 競合回避)
- destructive 操作 (force push, branch -D, push --delete) は明示指示なしで実行しない

## 5. Workflow を「ぐちゃぐちゃ」にしない

> 「今後このようにぐちゃぐちゃにならないようにしっかりと整えてください」 (2026-05-15 明示)

- branch 命名は scope を表す (`fix/pr1-codex-p1-security` / `chore/ci-concurrency-push-sha-fix` 等)
- PR 1 つ = scope 1 つ (Pack 完遂単位、Sprint 機能単位、Codex finding 緊急度単位等)
- merged PR の branch は user 側 GitHub auto-delete 設定で自動削除
- local branch / remote branch / stash の state を session 末で必ず確認 (`git branch -a` / `git stash list`)

## 6. Codex 自動 review の活用

> 「プロリクエストをトリガーにするやつは、もうすでに Codex のアプリの方で私が設定してあるんで自動的になると思うんですがどうでしょう」 (2026-05-15 明示)

- ChatGPT Codex 側で auto-review 設定済 (`chatgpt-codex-connector[bot]`)
- 私から explicit に trigger 不要 (PR open / push で自動)
- review timing: push から 1-5 分 (small) / 5-10 分 (large)
- **CI green ≠ Codex clean**: CI 通過後も inline finding が来る可能性、必ず別途確認

## 7. 「全部やる」と言われた時の理解

> 「本セッションで全てしっかりと完結してください」「一番完璧になるものでお願いします」 (2026-05-15 明示)

意味:
- A. 単 task の完了ではなく **scope 全体の完結** (関連 finding / follow-up / 再発防止まで)
- B. 部分実装で「次セッションへ持ち越し」は **避けるべき**
- C. Codex 委譲 (品質) と Claude 直接 (速度) のバランスを **品質側に振る**
- D. **ルール化 / memory 化 / doc 化を伴う恒久対応** (一回切りの fix ではなく workflow 改善)

## 8. 明示語彙の解釈

| user 発言 | 意味 |
|---|---|
| 「しっかり」 | 品質重視、Codex 委譲 OK、時間かけて良い |
| 「完璧に」 | round=clean まで polish、follow-up なし |
| 「根本的に」 | symptom fix ではなく root cause fix、再発防止セット |
| 「全て」 | scope 全件 (related findings / docs / rule / memory 含む) |
| 「ぐちゃぐちゃにならないように」 | branch / PR / stash / memory の state を session 末で clean に |
| 「次のセッションに行きたい」 | 本 session で work-in-progress を残さず、memory entry point 整理して終わる |

## 9. Memory 運用

- **session 末で必ず memory entry を更新** (次 session の entry point 整理)
- ぐちゃぐちゃな state を memory に書かない (clean state を残す)
- `MEMORY.md` index は 200 行以内、各 entry 1 line summary

## 10. 報告 style

- 報告は **table / bullet で簡潔**、長文 narrative は避ける
- branch / PR 番号 / commit hash を必ず記載 (trace 可能性)
- 「user 直接実行が必要なコマンド」は **コードブロックで `pbcopy` しやすく**

## 11. 過去の事故 / 教訓 (再発防止用)

| 事故 | 教訓 | session |
|---|---|---|
| 過去 PR の inline review 9 件見落とし | `gh pr view --json reviews` だけでなく `gh api .../comments` も必須 (§6.5.9) | 2026-05-15 |
| PR #4 concurrency 設計バグ (cancel-in-progress=false でも queue 1 個) | GitHub Actions 公式仕様の事前確認、特に edge case | 2026-05-15 |
| Sprint 9 page 「skeleton text」だけで実装、CI fail | UI 改善は実機能 + 業界 best practice 統合 | 2026-05-15 |
| pre-existing CI 272 件 failure 放置 | main 初作成時の cascade fix を Codex 委譲 (root cause 分類) | 2026-05-10 |

## 参照

- CLAUDE.md §6.5.0 - §6.5.9 全 section
- `~/.claude/CLAUDE.md` (user-global、`codex-second-opinion` / Worktree 判定ルール)
- `.claude/rules/codex-pr-review-checklist.md`
- `.claude/rules/codex-usage-policy.md`
- `.claude/rules/branch-and-pr-workflow.md`
