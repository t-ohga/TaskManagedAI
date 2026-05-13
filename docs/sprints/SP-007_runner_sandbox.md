---
id: "SP-007_runner_sandbox"
type: "heavy"
status: "in_progress"
sprint_no: 7
created_at: "2026-05-08"
updated_at: "2026-05-13"
target_days: 4.7
max_days: 7
adr_refs:
  - "[ADR-00008](../adr/00008_destructive_operation.md) # 2026-05-13 accepted (Sprint 7 batch 0)"
planned_adr_refs:
  - "[ADR-00012](../adr/00012_hook_trust_boundary.md) # 2026-05-13 proposed (Sprint 7 batch 0)、Phase 4 hooks の repo 外 trusted wrapper 実装は Phase 5 で扱う"
related_sprints:
  - "SP-006_cli_artifact"
downstream_sprints:
  - "SP-008_github_pr"
risks:
  - "forbidden path bypass (symlink / .. traversal)"
  - "dangerous command bypass (shell injection / encoding tricks)"
  - "resource cap leak (fork bomb / zip bomb)"
  - "Phase 4 hooks の repo 外 wrapper 化が dotfiles 管理失敗で hook 実行不能化"
---

このテンプレの使い方: Sprint 7 の Docker Isolated Runner + Hook Trust Boundary で、run ごとの Docker sandbox、forbidden path / dangerous command / resource cap、secret 非注入、`runner_mutation_gateway`、runner audit、AC-HARD-05 / AC-HARD-06 fixture、Phase 4 hooks の repo 外 trusted wrapper 化を実装するための heavy Sprint Pack。ADR Gate Criteria #8 破壊的操作と #5 MCP / tool 権限に該当するため、実装前に ADR-00008 / ADR-00012 を proposed 化し、該当 boundary を実装する前に accepted 化して `adr_refs` へ昇格する。

最終更新: 2026-05-08

## 目的

- RunnerAdapter を Docker isolated runner として実装し、AgentRun ごとに分離された workdir、container、resource cap、network egress allowlist を持たせる。
- `.env`、`.git/config`、secrets、migrations、`.github/workflows/**` 等の forbidden path への書込を path normalization と symlink resolution 後に拒否する。
- `rm -rf`、`curl | sh`、fork bomb、`chmod 777`、Docker socket、privileged、host network 等の dangerous command を parser と denylist で拒否する。
- CPU、memory、disk、wall clock、process count の resource cap を Docker / cgroups / runner watchdog で enforce する。
- runner env に raw secret、provider key、GitHub token、Tailscale auth key、SOPS / age key を注入しない。必要な外部操作は SecretBroker / RepoProxy の broker-mediated capability に分離する。
- `runner_mutation_gateway` を完成させ、policy、approval、forbidden path、command gate を通過した patch だけを sandbox 内で適用する。
- `runner_started` / `runner_completed` / `runner_blocked` event を audit と AgentRunEvent に残し、AC-HARD-05 / AC-HARD-06 fixture-based eval に接続する。
- Phase 4 hooks の残リスク PH4-F-001 / PH4-F-002 を repo 外 trusted wrapper と ADR-00012 で解消する。

## 背景

- Sprint 6 は CLI agent を artifact と subprocess launcher として扱う。Sprint 7 はその実行境界を Docker sandbox に閉じ、patch 適用と command 実行を安全にする。
- F-015 は Docker Isolated Runner と `runner_mutation_gateway` を P0 must_ship として要求している。これは Sprint 4.5 の `tool_mutating_gateway_stub` とは別概念である。
- AI Output Boundary は、AI 出力 patch を `runner_mutation_gateway` を経由せず適用すること、AI 出力 command を直接実行することを禁止している。
- DD-04 は `forbidden_path_block` と `dangerous_command_block` を Hard Gate とし、fixture は public_regression / private_holdout / adversarial_new に分ける方針を示している。
- `harness-residual-risks.md` は Phase 4 hooks の CRITICAL 残リスクとして PH4-F-001 dispatcher 自己改ざん耐性、PH4-F-002 snapshot state 改ざん耐性を Sprint 7 へ defer している。
- Sprint 7 では `~/.claude-trusted/taskmanagedai-hook-wrapper.sh` と `~/.claude-trusted-state/taskmanagedai/` を使い、repo 外 trusted wrapper、sha256 manifest、executable bit 検証、settings rollback を設計する。

## 対象外

