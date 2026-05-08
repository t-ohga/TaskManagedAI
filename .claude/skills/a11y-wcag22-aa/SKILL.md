---
name: a11y-wcag22-aa
description: "TaskManagedAI frontend を WCAG 2.2 AA と P0 UI 状態表示で監査する。Triggers: a11y, WCAG 2.2, UI review"
when_to_use: |
  frontend/app、frontend/components の UI 実装を WCAG 2.2 AA、keyboard nav、focus、form label、loading/error/empty state で監査する時。
  P0 UI は Sprint 9 以降が主対象。実装開始前は dormant として未作成範囲を WARN にする。
  トリガーフレーズ: 'a11y', 'WCAG 2.2', 'アクセシビリティ監査', 'UI review'
argument-hint: "[--scope=current-branch|staged|all|specified-files] [--files=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# a11y-wcag22-aa — WCAG 2.2 AA 監査

## 目的

TaskManagedAI の `frontend/app/**/*.{tsx,jsx}` と `frontend/components/` を対象に、WCAG 2.2 AA、semantic HTML、role / aria、contrast、focus、keyboard navigation、form label、loading / error / empty state、destructive action の P0 deny 表示を監査する。

この skill は監査専用であり、修正は行わない。別 Skill / Agent を再帰起動しない。P0 UI 実装が始まるまで dormant に近い扱いだが、Sprint 9 以降で即使えるようにする。

## 必読資料

- `.claude/rules/rendering.md` §7
- `.claude/rules/rendering.md` §5-§8
- `.claude/rules/core.md` §5-§7
- `.claude/rules/agentrun-state-machine.md`
- `.claude/reference/frontend-strategy.md`
- 関連 Sprint Pack / UI ADR

## 対象

- `frontend/app/**/*.{tsx,jsx}`
- `frontend/components/**/*.{tsx,jsx}`
- `frontend/**/*.css`
- UI state / approval / AgentRun / audit log / dashboard 関連 component
- Playwright / Vitest UI test

## 検査手順

1. 対象ファイルを確定する。

```bash
git diff --name-only
git diff --cached --name-only
rg --files frontend 2>/dev/null | rg '(\.tsx$|\.jsx$|\.css$)'
```

`frontend/` が未作成の場合は dormant WARN として終了する。

2. semantic HTML と landmark を確認する。

```bash
rg -n "<div|<span|<main|<nav|<header|<footer|<section|<article|role=|aria-" frontend/app frontend/components 2>/dev/null
```

BLOCK:

- clickable `div` / `span` が keyboard 操作できない
- main content に `<main>` 相当がない
- navigation / dialog / table を semantic element なしで実装
- role を付けたが required aria state がない
- role と native element が矛盾する

WARN:

- heading order が不自然
- dashboard / audit table に caption / summary がない
- landmark が重複して screen reader navigation が曖昧

3. accessible name を確認する。

```bash
rg -n "<button|<a |<input|<select|<textarea|aria-label|aria-labelledby|title=|alt=" frontend/app frontend/components 2>/dev/null
```

BLOCK:

- icon-only button に accessible name がない
- `<img>` / framework image component に `alt` がない
- form control に label / `aria-label` / `aria-labelledby` がない
- destructive / approval action の button name が曖昧
- link text が `click here` 相当で目的を説明しない

WARN:

- placeholder を label 代わりにしている
- dynamic button label が loading 中に空になる
- tooltip だけが accessible name になっている

4. focus / keyboard navigation を確認する。

```bash
rg -n "tabIndex|onKeyDown|onClick|outline-none|focus-visible|autoFocus|Dialog|Modal|Popover|Menu|Dropdown" frontend/app frontend/components frontend/**/*.css 2>/dev/null
```

BLOCK:

- `outline-none` で代替 focus style がない
- keyboard で到達できない操作
- modal / dialog で focus trap / return focus がない
- Escape / Enter / Space の基本操作がない interactive control
- destructive action confirm が pointer-only

WARN:

- custom roving tabindex の test がない
- focus order が DOM order と矛盾
- loading 中に focus が失われる

5. color contrast / responsive / overflow を確認する。

```bash
rg -n "text-|bg-|border-|opacity-|contrast|#[0-9a-fA-F]{3,8}|rgb|hsl|truncate|overflow-hidden|whitespace-nowrap" frontend/app frontend/components frontend/**/*.css 2>/dev/null
```

BLOCK:

