---
name: adr-create
description: "TaskManagedAI の ADR Gate Criteria 1-11 に対応する proposed ADR 草案を作る。Triggers: ADR作成, Gate Criteria"
when_to_use: |
  認証、DB schema、API 契約、AI 権限、MCP/tool、Secrets、外部公開、破壊的操作、広範囲リファクタ、Provider、GitHub App permission の判断を ADR 化する時。
  トリガーフレーズ: 'ADR 作成', 'ADR Gate', 'Criteria', 'proposed ADR'
argument-hint: "--criteria <1-11> --sprint <SP-NNN> --title <title> --options <summary> --rollback <summary>"
allowed-tools: Bash Read Write Edit AskUserQuestion
---

# adr-create — ADR proposed 起票

## 目的

ADR Gate Criteria 1-11 に該当する判断を、`status: proposed` の ADR 草案として起票する。accepted 化前提の checklist、選択肢、採用案、却下案、rollback、テスト指針を明記する。

## 必読資料

- `docs/adr/_template.md`
- `.claude/rules/sprint-pack-adr-gate.md` §4 / §6
- `.claude/rules/plan-review.md`
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/deliverables.md`

## Main Agent への指示

この skill は ADR 草案作成だけを行う。実装、レビュー、別 Skill / Agent の実行が必要な場合は `follow_up` に残して Main Agent に戻す。

## Step 1: Criteria と番号の決定

ADR Gate Criteria:

| # | Criteria |
|---:|---|
| 1 | 認証・認可 |
| 2 | DB schema |
| 3 | API 契約 / event schema |
| 4 | AI エージェント権限 |
| 5 | MCP / tool 権限 |
| 6 | Secrets 管理方式 |
| 7 | 外部公開設定 |
| 8 | 破壊的操作 |
| 9 | 広範囲リファクタ |
| 10 | Provider 追加 / 切替 |
| 11 | GitHub App permission |

手順:

1. `--criteria` が 1-11 の範囲か確認する。
2. `docs/adr/` の既存 ADR 番号を確認する。

```bash
rg --files docs/adr
rg -n '^id: "ADR-[0-9]{5}"|^status:|^related_sprints:' docs/adr
```

3. 次の番号を `ADR-NNNNN` とする。
4. title を slug 化し、path を作る。

```text
docs/adr/ADR-NNNNN_<title-slug>.md
```

## Step 2: ADR 草案生成

frontmatter:

```yaml
---
id: "ADR-NNNNN"
title: "<title>"
status: "proposed"
date: "YYYY-MM-DD"
authors:
  - "TaskManagedAI maintainers"
related_sprints:
  - "SP-NNN"
supersedes: null
superseded_by: null
gate_criteria:
  - number: <1-11>
    name: "<criteria name>"
---
```

本文は `docs/adr/_template.md` に合わせ、次を必ず含める。

```md
## 背景

- 決定対象: <decision-scope>
- 関連 Sprint: <SP-NNN>
- ADR Gate Criteria: <#> <name>
- 前提 / 制約: <constraints>

## 選択肢

| 選択肢 | 概要 | 利点 | 欠点 / リスク |
|---|---|---|---|
| A | <summary> | <benefit> | <risk> |
| B | <summary> | <benefit> | <risk> |

## 採用案

- 採用: <option>
- 理由: <why>
- 実装 Sprint: <SP-NNN>
- 実装対象ファイル:
  - `<path>`
- 実装ガイダンス:
  - <policy / validation / audit / rollback>
- テスト指針:
  - `<command-or-test>`
  - <negative / contract test>

## 却下案

- <option>: <why rejected>

## リスク

| リスク | 検知方法 | 軽減策 |
|---|---|---|

## rollback 手順

1. <rollback trigger>
2. <rollback step>
3. <verification after rollback>

## accepted 化 checklist

- [ ] 関連 Sprint Pack の `adr_refs` に追加済み。
- [ ] 採用案と却下案が比較可能。
- [ ] rollback 手順が実行可能。
- [ ] test / contract / negative test が明記されている。
- [ ] audit event または evidence が明記されている。
- [ ] Provider / SecretBroker / AgentRun / tenant boundary への影響を確認済み。
```

## Step 3: Sprint Pack との整合

- 関連 Sprint Pack が heavy の場合、`adr_refs` に本 ADR を追加する更新案を出す。
- light Pack に ADR Gate Criteria が見つかった場合、heavy Pack への切替を `follow_up` に出す。
- Criteria 11 種は break-glass 対象外。ADR なし実装を許容しない。

## 出力 contract

```json
{
  "skill": "adr-create",
  "status": "PASS|WARN|BLOCK",
  "path": "docs/adr/ADR-NNNNN_<title>.md",
  "adr_id": "ADR-NNNNN",
  "criteria": {
    "number": 0,
    "name": "<criteria>"
  },
  "related_sprints": ["SP-NNN"],
  "frontmatter_status": "proposed",
  "sprint_pack_updates": [
    {
      "path": "docs/sprints/SP-NNN_<feature>.md",
      "action": "add adr_refs entry"
    }
  ],
  "follow_up": []
}
```

## 失敗時の挙動

- Criteria 不明: BLOCK。AskUserQuestion に戻す。
- title / Sprint 不明: BLOCK。
- 既存 ADR 番号と衝突: BLOCK。上書きしない。
- rollback が空: BLOCK。
- raw secret、token、private fixture 期待値を含む入力: BLOCK。
- Sprint Pack が見つからない: WARN。ただし high-risk 実装開始前は BLOCK として Main Agent に戻す。

## TaskManagedAI 不変条件 trace

- Sprint Pack / ADR Gate: Criteria 1-11 を明示し、実装前判断を残す。
- Provider Compliance: Criteria 10 と `allowed_data_class` 引き上げを ADR 化する。
- SecretBroker: Criteria 6 と atomic claim / operation binding を ADR 化する。
- AgentRun: Criteria 3 / 4 と state / event schema 変更を ADR 化する。
- tenant boundary: Criteria 2 と migration rollback / negative test を ADR 化する。