- runner orchestrator 高度化、multi-runner、job queue、本格 scheduling。target_days 超過時は P0.1 / P1 へ defer する。
- Kubernetes、Firecracker、remote runner、external agent runner。P0 は Docker isolated runner に閉じる。
- GitHub branch create / push / Draft PR 作成。Sprint 8 の RepoProxy / GitHub App で扱う。
- `.github/workflows/**` の生成や更新。P0 では forbidden path として拒否し、Sprint 8 でも write rejection fixture を扱う。
- 書込系 MCP / external tool gateway 本格化。P0 は `tool_mutating_gateway_stub` deny-only のまま。
- production deploy、merge、host Docker socket 利用、privileged container、host network。P0 では常時 deny。
- raw secret / API key / canary 値を含む fixture や docs。fixture は pattern 種別、redacted expected result、dataset metadata のみを保存する。

## 設計判断

- Runner は run-per-container にする: AgentRun ごとに disposable container と workdir を作り、base image は read-only、write は isolated workdir と artifact output directory に限定する。
- path validation は文字列 prefix ではなく canonical path で行う: `..`、symlink、hardlink、case variant、URL encoded / escaped path を normalization 後に判定する。
- forbidden path は denylist と allowlist の両方で守る: allowlist は run workdir / artifact outbox / temp のみに絞り、`.env`、`.git/config`、secrets、migrations、`.github/workflows/**` は常時 deny する。
- dangerous command は shell 実行前の command plan parser で判定する: shell metachar、pipe、subshell、base64 decode、env expansion、encoded payload も canonical form に戻して見る。
- Docker policy は fail-closed にする: Docker socket mount、`--privileged`、host network、host pid/ipc、root filesystem write、unbounded volume mount は reject する。
- resource cap は layered にする: Docker flags / cgroups、runner watchdog、output byte limit、wall-clock timeout、pids limit、disk quota を組み合わせる。
- network は no public ingress を前提にし、egress は allowlist 化する: P0 は Tailscale 内必要先だけを許可し、public internet egress は明示許可がない限り deny する。
- runner env は scrubbed baseline にする: secret 値と installation token は渡さない。必要な repo operation は Sprint 8 の RepoProxy、secret operation は SecretBroker に分離する。
- `runner_mutation_gateway` は sandbox 内 patch apply だけを扱う: policy、approval、forbidden path、dangerous command、artifact hash、repo_state が一致した patch のみ適用する。
- audit は runner の制御面を説明する: start、complete、blocked、timeout、resource cap hit、path blocked、command blocked、cancelled、cleanup の event を raw secret なしで残す。
- Phase 4 hooks wrapper は repo 外を trust root とする: wrapper が repo dispatcher / child hooks の sha256 manifest と executable bit を検証してから exec し、snapshot state も repo 外に置く。
- rollback は明示的に用意する: `.claude/settings.json` を元 settings に戻す手順、trusted wrapper 無効化、state directory 移行の戻し方を ADR-00012 と Pack に残す。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 trace |
|---|---|---:|---:|---|---|---|
| BL-0071 | Docker isolated runner (run-per-container / workdir / read-only base) | F-015,NF-001 | 0.4 | SP-006 | RunnerAdapter、container lifecycle、workspace ref | DD-01 RunnerAdapter |
| BL-0072 | forbidden path allowlist / denylist | F-015,AC-HARD-05 | 0.4 | BL-0071,SP-005-5 | path normalization、symlink resolution、deny rules | AI Output Boundary §7 |
| BL-0073 | dangerous command parser + denylist | F-015,AC-HARD-06 | 0.4 | BL-0071,SP-005-5 | command plan parser、canonicalization、deny reason | DD-04 Hard Gates |
| BL-0074 | resource cap (cgroups: CPU / memory / pids / disk quota) | F-015,NF-010 | 0.4 | BL-0071 | Docker flags、watchdog、quota test | BudgetGuard |
| BL-0075 | network egress allowlist | F-015,NF-001 | 0.3 | BL-0071 | no public ingress、Tailscale-only allowlist | Network boundary |
| BL-0076 | env scrubbing (no secret / token 注入) | F-015,NF-003,AC-HARD-02 | 0.3 | BL-0071 | scrubbed env、negative assertion | SecretBroker boundary |
| BL-0077 | `runner_mutation_gateway` 実装 | F-015,F-013,AC-HARD-05,AC-HARD-06 | 0.5 | BL-0072,BL-0073 | policy / approval / path / command gate 後の patch apply | DD-04 §6.5 |
| BL-0078 | runner cancel propagation + cleanup | F-015,F-008,NF-011 | 0.3 | BL-0071,BL-0074 | Redis cancel、container stop / kill、workspace cleanup | DD-03 cancel |
| BL-0079 | runner audit event | F-015,NF-005 | 0.3 | BL-0071 | `runner_started` / `runner_completed` / `runner_blocked` | audit_events |
| BL-0080 | AC-HARD-05 fixture | F-019,AC-HARD-05 | 0.3 | BL-0072,BL-0077 | forbidden_path_block fixture、public/private/adversarial split | Eval Harness |
| BL-0081 | AC-HARD-06 fixture | F-019,AC-HARD-06 | 0.3 | BL-0073,BL-0077 | dangerous_command_block fixture、public/private/adversarial split | Eval Harness |
| BL-0082 | Phase 4 hooks の repo 外 trusted wrapper 実装 | F-001,NF-001 | 0.4 | ADR-00012 | wrapper、settings rewrite、ADR proposed to accepted | PH4-F-001 |
| BL-0083 | snapshot state を repo 外移動 + dotfiles 管理化 | F-001,NF-005 | 0.3 | BL-0082 | trusted state dir、dotfiles entry、migration note | PH4-F-002 |
| BL-0084 | hook integrity check + sha256 manifest 生成 / 検証 | F-001,NF-001 | 0.2 | BL-0082,BL-0083 | manifest、executable bit check、fail-closed | ADR-00012 |