- text contrast が WCAG 2.2 AA を満たす根拠なしに低い
- disabled / loading / error state が色だけで表現される
- button / card / table cell で text overflow が操作不能にする
- focus indicator が背景と識別できない

WARN:

- status / severity が色だけに依存
- long task title / provider name / reason_code で layout が崩れる可能性
- mobile viewport の主要 flow が未確認

6. loading / error / empty state を確認する。

```bash
rg -n "loading|pending|skeleton|spinner|error|empty|not found|fallback|Suspense|ErrorBoundary|toast|alert|role=\"alert\"|aria-live" frontend/app frontend/components 2>/dev/null
```

BLOCK:

- data fetch UI に loading / error / empty state がない
- error state が raw provider response / raw secret / raw stack を表示する
- async status が screen reader に伝わらない
- toast が audit event の代替になっている
- `role="alert"` / `aria-live` が濫用または欠落して重要 state が伝わらない

WARN:

- retry / resume affordance が `provider_incomplete` と連動しない
- empty state が次 action を説明しない
- long-running AgentRun の progress が event trace と結びつかない

7. TaskManagedAI 固有 UI 状態を確認する。

```bash
rg -n "AgentRun|blocked_reason|policy_blocked|budget_blocked|runtime_blocked|waiting_approval|provider_incomplete|provider_refused|payload_data_class|allowed_data_class|secret_ref|approval|destructive|deny|blocked|audit" frontend/app frontend/components 2>/dev/null
```

BLOCK:

- AgentRun 16 状態を UI で欠落 / 誤表示
- `blocked_reason` を status と混同
- `provider_incomplete` を terminal として表示
- `payload_data_class` と `allowed_data_class` を同じ field として表示
- secret 値 / provider key / capability token 生値を DOM に表示
- destructive action が P0 deny であることを表示しない
- merge / deploy / workflow write を P0 で実行可能に見せる

WARN:

- Hard Gate / KPI dashboard が fixture ID / dataset version に辿れない
- approval invalidated / expired / rejected の区別がない
- audit log が trace_id / correlation_id で辿れない

8. test / browser verification を確認する。

```bash
rg -n "playwright|axe|accessibility|keyboard|tab|focus|aria|toHaveAccessibleName|toBeVisible|viewport" frontend tests 2>/dev/null
```

WARN:

- keyboard nav test がない
- accessible name test がない
- mobile / desktop viewport test がない
- destructive deny display の test がない

BLOCK:

- UI 実装変更で主要 approval / AgentRun flow の accessibility regression が未確認
- known violation を test skip で隠している

## 出力 contract

Markdown で返す。

```markdown
## WCAG 2.2 AA Audit Result
Verdict: PASS|WARN|BLOCK
Scope: current-branch|staged|all|specified-files
Dormant: true|false

## Findings
| severity | file:line | WCAG / policy | issue | user_impact | suggested_fix |
|---|---|---|---|---|---|

## TaskManagedAI UI State Checks
| invariant | verdict | evidence | fix |
|---|---|---|---|

## Required Verification
- <Playwright / keyboard / contrast / screen reader check>
```

`WCAG / policy` には WCAG SC 番号が明確な場合は番号を書く。TaskManagedAI 固有の場合は `TaskManagedAI rendering §7` または `P0 deny display` と書く。

## 失敗時の挙動

- `frontend/` が未作成なら WARN、`Dormant: true` とし、Sprint 9 以降に再実行する前提を書く。
- line 特定ができない grep hit は Read で確認してから finding にする。
- secret / provider key / capability token 生値が DOM に出る場合は BLOCK。値は再出力しない。
- keyboard 操作不能、accessible name 欠落、form label 欠落、focus 不可視は BLOCK。
- contrast は静的 grep だけで断定できない場合があるため、根拠不足は WARN とし、ブラウザ / axe / Playwright 確認を要求する。
- UI が未実装の P0 deny action は WARN。実装済みで deny 表示がない場合は BLOCK。

## TaskManagedAI 不変条件 trace

- `.claude/rules/rendering.md` §7 Accessibility / UX
- AgentRun 16 状態 + `blocked_reason` サブ 3 の正確な UI 表示
- `payload_data_class` / `allowed_data_class` 分離表示
- Secret 値 / raw provider response / capability token 生値の DOM 非露出
- Approval state: pending / approved / rejected / expired / invalidated の区別
- P0 destructive action deny 表示
- AC-KPI-01 acceptance flow の UI 到達性
- AC-KPI-03 approval wait の UI trace
- AC-HARD-02 secret canary no leak

