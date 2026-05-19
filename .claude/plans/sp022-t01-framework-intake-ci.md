# SP022-T01: Framework Intake CI 機械化

最終更新: 2026-05-19 (codex-plan-review R1 14 + R2 6 + R3 2 = 累計 22 findings 全件 adopt 反映済、Readiness Gate READY)

## 1. 目的 (Goal)

SP-022 must_ship の最初 task。**ADR-00020 §1 全 8 verify item を CI で機械検査** する `scripts/ci/check_framework_intake.sh` を完成し、対応 tests + citation enforcement + `.github/workflows/ci-smoke.yml` への step 統合を実装する。

新 dependency 追加時の framework intake checklist (license / attribution / no embed / persistence / external network / telemetry / secret canary / tenant boundary 全 8 verify) が CI で自動 reject されることを保証する。

## 2. 背景 (Background)

- **ADR-00020 (Framework Intake Checklist)** は 2026-05-19 SP022-T00 で accepted promotion 完了 (PR #69 merged at 62f8e69)。SP022-T01 着手 trigger。
- ADR-00020 §2 で script skeleton は提示済 (5 violation type 部分実装: license / telemetry_import / persistence / external_network、残 3 type は未実装)。本 task で完成。
- `docs/citations/framework_pattern_candidates.md` で 10 framework 候補の citation ledger は確立済 (LangGraph / CrewAI / AutoGen / Semantic Kernel / Dapr Agents / Dify / Flowise / Letta / OpenHands / TaskingAI)。本 task で **CI で機械検査** を追加。
- AC-HARD-02 (secret_canary_no_leak) / AC-HARD-03 (tenant_isolation_negative_pass) 既存 fixture は SP-022 で **regression-only verify** 範囲のため、本 task の verify item #7 (secret canary) / #8 (tenant boundary) は **既存 canary / boundary 仕組みへの reference verify のみ**、新 fixture 追加は不要。
- 既存 CI workflow は `.github/workflows/ci-smoke.yml` の `backend-quality` job に集約。本 task の framework intake check step も同 job に追加。

## 3. Scope (実装範囲)

### 3.1 must_ship (本 PR 内)

| # | 対象 | 種別 |
|---|---|---|
| 1 | `scripts/ci/check_framework_intake.sh` (NEW) | 新規 CI script、8 verify item 全件実装 |
| 2 | `tests/scripts/test_check_framework_intake.sh` (NEW、Bash test runner) | positive (deny) + negative (pass) fixture 全 8 type |
| 3 | `tests/citations/__init__.py` + `tests/citations/test_citation_completeness.py` (NEW) | 新 dependency に対応する citation 存在を pytest で verify |
| 4 | `.github/workflows/ci-smoke.yml` (MODIFY) | `backend-quality` job に "Framework intake check" step 追加 |
| 5 | `docs/citations/README.md` (NEW、不在の場合のみ) | citation 構造の正本 docs (既存 `framework_pattern_candidates.md` への index) |
| 6 | `docs/sprints/SP-022_framework_intake_hardening.md` (MODIFY、SP022-T01 完了記録) | `## Review` 章に SP022-T01 完了記録 (CI step 追加 + 8 verify trace matrix) |

### 3.2 対象外 (本 task では実装しない)

- **SP022-T05** AC-HARD multi-agent fixture: 本 task scope 外 (post-P0.1 carry-over)。
- **SP022-T02-T09** その他 SP-022 must_ship task: 別 PR で実装。
- **新 framework dependency の実追加**: 本 task は CI gate 実装のみ、新 dependency 採用判定は別 ADR / PR。
- **既存 dependency への retrofit verify**: 既 `pyproject.toml` / `frontend/package.json` への retrofit check は本 task で行わない (ADR-00020 §5 「既存 dependency に retrofit verify は SP-022 で実施」は SP-022 全体 scope、T01 では新 dependency PR への gate のみ確立)。

## 4. 8 Verify Item の機械化方針 (ADR-00020 §1) [R1 F-001/F-002/F-003/F-004 adopt]

### 4.0 CI event 別 mode 分離設計 (R1 F-001 + F-004 adopt)

本 script は **CI event** で 2 mode 分離動作 (DoD 空振り防止):

| mode | trigger | scope | 動作 |
|---|---|---|---|
| `diff-gate` | `pull_request` event (`GITHUB_EVENT_NAME=pull_request`) AND `pyproject.toml` / `uv.lock` / `frontend/package.json` / `frontend/pnpm-lock.yaml` のいずれかが changed | 新規 / 変更された direct dependency に対する 8 verify 全件 | dependency diff が空なら early exit 0 (skip)、非空なら 8 verify 実行 |
| `baseline-scan` | `push` to `main` event (`GITHUB_EVENT_NAME=push` AND `GITHUB_REF_NAME=main`) | **repository 全体に対する #3-#8 regression scan** (license/attribution は dependency 単位なので baseline scan で常時 PASS 期待) | dependency diff 有無に関係なく実行、既存 code embed / telemetry / network / persistence violation を検出 |

判定優先順:
- `GITHUB_EVENT_NAME=pull_request` → `diff-gate` mode
- `GITHUB_EVENT_NAME=push` AND `GITHUB_REF_NAME=main` → `baseline-scan` mode
- それ以外 (local 実行 / 他 ref への push) → script 引数で `--mode={diff-gate,baseline-scan}` 指定、default は `diff-gate` で `origin/main...HEAD` 比較。引数なし + 環境変数なしは `baseline-scan` fallback (regression 安全側)

mode の決定は script 冒頭で `MODE=$(determine_mode)` で固定、各 check 関数は `$MODE` を参照して #1/#2 (dependency 単位、baseline-scan では skip) と #3-#8 (どちらの mode でも実行) を分岐。

### 4.1 changed dependency 抽出 (diff-gate mode、R1 F-005 + R2 F-003 adopt)

direct dependency のみ対象。推移依存 (transitive) は scope 外。

| source | 抽出対象 | 抽出方法 |
|---|---|---|
| `pyproject.toml` | `[project.dependencies]` リスト + `[project.optional-dependencies.*]` (全 group) **+ `[dependency-groups].*` (全 group、R2 F-003 adopt: 本 repo は `[dependency-groups].dev` を採用、uv の direct dev dependency)** | Python `tomllib` (3.11+ 標準) で parse、package name canonicalize (PEP 503: lowercase + `[-_.]+` → `-`) |
| `frontend/package.json` | `dependencies` + `devDependencies` | Python `json` 標準で parse、package name は npm 標準 (lowercase、**scoped name `@scope/name` は `@scope/name` のまま保持**、canonical name) |
| `uv.lock` / `frontend/pnpm-lock.yaml` | 差分検知 trigger としてのみ、抽出対象外 | `git diff --name-only` で変更検知のみ |

`changed_deps` = `(HEAD time の direct deps set) - (origin/main time の direct deps set)`。リネーム / 削除は本 task では対象外 (新規 added のみ check)。

**`[dependency-groups]` 全 group 対象化の根拠 (R2 F-003 adopt)**: 本 repo の `pyproject.toml:41-48` で `dev = ["mypy", "pytest", ...]` が `[dependency-groups].dev` に置かれており、CI `uv sync --locked` で install される direct dependency になる。framework / SDK を `[dependency-groups].dev` に追加する PR で license / attribution が bypass されないよう、全 group を対象に含める。group 除外の allowlist は本 task では設定しない (全 group 対象が安全側)。

### 4.2 8 verify item の詳細

| # | verify | 機械検査方針 (本 task で実装) | violation reason_code |
|---|---|---|---|
| 1 | License | **diff-gate mode のみ実行**。`changed_deps` の各 dependency に対して **`uv run python -m pip show <pkg>` (R2 F-002 adopt: `.venv` 内 dependency を確実に見る)** で `License:` field を取得、空 / 不明なら **`uv run python -c 'import importlib.metadata as m; md=m.metadata("<pkg>"); print((md.get("License-Expression") or md.get("License") or "").strip())'`** fallback、それでも空なら **violation** (license 不明)。取得 license を LICENSE_DENYLIST (`polyform-shield` / `polyform-perimeter` / `polyform-noncommercial` / `rus license` / `sspl` / `commons clause`) に case-insensitive substring match。**network 不要** (`pip show` は project venv site-packages cache から取得、CI で `uv sync --locked` 直後に実行)。frontend pkg は license verify 対象外 (本 task scope、post-T01 で SPDX 拡張) と明文化。 (R1 F-002 + R2 F-002 adopt) | `framework_intake_violation_license` |
| 2 | Attribution | **diff-gate mode のみ実行**。`changed_deps` の各 dependency に対して、`docs/citations/dependency_to_framework_map.json` (本 task で新規作成、後述 §4.3) で dependency → framework 名を **exact canonical name** 解決 (fuzzy match 禁止、R1 F-006 adopt)。`langchain-core` と `langchain` は **別 framework** として扱う。解決された framework 名が `docs/citations/framework_pattern_candidates.md` の表内 (`| **<framework>** |` pattern) に **exact match** で存在しない場合 **violation**。map に該当 dependency が無い場合は **violation** (citation 未登録扱い)。 | `framework_intake_violation_attribution` |
| 3 | No code embed | **両 mode で実行**。ADR-00020 §7 denylist 名 + frontend npm 名 (langgraph / crewai / autogen / letta / dapr / dify / flowise / openhands / taskingai + npm scoped `@langchain/langgraph` / `@langchain/core` / `@langchain/langgraph-sdk` 等) を以下 pattern で grep (R1 F-007 + R2 F-006 adopt): Python 側 `backend/app/` 配下で `^[[:space:]]*(import|from)[[:space:]]+(<denylist>)([[:space:]]\|\.\|$)`、TypeScript/JavaScript 側 **`frontend/app/` / `frontend/components/` / `frontend/lib/` / `frontend/middleware.ts` / `frontend/next.config.ts`** (R2 F-006 adopt: 実 Next.js App Router 構成、`frontend/src/` は本 repo に存在しないため除外) 配下で `from[[:space:]]+['\"](<denylist>)['\"]` または `require\(['\"](<denylist>)['\"]\)` または `import\(['\"](<denylist>)['\"]\)` (dynamic import)。**vendoring 検出 (source code copy/paste) は本 task scope 外**、post-T01 で追加。`tests/` / `frontend/__tests__/` / `frontend/tests/` / `frontend/node_modules/` は scan 除外。 | `framework_intake_violation_code_embed` |
| 4 | Persistence | **両 mode で実行**。`backend/app/{services,adapters,db}/` (但し `backend/app/db/migrations/` 除外) で以下 pattern grep (R1 F-009 adopt): `^[[:space:]]*(import[[:space:]]+sqlite3\|from[[:space:]]+sqlite3[[:space:]]+import)` + `psycopg(2)?\.connect\(` 直接呼出 (TaskManagedAI 既存 sqlalchemy / asyncpg session boundary を経由しない直接 connect)。**frontend 側 Node DB client (Prisma/Drizzle/Knex) は scope 外**、TaskManagedAI frontend は backend API 経由で persistence access する設計のため本 task では verify 対象外と明文化、post-T01 で frontend persistence inventory 追加判断。`tests/` 除外。 | `framework_intake_violation_persistence` |
| 5 | External network | **両 mode で実行**。NETWORK_DENYLIST (`api.honcho.dev` / `api.mem0.ai` / `api.supermemory.ai` / `sentry.io` / `api.datadoghq.com` / `api.newrelic.com`) を `backend/app/` / **`frontend/app/` / `frontend/components/` / `frontend/lib/` / `frontend/middleware.ts` / `frontend/next.config.ts`** (R2 F-006 adopt 実 frontend layout) / `config/` で URL literal grep (`https?://[^\"'\\s]*(<denylist>)`)。**unknown host fail-closed (allowlist contract) は本 task scope 外**、post-task SP-022.X で network egress allowlist 追加判断 (R1 F-008 adopt)。ADR-00020 §1 #5 で要求される水準は denylist literal で当面足りる scope と明文化。`tests/` / `frontend/__tests__/` / `frontend/tests/` / `frontend/node_modules/` 除外。 | `framework_intake_violation_external_network` |
| 6 | Telemetry off | **両 mode で実行**。TELEMETRY_DENYLIST (`sentry_sdk` / `datadog` / `newrelic` / `honcho`) を `backend/app/` で `^[[:space:]]*(import[[:space:]]+(<denylist>)\|from[[:space:]]+(<denylist>)[[:space:]]+import)` grep、**`frontend/app/` / `frontend/components/` / `frontend/lib/` / `frontend/middleware.ts` / `frontend/next.config.ts`** (R2 F-006 adopt) で `from[[:space:]]+['\"](<denylist>)['\"]` / `require\(['\"](<denylist>)['\"]\)` grep。`tests/` / `frontend/__tests__/` / `frontend/tests/` / `frontend/node_modules/` 除外。 | `framework_intake_violation_telemetry` |
| 7 | Secret canary | **両 mode で実行 (R2 F-004 + F-005 adopt: rg 依存撤回、Python scanner 経由 + 実 path 修正)**。Python scanner で **`backend/app/services/providers/preflight.py`** (R2 F-005 adopt: 実パス、旧計画の `provider_compliance/preflight.py` は誤り) 内に `secret_canary` または `provider_request_preflight` を含む行が **1 行以上** hit、+ `tests/security/test_provider_preflight_canary.py` および `tests/security/test_provider_request_preflight.py` の **両方が存在**、+ `eval/security/secret_canary/` ディレクトリが存在。1 条件でも欠落 = violation exit 1 で reason_code `framework_intake_violation_secret_canary` (R1 F-003 + R2 F-004/F-005 adopt、`rg -l` 案撤回、Python `pathlib` + `re` で実装、ripgrep 依存なし)。 | `framework_intake_violation_secret_canary` |
| 8 | Tenant/project boundary | **両 mode で実行 (R2 F-004 + F-005 adopt: rg 依存撤回、Python scanner 経由)**。Python scanner で `tests/db/` / `tests/repositories/` / `eval/security/tenant_isolation/` ディレクトリ配下のいずれかの file 内に `AC-HARD-03` または `tenant_isolation` または `cross_tenant` を含む行が **1 ファイル以上** hit。0 件 = violation exit 1 で reason_code `framework_intake_violation_tenant_boundary` (R1 F-003 + R2 F-004 adopt、`rg -l` 案撤回、Python scanner 経由、ripgrep 依存なし)。 | `framework_intake_violation_tenant_boundary` |

### 4.3 `docs/citations/dependency_to_framework_map.json` (新規、R1 F-006 + R2 F-006 adopt)

framework name と dependency (PyPI / npm package name、**npm は scoped name `@scope/name` をそのまま canonical** = R2 F-006 adopt) の対応 allowlist。本 task で初期 entries (10 framework × Python/JS) を埋める:

```json
{
  "schema_version": 1,
  "entries": [
    {"dependency_name": "langgraph", "ecosystem": "pypi", "framework_canonical": "LangGraph"},
    {"dependency_name": "@langchain/langgraph", "ecosystem": "npm", "framework_canonical": "LangGraph"},
    {"dependency_name": "@langchain/langgraph-sdk", "ecosystem": "npm", "framework_canonical": "LangGraph"},
    {"dependency_name": "crewai", "ecosystem": "pypi", "framework_canonical": "CrewAI"},
    {"dependency_name": "autogen", "ecosystem": "pypi", "framework_canonical": "AutoGen"},
    {"dependency_name": "pyautogen", "ecosystem": "pypi", "framework_canonical": "AutoGen"},
    {"dependency_name": "letta", "ecosystem": "pypi", "framework_canonical": "Letta"},
    {"dependency_name": "dapr", "ecosystem": "pypi", "framework_canonical": "Dapr Agents"},
    {"dependency_name": "dify-client", "ecosystem": "pypi", "framework_canonical": "Dify"},
    {"dependency_name": "openhands-ai", "ecosystem": "pypi", "framework_canonical": "OpenHands"},
    {"dependency_name": "taskingai", "ecosystem": "pypi", "framework_canonical": "TaskingAI"}
  ]
}
```

新 dependency 追加時に本 file に entry 追加が必要。entry なし → `framework_intake_violation_attribution` (citation 未登録)。

**npm scoped name の扱い (R2 F-006 adopt)**: LangGraph.js の canonical npm package は `@langchain/langgraph` (https://www.npmjs.com/package/@langchain/langgraph)。denylist + map の `dependency_name` field では `@langchain/langgraph` の **fully qualified scoped name** を保持、unscoped `langgraph` と区別。code embed scanner の denylist は両方含める (Python PyPI 側は `langgraph` 単独、frontend 側は scoped name)。

### 4.4 script 実行 environment (R1 F-012 + R2 F-001/F-002/F-004 adopt)

backend-quality job (`.github/workflows/ci-smoke.yml`) 内 `Install backend dependencies` step (uv sync --locked) の後で実行。

- 必要 tool: `bash` / `git` / **`uv run python3` (R2 F-002 adopt: project venv 経由)** / `jq` / **`pip` (uv 経由)**。`uv` (uv sync 後の venv で `pip` が利用可能) と Python 3.12 が CI runner に確実に存在 (公式 actions/setup-uv@v3 経由)。
- **Node/pnpm 不要**: package.json / pnpm-lock.yaml の解析は Python `json` / 静的 `git diff` で実施、Node runtime / pnpm CLI に依存しない。
- 既 `bash` (default `ubuntu-latest` runner) で実行可、新 dev dependency 追加なし。`pip-licenses` 等は導入不要 (R1 F-002 adopt、`pip show` 標準で license field 取得)。
- **`rg` (ripgrep) 依存撤回 (R2 F-004 adopt)**: ubuntu-latest runner に preinstalled ではないため、Python scanner (pathlib + re module) で実装する設計に変更。verify item #7/#8 の reference verify も Python scanner 経由。
- **`actions/checkout@v4` は `fetch-depth: 0` 必須 (R2 F-001 adopt)**: PR shallow checkout で `origin/main` が解決できない事故防止。workflow 側で `with: fetch-depth: 0` を明示。

### 4.5 script 実行 trigger (CI integration)

- **pull_request event** (`backend-quality` job): mode=`diff-gate`、`origin/main...HEAD` で dependency 変更検知 → 変更なし `exit 0 (SKIP)`、変更あり → 8 verify 全件実行
- **push to main**: mode=`baseline-scan`、dependency 変更検知無関係に #3-#8 を repo 全体 scan (regression 検出)。#1/#2 は baseline では既 PASS 期待 (既存 main で reject 済 dependency は存在しないはず)、skip。
- **local 実行 / 他 ref push**: `--mode={diff-gate,baseline-scan}` 引数で明示指定、default は `baseline-scan` fallback (regression 安全側)

### 4.2 script 出力 contract

- exit code 0 = 全 verify PASS or dependency 変更なし
- exit code 1 = いずれかの verify FAIL (violation 詳細 + reason_code を stdout に列挙)
- exit code 2 = script 内部 error (verify item 自体が実行不能、例: pyproject.toml parse 失敗)
- stdout 形式: 各 violation を `VIOLATION reason_code=<code> evidence=<file:line> framework=<name>` の 1 行で列挙、最後に `framework_intake_check: FAIL (N violations)` または `framework_intake_check: PASS`

## 5. 実装詳細

### 5.1 `scripts/ci/check_framework_intake.sh` 構造 (R1 F-001/F-004/F-013 adopt)

```bash
#!/usr/bin/env bash
set -euo pipefail

# ---- 0. mode determination (CI event 別) ----
determine_mode() {
    # 引数 --mode 優先
    for arg in "$@"; do
        case "$arg" in
            --mode=diff-gate) echo "diff-gate"; return ;;
            --mode=baseline-scan) echo "baseline-scan"; return ;;
        esac
    done
    # CI 環境変数判定
    if [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ]; then
        echo "diff-gate"
    elif [ "${GITHUB_EVENT_NAME:-}" = "push" ] && [ "${GITHUB_REF_NAME:-}" = "main" ]; then
        echo "baseline-scan"
    else
        # local 実行 / 他 ref push: 安全側 baseline-scan
        echo "baseline-scan"
    fi
}
MODE=$(determine_mode "$@")

# ---- 1. emergency disable flag (admin/repository-controlled only、R1 F-013 adopt) ----
# 通常 PR author は本 env を設定不可、CI repository secret / admin-controlled environment 変数として
# のみ設定可能 (.github/workflows/ci-smoke.yml で envs.FRAMEWORK_INTAKE_CHECK_DISABLED を
# secret/repo variable 参照する設計を docs に明記、PR diff から author が任意設定不可)
if [ "${FRAMEWORK_INTAKE_CHECK_DISABLED:-}" = "1" ]; then
    echo "framework_intake_check: SKIP (emergency disable flag set, mode=$MODE)" >&2
    echo "audit_marker: framework_intake_check_disabled_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
    exit 0
fi

# ---- 2. base ref 解決 (R2 F-001 adopt、shallow checkout 防止) ----
# fetch-depth: 0 でない場合の早期検出 = exit 2 (SKIP と区別)
if ! git rev-parse --verify origin/main >/dev/null 2>&1; then
    echo "framework_intake_check: ERROR origin/main not resolvable (shallow checkout?)" >&2
    echo "  hint: actions/checkout@v4 with fetch-depth: 0 required" >&2
    exit 2
fi

# ---- 3. diff-gate mode early exit (R1 F-001 + R2 F-001 adopt) ----
if [ "$MODE" = "diff-gate" ]; then
    # base 解決失敗 (exit code 非 0) は exit 2 (SKIP と区別)
    if ! DEPS_CHANGED=$(git diff --name-only origin/main...HEAD -- \
        pyproject.toml uv.lock frontend/package.json frontend/pnpm-lock.yaml 2>&1); then
        echo "framework_intake_check: ERROR git diff failed (base resolve error): $DEPS_CHANGED" >&2
        exit 2
    fi
    if [ -z "$DEPS_CHANGED" ]; then
        echo "framework_intake_check: SKIP (mode=diff-gate, no dependency changes)"
        exit 0
    fi
fi

# ---- 3. violation collector ----
declare -a VIOLATIONS=()

# ---- 4. helper: extract changed direct deps (diff-gate mode only) ----
extract_changed_deps_pypi() { python3 scripts/ci/_extract_changed_deps.py --ecosystem=pypi; }
extract_changed_deps_npm() { python3 scripts/ci/_extract_changed_deps.py --ecosystem=npm; }

# ---- 5. verify item #1: License (diff-gate mode only、R2 F-002 + R3 F-001 adopt) ----
# R3 F-001 adopt: pip show / importlib.metadata 失敗を `|| true` で明示的に非致命化、
# set -euo pipefail 下でも errexit しない。全失敗ケースを license_field_empty として
# 必ず collector に積む。fake repo test では未インストール pkg を扱うが、本制御で
# script exit せず期待 violation が出力される。
check_license() {
    [ "$MODE" = "baseline-scan" ] && return 0
    local pkg license
    while IFS= read -r pkg; do
        [ -z "$pkg" ] && continue
        # R3 F-001 adopt: || true で metadata 取得失敗を非致命化
        license=$(uv run --no-sync python -m pip show "$pkg" 2>/dev/null | awk -F': ' '/^License: /{print $2}' 2>/dev/null || true)
        if [ -z "$license" ]; then
            license=$(uv run --no-sync python -c "import importlib.metadata as m; md=m.metadata('$pkg'); print((md.get('License-Expression') or md.get('License') or '').strip())" 2>/dev/null || true)
        fi
        if [ -z "$license" ]; then
            # 未インストール / license field 空 / metadata 失敗 すべて violation
            VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_license evidence=$pkg framework=$pkg detail=license_field_empty_or_unresolved")
            continue
        fi
        for denied in "polyform-shield" "polyform-perimeter" "polyform-noncommercial" "rus license" "sspl" "commons clause"; do
            if echo "$license" | grep -iq "$denied"; then
                VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_license evidence=$pkg framework=$pkg detail=$denied")
            fi
        done
    done < <(extract_changed_deps_pypi || true)   # extract 失敗時も非致命
}

# ---- 6. verify item #2: Attribution (diff-gate mode only) ----
check_attribution() {
    [ "$MODE" = "baseline-scan" ] && return 0
    local map_file="docs/citations/dependency_to_framework_map.json"
    [ ! -f "$map_file" ] && { VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_attribution evidence=$map_file detail=dep_to_framework_map_missing"); return 0; }
    local pkg ecosystem framework_canonical
    for ecosystem in pypi npm; do
        while IFS= read -r pkg; do
            [ -z "$pkg" ] && continue
            framework_canonical=$(jq -r --arg p "$pkg" --arg e "$ecosystem" '.entries[] | select(.dependency_name==$p and .ecosystem==$e) | .framework_canonical' "$map_file")
            if [ -z "$framework_canonical" ]; then
                VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_attribution evidence=$pkg framework=$pkg detail=map_entry_missing_ecosystem=$ecosystem")
                continue
            fi
            if ! grep -qE "\| \*\*${framework_canonical}\*\* \|" docs/citations/framework_pattern_candidates.md; then
                VIOLATIONS+=("VIOLATION reason_code=framework_intake_violation_attribution evidence=$pkg framework=$framework_canonical detail=citation_table_missing")
            fi
        done < <([ "$ecosystem" = "pypi" ] && extract_changed_deps_pypi || extract_changed_deps_npm)
    done
}

# ---- 7. verify item #3-#8 (両 mode で実行、R2 F-004/F-005/F-006 adopt: Python scanner 経由) ----
# 全 verify item #3-#8 は Python scanner (scripts/ci/_intake_scanner.py) に委譲、ripgrep 依存なし
# frontend 対象 path は frontend/app, frontend/components, frontend/lib, frontend/middleware.ts, frontend/next.config.ts
# scan 除外 path は tests/, frontend/__tests__/, frontend/tests/, frontend/node_modules/, backend/app/db/migrations/
run_python_scan() {
    local rule_name="$1"   # no_code_embed / persistence / external_network / telemetry / secret_canary / tenant_boundary
    local output
    if output=$(uv run python -m scripts.ci._intake_scanner --rule="$rule_name" --mode="$MODE" 2>&1); then
        # exit 0: violation なし
        return 0
    fi
    # exit 1: violation あり、output を VIOLATIONS に追加
    while IFS= read -r line; do
        [ -n "$line" ] && VIOLATIONS+=("$line")
    done <<< "$output"
}

check_no_code_embed() { run_python_scan no_code_embed; }
check_persistence() { run_python_scan persistence; }
check_external_network() { run_python_scan external_network; }
check_telemetry() { run_python_scan telemetry; }
check_secret_canary() { run_python_scan secret_canary; }
check_tenant_boundary() { run_python_scan tenant_boundary; }

# ---- 8. run all + report ----
check_license
check_attribution
check_no_code_embed
check_persistence
check_external_network
check_telemetry
check_secret_canary
check_tenant_boundary

if [ ${#VIOLATIONS[@]} -gt 0 ]; then
    printf '%s\n' "${VIOLATIONS[@]}"
    echo "framework_intake_check: FAIL (${#VIOLATIONS[@]} violations, mode=$MODE)"
    exit 1
fi
echo "framework_intake_check: PASS (mode=$MODE)"
exit 0
```

補助 Python script `scripts/ci/_extract_changed_deps.py` (R1 F-005 + F-012 + R2 F-003 adopt、Python 標準 tomllib + json で実装、Node/pnpm 不要):

```python
"""Extract changed direct dependencies from pyproject.toml or frontend/package.json (origin/main...HEAD).

R2 F-003 adopt: [dependency-groups].* (全 group) も対象に含める。
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, tomllib
from pathlib import Path

def normalize_pypi(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower()).strip("-")

def load_pyproject_at(ref: str | None) -> set[str]:
    if ref is None:
        path = Path("pyproject.toml")
        if not path.exists(): return set()
        data = tomllib.loads(path.read_text())
    else:
        try:
            content = subprocess.check_output(["git", "show", f"{ref}:pyproject.toml"], text=True)
        except subprocess.CalledProcessError:
            return set()
        try:
            data = tomllib.loads(content)
        except tomllib.TOMLDecodeError as e:
            print(f"ERROR: pyproject.toml parse failed at ref={ref}: {e}", file=sys.stderr)
            sys.exit(2)
    deps: set[str] = set()
    project = data.get("project", {})
    # [project.dependencies]
    for dep in project.get("dependencies", []):
        m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", dep)
        if m: deps.add(normalize_pypi(m.group(1)))
    # [project.optional-dependencies.*]
    for group, items in (project.get("optional-dependencies") or {}).items():
        for dep in items:
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", dep)
            if m: deps.add(normalize_pypi(m.group(1)))
    # R2 F-003 adopt: [dependency-groups].* (全 group)
    for group, items in (data.get("dependency-groups") or {}).items():
        for dep in items:
            if not isinstance(dep, str): continue  # include-group 形式は対象外
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)", dep)
            if m: deps.add(normalize_pypi(m.group(1)))
    return deps

def load_package_json_at(ref: str | None) -> set[str]:
    if ref is None:
        path = Path("frontend/package.json")
        if not path.exists(): return set()
        try: data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"ERROR: frontend/package.json parse failed: {e}", file=sys.stderr)
            sys.exit(2)
    else:
        try:
            content = subprocess.check_output(["git", "show", f"{ref}:frontend/package.json"], text=True)
        except subprocess.CalledProcessError:
            return set()
        try: data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"ERROR: frontend/package.json parse failed at ref={ref}: {e}", file=sys.stderr)
            sys.exit(2)
    deps: set[str] = set()
    # R2 F-006 adopt: scoped name は @scope/name のまま保持 (canonical)
    deps.update((data.get("dependencies") or {}).keys())
    deps.update((data.get("devDependencies") or {}).keys())
    return deps

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ecosystem", choices=["pypi", "npm"], required=True)
    p.add_argument("--base", default="origin/main", help="base ref for diff (default origin/main)")
    args = p.parse_args()
    loader = load_pyproject_at if args.ecosystem == "pypi" else load_package_json_at
    base = loader(args.base)
    head = loader(None)
    for added in sorted(head - base):
        print(added)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

補助 Python script `scripts/ci/_intake_scanner.py` (新規、R2 F-004 + F-005 + F-006 adopt、verify item #3-#8 を Python で実装、ripgrep 依存なし):

```python
"""Framework intake scanner for verify items #3-#8.

Reads target directories, applies pattern matching, prints VIOLATION lines on stdout.
Exit 0: no violation. Exit 1: violations found.

R2 F-004 adopt: ripgrep 依存撤回、pathlib + re module で実装。
R2 F-005 adopt: 実 preflight path は backend/app/services/providers/preflight.py。
R2 F-006 adopt: frontend 対象 path は frontend/app/components/lib/middleware.ts/next.config.ts。
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

PY_DENYLIST_FRAMEWORKS = ["langgraph", "crewai", "autogen", "pyautogen", "letta", "dapr", "dify_client", "openhands", "taskingai"]
NPM_DENYLIST_FRAMEWORKS = ["langgraph", "@langchain/langgraph", "@langchain/langgraph-sdk", "@langchain/core", "crewai", "autogen", "letta", "dapr", "dify", "flowise", "openhands", "taskingai"]
NETWORK_DENYLIST = ["api.honcho.dev", "api.mem0.ai", "api.supermemory.ai", "sentry.io", "api.datadoghq.com", "api.newrelic.com"]
TELEMETRY_PY = ["sentry_sdk", "datadog", "newrelic", "honcho"]
TELEMETRY_NPM = ["@sentry/node", "@sentry/nextjs", "@datadog/browser-logs", "newrelic", "honcho"]

# R2 F-006 adopt: 実 frontend layout
FRONTEND_SCAN_ROOTS = [Path("frontend/app"), Path("frontend/components"), Path("frontend/lib"), Path("frontend/middleware.ts"), Path("frontend/next.config.ts")]
FRONTEND_EXCLUDE = {"__tests__", "tests", "node_modules"}
BACKEND_SCAN_ROOTS = [Path("backend/app")]
BACKEND_EXCLUDE_PATH_PARTS = {"migrations"}  # backend/app/db/migrations 除外

def iter_python_files(roots: list[Path]) -> list[Path]:
    files = []
    for root in roots:
        if not root.exists(): continue
        for p in root.rglob("*.py"):
            if any(part in BACKEND_EXCLUDE_PATH_PARTS for part in p.parts): continue
            files.append(p)
    return files

def iter_frontend_files(roots: list[Path]) -> list[Path]:
    files = []
    for root in roots:
        if not root.exists(): continue
        if root.is_file():
            files.append(root); continue
        for p in root.rglob("*"):
            if not p.is_file(): continue
            if p.suffix not in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"): continue
            if any(part in FRONTEND_EXCLUDE for part in p.parts): continue
            files.append(p)
    return files

def check_no_code_embed() -> list[str]:
    violations: list[str] = []
    # Python side
    py_pattern = re.compile(r"^\s*(import|from)\s+(" + "|".join(re.escape(n) for n in PY_DENYLIST_FRAMEWORKS) + r")(\s|\.|$)", re.MULTILINE)
    for f in iter_python_files(BACKEND_SCAN_ROOTS):
        try: content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for m in py_pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(f"VIOLATION reason_code=framework_intake_violation_code_embed evidence={f}:{line_num} framework={m.group(2)} detail=python_import")
    # Frontend side (scoped + unscoped、R2 F-006 adopt)
    npm_alts = "|".join(re.escape(n) for n in NPM_DENYLIST_FRAMEWORKS)
    npm_pattern = re.compile(r"""(?:from\s+['"]|require\(['"]|import\(['"])(""" + npm_alts + r""")(?:/[^'"]*)?['"]""")
    for f in iter_frontend_files(FRONTEND_SCAN_ROOTS):
        try: content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for m in npm_pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(f"VIOLATION reason_code=framework_intake_violation_code_embed evidence={f}:{line_num} framework={m.group(1)} detail=npm_import")
    return violations

def check_persistence() -> list[str]:
    violations: list[str] = []
    services_roots = [Path("backend/app/services"), Path("backend/app/adapters"), Path("backend/app/db")]
    sqlite_pattern = re.compile(r"^\s*(import\s+sqlite3|from\s+sqlite3\s+import)", re.MULTILINE)
    psycopg_pattern = re.compile(r"psycopg2?\.connect\(")
    for f in iter_python_files(services_roots):
        try: content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for m in sqlite_pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(f"VIOLATION reason_code=framework_intake_violation_persistence evidence={f}:{line_num} framework=sqlite3 detail=direct_import")
        for m in psycopg_pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(f"VIOLATION reason_code=framework_intake_violation_persistence evidence={f}:{line_num} framework=psycopg detail=direct_connect")
    return violations

def check_external_network() -> list[str]:
    violations: list[str] = []
    net_alts = "|".join(re.escape(n) for n in NETWORK_DENYLIST)
    url_pattern = re.compile(r"https?://[^\"'\s]*(" + net_alts + r")")
    targets = iter_python_files(BACKEND_SCAN_ROOTS) + iter_frontend_files(FRONTEND_SCAN_ROOTS)
    config_root = Path("config")
    if config_root.exists():
        for p in config_root.rglob("*"):
            if p.is_file() and p.suffix in (".toml", ".yaml", ".yml", ".json", ".py"):
                targets.append(p)
    for f in targets:
        try: content = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError): continue
        for m in url_pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(f"VIOLATION reason_code=framework_intake_violation_external_network evidence={f}:{line_num} host={m.group(1)} detail=denylisted_endpoint")
    return violations

def check_telemetry() -> list[str]:
    violations: list[str] = []
    # Python
    py_pattern = re.compile(r"^\s*(import|from)\s+(" + "|".join(re.escape(n) for n in TELEMETRY_PY) + r")(\s|\.|$)", re.MULTILINE)
    for f in iter_python_files(BACKEND_SCAN_ROOTS):
        try: content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for m in py_pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(f"VIOLATION reason_code=framework_intake_violation_telemetry evidence={f}:{line_num} framework={m.group(2)} detail=python_import")
    # Frontend
    npm_alts = "|".join(re.escape(n) for n in TELEMETRY_NPM)
    npm_pattern = re.compile(r"""(?:from\s+['"]|require\(['"]|import\(['"])(""" + npm_alts + r""")(?:/[^'"]*)?['"]""")
    for f in iter_frontend_files(FRONTEND_SCAN_ROOTS):
        try: content = f.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for m in npm_pattern.finditer(content):
            line_num = content[:m.start()].count("\n") + 1
            violations.append(f"VIOLATION reason_code=framework_intake_violation_telemetry evidence={f}:{line_num} framework={m.group(1)} detail=npm_import")
    return violations

def check_secret_canary() -> list[str]:
    """R2 F-005 adopt: 実 preflight path + 実 test path 確認."""
    violations: list[str] = []
    # (a) preflight に canary または provider_request_preflight 言及
    preflight = Path("backend/app/services/providers/preflight.py")
    if not preflight.exists():
        violations.append(f"VIOLATION reason_code=framework_intake_violation_secret_canary evidence={preflight} detail=preflight_file_missing")
        return violations
    content = preflight.read_text(encoding="utf-8")
    if "secret_canary" not in content and "provider_request_preflight" not in content:
        violations.append(f"VIOLATION reason_code=framework_intake_violation_secret_canary evidence={preflight} detail=canary_marker_missing")
    # (b) tests/security/ に preflight + canary fixture
    fixture_a = Path("tests/security/test_provider_preflight_canary.py")
    fixture_b = Path("tests/security/test_provider_request_preflight.py")
    if not fixture_a.exists() or not fixture_b.exists():
        violations.append(f"VIOLATION reason_code=framework_intake_violation_secret_canary evidence={fixture_a},{fixture_b} detail=test_fixture_missing")
    # (c) eval/security/secret_canary/
    eval_dir = Path("eval/security/secret_canary")
    if not eval_dir.exists():
        violations.append(f"VIOLATION reason_code=framework_intake_violation_secret_canary evidence={eval_dir} detail=eval_fixture_dir_missing")
    return violations

def check_tenant_boundary() -> list[str]:
    """R2 F-004 adopt: Python scanner で AC-HARD-03 / tenant_isolation 存在確認."""
    violations: list[str] = []
    roots = [Path("tests/db"), Path("tests/repositories"), Path("eval/security/tenant_isolation")]
    pattern = re.compile(r"AC-HARD-03|tenant_isolation|cross_tenant")
    found = False
    for root in roots:
        if not root.exists(): continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix not in (".py", ".json", ".md", ".toml"): continue
            try: content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError: continue
            if pattern.search(content):
                found = True; break
        if found: break
    if not found:
        violations.append(f"VIOLATION reason_code=framework_intake_violation_tenant_boundary evidence={roots} detail=no_ac_hard_03_marker_found")
    return violations

RULES = {
    "no_code_embed": check_no_code_embed,
    "persistence": check_persistence,
    "external_network": check_external_network,
    "telemetry": check_telemetry,
    "secret_canary": check_secret_canary,
    "tenant_boundary": check_tenant_boundary,
}

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--rule", choices=list(RULES.keys()), required=True)
    p.add_argument("--mode", choices=["diff-gate", "baseline-scan"], required=True)
    args = p.parse_args()
    violations = RULES[args.rule]()
    for v in violations:
        print(v)
    return 1 if violations else 0

if __name__ == "__main__":
    sys.exit(main())
```

### 5.2 `tests/scripts/test_check_framework_intake.sh` 構造 (R1 F-010 adopt)

bash test runner (`bats` 等の追加 framework 不採用、pure shell + assert helper)。各 positive test は **fake repo** に bare git origin + main branch + feature branch + baseline files を構築してから script を起動 (R1 F-010 adopt)。

```bash
#!/usr/bin/env bash
set -euo pipefail
TESTS_PASSED=0
TESTS_FAILED=0
REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SCRIPT_UNDER_TEST="$REPO_ROOT/scripts/ci/check_framework_intake.sh"

# ---- 1. fixture builder: fake repo with bare origin + main + feature branch ----
setup_fake_repo() {
    local fixture_dir="$1"   # /tmp/sp022_t01_fixture_<test_name>_<pid>
    rm -rf "$fixture_dir"
    mkdir -p "$fixture_dir/origin.git" "$fixture_dir/work"

    # bare repo (origin)
    git -C "$fixture_dir/origin.git" init --bare --initial-branch=main >/dev/null

    # work tree: clone + 必要 baseline file 作成
    git -C "$fixture_dir" clone -q "$fixture_dir/origin.git" work
    cd "$fixture_dir/work"
    git config user.email "test@example.com"
    git config user.name "test"

    # baseline files (R3 F-002 adopt: scanner contract と完全同期):
    # - 実 preflight path: backend/app/services/providers/preflight.py (旧 provider_compliance/ は誤り)
    # - 両 secret canary test fixture
    # - eval/security/secret_canary/ ディレクトリ
    # - scripts/ci/_intake_scanner.py を fake repo に copy
    # - scripts/ci/__init__.py で package 化 (uv run python -m scripts.ci._intake_scanner で import 可能)
    mkdir -p backend/app/services/providers tests/security tests/db tests/repositories \
             eval/security/secret_canary eval/security/tenant_isolation \
             frontend/app frontend/components frontend/lib docs/citations scripts/ci
    cat > pyproject.toml <<'PY'
[project]
name = "taskmanagedai-test-fixture"
version = "0.0.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[dependency-groups]
dev = []

[tool.setuptools.packages.find]
include = ["backend*", "scripts*"]
PY
    echo '{"name": "taskmanagedai-frontend-test", "version": "0.0.0", "dependencies": {}, "devDependencies": {}}' > frontend/package.json

    # R3 F-002 adopt: scanner が要求する 4 baseline file/dir をすべて作成
    echo "# preflight stub" > backend/app/services/providers/preflight.py
    echo "secret_canary = 'marker'" >> backend/app/services/providers/preflight.py
    echo "def provider_request_preflight(): pass" >> backend/app/services/providers/preflight.py
    echo "# AC-HARD-02 secret canary fixture stub" > tests/security/test_provider_preflight_canary.py
    echo "# AC-HARD-02 provider request preflight fixture stub" > tests/security/test_provider_request_preflight.py
    echo "# AC-HARD-03 tenant boundary fixture stub" > tests/db/test_tenant_boundary_stub.py
    echo "# AC-HARD-03 cross_tenant negative fixture" > tests/repositories/test_cross_tenant_negative_stub.py
    echo '{"version": 1, "fixtures": []}' > eval/security/secret_canary/manifest.json
    echo "# tenant_isolation marker AC-HARD-03" > eval/security/tenant_isolation/manifest.json

    echo '{"schema_version": 1, "entries": []}' > docs/citations/dependency_to_framework_map.json
    echo "# Framework Pattern Candidates fixture (test only)" > docs/citations/framework_pattern_candidates.md
    echo "" >> docs/citations/framework_pattern_candidates.md
    echo "| **NoSuchFramework** | x | y | z | w | v |" >> docs/citations/framework_pattern_candidates.md

    # R3 F-002 adopt: scanner module を fake repo に copy + scripts/ci/__init__.py 作成
    touch scripts/__init__.py scripts/ci/__init__.py
    cp "$REPO_ROOT/scripts/ci/check_framework_intake.sh" scripts/ci/
    cp "$REPO_ROOT/scripts/ci/_extract_changed_deps.py" scripts/ci/
    cp "$REPO_ROOT/scripts/ci/_intake_scanner.py" scripts/ci/

    git add -A
    git commit -q -m "baseline"
    git push -q origin main

    # feature branch
    git switch -q -c feature/test
}

assert_exit_code() { local actual="$1" expected="$2" name="$3"
    if [ "$actual" -eq "$expected" ]; then
        TESTS_PASSED=$((TESTS_PASSED+1)); echo "PASS: $name (exit=$actual)"
    else
        TESTS_FAILED=$((TESTS_FAILED+1)); echo "FAIL: $name (got=$actual expected=$expected)"
    fi
}
assert_stdout_contains() { local out="$1" needle="$2" name="$3"
    if echo "$out" | grep -q "$needle"; then
        TESTS_PASSED=$((TESTS_PASSED+1)); echo "PASS: $name (contains=$needle)"
    else
        TESTS_FAILED=$((TESTS_FAILED+1)); echo "FAIL: $name (missing=$needle)"; echo "$out" | head -20
    fi
}

# ---- 2. tests ----
test_license_violation() {
    local d=/tmp/sp022_t01_license_$$
    setup_fake_repo "$d"
    # Polyform Shield licensed dependency 追加 (fake site-packages なし → license empty で violation)
    sed -i.bak 's/dependencies = \[\]/dependencies = ["fakepkg-polyform-shield"]/' pyproject.toml
    git add -A; git commit -q -m "add polyform pkg"
    out=$(GITHUB_EVENT_NAME=pull_request bash scripts/ci/check_framework_intake.sh --mode=diff-gate 2>&1 || true)
    assert_stdout_contains "$out" "framework_intake_violation_license" "license_violation"
    assert_stdout_contains "$out" "FAIL" "license_violation_exit_msg"
    cd "$REPO_ROOT"; rm -rf "$d"
}

test_attribution_violation() { ... }       # fake pkg を added、map に entry なし → violation
test_no_code_embed_violation() { ... }     # backend/app/foo.py に "import crewai" 追加
test_persistence_violation() { ... }       # backend/app/services/foo.py に "import sqlite3" 追加
test_external_network_violation() { ... }  # backend/app/foo.py に "https://api.honcho.dev/" 追加
test_telemetry_violation() { ... }         # backend/app/foo.py に "import sentry_sdk" 追加
test_secret_canary_violation_unavailable() { ... }  # tests/security/ を rm → 0 件 hit
test_tenant_boundary_violation_unavailable() { ... } # tests/db/ + eval/security/ から AC-HARD-03 削除
test_clean_pass() { ... }                  # baseline state で diff-gate mode、deps 変更なし → exit 0 SKIP
test_skip_no_deps_change() { ... }         # pull_request event、deps file 変更なし → SKIP

# ---- 3. baseline-scan mode test (push to main 想定) ----
test_baseline_scan_clean() { ... }         # baseline state、GITHUB_EVENT_NAME=push GITHUB_REF_NAME=main → PASS
test_baseline_scan_detects_existing_violation() { ... }  # 既存 main に "import crewai" 残存 → violation 検出

# ---- 4. run all ----
test_license_violation
test_attribution_violation
test_no_code_embed_violation
test_persistence_violation
test_external_network_violation
test_telemetry_violation
test_secret_canary_violation_unavailable
test_tenant_boundary_violation_unavailable
test_clean_pass
test_skip_no_deps_change
test_baseline_scan_clean
test_baseline_scan_detects_existing_violation

echo "passed: $TESTS_PASSED / failed: $TESTS_FAILED"
[ "$TESTS_FAILED" -eq 0 ]
```

合計 fixture 数: positive 8 + negative 2 + baseline-scan 2 = **12 tests** (R1 F-001/F-004 mode 分離反映)。

### 5.3 `tests/citations/test_citation_completeness.py` 構造

```python
"""ADR-00020 §1 #2 Attribution verify (pytest 経路).

新 dependency が pyproject.toml に追加された場合、docs/citations/ 内に対応 entry
(framework_pattern_candidates.md 内の table row OR <framework>_adoption.md) が
存在することを verify.
"""
from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _get_changed_deps_in_pr() -> list[str]:
    """Return list of dependency names changed in PR (vs origin/main)."""
    # git diff origin/main...HEAD で差分なし環境では空 list → skip
    ...


def _load_citations_index() -> set[str]:
    """Load all framework names mentioned in docs/citations/."""
    ...


def test_changed_deps_have_citation() -> None:
    """Each added dependency must have an entry in docs/citations/."""
    changed = _get_changed_deps_in_pr()
    if not changed:
        pytest.skip("no dependency changes in this PR")
    citations = _load_citations_index()
    missing = [d for d in changed if d.lower() not in citations]
    assert not missing, f"dependencies missing citation: {missing}"
```

### 5.4 `.github/workflows/ci-smoke.yml` への step 追加 (R2 F-001 + F-002 adopt)

`backend-quality` job の **`checkout` step に `fetch-depth: 0` 追加** (R2 F-001 adopt: shallow checkout で `origin/main` 解決不能事故防止)、`Install backend dependencies` 後、`Ruff` の前に **Framework intake check step** 挿入:

```yaml
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # R2 F-001 adopt: framework intake check で origin/main...HEAD diff を解決するため shallow 不可

      # ... 既存 setup-python / setup-uv / cache / env file / install ...

      - name: Framework intake check (ADR-00020 8 verify, SP022-T01)
        env:
          FRAMEWORK_INTAKE_CHECK_DISABLED: ${{ vars.FRAMEWORK_INTAKE_CHECK_DISABLED }}   # R1 F-013 adopt: repository variable 経由、PR author 任意 disable 不可
        run: bash scripts/ci/check_framework_intake.sh
```

**注**: `actions/checkout@v4` default は `fetch-depth: 1` (https://github.com/actions/checkout README、R2 F-001 adopt)、明示 `fetch-depth: 0` で全 history fetch、`origin/main` 解決可能化。frontend-quality / frontend-e2e job への影響は無 (本 step は backend-quality job 内のみ)。frontend-quality job の checkout は別 actions/checkout call で、本 task では fetch-depth 変更不要。

### 5.5 `docs/citations/README.md` 構造 (新規)

`framework_pattern_candidates.md` の存在告知 + 新 dependency 追加時の citation 義務化 SOP。30-50 行程度の short index docs。

## 6. 検証手順 (verification before commit)

```bash
# 1. script 直接実行 (本 worktree の current branch、dependency 変更なし → SKIP exit=0)
bash scripts/ci/check_framework_intake.sh
echo "exit=$?"   # 期待: 0 (SKIP)

# 2. positive fixture test (各 violation type を deny できるか)
bash tests/scripts/test_check_framework_intake.sh
# 期待: passed: 10 / failed: 0

# 3. pytest (citation completeness) [R1 F-011 adopt]
uv run pytest tests/citations/ -q
# 本 worktree は dependency 変更なし → 期待: 1 skipped (CI 上 skip = success 扱い、`exit code 0`)
# changed dep ありの PR では 期待: 1 passed

# 4. ruff + mypy regression
uv run ruff check backend tests
uv run mypy backend
# 期待: 0 issues (citation test の新 file は backend ではなく tests 配下)

# 5. shellcheck (任意、可能なら)
shellcheck scripts/ci/check_framework_intake.sh tests/scripts/test_check_framework_intake.sh || echo "shellcheck unavailable, skip"
```

## 7. レビュー観点 (codex-plan-review trigger 必須)

mandatory Codex gate (codex-usage-policy.md §14.1 3+ file 横断、ADR-00020 直接 trace):
- `codex-plan-review R1 minimum + 採否判定` 経路必須
- finding 数 + clean 状態次第で adversarial round 追加判断

### 7.1 期待される review focus

1. **bypass 経路**: 各 verify item が grep / rg だけの場合、escape 文字 (`\\u0069mport` 等) で bypass される可能性。本 task では明確な ASCII pattern + line-anchor で検出するが、Codex でさらに edge case 拾い出してもらう。
2. **false positive**: legitimate dependency (例: SQLAlchemy が内部で sqlite3 を import) を誤 reject しない設計。`backend/app/{services,adapters,db}` のみ scan、`backend/app/db/migrations/` や `tests/` 除外、tenant_id-allowed pattern 除外。
3. **PyPI license metadata 取得**: `uv pip licenses` の出力形式が安定か、`pip show` の license field が空のケース対処。
4. **citation match**: framework 名の lowercase 比較 / fuzzy match の境界 (例: `langchain-core` と `langchain` の区別、`langchain` は ADR-00020 7 denylist に含まれない)。
5. **AC-HARD-02/03 reference verify** (verify item #7/#8): 既存 canary / boundary fixture が存在することの reference 確認のみで足りるか、本 task で新 fixture 追加が必要か。
6. **CI workflow integration**: `backend-quality` job への step 追加位置、PR で dependency 変更なしの場合に early exit が確実に動作するか (`git diff origin/main...HEAD` が CI で正しく resolve するか)。
7. **shellcheck-clean**: `set -euo pipefail` での array expansion (`"${VIOLATIONS[@]}"` empty case)、`local` 変数の scope、`grep -E` の portable パターン。

## 8. リスク / Rollback

| リスク | 影響 | mitigation |
|---|---|---|
| false positive | legitimate PR が reject される | 初回 deploy 後 1 週間 monitor、denylist tuning。**emergency disable は repository/admin controlled な env path のみ** (R1 F-013 adopt、PR author が任意に無効化不可、§Rollback 参照)。 |
| verify item #7/#8 reference verify の脆弱性 | canary / boundary fixture 不在で silent pass | reference verify は `rg -l 'secret_canary\|AC-HARD-02'` / `rg -l 'AC-HARD-03'` で 1 件以上 hit 必須、0 件は **violation exit 1 (reason_code 付き)** に統一 (R1 F-003 adopt、exit 2 案撤回) |
| dependency lockfile 解析失敗 | script 内部 error で CI fail | exit code 2 で明示、user / reviewer が原因確認可能。`_extract_changed_deps.py` で `tomllib.TOMLDecodeError` / `json.JSONDecodeError` catch して error 出力 |
| Codex CI gate review が delayed | merge 遅延 | 30 min max polling、admin merge bypass (CI billing failure 継続中、user 明示指示時) |
| `pip show` の license field が空 | license 不明で誤 reject | `importlib.metadata` `License-Expression` (PEP 639) fallback、それでも空なら violation (license 不明 dependency は audit 必須として fail-closed) |
| `baseline-scan` mode で main 既存 violation 検出 | main push 時に CI が真っ赤 | 既存 main に violation 残存している場合は、本 PR merge 前に baseline-scan dry-run (本 PR 内 verification §6 で実施) で確認、必要なら既存 violation を別 PR で先に解消 |

### Rollback 手順

1. **Step-level disable**: `.github/workflows/ci-smoke.yml` から "Framework intake check" step を `if: false` で disable (admin が PR でこの変更を merge)
2. **Emergency disable env (admin/repository-controlled only、R1 F-013 adopt)**:
   - workflow に `env.FRAMEWORK_INTAKE_CHECK_DISABLED` を **repository variable / secret から参照** する形で渡す (`.github/workflows/ci-smoke.yml` 側で `env: FRAMEWORK_INTAKE_CHECK_DISABLED: ${{ vars.FRAMEWORK_INTAKE_CHECK_DISABLED }}`)
   - PR diff からは設定不可、repository admin が GitHub Settings → Variables で設定/解除
   - 設定すると script は audit_marker (`framework_intake_check_disabled_at=<UTC timestamp>`) を stderr に出力して exit 0
   - **使用条件**: critical incident で merge 不可避 + admin 判断、24h 以内に retro Pack / 該当 PR 内 audit 記録 (`docs/sprints/SP-022_framework_intake_hardening.md` § Review に「disable 日時 / 理由 / 復旧 commit SHA」明記)
   - **復旧条件**: 該当 violation を別 PR で解消 + admin が variable を unset
3. ADR-00020 §残リスク「rollback: CI script を maintenance mode (`exit 0` で skip)」と整合

## 9. commit 戦略: single commit に集約 (本 PR 内、R1 F-014 adopt)

本 PR は **single commit** にまとめる (SP022-T00 PR #69 pattern 踏襲、review/rollback 単位を 1 PR = 1 commit に統一)。実装順序は以下だが、**git commit は最後に 1 回**:

| step | file | 種別 |
|---|---|---|
| 1 | `scripts/ci/check_framework_intake.sh` | 新規 |
| 2 | `scripts/ci/_extract_changed_deps.py` | 新規 (Python helper) |
| 3 | `tests/scripts/test_check_framework_intake.sh` | 新規 (12 fixtures) |
| 4 | `tests/citations/__init__.py` + `tests/citations/test_citation_completeness.py` | 新規 |
| 5 | `docs/citations/dependency_to_framework_map.json` | 新規 (初期 10 framework entries) |
| 6 | `docs/citations/README.md` | 新規 (不在の場合のみ) |
| 7 | `.github/workflows/ci-smoke.yml` | modify (step 追加 + `env.FRAMEWORK_INTAKE_CHECK_DISABLED` repository variable 参照) |
| 8 | `docs/sprints/SP-022_framework_intake_hardening.md` | modify (`## Review` に SP022-T01 完了記録 + 8 verify trace matrix) |
| 9 | `.claude/plans/sp022-t01-framework-intake-ci.md` | 本計画、commit に含める |

verify 失敗時は **全件 rollback** (`git restore .` で working tree clean → 再 implementation)。**部分 commit は禁止** (git revert 1 件で全変更を rollback できる単位を維持)。

## 10. PR workflow (本 session 確立 pattern 踏襲)

1. ✅ branch `worktree-sp022-t01-framework-intake-ci` 作成済 (`git switch -c` from origin/main)
2. ⏳ 計画書 draft (本 file) 作成
3. ⏳ `Skill(skill="codex-plan-review", args=".claude/plans/sp022-t01-framework-intake-ci.md")` 起動 (mandatory gate、R1 minimum)
4. ⏳ findings 採否判定 + 計画書反映 → R2 / R3 必要なら polish
5. ⏳ 実装 (Section 9 sequence)
6. ⏳ pre-commit verification (Section 6)
7. ⏳ commit + push + PR 起票 (`gh pr create`)
8. ⏳ Codex auto-review polling (`codex_pr_full_review.sh` baseline 内容確認 + delta polling + 30 min max)
9. ⏳ 採否判定 3 分類 + multi-round polish (R{N} clean まで)
10. ⏳ user merge or admin merge bypass (CI billing failure 継続中、user 明示指示時)

## 11. 受け入れ条件 (本 task の DoD、R1 F-001/F-004 adopt mode 分離反映)

- [ ] `scripts/ci/check_framework_intake.sh` が `diff-gate` mode で 8 verify item 全件機械検査 + `baseline-scan` mode で #3-#8 を repo 全体 regression scan する
- [ ] script は `diff-gate` mode + dependency 変更なし PR で early exit 0 (SKIP)、`baseline-scan` mode + clean main で exit 0 (PASS)
- [ ] `scripts/ci/_extract_changed_deps.py` で Python `pyproject.toml` + frontend `package.json` 両方の direct dependency が canonicalize + 抽出可能 (Node/pnpm 不要、Python 標準 tomllib + json のみ)
- [ ] `docs/citations/dependency_to_framework_map.json` schema_version=1 で 10 framework × Python/JS の初期 entries が登録済
- [ ] `tests/scripts/test_check_framework_intake.sh` の 12 fixture 全件 PASS (positive 8 + negative 2 + baseline-scan 2)
- [ ] `tests/citations/test_citation_completeness.py` が pytest 経路で PASS (dependency 変更なし環境では `1 skipped`、CI 上 skip = exit 0 success)
- [ ] `.github/workflows/ci-smoke.yml` の `backend-quality` job に step 追加済 + `env.FRAMEWORK_INTAKE_CHECK_DISABLED` を repository variable から参照 (PR author 任意 disable 不可)、CI run で実行確認 (post-merge 確認)
- [ ] `docs/sprints/SP-022_framework_intake_hardening.md` `## Review` 章に SP022-T01 完了記録追加 + 8 verify trace matrix + emergency disable audit format 記述
- [ ] codex-plan-review R{N} clean (CRITICAL=0 + HIGH ≤ 2)
- [ ] PR Codex auto-review R{N} clean (採否判定 3 分類 + multi-round polish 後)

## 12. 関連 ADR / Sprint Pack / Rules

- ADR-00020 (Framework Intake Checklist) §1-§6 — 本 task の正本
- ADR-00007 (External Exposure) §host-portable — verify item #5 external network denylist と整合
- SP-022_framework_intake_hardening.md SP022-T01 row — 本 task scope
- `.claude/rules/codex-usage-policy.md` §14.1 — mandatory Codex gate trigger (3+ file 横断)
- `.claude/rules/sprint-pack-adr-gate.md` §10 break-glass 例外運用 — 該当なし (実装着手前 ADR 必須 OK)
- `docs/citations/framework_pattern_candidates.md` — verify item #2/#3 の citation ledger 正本

## 13. codex-plan-review findings 採否判定 ledger (本 plan polish 起源)

### 13.1 R1 (Phase A 構造レビュー) 計 14 finding (HIGH=4, MEDIUM=8, LOW=2)、全件 **adopt** 反映済。

| ID | severity | category | symptom (50 字) | 採否 | 反映先 |
|---|---|---|---|---|---|
| F-001 | HIGH | inconsistency | push to main で `origin/main...HEAD` empty → 8 verify 空振り | adopt | §4.0 CI event 別 mode 分離 + §5.1 script `determine_mode` + §11 DoD mode 分離 |
| F-002 | HIGH | missing | License verify が未確認 CLI に依存、fallback 未定義 | adopt | §4.2 #1 で `pip show` + `importlib.metadata` 標準のみ採用 + §4.4 新 tool 不要明文化 |
| F-003 | HIGH | inconsistency | #7/#8 reference verify 仕様矛盾 (collect-only vs rg -l vs exit 2) | adopt | §4.2 #7/#8 を `rg -l` 存在確認 + violation exit 1 に統一 + §8 Risk 表 update |
| F-004 | HIGH | missing | DoD「全件機械検査」と「差分 only」の scope 矛盾 | adopt | §4.0 mode 分離で baseline-scan 追加 + §11 DoD update |
| F-005 | MEDIUM | missing | changed dependency 抽出方法 (groups/optional/lockfile) 未定義 | adopt | §4.1 direct deps 限定 + §5.1 helper `_extract_changed_deps.py` 詳細実装提示 |
| F-006 | MEDIUM | ambiguity | framework 名 / dependency 名 mapping fuzzy 曖昧 | adopt | §4.3 `dependency_to_framework_map.json` schema + exact canonical name 明文化 |
| F-007 | MEDIUM | risk | code embed grep が Python import 限定、JS/TS 未対応 | adopt | §4.2 #3 で Python + TS/JS 両方 pattern 明示 + vendoring は post-T01 scope と明文化 |
| F-008 | MEDIUM | risk | External network が literal grep 限定、unknown host 未対応 | adopt | §4.2 #5 で literal scope 明示 + allowlist contract は post-task scope と明文化 |
| F-009 | MEDIUM | risk | Persistence grep が限定的、asyncpg/Prisma 等未対応 | adopt | §4.2 #4 で TaskManagedAI 既存 sqlalchemy/asyncpg session boundary 経由しない直接 connect 限定 + frontend persistence は scope 外明文化 |
| F-010 | MEDIUM | missing | Bash fixture runner の git topology 未定義 | adopt | §5.2 fixture builder `setup_fake_repo` で bare origin + main + feature branch + baseline file 構築手順明示 |
| F-011 | MEDIUM | inconsistency | pytest skip semantics と期待 output 不整合 | adopt | §6 検証手順 で `1 skipped` 期待値に修正 + CI skip = success 明記 |
| F-012 | MEDIUM | risk | CI step 位置に frontend dependency 解析環境前提未定義 | adopt | §4.4 Python 標準 tomllib + json 主体実装、Node/pnpm 不要明文化 |
| F-013 | LOW | ambiguity | `FRAMEWORK_INTAKE_CHECK_DISABLED` 濫用防止未定義 | adopt | §5.1 audit_marker 追加 + §8 Rollback で repository/admin-controlled only + 24h retro 義務化 |
| F-014 | LOW | planning | atomic commit と single commit の表現混在 | adopt | §9 commit 戦略 を single commit に明文化、部分 commit 禁止 |

reject: 0 / defer: 0 / 全件 adopt。

R1 Readiness Gate: 反映前 = BLOCKED (HIGH=4 > 2)、反映後 = READY 期待 (R2 で確認)。

### 13.2 R2 (Phase B 実装可能性レビュー) 計 6 finding (HIGH=6)、全件 **adopt** 反映済。

| ID | severity | category | symptom (50 字) | 採否 | 反映先 |
|---|---|---|---|---|---|
| F-001 | HIGH | risk | `actions/checkout@v4` fetch-depth=1 で origin/main 解決不能 → SKIP で 8 verify 空振り | adopt | §4.4 + §5.1 base 解決失敗 = exit 2 + §5.4 workflow に `fetch-depth: 0` 明示 |
| F-002 | HIGH | inconsistency | `pip show` を plain `python3` で → `.venv` 内 dependency 見えず誤 reject | adopt | §4.2 #1 で `uv run python -m pip show` / `uv run python -c` に統一 + §5.1 script update |
| F-003 | HIGH | missing | extractor が `[dependency-groups]` 未対応、dev group 追加で bypass | adopt | §4.1 `[dependency-groups].*` 全 group 対象化 + §5.1 `_extract_changed_deps.py` 拡張 |
| F-004 | HIGH | risk | `rg` は ubuntu-latest preinstalled でない、`apt-get install` or 置換必要 | adopt | §4.4 ripgrep 依存撤回 + §5.1 Python scanner (`_intake_scanner.py`) で実装 |
| F-005 | HIGH | inconsistency | `rg -l 'a\|b'` の `\|` literal pipe + 実 preflight path は `backend/app/services/providers/preflight.py` | adopt | §4.2 #7 で実 path 修正 + Python scanner 移行で正規表現方言問題解消 |
| F-006 | HIGH | risk | frontend は `frontend/src/` 不存在、実は `app/` `components/` `lib/` + npm scoped name 未対応 | adopt | §4.2 #3/#5/#6 で frontend 対象 path を実構成に修正 + §4.3 dependency_map に npm scoped name 追加 |

reject: 0 / defer: 0 / 全件 adopt。

R2 Readiness Gate: 反映前 = BLOCKED (HIGH=6 > 2)、反映後 = READY 期待 (R3 で CRITICAL final 確認)。

### 13.3 R3 (Phase B 最終確認、CRITICAL のみ) 計 2 finding (CRITICAL=2)、全件 **adopt** 反映済。

| ID | severity | category | symptom (50 字) | 採否 | 反映先 |
|---|---|---|---|---|---|
| F-001 | CRITICAL | inconsistency | `check_license` の `pip show \| awk` が `pipefail` で script exit、fakepkg fixture で必発火、positive license test 成立不能 | adopt | §5.1 check_license で `\|\| true` 明示 + `uv run --no-sync` + extract も `\|\| true` で非致命化、全失敗ケースを `license_field_empty_or_unresolved` violation として記録 |
| F-002 | CRITICAL | inconsistency | `setup_fake_repo` が R2 update 後の scanner contract と未 sync (旧 `provider_compliance/preflight.py`、両 test fixture / eval dir / scanner module の copy 欠如) | adopt | §5.2 setup_fake_repo を scanner contract に完全 sync (実 preflight path / 両 fixture / eval/security/secret_canary/ + tenant_isolation/ / scripts/ci/_intake_scanner.py copy / scripts/__init__.py + scripts/ci/__init__.py 作成) |

reject: 0 / defer: 0 / 全件 adopt。

### 13.4 累計 (R1+R2+R3): 22 finding adopt、CRITICAL=0 (全件 fix 後)、HIGH=0、READINESS GATE READY

R3 で round_max=3 到達。Readiness Gate 判定:
- 残存 CRITICAL: 0 (R3 で出た 2 件は plan polish で完全反映、新規 regression リスクは確認関数を fixture でカバー)
- 残存 HIGH: 0 (R2 6 件すべて R3 確認時点で adopt 反映済)
- 残存 MEDIUM: 0 (R1 8 件すべて adopt 反映済)
- 残存 LOW: 0 (R1 2 件 adopt 反映済)
- **READINESS_STATUS: READY** (実装着手可)
