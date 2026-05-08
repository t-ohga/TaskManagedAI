---
id: "ADR-NNNNN"
title: "<title>"
status: "proposed"
date: "<date>"
authors:
  - "<author>"
related_sprints:
  - "SP-000_<feature-name>"
supersedes: null
superseded_by: null
---

このテンプレの使い方: 認証、DB schema、API 契約、AI 権限、MCP、Secrets、外部公開、破壊的操作、広範囲リファクタ、Provider、GitHub App permission 変更など、ADR Gate Criteria に該当する判断で使う。1-2 ページに収め、実装前に proposed として作成し、合意後に accepted へ更新する。

最終更新: <date>

## 背景

<!-- 記入ガイド: 何を決める ADR か、なぜ今必要か、どの Sprint / 設計文書 / 制約に関係するかを書く。機密情報は書かない。 -->

- 決定対象: <decision-scope>
- 関連 Sprint: <SP-000>
- 前提 / 制約: <constraints>

## 選択肢

<!-- 記入ガイド: 複数案を並列に書く。判断材料が足りない案は「未確認」と明記し、推測で埋めない。 -->

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|--------|------|------|---------------|
| A: <option-a> | <概要> | <利点> | <欠点 / リスク> |
| B: <option-b> | <概要> | <利点> | <欠点 / リスク> |
| C: <option-c> | <概要> | <利点> | <欠点 / リスク> |

## 採用案

<!-- 記入ガイド: 採用する案、採用理由、実装ガイダンスを書く。どのファイル / どの Sprint で実装するか、テスト指針を必ず含める。 -->

- 採用: <option>
- 理由: <why-this-option>
- 実装 Sprint: <SP-000>
- 実装対象ファイル:
  - `<path>`
  - `<path>`
- 実装ガイダンス:
  - <policy / validation / audit / rollback に関する実装方針>
- テスト指針:
  - `<command-or-test-name>`
  - <negative test / state contract test / smoke など>

## 却下案

<!-- 記入ガイド: 却下した案ごとに「なぜ却下したか」を必ず書く。単に「不採用」だけで終えない。 -->

- <option-a>: <却下理由>
- <option-b>: <却下理由>

## リスク

<!-- 記入ガイド: 採用案に残るリスク、検知方法、軽減策を書く。リスクがない場合も「現時点でなし」と明記する。 -->

| リスク | 検知方法 | 軽減策 |
|--------|----------|--------|
| <risk> | <how-to-detect> | <mitigation> |

## rollback 手順

<!-- 記入ガイド: 戻す条件、戻し方、影響を確認する方法を書く。破壊的操作を含む場合は backup / restore / migration rollback を明記する。 -->

1. <rollback trigger>
2. <rollback step>
3. <verification after rollback>
