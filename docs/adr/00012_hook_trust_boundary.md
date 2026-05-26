---
id: "ADR-00012"
title: "Hook Trust Boundary (repo 外 trusted wrapper + sha256 manifest)"
status: "proposed"
date: "2026-05-13"
deciders:
  - "TaskManagedAI core"
adr_gate_criteria:
  - "#5 MCP / tool 権限"
  - "#7 外部公開設定 (本 ADR は host-level dotfiles 連携を扱うため #5 + 関連で扱う)"
related_sprints:
  - "SP-007_runner_sandbox"
related_adrs:
  - "ADR-00008 (Destructive Operation Boundary)"
---

# ADR-00012: Hook Trust Boundary (Phase 4 hooks repo 外 trusted wrapper)

## 背景

Phase 4 で `.claude/hooks/` 配下に防御 hook (Bash command tool denylist / git command guard / sprint pack frontmatter validator / 等) を実装したが、`harness-residual-risks.md` で次の CRITICAL 残リスクが defer されている:

- **PH4-F-001**: dispatcher 自己改ざん耐性なし。`Bash` tool で AI が `.claude/hooks/dispatcher.sh` を上書き → hook 機能無効化。
- **PH4-F-002**: snapshot state 改ざん耐性なし。AI が `.claude/local/hook-state/*` を編集 → 過去 violation 記録抹消。

これらは Sprint 7 RunnerAdapter + ADR-00008 forbidden path で repo 内 hook 改ざんを block するが、**`.claude/hooks/dispatcher.sh` 自体を信頼する** ことが前提となる。repo 外に trust root を置くことで dispatcher 改ざんも検出可能になる。

## 決定対象

- Phase 4 hooks の **trust root** をどこに置くか
- snapshot state を repo 内 / repo 外のどちらに置くか
- hook integrity 検証 method
- rollback 手順

## 前提 / 制約

- dotfiles repo (`/Users/tohga/dotfiles/`) は 1 user で管理、Git symlink 経由で `~/.claude/` にロード。
- TaskManagedAI repo は別 Git repo で、`.claude/` 配下が project-scoped hooks。
- Claude Code は session 開始時に project-scoped + user-scoped の両方の hooks を load。
- AI / runner が `Bash` で書込可能な path は `.claude/` 配下を含む。

## 選択肢

### 採用案 (proposed): repo 外 trusted wrapper + sha256 manifest

**trust root**:

- `~/.claude-trusted/taskmanagedai-hook-wrapper.sh` (dotfiles 管理、chmod 700)
- `~/.claude-trusted-state/taskmanagedai/` (snapshot state、chmod 700)

**flow**:

1. Claude Code が `.claude/settings.json` の `hooks.*.command` で `~/.claude-trusted/taskmanagedai-hook-wrapper.sh` を呼ぶ。
2. Wrapper は最初に `~/.claude-trusted/taskmanagedai-hook-manifest.sha256` を読み、対象 repo `.claude/hooks/dispatcher.sh` の sha256 を比較。
3. 比較 OK なら dispatcher を `exec`、NG なら `exit 2` で block。
4. dispatcher が child hook を呼ぶ際も同様の sha256 manifest check。
5. snapshot state は `~/.claude-trusted-state/taskmanagedai/${session_id}/` に書き込み、`.claude/local/` には書かない。

**manifest 更新フロー** (legitimate hook change 時):

1. `bash scripts/regenerate-hook-manifest.sh` (dotfiles で管理) を user が手動実行。
2. `.claude/hooks/**` の現状を sha256 で計算し `~/.claude-trusted/taskmanagedai-hook-manifest.sha256` を書き換え。
3. User commit + push (dotfiles 側)。

### 却下案 A: snapshot state を repo 内 `.claude/local/` に置く

- 利点: 簡潔
- 却下理由: AI が `.claude/local/hook-state/*.json` を編集 → 過去 violation 抹消可能。PH4-F-002 の根本対策にならない。

### 却下案 B: hook を全 disable

- 利点: 改ざん不可
- 却下理由: hook の防御効果を放棄する選択肢。AI 出力 boundary 強化に逆行。

### 却下案 C: read-only filesystem mount で `.claude/hooks/` を保護

- 利点: file-level immutability
- 却下理由: Mac/Linux host fs 制御は user-mode で困難 (root 権限 + chattr 等)、dotfiles で symlink 管理する pattern と衝突。

## リスク

- **dotfiles symlink 失敗で hook 実行不能**: `~/.claude-trusted/` 配下に wrapper が存在しないと全 hook が `exit 2`。fallback として「dotfiles symlink 確認 + manifest 再生成」script を `scripts/verify-hook-trust-root.sh` で提供。
- **manifest 自体の改ざん**: `~/.claude-trusted/taskmanagedai-hook-manifest.sha256` を AI が書き換える経路。これは host home 配下なので Sprint 7 forbidden path enforcement で `~/.claude-trusted/` を deny list に追加 (本 Sprint 7 BL-0072 で実装)。
- **session_id 衝突**: snapshot state path に session_id を入れることで session 間衝突を防ぐが、同 session 内の hook race は別途扱う必要 (本 ADR scope 外、別 ADR)。

## rollback 手順

1. `.claude/settings.json` の `hooks.*.command` を repo 内 `.claude/hooks/dispatcher.sh` に戻す (本 ADR proposed 化前の状態)。
2. `~/.claude-trusted/` 配下を削除。
3. `.claude/local/hook-state/` に snapshot state を戻す。

ADR-00012 が **proposed (本 Sprint 7 では accept しない)** のため、本 Sprint 7 では実装せず Phase 5 で扱う。

## 実装対象ファイル (Sprint 7 では proposed のみ、実装は Phase 5)

- `~/.claude-trusted/taskmanagedai-hook-wrapper.sh` (dotfiles 管理、Phase 5)
- `~/.claude-trusted/taskmanagedai-hook-manifest.sha256` (Phase 5)
- `scripts/regenerate-hook-manifest.sh` (Phase 5)
- `scripts/verify-hook-trust-root.sh` (Phase 5)
- `.claude/settings.json` rewrite (Phase 5)

## テスト指針 (Phase 5)

- manifest mismatch → wrapper が `exit 2` で block。
- manifest match → dispatcher exec。
- snapshot state が repo 外に書かれることを確認。
- `.claude/hooks/dispatcher.sh` の改ざん → 次 hook 起動で block。

## Sprint 7 への影響

- 本 ADR は **proposed のまま** で Sprint 7 を進める。
- Sprint 7 BL-0082 / BL-0083 / BL-0084 の実装は Phase 5 / Sprint 11 へ defer。
- 代わり Sprint 7 で `.claude/hooks/dispatcher.sh` および snapshot state path (`~/.claude-trusted/` / `~/.claude-trusted-state/`) を **forbidden path に追加** することで、本 ADR accepted 化後の trust root を pre-protect する (BL-0072 forbidden path で実装)。
