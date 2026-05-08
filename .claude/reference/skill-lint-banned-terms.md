# Skill Lint Banned Terms (TaskManagedAI)

`.claude/skills/*/SKILL.md` の lint 用禁止語レジストリ。  
**本ファイルは reference であり、`.claude/skills/` 配下ではない**。`skill-lint` skill から本レジストリを参照して pattern を組み立てる (skill 本文に禁止語を直書きすると skill-lint 自身が自己違反になるため)。

最終更新: 2026-05-07

## 1. BLOCK 対象禁止語

### 1.1 ieshima 固有 — 機械検出 (skill-lint が自動 BLOCK)

§5 の `BANNED_TERMS_IESHIMA` block に同期する。**ここに書いた語は §5 block にも regex として必ず存在させる**こと。検査は `rg -ni` (case-insensitive) で実行されるため、大小文字 variant を block に列挙する必要はない。「カテゴリ」列は人間向け索引であり、lint pattern ではない (重複・代替表記を許容)。

| カテゴリ (索引のみ、lint pattern ではない) | 禁止語 (§5 block と同期、検索は case-insensitive) |
|---|---|
| ieshima ID pattern | `US-[0-9]{3}`, `S1-CH[0-9]{2}` |
| BaaS | `Supabase` |
| 公開 ingress | `Vercel`, `Cloudflare` |
| UI lib | `shadcn`, `zustand` |
| Next.js cache | `Next.js cache components`, `Cache Components`, `cacheTag` |
| PWA / SW | `PWA`, `service worker` |
| ieshima content | `タイピング`, `クイズ`, `学習コンテンツ` |

### 1.1.1 文脈依存 — 手動レビュー対象 (skill-lint は自動検出しない)

以下は誤検出リスクが高いため自動 lint には含めず、PR レビュー / docs review で文脈確認する:

| 語 | 注意点 |
|---|---|
| `chapter` | docs / 章タイトルでの正当用途と衝突 |
| `story id` | story 用語が将来 TaskManagedAI で別文脈に出る可能性 |
| `RLS` | 「RLS-ready metadata」等 TaskManagedAI 文脈で正当に出現する |

### 1.2 raw secret らしきパターン

| パターン | 例 |
|---|---|
| OpenAI API key | `sk-[A-Za-z0-9]{20,}` |
| Anthropic API key | `sk-ant-[A-Za-z0-9]{20,}` |
| GitHub token | `ghp_[A-Za-z0-9]{20,}`, `ghs_[A-Za-z0-9]{20,}` |
| Tailscale auth key | `tskey-auth-[A-Za-z0-9_-]{20,}` |
| age private key | `AGE-SECRET-KEY-[A-Z0-9]{20,}` |
| GitHub installation token | `v1\.[A-Fa-f0-9]{40,}` |

## 2. TaskManagedAI 必須 trace 用語 (どれか含めること)

各 SKILL.md は以下のいずれかに trace していなければ WARN:

| カテゴリ | 用語 |
|---|---|
| Sprint Pack | `SP-[0-9]{3}`, `Sprint Pack` |
| ADR | `ADR-[0-9]{5}`, `ADR Gate` |
| Hard Gates | `AC-HARD-[0-9]{2}` |
| Quality KPIs | `AC-KPI-[0-9]{2}` |
| AgentRun | `AgentRun`, `agent_runs` |
| ContextSnapshot | `ContextSnapshot` |
| Provider Compliance | `payload_data_class`, `allowed_data_class`, `provider_compliance`, `Provider Compliance Matrix` |
| SecretBroker | `SecretBroker`, `secret_ref`, `capability token`, `atomic claim` |
| Gateway 区別 | `tool_mutating_gateway_stub`, `runner_mutation_gateway` |
| Tenant boundary | `tenant_id`, `project_id` |

## 3. 再帰起動禁止 patterns

