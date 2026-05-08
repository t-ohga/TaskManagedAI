---
name: sprint-pack-create
description: "TaskManagedAI の light/heavy Sprint Pack 草案を docs/sprints に起票する。Triggers: Sprint Pack作成, SP-NNN, feature名"
when_to_use: |
  feature 名や Sprint 番号から `docs/sprints/SP-NNN_<feature>.md` の light/heavy Sprint Pack 草案を作る時。
  トリガーフレーズ: 'Sprint Pack 作成', 'SP を起票', 'light Pack', 'heavy Pack'
argument-hint: "<feature 名> --sprint-no <N> --adr-gate <yes|no|unknown> --risk-class <low|medium|high>"
allowed-tools: Bash Read Write Edit AskUserQuestion
---

# sprint-pack-create — 軽量/重量 Sprint Pack 起票

## 目的

TaskManagedAI の機能単位 Sprint を実装前 gate として起票する。ADR Gate Criteria に該当しない低リスク作業は light、該当または high-risk の作業は heavy を使う。

## 必読資料

- `docs/sprints/_template_light.md`
- `docs/sprints/_template_heavy.md`
- `.claude/rules/sprint-pack-adr-gate.md`
- `.claude/rules/plan-review.md`
- `.claude/reference/deliverables.md`
- `.claude/reference/hard-gates-and-kpis.md`

## Main Agent への指示

この skill は Sprint Pack 草案作成だけを行う。別 Skill / Agent の実行が必要な判断は出力の `follow_up` に残して Main Agent に戻す。

## Step 1: 入力と既存 Pack の確認

1. feature 名、Sprint 番号、ADR Gate 該当有無、risk class を取得する。
2. `docs/sprints/` を検索し、同じ Sprint 番号または近い feature slug の Pack がないか確認する。

```bash
rg --files docs/sprints
rg -n "id: \"SP-|sprint_no:|adr_refs:|planned_adr_refs:|risks:" docs/sprints
```

3. 既存 Pack がある場合は上書きしない。更新案として提示する。
4. `--adr-gate=unknown` または `risk-class=high` で判断が曖昧な場合は AskUserQuestion で確認する。

## Step 2: light / heavy 判定

heavy が必要な条件:

- ADR Gate Criteria 11 種のいずれかに該当。
- `tenant_id`、project boundary、複合 FK。
- API / event schema。
- Provider Compliance Matrix、`payload_data_class`、`allowed_data_class`。
- SecretBroker、`secret_ref`、atomic claim。
- AgentRun 16 状態、ContextSnapshot 10 カラム。
- `tool_mutating_gateway_stub`、`runner_mutation_gateway`。
- forbidden path、dangerous command、backup / restore、external exposure。
- GitHub App permission、workflow path、破壊的操作。

light が許容される条件:

- ADR Gate Criteria に該当しない。
- 低リスクで rollback が容易。
- P0 invariant への影響がない、または明確に not_applicable と説明できる。

## Step 3: 草案生成

path:

```text
docs/sprints/SP-NNN_<feature-slug>.md
```

frontmatter は次を必ず含める。

```yaml
---
id: "SP-NNN_<feature-slug>"
type: "light|heavy"
status: "draft"
sprint_no: N
created_at: "YYYY-MM-DD"
updated_at: "YYYY-MM-DD"
target_days: 0
max_days: 0
adr_refs: []
planned_adr_refs: []
risks: []
---
```

light 本文 skeleton:

```md
## 目的

- <目的>

## 対象外

- <対象外>

## 受け入れ条件

- [ ] <観測可能な条件>

## 検証手順

- [ ] `<command-or-manual-check>`

## 残リスク

- <risk-or-none>

## Review

- changed: <Sprint 完了後に記入>
- verified: <Sprint 完了後に記入>
- deferred: <Sprint 完了後に記入>
- risks: <Sprint 完了後に記入>
```

heavy 本文 skeleton には light に加えて次を必ず含める。

```md
## 背景
## 設計判断
## 実装チケット
## タスク一覧
## must_ship / defer_if_over_budget 対応表
## レビュー観点
## 次スプリント候補
## 関連 ADR
```

`must_ship / defer_if_over_budget` table skeleton:

```md
| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|---|---:|---:|---|---|
| SP-NNN | <target_days> | <max_days> | <P0 must ship item> | <P0.1/P1 defer candidate> |
```

## 出力 contract

```json
{
  "skill": "sprint-pack-create",
  "status": "PASS|WARN|BLOCK",
  "path": "docs/sprints/SP-NNN_<feature>.md",
  "pack_type": "light|heavy",
  "frontmatter": {
    "id": "SP-NNN_<feature>",
    "type": "light|heavy",
    "status": "draft",
    "sprint_no": 0,
    "target_days": 0,
    "max_days": 0,
    "adr_refs": [],
    "planned_adr_refs": [],
    "risks": []
  },
  "adr_gate": {
    "required": true,
    "criteria": [1, 2],
    "reason": "<summary>"
  },
  "follow_up": []
}
```

## 失敗時の挙動

- feature 名または Sprint 番号が不明: BLOCK。AskUserQuestion に戻す。
- 既存 Pack と衝突: BLOCK。上書きせず更新案を出す。
- heavy 必須だが ADR criteria が曖昧: WARN ではなく確認に戻す。
- raw secret、token、private fixture 期待値を入力に含む場合: BLOCK。redaction を要求する。
- template が存在しない場合: `.claude/rules/sprint-pack-adr-gate.md` の必須 section から生成し、template 欠落を WARN に記録する。

## TaskManagedAI 不変条件 trace

- Sprint Pack / ADR Gate を実装前条件として固定する。
- Provider Compliance、SecretBroker、AgentRun、tenant boundary、runner gateway への影響を `risks` と `planned_adr_refs` に残す。
- Hard Gates 7 / Quality KPIs 5 への trace を受け入れ条件またはレビュー観点に含める。
- Review 欄に changed / verified / deferred / risks を残せる状態にする。