## タスク一覧

- [ ] ADR-00008 を `docs/adr/00008_destructive_operation.md` として proposed 化し、runner sandbox 内の破壊的操作 boundary、denylist、rollback、fixture 方針を記録する。
- [ ] ADR-00012 を `docs/adr/00012_hook_trust_boundary.md` として proposed 化し、repo 外 trusted wrapper、snapshot state 移動、sha256 manifest、settings rollback を記録する。
- [ ] ADR-00008 / ADR-00012 の該当実装前に accepted 化し、frontmatter の `adr_refs` へ昇格する。
- [ ] RunnerAdapter interface を `prepareWorkspace`、`runCommand`、`collectArtifacts`、`cancel` に分け、run-per-container を前提にする。
- [ ] Docker base image は read-only root filesystem、non-root user、no privileged、no host network、no Docker socket mount を default にする。
- [ ] AgentRun ごとに isolated workdir を作り、run 完了 / cancel / timeout 時に cleanup する。
- [ ] path validator で `..`、symlink、hardlink、case variant、escaped path を canonical path に解決してから allowlist / denylist 判定する。
- [ ] `.env`、`.git/config`、secret inventory、migrations、`.github/workflows/**`、trusted wrapper / state directory を forbidden path として拒否する。
- [ ] command plan parser で shell metachar、pipe、subshell、encoded command、env expansion、download-and-execute pattern を canonicalize して危険コマンドを拒否する。
- [ ] `rm -rf`、`curl | sh`、fork bomb、`chmod 777`、Docker socket、privileged、host network、host mount を deny reason 付きで block する。
- [ ] CPU、memory、pids、disk、wall clock、output bytes の cap を Docker / cgroups / runner watchdog で enforce する。
- [ ] network は no public ingress を必須とし、egress は Tailscale 内必要先のみ allowlist する。
- [ ] env scrubbing test で provider key、GitHub token、Tailscale auth key、SOPS / age key、raw secret、capability token 生値が runner env にないことを確認する。
- [ ] `runner_mutation_gateway` は approved artifact hash、policy decision、approval request、path validation、command gate、repo_state を検証してから patch を sandbox 内に適用する。
- [ ] `runner_mutation_gateway` bypass、approval bypass、path check bypass、command gate bypass を negative test にする。
- [ ] runner cancel は Redis pub/sub から container stop、猶予後 kill、workspace cleanup、`run_cancelled` event へ伝播する。
- [ ] `runner_started`、`runner_completed`、`runner_blocked`、`runner_cancelled`、`runner_cleanup_completed` の event payload を raw secret なしで定義する。
- [ ] AC-HARD-05 fixture を public_regression、private_holdout、adversarial_new に分け、symlink / traversal / workflow path / migration path variant を含める。
- [ ] AC-HARD-06 fixture を public_regression、private_holdout、adversarial_new に分け、shell injection / encoding / fork bomb / Docker escape variant を含める。
- [ ] `~/.claude-trusted/taskmanagedai-hook-wrapper.sh` を repo 外 trusted wrapper として設計し、repo dispatcher と child hooks の sha256 manifest / executable bit を検証してから exec する。
- [ ] snapshot state を `~/.claude-trusted-state/taskmanagedai/` へ移し、repo 内 `.claude/.hook-state/**` 依存を減らす。
- [ ] `.claude/settings.json` の hook command を wrapper 呼び出しへ変更する手順と rollback 手順を ADR-00012 に明記する。
- [ ] trusted wrapper と state directory の dotfiles 管理方法を決め、管理漏れで hook 実行不能になった時の検知と戻し方を残す。

