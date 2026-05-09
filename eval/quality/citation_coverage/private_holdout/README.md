# citation_coverage/private_holdout/

private holdout fixture は期待値漏えいを禁止する。Sprint 11 (Eval Harness) で 30+ 件追加予定。値の格納は repo 外の暗号化 vault で管理し、本 dir には `.gitkeep` とこの README のみを置く。

## anti-gaming rules

- 期待値を見ながら prompt / retrieval / ranking / metric 実装を調整する行為は禁止
- private holdout 作成 commit と prompt / retrieval / metric / 実装修正 commit は分離
- monthly refresh は append-only
- final report には private fixture 全文を転載しない
- `evidence_set_hash` は trace 用 metadata として保持するが、private expectation は保持しない

## 関連

- `.claude/rules/testing.md` §10
- `.claude/reference/hard-gates-and-kpis.md` §3 AC-KPI-04

