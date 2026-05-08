# backup_restore/private_holdout/

private holdout fixture は **期待値漏えいを禁止** する。Sprint 11 (Eval Harness) で 30-50 件追加予定。値の格納は repo 外の暗号化 vault (例: `~/.claude-eval-vault/backup_restore/`) で管理し、本 dir には `.gitkeep` とこの README のみを置く。

## anti-gaming rules

- 期待値を見ながら backup script / restore 手順 / monitoring threshold を調整する行為は禁止
- private holdout 作成 commit と ops script / policy / prompt 修正 commit は分離
- monthly refresh は append-only
- private backup path、checksum、鍵情報、restore target の全文は final report に転載しない

## 関連

- `.claude/rules/testing.md` §10
- `.claude/skills/hard-gate-fixture-create/SKILL.md`