## must_ship / defer_if_over_budget 対応表

### ロードマップ §94 正本 (verbatim quote)

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 7 | 4.7 | 7 | Docker isolated runner + forbidden path + resource cap + `runner_mutation_gateway` 完成 | runner orchestrator 高度化 |

### Sprint Pack 内詳細 trace

ロードマップ正本の must_ship を Sprint Pack 内で詳細化したもの:

| 項目 | ロードマップ → Sprint Pack trace |
|---|---|
| Docker isolated runner | 実装チケット BL-0071 |
| forbidden path | 実装チケット BL-0072, BL-0080 |
| resource cap | 実装チケット BL-0074 |
| `runner_mutation_gateway` 完成 | 実装チケット BL-0077 |

## 受け入れ条件

- [ ] ADR-00008 が proposed 以上で存在し、runner sandbox の destructive operation boundary、dangerous command、rollback、fixture 方針を含む。
- [ ] ADR-00012 が proposed 以上で存在し、repo 外 trusted wrapper、snapshot state 移動、sha256 manifest、settings rollback、dotfiles 管理失敗時の復旧を含む。
- [ ] RunnerAdapter は AgentRun ごとに isolated workdir と disposable Docker container を作り、run 間で filesystem state が共有されない。
- [ ] Docker runner は read-only base、non-root user、no privileged、no host network、no Docker socket mount、bounded volume mount を default にする。
- [ ] path validator は symlink、`..` traversal、escaped path、case variant を canonicalize してから判定する。
- [ ] `.env`、`.git/config`、secrets、migrations、`.github/workflows/**` への write / patch / command plan は全件 `runner_blocked` になる。
- [ ] dangerous command parser は `rm -rf`、`curl | sh`、fork bomb、`chmod 777`、Docker socket、privileged、host network、host mount、shell injection、encoding tricks を deny reason 付きで拒否する。
- [ ] resource cap は CPU、memory、pids、disk、wall clock、output bytes を enforce し、cap hit は `blocked` + `runtime_blocked` または runner-specific blocked event で説明できる。
- [ ] network は no public ingress で、egress は allowlist 以外へ出られない。
- [ ] runner env に provider key、GitHub token、Tailscale auth key、SOPS / age key、raw secret、capability token 生値が存在しない。
- [ ] `runner_mutation_gateway` は policy decision、approval、artifact hash、repo_state、path validation、command gate が揃った patch のみ sandbox 内で apply する。
- [ ] `runner_mutation_gateway` bypass、approval bypass、forbidden path bypass、dangerous command bypass が negative test で失敗する。
- [ ] runner cancel は container stop / kill、workspace cleanup、AgentRunEvent、audit event まで伝播する。
- [ ] `runner_started` / `runner_completed` / `runner_blocked` event が actor_id、run_id、trace_id、correlation_id、reason_code、redacted artifact refs を持つ。
- [ ] AC-HARD-05 `forbidden_path_block` fixture が public_regression / private_holdout / adversarial_new に分かれ、symlink / traversal / forbidden file variant を含む。
- [ ] AC-HARD-06 `dangerous_command_block` fixture が public_regression / private_holdout / adversarial_new に分かれ、shell injection / encoding / resource abuse variant を含む。
- [ ] `~/.claude-trusted/taskmanagedai-hook-wrapper.sh` が repo dispatcher / child hooks の sha256 manifest と executable bit を検証し、検証失敗時は fail-closed になる。
- [ ] snapshot state が `~/.claude-trusted-state/taskmanagedai/` に移り、repo 内 state 削除で PH4-F-002 が再発しない。
- [ ] `.claude/settings.json` の wrapper 呼び出しへの変更と、元 settings.json へ戻す rollback 手順が明記されている。
- [ ] trusted wrapper / state の dotfiles 管理漏れが検知可能で、hook 実行不能時の復旧手順が残っている。
- [ ] TaskManagedAI 不変条件 trace として、`tool_mutating_gateway_stub` と `runner_mutation_gateway` の分離、Secret 非露出、AgentRunEvent append-only、AC-HARD-05 / AC-HARD-06 が説明できる。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-007_runner_sandbox.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ruby -e 'text=File.read("docs/sprints/SP-007_runner_sandbox.md"); missing=%w[BL-0071 BL-0072 BL-0073 BL-0074 BL-0075 BL-0076 BL-0077 BL-0078 BL-0079 BL-0080 BL-0081 BL-0082 BL-0083 BL-0084].reject { |id| text.include?(id) }; abort("missing: #{missing.join(",")}") unless missing.empty?'` で 14 チケットが揃っていることを確認する。
- [ ] `ls docs/adr/00008_destructive_operation.md docs/adr/00012_hook_trust_boundary.md` で planned ADR が存在することを確認する。
- [ ] `uv run pytest tests/runner/test_docker_runner_lifecycle.py -q` で run-per-container、isolated workdir、read-only base、cleanup を確認する。
- [ ] `uv run pytest tests/runner/test_forbidden_path_validator.py -q` で `.env`、`.git/config`、secrets、migrations、`.github/workflows/**`、symlink、traversal を確認する。
- [ ] `uv run pytest tests/runner/test_dangerous_command_parser.py -q` で dangerous command、shell injection、encoding tricks、Docker escape variant を確認する。
- [ ] `uv run pytest tests/runner/test_resource_caps.py -q` で CPU、memory、pids、disk、wall clock、output byte cap を確認する。
- [ ] `uv run pytest tests/runner/test_network_egress_allowlist.py -q` で no public ingress と egress allowlist を確認する。
- [ ] `uv run pytest tests/runner/test_env_scrubbing.py -q` で provider key、repo token、Tailscale auth key、SOPS / age key、raw secret、capability token 生値が runner env にないことを確認する。
- [ ] `uv run pytest tests/runner/test_runner_mutation_gateway.py -q` で policy / approval / path / command gate 通過後のみ patch apply されることを確認する。
- [ ] `uv run pytest tests/runner/test_runner_cancel_cleanup.py -q` で cancel propagation、container stop / kill、workspace cleanup、event append を確認する。
- [ ] `uv run pytest tests/runner/test_runner_audit_events.py -q` で `runner_started` / `runner_completed` / `runner_blocked` の payload と raw secret 非露出を確認する。
- [ ] `uv run pytest tests/eval/test_forbidden_path_block_fixture.py -q` で AC-HARD-05 fixture の public/private/adversarial split と expected result を確認する。
- [ ] `uv run pytest tests/eval/test_dangerous_command_block_fixture.py -q` で AC-HARD-06 fixture の public/private/adversarial split と expected result を確認する。
- [ ] `bash ~/.claude-trusted/taskmanagedai-hook-wrapper.sh --self-test` で wrapper、sha256 manifest、executable bit check、fail-closed を確認する。
- [ ] `uv run pytest tests/harness/test_hook_trust_boundary.py -q` で PH4-F-001 / PH4-F-002 の再現 fixture が wrapper / trusted state で block されることを確認する。
- [ ] `rg -n "privileged|host network|/var/run/docker.sock|chmod 777|curl.*sh|rm -rf" backend worker runner tests` で denylist と test 以外に危険設定が混入していないことを review する。
- [ ] `rg -n "secret_value|get_secret_value|canary_value|api_key\\s*=" backend worker runner tests config --glob '!**/*.md'` で raw secret / raw canary を保存する実装がないことを確認する。
- [ ] `ruby -e 'text=File.read(ARGV[0]); forbidden=[["ie","shima"].join, ["academy",["ie","shima"].join].join("."), ["i","FILTER"].join("-")].select { |s| text.include?(s) }; abort("forbidden terms: #{forbidden.join(",")}") unless forbidden.empty?' docs/sprints/SP-007_runner_sandbox.md` で別プロジェクト固有語がないことを確認する (検証コマンド自身が self-match しないよう禁止語は実行時組立て)。

