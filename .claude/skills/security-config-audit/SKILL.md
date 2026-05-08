---
name: security-config-audit
description: "TaskManagedAI の config/.env/docker-compose/Tailscale 設定を監査する。Triggers: config audit, Tailscale, ADR-00007"
when_to_use: |
  docker-compose、.env.example、config、Tailscale Serve/SSH/grants、暗号化設定、debug mode、public bind を監査する時。
  security-suite から呼ばれる場合も単独実行の場合も、設定変更は行わず findings だけ返す。
  トリガーフレーズ: 'config audit', 'security-config-audit', 'Tailscale 設定監査', 'ADR-00007'
argument-hint: "[--scope=current-branch|staged|all|specified-files] [--files=<comma-separated>]"
allowed-tools: Read Bash Grep
---

# security-config-audit — config / .env / docker-compose / Tailscale 設定監査

## 目的

TaskManagedAI の `docker-compose*.yml`, `.env.example`, `config/`, Tailscale 関連設定を対象に、P0 の Tailscale 閉域、deny-by-default、secret 非露出、ADR-00007 trace を満たすか監査する。

この skill は監査専用であり、設定変更は行わない。別 Skill / Agent を再帰起動しない。

## 必読資料

- `.claude/rules/core.md` §6
- `.claude/rules/instincts.md` §11
- `.claude/rules/sprint-pack-adr-gate.md` §4-§5
- `.claude/reference/audit-ownership-matrix.md`
- `.claude/reference/directory-structure.md`
- 関連 Sprint Pack / ADR-00007

## 対象

- `docker-compose*.yml`
- `.env.example`
- `.env.*.example`
- `config/**/*`
- `tailscale/**/*`
- `.sops.yaml`
- `docs/adr/*00007*`
- network / secret / service exposure / grant 関連 docs

## 検査手順

1. 対象ファイルを確定する。

```bash
rg --files docker-compose*.yml .env.example config tailscale .sops.yaml docs/adr 2>/dev/null
git diff --name-only
git diff --cached --name-only
```

2. public bind / public ingress を検出する。

```bash
rg -n "0\.0\.0\.0|::0|host:\s*0\.0\.0\.0|ports:|80:|443:|8080:|3000:|8000:|public|ingress|Funnel|funnel|serve.*https|serve.*tcp" docker-compose*.yml config tailscale docs 2>/dev/null
```

BLOCK:

- P0 の FastAPI / frontend / database / Redis が `0.0.0.0` に直接 bind
- Tailscale Funnel 有効化
- public ingress / public DNS / Cloud edge への公開
- database / Redis / runner API の host port 公開
- ADR-00007 なしの外部公開変更

WARN:

- localhost bind だが意図が docs にない
- compose service port が internal network と host publish で混在
- private staging の exposure path が Sprint Pack にない

3. Tailscale grants / Serve / SSH を確認する。

```bash
rg -n "tailscale|grants|tag:taskhub-ci|ssh|serve|funnel|autogroup|users|groups|accept|src|dst|ipn|authkey" config tailscale docs 2>/dev/null
```

BLOCK:

- grants が broad user / device / tag に開きすぎている
- `tag:taskhub-ci` が必要最小限を超える
- Funnel 許可
- Tailscale auth key を raw 値として config / docs に書く
- runner env に Tailscale auth key を直接注入する
- ADR-00007 なしの network boundary 変更

WARN:

- device approval / SSH policy の記録がない
- Tailscale Serve と Docker bind の責務が曖昧
- private staging CI/E2E の credential flow が `secret_ref` ではない

4. secret ハードコード / .env.example を確認する。

```bash
rg -n "(API_KEY|TOKEN|SECRET|PRIVATE_KEY|PASSWORD|AUTH_KEY|AGE|SOPS|GITHUB).*=" .env.example .env.*.example config docker-compose*.yml tailscale docs 2>/dev/null
rg -n "secret_ref|secret://sops|runner_injectable|raw_secret|secret_value|private_key" config docker-compose*.yml .env.example docs 2>/dev/null
```

BLOCK:

- 実値に見える secret / token / private key / auth key
- `.env.example` に placeholder ではなく credential 値
- Docker Compose env に raw provider key / GitHub token / Tailscale auth key
- SecretBroker を通さず runner env に secret を渡す
- SOPS age private key を repo file に記載

WARN:

- `.env.example` に required / optional の説明がない
- `secret_ref` ではなく plain env var 前提が残る
- rotation / owner / scope の metadata がない

5. SOPS / encryption policy を確認する。

```bash
rg -n "sops|creation_rules|encrypted_regex|age|kms|pgp|ENC\\[" .sops.yaml config docs 2>/dev/null
rg -n "api_key|token|private_key|password|secret" config 2>/dev/null
```

BLOCK:

- secret file が SOPS 対象外
- secret 値が `ENC[` なしで保存されている
- `.sops.yaml` が暗号化対象を狭めすぎている
- age private key path / key 値を repo に書く

WARN:

- encrypted_regex が secret naming と同期していない
- secret inventory / owner actor が未記録
- config parser の schema validation がない

6. debug mode / weak crypto / dangerous defaults を確認する。

```bash
rg -n "DEBUG|debug|reload|insecure|verify=false|sslmode=disable|TLS|cipher|CORS|allow_origins|localhost|dev-only|privileged|network_mode:\s*host|volumes:.*docker\.sock|read_only|cap_drop|security_opt" docker-compose*.yml config backend frontend docs 2>/dev/null
```

BLOCK:

- production profile で debug / reload / insecure TLS
- wildcard CORS
- weak / disabled TLS verification
- Docker privileged / host network / docker socket mount
- runner に broad host path mount
- database password なし / default credential

WARN:

- dev-only 設定の scope が明記されていない
- security_opt / cap_drop / read_only root filesystem が runner で未検討
- config schema validation が不足

## 出力 contract

Markdown で返す。

```markdown
## Security Config Audit Result
Verdict: PASS|WARN|BLOCK
Scope: current-branch|staged|all|specified-files

## Findings
| severity | file:line | category | issue | required_fix | trace |
|---|---|---|---|---|---|

## ADR-00007 Trace
| config_change | adr_reference | verdict | note |
|---|---|---|---|

## Exposure Summary
| service | bind | public_path | verdict |
|---|---|---|---|

## Secret Handling Summary
| path | pattern | verdict | note |
|---|---|---|---|
```

category は `public-bind`, `tailscale`, `secret`, `sops`, `debug`, `crypto`, `docker`, `adr-trace` のいずれかを使う。

## 失敗時の挙動

- raw secret / token / private key らしき値を検出しても、値を再出力しない。`redacted pattern hit` と file:line のみ書く。
- public bind、Funnel、有効な public ingress、secret hardcode、Docker privileged / host network は BLOCK。
- ADR-00007 が見つからない外部公開変更は BLOCK。
- `.env.example` が未作成なら WARN。secret handling 実装と同時なら BLOCK。
- Tailscale config が未作成なら WARN とし、P0 dormant 状態を明記する。
- `rg` で検出した line は Read で周辺を確認してから finding にする。

## TaskManagedAI 不変条件 trace

- P0 Tailscale 閉域 / Funnel 不使用
- deny-by-default network / tool / repo / secret
- ADR-00007 外部公開 / network boundary trace
- SecretBroker `secret_ref` / raw secret 非露出
- AC-HARD-02 `secret_canary_no_leak`
- AC-HARD-05 / AC-HARD-06 runner exposure hardening
- Sprint Pack / ADR Gate Criteria: 外部公開、Secrets、MCP / tool 権限、破壊的操作

