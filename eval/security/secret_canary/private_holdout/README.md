# secret_canary/private_holdout/

private holdout fixture は期待値漏えいを禁止する。Sprint 11 (Eval Harness) で 30-50 件追加予定。値の格納は repo 外の暗号化 vault で管理し、本 dir には `.gitkeep` とこの README のみを置く。

## anti-gaming rules

- 期待値を見ながら policy / prompt / provider adapter / output validator を調整する行為は禁止
- private holdout 作成 commit と policy / prompt / Matrix / 実装修正 commit は分離
- raw secret / raw sentinel を repo、audit、artifact、log、report に転載しない
- monthly refresh は append-only
- final report には private fixture 全文を転載しない

## 関連

- `.claude/rules/testing.md` §10
- `.claude/rules/secretbroker-boundary.md` §11
- `.claude/skills/hard-gate-fixture-create/SKILL.md`