## レビュー観点

- [ ] ADR-00008 / ADR-00012 が該当実装前に proposed / accepted へ進み、frontmatter の planned から adr_refs へ昇格する運用が明確である。
- [ ] Docker runner は run-per-container で、host filesystem、Docker socket、privileged、host network、unbounded mount を許していない。
- [ ] forbidden path 判定が文字列 prefix ではなく canonical path で、symlink / traversal / escaped path を bypass できない。
- [ ] dangerous command parser が shell injection、pipe、subshell、encoded payload、download-and-execute を canonical form で判定している。
- [ ] resource cap が Docker flags だけに依存せず、watchdog、output byte limit、wall-clock timeout、pids limit で多層化されている。
- [ ] runner env に secret / token 生値がなく、必要操作は SecretBroker / RepoProxy の broker-mediated boundary へ分離されている。
- [ ] `runner_mutation_gateway` は sandbox 内 patch apply だけを扱い、MCP / external tool の `tool_mutating_gateway_stub` と混同していない。
- [ ] `runner_mutation_gateway` が policy、approval、artifact hash、repo_state、forbidden path、dangerous command の全 gate を通す。
- [ ] cancel / timeout / blocked / completed の event ordering が AgentRun 16 状態と矛盾していない。
- [ ] AC-HARD-05 / AC-HARD-06 fixture が public_regression / private_holdout / adversarial_new に分かれ、Anti-Gaming ルールと接続できる。
- [ ] Phase 4 hooks wrapper は repo 外に trust root を置き、dispatcher 自己改ざんと snapshot state 改ざんを fail-closed にできる。
- [ ] dotfiles 管理失敗時の hook 実行不能化について、検知、rollback、元 settings への復帰手順が具体的である。
- [ ] TaskManagedAI 不変条件 trace: SecretBroker raw secret 非露出、AI Output Boundary、AgentRunEvent append-only、Hard Gate AC-HARD-05 / 06 が実装と test に紐づく。

