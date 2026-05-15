---
id: PLAN-PHASE-5-HOOK-TRUST-BOUNDARY-2026-05-13
title: "Phase 5 — Hook Trust Boundary 実装計画 (ADR-00012 accepted 化)"
status: draft
date: 2026-05-13
authors:
  - "claude (sprint7 audit owner)"
related_documents:
  - "../adr/00012_hook_trust_boundary.md"
  - "../設計検討/harness-residual-risks.md"
  - "../sprints/SP-007_runner_sandbox.md"
  - "./2026-05-13_p0_exit_master_plan.md"
---

# Phase 5 — Hook Trust Boundary 実装計画

## 0. 概要

Sprint 7 (Runner Sandbox) で `status: done_with_phase5_defer` として完了した Phase 4 hooks の PH4-F-001 (dispatcher 自己改ざん耐性) + PH4-F-002 (snapshot state 改ざん耐性) を **repo 外 trusted wrapper + sha256 manifest** で根本解決し、ADR-00012 を `proposed` → `accepted` 化する Phase 工程。

Sprint 11 / 12 と **並走可能** (SP-007 status 昇格にのみ影響、P0 Exit blocker ではない)。

## 1. 背景

- Sprint 7 batch 0 で ADR-00012 (Hook Trust Boundary) を `proposed` 起票
- Phase 4 hooks (`.claude/hooks/runner/` 等 80+ scripts) は repo 内に存在、Bash tool 経由で AI が改ざん可能 (PH4-F-001 / PH4-F-002)
- SP-007 batch 0 + batch 1 で **`~/.claude-trusted/` を forbidden path として pre-protect** し、本 Phase 5 で wrapper 実装
- 本 Phase 完了で SP-007 status `done_with_phase5_defer` → `done` 昇格、ADR-00012 accepted

## 2. 実装スコープ

### 2.1 BL 一覧 (3 BL + ADR 1)

| BL ID | 内容 | depends_on |
|---|---|---|
| BL-0082 | repo 外 trusted wrapper (`~/.claude-trusted/taskmanagedai-hook-wrapper.sh`) + manifest 検証 + fail-closed | — |
| BL-0083 | snapshot state repo 外移動 (`~/.claude-trusted-state/taskmanagedai/`) + dotfiles 管理化 + migration note | BL-0082 |
| BL-0084 | sha256 manifest 生成 / 検証 + wrapper self-test | BL-0082, BL-0083 |
| **ADR-00012** | accepted 化 (wrapper + state + manifest 完成 + self-test PASS 後) | BL-0084 |

### 2.2 ファイル配置

#### BL-0082: trusted wrapper

```text
~/.claude-trusted/
├── taskmanagedai-hook-wrapper.sh   # 中央 dispatcher、repo 外配置
├── taskmanagedai-manifest.sha256   # 全 hook の sha256 hash
└── taskmanagedai-allowlist.txt     # hook 名 allowlist (正本)

~/.claude/settings.json:
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "command": "~/.claude-trusted/taskmanagedai-hook-wrapper.sh PreToolUse Bash"},
      ...
    ]
  }
```

wrapper の挙動:
1. caller (Claude Code) が hook を invoke
2. wrapper が `taskmanagedai-manifest.sha256` を verify (manifest 自体の hash も protect)
3. wrapper が `taskmanagedai-allowlist.txt` で hook 名を verify
4. hook が allowlist + manifest 一致なら repo 内 hook を invoke
5. 不一致なら fail-closed (`exit 2` BLOCK + alert log)

#### BL-0083: snapshot state 移動

repo 内 `.claude/local/codex-tasks/` 等の "state" data を `~/.claude-trusted-state/taskmanagedai/` に移動。

```text
~/.claude-trusted-state/taskmanagedai/
├── codex-tasks/           # 旧 .claude/local/codex-tasks/
├── codex-reviews/         # 旧 .claude/local/codex-reviews/
├── snapshot-state/        # AgentRun snapshot 等
└── failure-counters/      # codex-failure-count.* 等
```

repo 内 `.claude/local/` は wrapper 経由でのみ書き込み可能 (read のみ permit)。

dotfiles 管理化:
```text
~/dotfiles/editor/claude-code/claude-trusted/
├── taskmanagedai-hook-wrapper.sh    # symlink target
├── taskmanagedai-manifest.sha256
└── taskmanagedai-allowlist.txt
```

migration note: 既存 `.claude/local/` 配下を `~/.claude-trusted-state/taskmanagedai/` に rsync (Phase 5 batch 0 で 1 回実施、その後 wrapper enforce)。

#### BL-0084: sha256 manifest

```bash
#!/usr/bin/env bash
# ~/.claude-trusted/taskmanagedai-manifest-generate.sh

WORKTREE="/Users/tohga/repo/TaskManagedAI"
MANIFEST="$HOME/.claude-trusted/taskmanagedai-manifest.sha256"

find "$WORKTREE/.claude/hooks/" -type f -name '*.sh' -exec sha256sum {} \; \
  | sed "s|$WORKTREE/||" \
  | sort -k2 \
  > "$MANIFEST"

# manifest 自身の hash
sha256sum "$MANIFEST" > "${MANIFEST}.sig"
```