skill 本文に以下が出現したら **specialty skill では BLOCK**、**Suite skill では文脈確認後 WARN/PASS**:

- `Skill(skill="..."` (Skill 内から別 Skill 起動)
- `Agent(subagent_type="..."` (Skill 内から Agent 起動)
- `codex-task` / `codex-second-opinion` / `codex-plan-review` / `codex-adversarial-review` / `codex-rescue` の起動命令

### Suite 例外条件

`dev-suite` / `quality-suite` / `review-suite` / `security-suite` / `release-suite` の 5 件は **Main Agent への orchestration 指示** として `Skill(...)` / `Agent(...)` 表記を許容する。ただし以下が必要:

- skill 本文に「**Main Agent への指示**」「**Main Agent が呼ぶ**」等の責務境界明記
- DRY_RUN モードで実 skill / agent を起動しないこと
- Codex chain は逐次実行 (並列禁止) と採否判定 (`adopt`/`reject`/`defer`) を明記

## 4. 適用範囲と例外リスト (allowlist)

### 4.0 適用範囲

`skill-lint` の機械 BLOCK は **`.claude/skills/*/SKILL.md` のみ**を対象とする。`.claude/rules/`, `.claude/reference/`, `.claude/agents/`, `.claude/hooks/`, `.codex/` は対象外 (これらは defer 説明、protective detection、ieshima 比較記述で正当に固有名詞を含むため)。Phase 7 横断 review で `.claude/` / `.codex/` 全体に適用すると false positive となるため、**横断レビューでは `.claude/skills/*/SKILL.md` だけ**を対象範囲として読むこと。

### 4.1 例外 path (`.claude/skills/` 内であっても BLOCK しない)

- 本レジストリ自体 (`.claude/reference/skill-lint-banned-terms.md`)
- Phase 0 mapping (`docs/設計検討/harness-phase0-mapping.md` の参考読み取り対象記述)
- `.claude/CLAUDE.md` の Codex 連携 skill 名列挙
- `harness-residual-risks.md` の defer 説明

### 4.2 protective detection ファイル (固有名詞を保持する正当な箇所)

以下のファイルは攻撃 / 公開検出 / defer 判断のため固有名詞を含む。**横断 review でも BLOCK 対象外**:

- `.claude/hooks/tailscale/check-tailscale-grants.sh` (Cloudflare / Funnel など公開検出 pattern)
- `.claude/rules/rendering.md` (shadcn / Cache Components / cacheTag を Sprint 9 ADR まで defer する説明)
- `.claude/rules/codex-usage-policy.md` (Supabase MCP 等の Codex 文脈例)
- `.claude/rules/instincts.md` (Supabase 等を "持ち込まない" と書く事故予防箇条)
- `.claude/rules/sprint-pack-adr-gate.md` (ADR Gate Criteria 11 種の例として固有名詞を残す)
- `.claude/reference/frontend-strategy.md` (shadcn / Cache Components の Sprint 9 defer 説明)
- `.claude/reference/directory-structure.md` (Sprint 9 で評価する frontend lib 名の保留)
- `.claude/agents/taskmanagedai/*.md` (固有名詞を比較対象として残す agent 説明)
- `.claude/skills/skill-lint/SKILL.md` (本レジストリを参照する pattern 定義)
- `.claude/skills/security-suite/SKILL.md` 等の Suite (Codex 連携 skill 名を Main Agent orchestration として明記)
- `.codex/agents/*.toml` (Claude 側 agent の Codex mirror として比較対象を含む)
- `docs/adr/00007_external_exposure.md` (Tailscale Funnel / Cloudflare Tunnel 等の外部公開選択肢を rejected option として比較する正当な文脈)
- `docs/adr/README.md` (ADR-00007 の説明で Cloudflare 等の外部公開 option を列挙)
- `docs/要件定義/01_P0要求定義.md` (P0 scope の rejected exposure option 説明で Cloudflare 等を列挙)
- `docs/実装計画/00_ロードマップ.md` (Tailscale Funnel / Cloudflare 等の Sprint 0 / 11.5 で扱う exposure 比較)