## 残リスク

- forbidden path bypass (symlink / `..` traversal): canonical path resolver、symlink race test、escaped path variant、private_holdout fixture で検出する。
- dangerous command bypass (shell injection / encoding tricks): command plan parser の canonicalization、deny reason enum、adversarial_new fixture の月次追加で検出する。
- resource cap leak (fork bomb / zip bomb): pids limit、disk quota、output byte cap、wall-clock timeout、container kill、cleanup test を release blocker にする。
- network egress policy の過小 / 過大設定: no public ingress を固定し、egress allowlist は P0 最小にする。必要先追加は Pack / ADR に戻す。
- `runner_mutation_gateway` bypass: apply path を gateway service に一本化し、direct apply helper、manual file write、approval stale bypass を negative test で拒否する。
- runner env への token 混入: scrubbed env snapshot test、known key name denylist、runtime assertion、redacted audit を必須化する。
- Phase 4 hooks の repo 外 wrapper 化が dotfiles 管理失敗で hook 実行不能化: wrapper self-test、manifest check、dotfiles install check、元 settings への rollback 手順で検知 / 復旧する。
- ADR 昇格漏れ: Sprint 7 実装前 review で ADR-00008 / ADR-00012 が planned のままなら BLOCK にする。

## 次スプリント候補

- Sprint 8: GitHub Draft PR Flow。runner sandbox で生成 / 検証した patch を RepoProxy 経由の branch create / push / Draft PR へ接続する。
- Sprint 9: Agent Runs / Audit UI。runner events、blocked reason、artifact refs、resource cap hit、fixture result を UI で確認できるようにする。
- Sprint 11: Eval Harness。AC-HARD-05 / AC-HARD-06 fixture registry / loader を統合し、private_holdout と adversarial_new を分離する。
- Sprint 11.5: Operational Hardening。runner metrics、OTel、Loki redaction、resource cap dashboards、alerting を本格化する。
- Sprint 12: P0 Acceptance Test。forbidden_path_block / dangerous_command_block final 判定を gold flow に接続する。
- P0.1 / P1: runner orchestrator 高度化、multi-runner、job queue、remote runner、Firecracker / Kubernetes 検討。

## 関連 ADR

- [ADR-00008](../adr/00008_destructive_operation.md): Sprint 7 で proposed 化し、runner sandbox における destructive operation boundary、dangerous command、resource cap、rollback、Hard Gate fixture を扱う。
- [ADR-00012](../adr/00012_hook_trust_boundary.md): Sprint 7 で proposed 化し、Phase 4 hooks の repo 外 trusted wrapper、snapshot state の repo 外移動、sha256 manifest、dotfiles 管理、settings rollback を扱う。
- ADR-00006 は SecretBroker と raw secret 非露出の前提として参照するが、この Sprint では secret 管理方式を変更しない。
- ADR-00004 は AgentRun 16 状態、blocked サブ 3、runner event ordering の前提として参照する。
- ADR-00011 は Sprint 8 の GitHub App permission 変更で扱う。この Sprint では GitHub installation token や RepoProxy permission を変更しない。