wrapper self-test:

```bash
~/.claude-trusted/taskmanagedai-hook-wrapper.sh --self-test
```

- manifest 一致 verify
- allowlist 一致 verify
- snapshot state 配置 verify
- repo 内 hook 実行可能 verify (sample run)
- exit 0 / fail-closed enforcement verify

## 3. 想定 Codex multi-round budget

- BL-0082: 3-5 round (wrapper script + fail-closed logic)
- BL-0083: 2-3 round (migration + dotfiles 管理)
- BL-0084: 2-3 round (manifest generator + self-test)
- ADR-00012 accepted 化: 1 round (review)
- **累計: 8-12 round (1-2 session)**

## 4. 検証手順

```bash
# wrapper installation verify
ls -la ~/.claude-trusted/
sha256sum -c ~/.claude-trusted/taskmanagedai-manifest.sha256.sig

# wrapper self-test
bash ~/.claude-trusted/taskmanagedai-hook-wrapper.sh --self-test

# manifest verify
sha256sum -c ~/.claude-trusted/taskmanagedai-manifest.sha256

# dotfiles 管理確認
ls -la ~/dotfiles/editor/claude-code/claude-trusted/
ls -la ~/.claude-trusted/  # symlink target が dotfiles に向いているか

# PH4-F-001 / PH4-F-002 解消 verify
# 1. .claude/hooks/runner/check-dangerous-command-fixture.sh を改ざん試行
echo "echo PWN" >> .claude/hooks/runner/check-dangerous-command-fixture.sh
# wrapper 経由で実行 → manifest mismatch で fail-closed
bash ~/.claude-trusted/taskmanagedai-hook-wrapper.sh PostToolUse Bash
# 期待: exit 2 BLOCK + alert log
git checkout .claude/hooks/runner/check-dangerous-command-fixture.sh  # restore

# 2. snapshot state 改ざん試行
echo "FAKE" > ~/.claude-trusted-state/taskmanagedai/snapshot-state/test.txt
# wrapper が snapshot state read 時に hash verify
bash ~/.claude-trusted/taskmanagedai-hook-wrapper.sh PreToolUse Read
# 期待: state corruption detect + alert

# integration test (Sprint 7 audit clean regression)
uv run pytest tests/runner/ -q
```

## 5. Sprint 11 / 12 との並走

本 Phase 5 は **Sprint 11 と並走可能** (SP-007 status 昇格にのみ影響、P0 Exit blocker ではない)。

並走パターン:

- Sprint 11 batch 0 (Eval Harness core) を main agent で進める間、Phase 5 BL-0082/0083/0084 を bg job (worktree 別) で並走
- Sprint 11 batch 0 完了後に Phase 5 BL-0084 verify を main agent で実施、ADR-00012 accepted 化

OR

- Sprint 11 完了後、Sprint 11.5 着手前に Phase 5 を 1-2 session で完遂

default: Sprint 11 と並走 (worktree 別 + scope 分離で conflict 回避)。

## 6. 完了条件

- BL-0082/0083/0084 完了
- wrapper self-test PASS
- manifest verify PASS
- snapshot state 配置 verify
- PH4-F-001 (dispatcher 自己改ざん耐性) + PH4-F-002 (snapshot state 改ざん耐性) 改ざん試行 fail-closed
- Sprint 7 audit clean regression (236 runner tests + 2219 full tests) PASS
- ADR-00012 `status: accepted`
- **SP-007 status `done_with_phase5_defer` → `done` 昇格**

## 7. Rollback

- wrapper 不在時は `~/.claude/settings.json` を `direct` mode に戻す (旧 hook 実行経路、wrapper bypass)
- snapshot state repo 内 fallback (Phase 5 完成前と同等)
- ADR-00012 `accepted` → `proposed` revert (rollback 専用)

## 8. Risk

- **dotfiles 管理失敗で hook 実行不能 (HIGH)**: dotfiles symlink 切れ / wrapper 不在で全 hook 実行不能。fail-closed 設計で wrapper unavailable detect + alert を必須にする。
- **migration data loss (MEDIUM)**: `.claude/local/` → `~/.claude-trusted-state/taskmanagedai/` rsync で data loss 可能性。rsync `--checksum` + dry-run + backup を migration script に組み込む。
- **manifest 更新忘れ (LOW)**: 新 hook 追加時に manifest 更新を忘れて wrapper が fail-closed。`scripts/regenerate-manifest.sh` を `.claude/hooks/_meta/regenerate-trusted-manifest.sh` として配置し、hook 追加時に手動 + CI で実行。

## 9. ADR-00012 accepted 化条件

ADR-00012 frontmatter `status: proposed` → `accepted` の昇格条件:

1. BL-0082/0083/0084 全件完了
2. wrapper self-test PASS
3. manifest verify PASS
4. PH4-F-001 / PH4-F-002 改ざん試行 fail-closed verify
5. Sprint 7 audit regression PASS
6. SP-007 frontmatter `status: done_with_phase5_defer` → `done` 同期

ADR-00012 ## Status 詳細に「Phase 5 完了 2026-MM-DD で accepted、PH4-F-001 / PH4-F-002 解消 verify 経緯を記録」を追記。
