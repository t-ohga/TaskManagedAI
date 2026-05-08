---
name: skill-lint
description: "TaskManagedAI Skill frontmatter と禁止語レジストリの lint。Triggers: skill lint, SKILL.md lint"
when_to_use: |
  .claude/skills/*/SKILL.md の frontmatter、name 衝突、description 長、allowed-tools 最小権限、禁止語残存、再帰起動表現を確認する時。
  トリガーフレーズ: 'skill lint', 'SKILL.md lint', 'frontmatter', 'allowed-tools', 'catalog drift'
argument-hint: "[--skill=<name>|--all] [--catalog=<path>] [--strict]"
allowed-tools: Read Bash Grep
---

# skill-lint — Skill catalog / metadata lint

## 目的

TaskManagedAI の `.claude/skills/*/SKILL.md` が frontmatter 必須 field、name 一意性、description 上限、allowed-tools 最小権限、禁止語レジストリ準拠、再帰起動禁止を満たすか lint する。auto-fix は行わない。

**重要**: 禁止語の具体パターンは本 SKILL.md 内に直書きせず、`.claude/reference/skill-lint-banned-terms.md` を正本として参照する。本 skill 自身が監査対象内にあるため、禁止語を本文に書くと自己違反になるため。

## 必読資料

- `.claude/reference/skill-lint-banned-terms.md` (禁止語レジストリの正本)
- `docs/設計検討/harness-phase0-mapping.md` §2.5 / §3.4
- `.claude/CLAUDE.md`
- `.claude/rules/core.md`
- `.claude/reference/harness-inventory.md`
- `.claude/reference/governance-cycle.md`
- `.claude/reference/agent-routing.md`

## 対象

- `.claude/skills/*/SKILL.md`
- optional catalog file if present
- `.claude/reference/harness-inventory.md`
- `.claude/reference/agent-routing.md`

検査対象から **除外** するファイル (レジストリの §4 例外リストに準拠):

- `.claude/reference/skill-lint-banned-terms.md` 自身
- `.claude/CLAUDE.md` (Codex 連携 skill 名列挙のため)
- `docs/設計検討/harness-phase0-mapping.md` (参考読み取り対象記述のため)

## 検査手順

### 1. Skill 一覧を確認

```bash
find .claude/skills -maxdepth 2 -name SKILL.md -print | sort
```

### 2. frontmatter 必須 field を確認

```bash
rg -n "^---$|^name:|^description:|^when_to_use:|^argument-hint:|^allowed-tools:" .claude/skills/*/SKILL.md
```

必須 field: `name`, `description`, `when_to_use`, `argument-hint`, `allowed-tools`

BLOCK 条件:

- frontmatter が `---` で始まらない
- 必須 field 欠落
- folder name と `name` が不一致
- `description` が 140 chars を超える

### 3. name 衝突

```bash
rg -n "^name:" .claude/skills/*/SKILL.md | awk -F: '{print $NF}' | sort | uniq -d
```

uniq -d の出力が 1 行でもあれば BLOCK。

### 4. allowed-tools 最小権限

原則:

- 監査 skill (review-* / *-audit / *-validator): `Read Bash Grep`
- skeleton 生成 skill (sprint-pack-create / adr-create / hard-gate-fixture-create): `Read Bash Edit Write`
- Suite skill: `Skill Agent Bash Read Edit Write AskUserQuestion`
- specialty skill には `Skill` / `Agent` を含めない

BLOCK 条件:

- 監査だけの skill に `Edit` / `Write`
- specialty skill に `Skill` / `Agent`
- 実在しない tool 名

### 5. 禁止語レジストリ準拠

レジストリ `.claude/reference/skill-lint-banned-terms.md` §5 の machine-readable block (`<!-- BEGIN_BANNED_TERMS_IESHIMA -->` 〜 `<!-- END_BANNED_TERMS_IESHIMA -->` および `BANNED_TERMS_RAW_SECRETS`) のみを抽出する。**§1 / §2 / §3 の文章部分は抽出しない** (false positive 防止)。

```bash
banned_pattern=$(awk '/^<!-- BEGIN_BANNED_TERMS_IESHIMA -->/{flag=1; next}
                       /^<!-- END_BANNED_TERMS_IESHIMA -->/{flag=0}
                       flag && /^[^`#<]/ {print}' \
                       .claude/reference/skill-lint-banned-terms.md \
                       | grep -v '^```' | grep -v '^$' \
                       | tr '\n' '|' | sed 's/|$//')

# block 欠落 / 空 pattern を fail-closed で BLOCK
if [ -z "$banned_pattern" ]; then
  echo "ERROR skill-lint: BANNED_TERMS_IESHIMA block missing or empty in .claude/reference/skill-lint-banned-terms.md" >&2
  exit 1
fi

# 検査対象 (レジストリ §4 例外リストを除外)。-ni で case-insensitive。
# rg exit code: 0=hit (BLOCK)、1=no-match (clean)、2 以上=実行エラー (BLOCK)
set +e
rg -ni --regexp "$banned_pattern" .claude/skills \
  --glob '*.md' \
  --glob '!.claude/reference/skill-lint-banned-terms.md' \
  --glob '!.claude/CLAUDE.md' \
  --glob '!docs/設計検討/harness-phase0-mapping.md'
rg_rc=$?
set -e
case "$rg_rc" in
  0)
    echo "ERROR skill-lint: BANNED_TERMS_IESHIMA pattern matched in .claude/skills" >&2
    exit 1
    ;;
  1) ;;  # no match = clean
  *)
    echo "ERROR skill-lint: rg failed while checking BANNED_TERMS_IESHIMA (exit $rg_rc, possible regex parse error)" >&2
    exit 1
    ;;
esac

# raw secret pattern (case-sensitive)
secret_pattern=$(awk '/^<!-- BEGIN_BANNED_TERMS_RAW_SECRETS -->/{flag=1; next}
                       /^<!-- END_BANNED_TERMS_RAW_SECRETS -->/{flag=0}
                       flag && /^[^`#<]/ {print}' \
                       .claude/reference/skill-lint-banned-terms.md \
                       | grep -v '^```' | grep -v '^$' \
                       | tr '\n' '|' | sed 's/|$//')

if [ -z "$secret_pattern" ]; then
  echo "ERROR skill-lint: BANNED_TERMS_RAW_SECRETS block missing or empty" >&2
  exit 1
fi

set +e
rg -n --regexp "$secret_pattern" .claude/skills --glob '*.md'
rg_secret_rc=$?
set -e
case "$rg_secret_rc" in
  0)
    echo "CRITICAL skill-lint: raw secret pattern matched in .claude/skills" >&2
    exit 1
    ;;
  1) ;;  # no match = clean
  *)
    echo "ERROR skill-lint: rg failed while checking BANNED_TERMS_RAW_SECRETS (exit $rg_secret_rc)" >&2
    exit 1
    ;;
esac

# ここまで到達 = clean
echo "skill-lint: PASS (no banned terms / raw secrets in .claude/skills)"
```

BLOCK 条件:

- `BANNED_TERMS_IESHIMA` block の pattern が specialty skill 本文に hit
- `BANNED_TERMS_RAW_SECRETS` block の pattern が hit (CRITICAL)
- レジストリ §2 の必須 trace 用語が 1 つも skill 本文に出現しない (WARN)

### 6. 再帰起動禁止

レジストリ §5 の `RECURSION_PATTERNS` block を抽出して specialty skill のみに適用 (Suite 5 件は §3 例外条件で別判定):

```bash
recursion_pattern=$(awk '/^<!-- BEGIN_RECURSION_PATTERNS -->/{flag=1; next}
                          /^<!-- END_RECURSION_PATTERNS -->/{flag=0}
                          flag && /^[^`#<]/ {print}' \
                          .claude/reference/skill-lint-banned-terms.md \
                          | grep -v '^```' | grep -v '^$' \
                          | tr '\n' '|' | sed 's/|$//')

if [ -z "$recursion_pattern" ]; then
  echo "ERROR skill-lint: RECURSION_PATTERNS block missing or empty" >&2
  exit 1
fi

# Suite 5 件 + skill-lint 自身は §3 例外条件で別判定するため `--glob` で除外。
# ripgrep の glob は検索 root からの絶対 path に対して評価されるため、`**/SKILL.md` 形式を使う必要がある。
# (`*/SKILL.md` は false clean を起こす)
set +e
rg -n --regexp "$recursion_pattern" .claude/skills \
  --glob '**/SKILL.md' \
  --glob '!**/dev-suite/SKILL.md' \
  --glob '!**/quality-suite/SKILL.md' \
  --glob '!**/review-suite/SKILL.md' \
  --glob '!**/security-suite/SKILL.md' \
  --glob '!**/release-suite/SKILL.md' \
  --glob '!**/skill-lint/SKILL.md'
rg_rec_rc=$?
set -e
case "$rg_rec_rc" in
  0)
    echo "ERROR skill-lint: specialty skill 内で recursion pattern を検出" >&2
    exit 1
    ;;
  1) ;;
  *)
    echo "ERROR skill-lint: rg failed while checking RECURSION_PATTERNS (exit $rg_rec_rc)" >&2
    exit 1
    ;;
esac
```

