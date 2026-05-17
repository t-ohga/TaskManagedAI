# Codex Output Contract

Codex 出力 truncation を防止するための grand contract。  
全 Codex 連携 skill (`codex-task`, `codex-second-opinion`, `codex-plan-review`, `codex-adversarial-review`, `codex-rescue`) で適用する。

## 1. 背景

Codex の `--output-last-message` (`result.md`) は **最終 assistant message のみ** 書き込む。Codex が探索 phase で大量の grep / file read を行うと最終 message が肥大化して **truncation** する事例が複数回観測された:

- 2026-05-10 `ci-pytest-vitest-fix` task: 181K tokens 使用、`result.md` 225 bytes、stderr 末尾で「以下がそのまま `result.md` に入れる内容です。最後の `」で切れた
- これは Codex の「explore 段階で大量読み込み → 最終 message に全部集約しようとして size 制限に hit」という pattern

truncation すると Codex の判断・patch が一切取得できないため、**完全失敗** として扱う必要がある。

## 2. Output サイズ規約

| 制約 | 値 | 根拠 |
|---|---|---|
| 最終 message 上限 | **200 KB** | Codex の output buffer hard limit に余裕を持つ |
| `result.md` summary 上限 | **50 KB** | 真の patch / content は別 file path 参照に分離 |
| 1 patch の上限 | **30 KB** | 1 file の修正は通常 30 KB 以内、超える場合は分割 |
| Codex prompt 上限 | **30 KB** | 探索 budget を残すため prompt 自体は簡潔に |

## 3. Explore 量制限

Codex prompt 内で必ず明示:

- **必読 file**: 絶対パス + 必要範囲 (line range) を prompt 側で先に指定 (`/path/to/file.py:50-120` 形式)
- **追加 grep**: 最大 20 結果まで要約、全文 paste 禁止 (Codex 自身が grep で取得した結果を全文転載するのを防ぐ)
- **file Read**: 最大 **20 file**、関連 file は prompt で事前リスト化
- **deep-review profile**: xhigh reasoning は探索量を増やしがち。1 task = 1 焦点に絞り、汎用調査は別 task に分割

## 4. 分割 output mode

Codex 自身が出力サイズを見積もり、**100 KB を超えそうな場合**は:

```text
=== OUTPUT_MODE: SPLIT ===
result.md には summary のみ。各 section を以下のように分割:
=== SECTION: A_root_cause ===
...content (30 KB 以内)...
=== END_SECTION ===
=== SECTION: B_patch_pyproject ===
...
```

Claude 側はこれらの `=== SECTION: <name> ===` block を抽出して個別に処理する。

1 message が 200 KB を超えそうなら、Codex は出力を切り上げて `=== OUTPUT_MODE: PARTIAL ===` を最終行に書き、Claude に **再 run 依頼** を提案する。

## 5. Claude 側 fallback (truncation 検知)

result.md が以下のいずれかなら **truncation = logical failure** として扱う:

- size < 1 KB (実質空の応答)
- 末尾が「以下がそのまま」「最後の」「以下を `result.md`」等で切れている (Codex が「ここから content」と書いたが続きがない)
- `=== OUTPUT_MODE: PARTIAL ===` を含む
- JSON expected (e.g., findings) で valid JSON でない

検知時の処理:

1. `~/.claude/local/codex-failure-count.${CLAUDE_SESSION_ID}` をインクリメント (logical failure)
2. stdout.log (JSONL stream) から各 message を抽出して partial 復元を試みる
3. 復元できない場合、AskUserQuestion で:
   - **再 run** (出力分割を強制する prompt で)
   - **Claude 単独で続行**
   - **一時中止**
4. 3 連続失敗で hook が `exit 2` ブロック (既存挙動)

## 6. Prompt template への必須追加文言

全 Codex prompt の `## 制約` section または `## 禁止事項` 直前に以下を必ず含める:

```markdown
## Output サイズ規約 (codex-output-contract.md §2-§4 準拠)

- 最終 message は **200 KB 以内**
- explore 量を制限 (最大 20 file Read / grep 結果 20 件以内、必読 file は prompt 内で予め指定済)
- 100 KB を超えそうな場合は分割 output mode (`=== SECTION: <name> ===` block) に切替
- 不要な docs 探索を避ける (深い grep は prompt で path/line range を先に絞る)
- 200 KB を超える場合は `=== OUTPUT_MODE: PARTIAL ===` を最終行に書き、Claude に再 run 依頼
```

## 7. Skill 側の反映 (user-scope)

各 user-scope skill は本 rules を **引用** する形で SKILL.md を update:

| Skill | 反映場所 |
|---|---|
| `~/.claude/skills/codex-task/SKILL.md` | Step 2 prompt 作成 必須要素 + Step 5 truncation 検知 |
| `~/.claude/skills/codex-second-opinion/SKILL.md` | Step 1 prompt template + Step 2 失敗検知 |
| `~/.claude/skills/codex-plan-review/SKILL.md` | 同上 |
| `~/.claude/skills/codex-adversarial-review/SKILL.md` | 同上 |
| `~/.claude/skills/codex-rescue/SKILL.md` | 同上 |

skill 側 update は user-scope (`~/.claude/skills/`) のため dotfiles 管理 (`/Users/tohga/dotfiles/editor/claude-code/claude/skills/`) で commit する。本 rules は project-scope の正本として参照される。

## 8. 適用 example

### 良い prompt (truncation 防止)

```markdown
## 入力ファイル (絶対パス + 範囲)
- /path/to/foo.py:1-150 (該当 function)
- /path/to/bar.py:80-120 (関連 helper)

## タスク
- foo.py の `_xxx()` の bug を fix。bar.py の helper との整合確認。
- 出力: 1 patch (30KB 以内) + root cause 分析 (10KB 以内) = 合計 40KB

## Output サイズ規約 (codex-output-contract.md §2-§4 準拠)
[本 rules §6 文言]
```

### 悪い prompt (truncation 招く)

```markdown
## タスク
全 backend code を読んで、bug を全部修正してください。
patch は完全な file content で出力。
```

→ Codex が大量 explore + 大量 patch で 200KB 超え、truncation。

## 9. 完了条件

- [ ] Codex skill 起動時に本 rules を必ず参照する。
- [ ] result.md size + truncation 検知を Step 5 で必ず実行。
- [ ] 検知時は failure counter INC + AskUserQuestion。
- [ ] prompt 作成時に Output サイズ規約 (§6 文言) を必須含める。
- [ ] 200 KB 超過 / 探索 budget 超過は **分割 mode** または **task 分割** で対応。