## 5. Machine-readable BANNED_TERMS block

skill-lint が確実に解釈するため、**ieshima 固有禁止語 (§1.1) のみ**を以下のブロックに 1 行 1 pattern で固定する。skill-lint は **このブロックだけ**を抽出して pattern を組み立てる (§2 trace 用語、§3 再帰 pattern、§4 例外 path は別ブロックで管理)。

<!-- BEGIN_BANNED_TERMS_IESHIMA -->
```regex
US-[0-9]{3}
S1-CH[0-9]{2}
\bSupabase\b
\bVercel\b
\bCloudflare\b
\bshadcn\b
\bzustand\b
Next\.js cache components
Cache Components
\bcacheTag\b
\bPWA\b
service worker
タイピング
クイズ
学習コンテンツ
```
<!-- END_BANNED_TERMS_IESHIMA -->

<!-- BEGIN_BANNED_TERMS_RAW_SECRETS -->
```regex
sk-[A-Za-z0-9]{20,}
sk-ant-[A-Za-z0-9]{20,}
ghp_[A-Za-z0-9]{20,}
ghs_[A-Za-z0-9]{20,}
tskey-auth-[A-Za-z0-9_-]{20,}
AGE-SECRET-KEY-[A-Z0-9]{20,}
v1\.[A-Fa-f0-9]{40,}
```
<!-- END_BANNED_TERMS_RAW_SECRETS -->

<!-- BEGIN_RECURSION_PATTERNS -->
```regex
Skill\(skill="
Agent\(subagent_type="
\bcodex-task\b
\bcodex-second-opinion\b
\bcodex-plan-review\b
\bcodex-adversarial-review\b
\bcodex-rescue\b
```
<!-- END_RECURSION_PATTERNS -->

skill-lint 実装例 (実コマンド):

```bash
# §5 ブロックから ieshima 禁止語だけを抽出 (rg -ni で case-insensitive 検索するため、大小文字 variant を列挙する必要はない)
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

# 検査対象から §4 例外 path を除外。
# rg exit code 解釈: 0=hit (BLOCK)、1=no-match (clean)、2 以上=実行エラー (regex parse 失敗等、BLOCK)
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

# raw secret block (case-sensitive、token 形式は大小文字を区別)
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

## 6. メンテナンス

- 新規禁止語追加時は本レジストリのみ編集する
- **§1.1 表と §5 `BANNED_TERMS_IESHIMA` block は同一 PR で更新**する。drift があると skill-lint で hit / no-hit がずれて誤検出 / 漏れになる
- §1.1 表 (人間向け索引) と §5 block (機械可読 regex) のレビュー手順:
  1. PR diff で §1.1 と §5 が両方更新されていること
  2. §5 block 抽出 → `awk ... | tr '\n' '|'` で組み立てた pattern を `bash -c` で確認
  3. §1.1 にあって §5 block にない語 / §5 block にあって §1.1 にない語をレビュアーが手動確認
- **文脈依存語は §1.1.1 に置き、§5 block には絶対に入れない** (RLS-ready metadata 等の正当用途を誤 BLOCK しないため)
- レジストリ §5 のサンプルと `skill-lint` SKILL.md Step 5 の bash 実装は **実行行 (rg / awk / case 構造) のみ同期必須**。コメント文言は drift を許容 (人間向け説明の最適化を優先)。完全 byte 一致は要求しない
- §1.1.1 の手動レビュー対象語は PR review / docs review / `release-suite` の最終 guard で人間が確認する。skill-lint 自動 BLOCK の対象ではない
- 例外を追加する際は §4 に追記し、根拠 (reference path / 文脈) を 1 行で書く
- 四半期レビュー (`.claude/reference/governance-cycle.md`) で禁止語と必須 trace 用語を見直す