判定 (レジストリ §3 に準拠):

- **specialty skill** (Suite 5 件以外、skill-lint 本体除く) に `RECURSION_PATTERNS` の pattern が出現 → BLOCK
- **Suite skill** (`dev-suite` / `quality-suite` / `review-suite` / `security-suite` / `release-suite`) は別判定:
  - 「Main Agent への指示」「Main Agent が呼ぶ」等の責務境界明記がある → PASS
  - DRY_RUN モードで実 skill / agent を起動しないこと → PASS
  - Codex chain が逐次実行 + 採否判定明記 → PASS
  - いずれか不在 → WARN

### 7. catalog 同期 (任意)

```bash
rg --files .claude | rg 'skills.*catalog|catalog.*skills|skills\.catalog\.json'
```

確認項目: catalog name と SKILL.md name 一致、owner suite、allowed-tools、description、deprecation/alias、inventory/routing reference との整合。

## 出力 contract

```markdown
## Skill Lint Result
Verdict: PASS|WARN|BLOCK

## Frontmatter Violations
| severity | file | field | issue | fix |
|---|---|---|---|---|

## Naming / Catalog Drift
| severity | skill | source | issue | fix |
|---|---|---|---|---|

## Banned Terms Registry Violations
| severity | file:line | category | matched_term | fix |
|---|---|---|---|---|

## Recursion Policy Violations
| severity | file:line | suite_or_specialty | matched_pattern | fix |
|---|---|---|---|---|
```

