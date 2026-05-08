---
name: supply-chain-audit
description: "TaskManagedAI の SBOM/依存/Docker/GitHub App/CI supply chain を監査する。Triggers: supply chain, ADR-00011"
when_to_use: |
  pnpm-lock.yaml、uv.lock、Dockerfile、docker-compose、GitHub Actions、GitHub App permission、private mirror、SBOM を監査する時。
  security-suite や release 前確認で使う。別 Skill / Agent は起動しない。
  トリガーフレーズ: 'supply chain', 'SBOM', 'dependency audit', 'ADR-00011'
argument-hint: "[--scope=current-branch|staged|all|specified-files] [--files=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# supply-chain-audit — SBOM / dependency / Docker / GitHub App 監査

## 目的

TaskManagedAI の dependency lockfile、Docker base image、CI workflow、GitHub App permission、private mirror、SBOM 生成状況を監査し、ADR-00011 と supply chain Hard Gate / security trace を残す。

この skill は監査専用であり、依存更新や workflow 変更は行わない。別 Skill / Agent を再帰起動しない。

## 必読資料

- `.claude/rules/core.md` §6
- `.claude/rules/sprint-pack-adr-gate.md` §4
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/hard-gates-and-kpis.md`
- `.claude/rules/instincts.md` §12, §15-§16
- 関連 Sprint Pack / ADR-00011

## 対象

- `package.json`
- `pnpm-lock.yaml`
- `pyproject.toml`
- `uv.lock`
- `Dockerfile`
- `Dockerfile.*`
- `docker-compose*.yml`
- `.github/workflows/**/*`
- GitHub App permission docs / config
- SBOM / dependency audit output
- `docs/adr/*00011*`

## 検査手順

1. 対象ファイルを確定する。

```bash
rg --files package.json pnpm-lock.yaml pyproject.toml uv.lock Dockerfile Dockerfile.* docker-compose*.yml .github/workflows docs/adr 2>/dev/null
git diff --name-only
git diff --cached --name-only
```

2. lockfile と package manager の整合を確認する。

```bash
rg -n '"packageManager"|"dependencies"|"devDependencies"|"overrides"|"resolutions"' package.json 2>/dev/null
rg -n "name =|version =|source =|sdist|wheels|hashes|resolution" pyproject.toml uv.lock 2>/dev/null
```

BLOCK:

- dependency 変更があるのに lockfile が更新されていない
- lockfile だけが更新され、package manifest の意図が不明
- dependency hash / source が不明なまま private mirror を使う
- direct dependency が version range だけで pin / lock に反映されない
- generated code / vendored code が provenance なしで追加される

WARN:

- SBOM 生成手順がない
- dependency overrides / vulnerability exception の ADR trace がない
- major update の migration note がない

3. audit / CVE / outdated の扱いを確認する。

```bash
pnpm audit --json 2>/dev/null || true
uv pip audit 2>/dev/null || true
rg -n "CVE|GHSA|advisory|audit|vulnerab|ignore|allowlist|exception|expires_at" docs .github package.json pyproject.toml 2>/dev/null
```

BLOCK:

- HIGH / CRITICAL 相当の既知脆弱性を例外理由なしに残す
- audit command failure を PASS 扱いする
- allowlist / ignore に expiry / owner / ADR がない
- security exception が Sprint Pack / ADR-00011 に trace しない

WARN:

- audit tool が未整備
- dev dependency の脆弱性影響範囲が未分類
- update automation がない

4. Docker base image と build provenance を確認する。

```bash
rg -n "^FROM|latest|@sha256|USER |root|apt-get|apk add|curl .*\\|.*sh|wget .*\\|.*sh|--no-cache|COPY|ADD|HEALTHCHECK" Dockerfile Dockerfile.* docker-compose*.yml 2>/dev/null
```

BLOCK:

- `latest` tag の base image
- digest pin なしの production / runner base image
- root 実行の runner image
- `curl | sh` / `wget | sh`
- package install が version / cache policy なし
- Docker socket mount / privileged / host network
- secret を Docker build arg / image layer に含める

WARN:

- SBOM / image scan の手順がない
- base image update policy がない
- non-root / read-only filesystem が未検討

5. GitHub Actions / CI secret injection を確認する。

```bash
rg -n "pull_request_target|workflow_run|secrets\\.|GITHUB_TOKEN|permissions:|id-token|contents: write|actions: write|packages: write|curl|bash|checkout|persist-credentials|env:" .github/workflows docs 2>/dev/null
```

BLOCK:

- untrusted PR で secret にアクセスする path
- `pull_request_target` で untrusted code を checkout / execute
- broad `GITHUB_TOKEN` permission
- CI workflow で raw secret を echo / artifact / cache に出す
- AI / runner が `.github/workflows/**` を承認なしに変更できる
- id-token / OIDC の audience / condition が不明

WARN:

- workflow permission が job 単位に最小化されていない
- third-party action が SHA pin されていない
- CI logs redaction / retention が未記録

6. GitHub App permission 変更を確認する。

```bash
rg -n "GitHub App|installation|permission|contents|pull_requests|checks|metadata|issues|workflows|administration|RepoProxy|Draft PR" docs config backend .github 2>/dev/null
```

BLOCK:

- GitHub App permission 拡張に ADR がない
- workflows / administration / secrets 等の high-risk permission を要求
- RepoProxy / SecretBroker を通さず installation token を扱う
- merge / deploy permission を P0 で許可
- permission rollback がない

WARN:

- permission の owner / reason / expiry がない
- Draft PR flow の audit event が不足
- installation token lifecycle が SecretBroker と未接続

7. Tool / MCP / Provider supply chain を確認する。

```bash
rg -n "tool_registry|tool_manifest|MCP|mcp|ProviderAdapter|provider_compliance|subprocessor|last_verified_at|trust_tier|schema_hash|manifest_hash|private mirror|mirror" config backend docs 2>/dev/null
```

BLOCK:

- tool manifest / MCP server が provenance / trust tier なし
- provider subprocessor / doc URL / `last_verified_at` なし
- tool schema が hash / version pin なしで更新される
- private mirror が integrity / auth / fallback policy なし

WARN:

- provider docs の確認日が古い
- tool registry review owner がない
- SBOM に tool / model / provider components が含まれない

## 出力 contract

Markdown で返す。

```markdown
## Supply Chain Audit Result
Verdict: PASS|WARN|BLOCK
Scope: current-branch|staged|all|specified-files

## Findings
| severity | file:line | category | issue | required_fix | trace |
|---|---|---|---|---|---|

## ADR-00011 Trace
| change | adr_reference | verdict | note |
|---|---|---|---|

## Dependency / Image Summary
| artifact | pinning | audit_status | verdict |
|---|---|---|---|

## GitHub Permission Summary
| permission | current | expected_p0 | verdict |
|---|---|---|---|
```

category は `dependency`, `sbom`, `docker`, `ci`, `github-app`, `tool-mcp`, `provider`, `private-mirror`, `adr-trace` のいずれかを使う。

## 失敗時の挙動

- audit command が未導入なら WARN。dependency / lockfile 変更と同時なら BLOCK 寄りに判定する。
- network が使えず audit が実行できない場合は、静的検査結果と未確認事項を分ける。
- HIGH / CRITICAL 脆弱性、unpinned production base、workflow secret injection、GitHub App permission 拡張 ADR 不在は BLOCK。
- third-party action / Docker image の digest pin 不足は WARN。runner / CI secret を扱う場合は BLOCK。
- secret 値らしきものは再出力しない。

## TaskManagedAI 不変条件 trace

- ADR-00011 supply chain trace
- ADR Gate Criteria 11: GitHub App permission、MCP / tool 権限、Provider 追加 / 切替
- AC-HARD-02 secret canary / CI secret injection 防止
- AC-HARD-05 forbidden path / workflow path protection
- AC-HARD-06 dangerous command / build script protection
- AC-HARD-07 prompt injection / tool poisoning 抵抗
- Provider Compliance Matrix `last_verified_at` / subprocessor trace
- Tool manifest / ContextSnapshot `tool_manifest` reproducibility