## Review

### batch 0 + batch 1 完了 (2026-05-13、commit `dc573cc`)

#### changed (batch 0 + batch 1)

- `docs/adr/00008_destructive_operation.md`: NEW、Sprint 7 batch 0 で `accepted` 化。forbidden path 13 種 + dangerous command 15 種 + allowlist 3 種 + canonical path normalization + command parser + rollback (`RUNNER_MUTATION_GATEWAY_FORCE_DENY=true`)。
- `docs/adr/00012_hook_trust_boundary.md`: NEW、Sprint 7 batch 0 で `proposed`。Phase 4 hooks PH4-F-001 / PH4-F-002 解消方針 (repo 外 trusted wrapper + sha256 manifest)。実装は Phase 5 へ defer。
- `backend/app/services/runner/__init__.py`: NEW。public API export。
- `backend/app/services/runner/forbidden_path.py`: NEW (248 行)。`canonicalize_path` (ANSI strip + Unicode Cc/Cf carpet-bomb + URL 5 段 iterate decode + NFC + POSIX `//` collapse + symlink reject)。`_FORBIDDEN_FRAGMENTS` 21 entries + `_FORBIDDEN_PREFIXES` 7 entries + `detect_forbidden_path` + `resolve_and_detect`。
- `backend/app/services/runner/dangerous_command.py`: NEW、`DangerousCommandDenyReason` 20 enum + carpet-bomb 戦略。`canonicalize_command` + env wrapper unwrap (max 5 段) + 30+ runtime wholesale deny + `_SAFE_KNOWN_COMMANDS` 約 50 entry fallback + Docker socket/host network/privileged 検出。
- `backend/app/services/runner/mutation_gateway.py`: NEW、`MutationGatewayDenyReason` 10 enum + `PatchApplyRequest` frozen dataclass + `_validate_4_integrity` (hmac.compare_digest) + `_validate_allowlist` + `enforce_runner_mutation_gateway` (priority: policy → approval → 4-integrity → empty_patch → forbidden_path → allowlist → dangerous_command)。Sprint 8 server-owned ID 化 defer 明記。
- `backend/app/services/runner/runner_adapter.py`: NEW、`RunnerAdapter` ABC + `MockRunnerAdapter`。`prepare_workspace` (0o700 + uid binding) + `run_command` (argv + detect_dangerous_command + cwd containment + 43 種 env scrub + process group SIGTERM→SIGKILL)。
- `tests/runner/`: NEW、4 test file 合計 160+ test (forbidden_path 50+ / dangerous_command 60+ / mutation_gateway 20+ / runner_adapter 30+)。`EXPECTED_DENY_REASONS` で 5+ source 整合検証。
- `.claude/CLAUDE.md`: §6.5.0 「絶対教訓 (品質最優先)」追加。「急がなくていい。それぞれ品質重視で codex をしっかり使い完璧に」+ 6 原則。

#### verified (batch 0 + batch 1)

- `uv run pytest tests/runner/ -q`: 236 tests pass
- `uv run pytest -q`: 2002 tests pass (全 backend、Sprint 1-6 regression なし)
- `uv run mypy backend`: clean
- `uv run ruff check backend tests`: clean (S108 / ASYNC240 は file-level noqa)
- ADR-00008 `status: accepted` + ADR-00012 `status: proposed` 確認
- SP-007 frontmatter `status: in_progress` + `adr_refs: [ADR-00008]` 確認
- Codex multi-round adversarial review 6 round 完遂、15 distinct finding 全件 adopt

#### deferred (batch 1 → 後続)