## 失敗時の挙動

- catalog が存在しない → WARN。SKILL.md frontmatter lint は継続
- レジストリ §1.1 禁止語残存 → BLOCK
- レジストリ §1.2 raw secret pattern hit → CRITICAL
- specialty skill 内 `Skill(...)` / `Agent(...)` → BLOCK
- Suite skill 内 `Skill(...)` / `Agent(...)` で責務境界明記なし → WARN
- description 140 chars 超 → BLOCK
- allowed-tools 過剰 (監査 skill に `Edit`/`Write`) → BLOCK
- 必須 trace 用語不在 → WARN
- レジストリ自身が変更されている (`.claude/reference/skill-lint-banned-terms.md`) → 四半期レビューでの審査対象として記録

## TaskManagedAI 不変条件 trace

- `.claude/reference/skill-lint-banned-terms.md` を禁止語の単一正本にする
- Phase 0 mapping §2.5 / §3.4 の custom / new skill 方針
- specialty skill での Skill/Agent 再帰起動禁止
- Suite skill は Main Agent orchestration 指示として明記
- Sprint Pack ID / ADR / Hard Gate / Quality KPI / AgentRun / ContextSnapshot / `payload_data_class` / `allowed_data_class` / Gateway 区別 / Tenant boundary を必須 trace 用語として確認