- **F-001 (Sprint 8)**: `PatchApplyRequest.policy_passed` / `approval_passed` を caller-supplied bool → server-owned ID 置換。Sprint 8 RepoProxy / GitHub App integration と一緒に provenance binding 実装 (docstring 明記)。
- **F-011 (batch 4)**: AC-HARD-05 forbidden_path_block + AC-HARD-06 dangerous_command_block fixture (public_regression / private_holdout / adversarial_new) を batch 4 BL-0080 / BL-0081 で実装。
- **strict allowlist 移行 (Sprint 8)**: Codex R6 で「Sprint 8 で deny-list → strict allowlist が本質解」と提言。本 Sprint では deny-list 最善努力で十分な fail-closed 状態を達成、Sprint 8 で command allowlist 設計を ADR 化。
- **Phase 4 hooks repo 外 trusted wrapper (Phase 5)**: ADR-00012 で proposed のみ、本 Sprint では `~/.claude-trusted/` を forbidden path pre-protect。Phase 5 で wrapper + sha256 manifest + dotfiles 管理を完成、PH4-F-001 / PH4-F-002 最終解消。
- **Docker runner integration (Sprint 11)**: `MockRunnerAdapter` で interface 確立、`DockerRunnerAdapter` は Sprint 11 (Eval Harness) で実装。

#### risks (batch 1 時点識別)

- **Command deny-list 限界 (HIGH, Sprint 8 で解消)**: Codex R3-R6 で連続的に新 attack 面発見、deny-list 戦略の本質的限界。本 batch では 30+ wholesale deny + carpet-bomb fallback で最善努力。Sprint 8 strict allowlist で根本解決。
- **Symlink race (MEDIUM, Sprint 11)**: `Path.resolve(strict=False)` 後の symlink 差替 TOCTOU。allowlist prefix check + apply 前 re-resolve で緩和、Sprint 11 で container readonly mount + O_NOFOLLOW。
- **PatchApplyRequest 4 整合の caller bool (MEDIUM, Sprint 8)**: 現状 `policy_passed` / `approval_passed` が caller-supplied bool。Sprint 8 で server-owned ID 化 (F-001)。
- **Env scrub allowlist drift (LOW, Sprint 11.5)**: 43 種 forbidden env hardcode。新 secret env 出現で drift 可能。Sprint 11.5 で audit + auto-discovery。
- **Phase 4 hooks dispatcher 改ざん (CRITICAL, Phase 5)**: 本 Sprint 7 では ADR-00012 proposed のみで wrapper 未実装。Bash tool 経由 `.claude/hooks/` 改ざん攻撃は依然可能。Phase 5 で wrapper + manifest 完成。
- **AC-HARD-05 / AC-HARD-06 fixture 未完 (HIGH, batch 4)**: 本 batch 1 では unit test のみ。Hard Gate fixture (public / private / adversarial 3 分割) を batch 4 で実装、Sprint 11 で eval harness 統合。

#### Codex R0-R6 review summary

| Round | Severity | 件数 | adopt / reject / defer |
|---|---|---|---|
| R0 (test 生成中検出) | bug | 4 | adopt 4 (relative path / double-slash / env scrub / cwd prefix) |
| R1 | HIGH 6 + MEDIUM 5 + LOW 1 | 12 | adopt 10 + partial-defer 2 (F-001 Sprint 8 / F-011 batch 4) |
| R2 | HIGH 1 | 1 | adopt 1 (inline_exec coverage) |
| R3 | HIGH 2 | 2 | adopt 2 (env wrapper bypass / interpreter coverage) |
| R4 | HIGH 2 | 2 | adopt 2 (env -S/-- terminator / carpet-bomb 移行) |
| R5 | HIGH 1 | 1 | adopt 1 (find -exec bypass) |
| R6 | HIGH 1 | 1 | adopt 1 (ssh/scp/tmux/vim/less/emacs/nc/socat 等 30+ runtime wholesale deny) |
| **累計** | - | **15 distinct** | **adopt 14 + partial-defer 2 (Sprint 8 / batch 4 明示記録)** |

R6 で Codex 自身が「strict allowlist 移行が本質解、deny-list mole-whacking は限界」と提言。本 Sprint では deny-list 最善努力を達成、Sprint 8 で allowlist 移行へ進める。

### batch 2-5 (進行中、別 commit で追記予定)

- batch 2 (BL-0074 + BL-0075 + BL-0076): resource cap + network egress allowlist + env scrub integration with runner_adapter
- batch 3 (BL-0078 + BL-0079): cancel propagation Redis pub/sub + runner audit event + event_type 28→30 拡張
- batch 4 (BL-0080 + BL-0081): AC-HARD-05 + AC-HARD-06 fixture (public / private / adversarial 3 分割)
- batch 5 (BL-0082 + BL-0083 + BL-0084): Phase 4 hooks repo 外 wrapper (Phase 5 defer 明文化 + SP-007 ## Review record)

