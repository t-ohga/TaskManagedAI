---
id: "SP-006_cli_artifact"
type: "heavy"
status: "completed"
sprint_no: 6
created_at: "2026-05-08"
updated_at: "2026-05-13"
target_days: 2.5
max_days: 5
adr_refs:
  - "[ADR-00003](../adr/00003_api_contract.md) # 2026-05-12 Sprint 6 batch 0 で proposed 起票、Sprint 6 batch 1 着手前に accepted 化予定。CLI artifact orchestration の API 契約 (artifact schema、subprocess launcher、AgentRunEvent 拡張、採否判定 API、AI 出力直結禁止 lint)。Criteria #3 (API 契約 / event schema) + #4/#5/#6/#10 該当"
planned_adr_refs:
  - "[ADR-00013](../adr/00013_remote_agent_extension.md) # reference_only_for_p0: true (R1-F-016 fix)。2026-05-10 proposed 化済、Codex app-server / Claude Agent SDK の extension point boundary 仕様。SP-006 では note + extension point に止め、accepted 化は P0.1 で。SP-006 exit の accepted 条件ではない (R1-F-014 fix)。Criteria #4/#5/#6/#7/#10 該当"
upstream_sprints:
  - "SP-005-5_output_validator"
related_sprints:
  - "SP-007_runner_sandbox"
risks:
  - "AI 出力の subprocess 直結リスク"
  - "stdout / stderr の secret 漏洩"
  - "subprocess timeout / cancel propagation 不備"
  - "Codex app-server / Claude Agent SDK の extension point note が ADR-00013 と drift するリスク (本 Sprint で extension point note のみ残し、boundary 仕様は ADR-00013 に閉じる)"
---

このテンプレの使い方: Sprint 6 の CLI Artifact Orchestration で、`codex exec` / `claude -p` 等の CLI agent を domain に密結合せず、Markdown / JSON artifact、subprocess launcher、stdout / stderr / exit code capture、採否判定 API、direct execution prohibition test として扱うための heavy Sprint Pack。CLI artifact orchestration は ADR Gate Criteria #3 API 契約 / event schema に該当するため、ADR-00003 を proposed 化して artifact schema、subprocess launcher request / result、AgentRunEvent 拡張、採否判定 API、AI 出力直結禁止 lint の境界を固定してから実装する。Sprint 4.5 の registry と `tool_mutating_gateway_stub` deny-only 方針、Sprint 5.5 の Output Validator / Input Trust Layer を前提にする。

最終更新: 2026-05-10 (R1-F-015 fix、frontmatter `updated_at` と整合)

## 目的

- CLI agent の入出力を、直接実行結果ではなく TaskManagedAI の immutable artifact として扱う。
- `codex exec` / `claude -p` 等の CLI 呼び出しを subprocess launcher に閉じ、timeout、resource cap、env scrubbing、secret 非注入を必須にする。
- Markdown / JSON artifact contract を作り、CLI input、stdout、stderr、exit code、result summary を AgentRunEvent から追える状態にする。
- stdout / stderr は raw secret、token pattern、canary pattern を redaction してから保存し、raw 値を DB、artifact、audit、logs に残さない。
- CLI result は `adopt` / `reject` / `defer` の採否判定 API を通してのみ後続 workflow に渡す。
- AI Output Boundary §1 に従い、AI 出力を command、SQL、workflow、external tool、repo patch に直接接続する経路を禁止する。

## 背景

- Sprint 5.5 は Output Validator / Input Trust Layer を作り、AI 出力を `trusted_instruction` と `untrusted_content` に分け、schema validation、policy lint、forbidden path、dangerous command の前段を提供する。
- Sprint 6 は外部 CLI agent を TaskManagedAI domain に密結合しないための bridge である。CLI は artifact を読み、artifact を返すだけで、TaskManagedAI の DB mutation、repo write、workflow 更新を直接実行しない。
- ロードマップの Sprint 6 must_ship は CLI artifact subprocess と stdout 追跡である。この Pack ではその正本を artifact schema、subprocess launcher、stdout / stderr capture、採否判定 API、direct execution prohibition tests に詳細化する。
- ADR Gate Criteria #3 は API 契約 / event schema の変更を要求する。Sprint 6 は `cli_*` artifact_kind、subprocess launcher request / result、`cli_process_completed` / decision event、採否判定 API を ADR-00003 に trace する。
- AI Output Boundary は、AI 出力を shell command、SQL、migration、`.github/workflows/**`、external mutating tool、repository patch へ直接渡すことを絶対禁止している。
- `tool_mutating_gateway_stub` は Sprint 4.5 の MCP / external tool 書込系 deny-only 境界であり、この Sprint では拡張しない。Sprint 7 の `runner_mutation_gateway` は runner sandbox 内 patch 適用の本実装境界であり、この Sprint ではまだ完成させない。

## 対象外

- Codex App Server / Claude Remote Control adapter。P0.1 / P1 へ defer し、この Sprint では設計 note と extension point に止める。
- Docker isolated runner、forbidden path enforcement、dangerous command block の本実装。Sprint 7 で扱う。ただし CLI launcher は Sprint 7 の RunnerAdapter に接続できる interface にする。
- external mutating tool gateway 本格化。P0 では `tool_mutating_gateway_stub` が deny-only のまま。
- CLI 出力から Ticket / Acceptance Criteria / repo / workflow を直接更新すること。採用後も policy / approval / runner / RepoProxy の後続 gate を通す。
- provider key、GitHub token、Tailscale auth key、SOPS / age key、capability token 生値を CLI env、artifact、audit、test fixture に含めること。
- CLI agent の性能比較、モデル bake-off、remote session management。P0 は artifact contract と安全境界を優先する。

## 設計判断

- CLI agent は `CliArtifactAdapter` で扱う: domain は CLI の具体コマンドを知らず、registered adapter が input artifact と launcher request を組み立てる。
- input artifact は Markdown と JSON を両方サポートする: Markdown は人間レビュー向け、JSON は schema validation と deterministic test 向けにする。
- launcher は allowlisted binary / args だけを受ける: `codex exec` / `claude -p` 等は registry entry として定義し、AI 出力が launcher command string を生成する設計は禁止する。
- env は scrubbed baseline から構成する: provider key、repo token、secret value、SOPS / age key、capability token 生値を注入しない。必要な操作は後続 Sprint の SecretBroker / RepoProxy / RunnerAdapter に分離する。
- stdout / stderr は artifact 化前に redaction する: raw buffer は永続化せず、pattern hit 種別、redaction count、truncation metadata、redacted content hash を保存する。
- exit code は AgentRun status と分けて保存する: `0` は CLI subprocess success であり、AI 生成物の採用を意味しない。採用は `adopt` / `reject` / `defer` API で別に決める。
- timeout は `blocked` + `runtime_blocked` または `failed` の判断を event payload で説明する: CLI timeout は provider refusal でも validation failure でもない。
- cancel propagation は Redis pub/sub から launcher process group へ伝播し、まず SIGTERM、猶予後 SIGKILL を行う。cancel 後は `run_cancelled` と CLI-specific event を append-only で残す。
- 採否判定 API は additive な internal API として扱う: ADR-00003 に API 契約 / event schema の proposed 判断を置き、既存の AgentRunEvent / artifact contract に乗せる。versioned public API の breaking change が必要になった場合は ADR-00003 を更新してから進める。
- direct execution prohibition lint は artifact graph を見る: `source=ai` の output が command / SQL / workflow / repo patch / external tool に直接流れる edge を reject する。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 trace |
|---|---|---:|---:|---|---|---|
| BL-0064 | CLI artifact contract (Markdown / JSON schema) | F-014,F-013 | 0.4 | SP-005-5 | `cli_input`, `cli_output`, `cli_result` schema、artifact_kind | DD-03 §5、AI Output Boundary §4 |
| BL-0065 | subprocess launcher (timeout / env scrubbing / no secret injection) | F-014,NF-001,NF-003 | 0.5 | BL-0064 | launcher service、allowlisted argv、scrubbed env | DD-04 deny-by-default |
| BL-0066 | stdout / stderr capture + redaction | F-014,NF-005,AC-HARD-02 | 0.4 | BL-0065 | redacted stdout/stderr artifact、pattern hit metadata | Secret 非露出 |
| BL-0067 | exit code capture + AgentRun status mapping | F-014,F-008 | 0.3 | BL-0065,BL-0066 | exit_code、duration、timeout mapping、event payload | AgentRun 16 状態 |
| BL-0068 | 採否判定 API (`adopt` / `reject` / `defer`) | F-014,F-006,NF-005 | 0.4 | BL-0064,BL-0067 | decision endpoint、AgentRunEvent、audit | Policy / Approval trace |
| BL-0069 | AI 出力直結禁止 lint | F-014,F-013,AC-HARD-06 | 0.3 | BL-0068 | artifact graph lint、direct command / SQL / workflow edge reject | AI Output Boundary §1 |
| BL-0070 | subprocess cancel propagation | F-014,F-008,NF-011 | 0.2 | BL-0065,BL-0067 | Redis pub/sub、process group kill、cancel event | DD-03 cancel |

## タスク一覧

- [ ] ADR-00003 を `docs/adr/00003_api_contract.md` として proposed 化し、CLI artifact schema、subprocess launcher request / result、AgentRunEvent 拡張、採否判定 API、AI 出力直結禁止 lint の API / event schema 境界を記録する。
- [ ] CLI artifact schema を Pydantic / JSON Schema で定義し、Markdown frontmatter と JSON payload の両方で `run_id`、`artifact_kind`、`content_hash`、`payload_data_class`、`source_agent`、`schema_version` を必須にする。
- [ ] `cli_input`、`cli_stdout`、`cli_stderr`、`cli_exit`、`cli_result_summary` の artifact_kind を固定する。
- [ ] CLI registry に allowlisted binary、allowed args pattern、timeout default、max output bytes、network expectation、env policy を定義する。
- [ ] launcher は shell string を受け取らず、argv 配列のみを受けるようにする。
- [ ] launcher env は scrubbed baseline から作り、provider key、repo token、secret value、SOPS / age key、capability token 生値を除外する assertion を入れる。
- [ ] stdout / stderr capture は stream size limit と truncation metadata を持たせ、保存前に redaction pipeline を通す。
- [ ] redaction は raw secret pattern、provider / GitHub / Tailscale / SOPS / age key pattern、secret canary pattern、capability token pattern を raw 値なしで検出する。
- [ ] redaction hit 時は `secret_canary_detected` または `cli_output_redacted` 相当の audit payload に pattern 種別と count だけを保存する。
- [ ] exit code、signal、duration、timeout、cancelled_by、resource cap hit を `cli_process_completed` event に保存する。
- [ ] exit code `0` でも CLI result を自動採用しない。`adopt` / `reject` / `defer` decision がない artifact は後続 mutation へ進めない。
- [ ] 採否判定 API は actor、artifact hash、policy_version、repo_state、decision reason、decided_at を保存する。
- [ ] `adopt` は次段の Output Validator / Approval / Runner へ渡す decision であり、Ticket 更新や repo write を直接実行しない。
- [ ] direct execution lint で AI output から command / SQL / migration / workflow / external mutating tool / repo patch へ直接つながる graph edge を fail-closed にする。
- [ ] cancel request は AgentRunEvent に append し、Redis pub/sub から launcher process group へ SIGTERM、猶予後 SIGKILL を送る。
- [ ] timeout / cancel / non-zero exit の error summary は raw stdout/stderr を含めず、artifact refs と redacted summary だけで説明する。
- [ ] Codex App Server / Claude Remote Control adapter は extension point と P1 note のみ残し、P0 implementation path に入れない。

## must_ship / defer_if_over_budget 対応表

### ロードマップ §94 正本 (verbatim quote)

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 6 | 2.5 | 5 | CLI artifact subprocess + stdout 追跡 | Codex App Server / Remote Control adapter |

### Sprint Pack 内詳細 trace

ロードマップ正本の must_ship を Sprint Pack 内で詳細化したもの:

| 項目 | ロードマップ → Sprint Pack trace |
|---|---|
| CLI artifact subprocess | 実装チケット BL-0064, BL-0065, BL-0067, BL-0068, BL-0069, BL-0070 |
| stdout 追跡 | 実装チケット BL-0066 |

## 受け入れ条件

- [ ] ADR-00003 が proposed 状態で存在し、CLI artifact schema、subprocess launcher request / result、AgentRunEvent 拡張、採否判定 API、AI 出力直結禁止 lint の API / event schema 境界を含む。
- [ ] CLI artifact contract が Markdown / JSON schema の両方で検証でき、schema mismatch は `validation_failed` または `blocked` として扱われる。
- [ ] `codex exec` / `claude -p` 等は registry の allowlisted argv からのみ起動でき、AI 出力が command string を直接指定できない。
- [ ] launcher env に provider key、repo token、secret value、SOPS / age key、capability token 生値が存在しないことを assertion で確認できる。
- [ ] subprocess timeout、max output bytes、basic resource cap が設定され、超過時は raw output なしで event に記録される。
- [ ] stdout / stderr は redaction 後の artifact として保存され、raw secret、raw token、canary raw value は DB、artifact、audit、logs、test snapshot に残らない。
- [ ] redaction hit は pattern 種別、count、artifact ref、run_id、trace_id、correlation_id を raw 値なしで audit する。
- [ ] exit code、signal、duration、timeout、cancelled が `cli_process_completed` event から追える。
- [ ] exit code `0` は採用を意味せず、`adopt` / `reject` / `defer` decision がない CLI result は後続 mutation に進めない。
- [ ] `adopt` / `reject` / `defer` は AgentRunEvent と audit event に append-only で残る。
- [ ] `adopt` 後も Output Validator、policy lint、approval、runner / RepoProxy gate を bypass しない。
- [ ] AI 出力から command / SQL / migration / workflow / external mutating tool / repo patch へ直接つながる経路が lint と negative test で fail-closed になる。
- [ ] cancel request は Redis pub/sub から subprocess process group へ伝播し、cancel 後に orphan process が残らない。
- [ ] `tool_mutating_gateway_stub` は deny-only のままで、Sprint 6 実装によって書込系 MCP / external tool が許可されない。
- [ ] `runner_mutation_gateway` は Sprint 7 まで未完成として扱い、CLI result の patch 適用を Sprint 6 で直接行わない。
- [ ] TaskManagedAI 不変条件 trace として、AI Output Boundary、AgentRun 16 状態、Secret 非露出、Hard Gate AC-HARD-06 への接続が本文・test・audit で説明できる。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-006_cli_artifact.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `ruby -e 'text=File.read("docs/sprints/SP-006_cli_artifact.md"); missing=%w[BL-0064 BL-0065 BL-0066 BL-0067 BL-0068 BL-0069 BL-0070].reject { |id| text.include?(id) }; abort("missing: #{missing.join(",")}") unless missing.empty?'` で 7 チケットが揃っていることを確認する。
- [ ] **ADR-00003 (API 契約) 状態確認**: Sprint 6 実装着手前に `ls docs/adr/00003_api_contract.md` が存在し、status が `proposed` 以上であること。本 Sprint Pack frontmatter `planned_adr_refs` に明記済の通り、ADR-00003 は Sprint 6 で proposed 化され、CLI artifact orchestration の API 契約 (artifact schema / subprocess launcher / AgentRunEvent 拡張 / 採否判定 API / AI 出力直結禁止 lint) を Criteria #3 として固定する。Sprint 6 着手時点で ADR が未作成なら Sprint Pack 着手 BLOCK。
- [ ] `uv run pytest tests/cli/test_cli_artifact_contract.py -q` で Markdown / JSON artifact schema と artifact_kind を確認する。
- [ ] `uv run pytest tests/cli/test_subprocess_launcher.py -q` で allowlisted argv、timeout、resource cap、env scrubbing、no secret injection を確認する。
- [ ] `uv run pytest tests/cli/test_cli_output_redaction.py -q` で stdout / stderr redaction、pattern hit metadata、raw 値非保存を確認する。
- [ ] `uv run pytest tests/cli/test_cli_exit_status_mapping.py -q` で success / failure / timeout / cancelled の AgentRunEvent mapping を確認する。
- [ ] `uv run pytest tests/cli/test_cli_decision_api.py -q` で `adopt` / `reject` / `defer` が append-only event と audit に残ることを確認する。
- [ ] `uv run pytest tests/security/test_ai_output_direct_execution_lint.py -q` で command / SQL / workflow / external mutating tool / repo patch 直結が fail-closed になることを確認する。
- [ ] `uv run pytest tests/cli/test_subprocess_cancel.py -q` で Redis pub/sub、SIGTERM、SIGKILL、orphan process cleanup を確認する。
- [ ] `rg -n "shell=True|subprocess\\.run\\([^[]|os\\.system|eval\\(|exec\\(" backend worker tests` で shell string 実行や危険な launcher 実装がないことを review する。
- [ ] `rg -n "secret_value|get_secret_value|canary_value|api_key\\s*=" backend worker tests config --glob '!**/*.md'` で raw secret / raw canary を保存する実装がないことを確認する。
- [ ] `ruby -e 'text=File.read(ARGV[0]); forbidden=[["ie","shima"].join, ["academy",["ie","shima"].join].join("."), ["i","FILTER"].join("-")].select { |s| text.include?(s) }; abort("forbidden terms: #{forbidden.join(",")}") unless forbidden.empty?' docs/sprints/SP-006_cli_artifact.md` で別プロジェクト固有語がないことを確認する (検証コマンド自身が self-match しないよう禁止語は実行時組立て)。

## レビュー観点

- [ ] ADR-00003 の proposed 内容と CLI artifact / subprocess / AgentRunEvent / 採否判定 API / direct execution lint の実装が一致している。
- [ ] CLI subprocess は TaskManagedAI domain の mutation 権限を持たず、artifact 入出力だけに閉じている。
- [ ] launcher は argv 配列と registry から構成され、AI 出力由来の shell string を実行していない。
- [ ] stdout / stderr redaction は保存前に実行され、raw output を artifact / audit / logs に残していない。
- [ ] exit code と採用 decision を混同していない。CLI process success は `adopt` ではない。
- [ ] `adopt` / `reject` / `defer` の decision actor、artifact hash、policy_version、repo_state が audit できる。
- [ ] direct execution prohibition lint が AI Output Boundary §1 の禁止経路をすべて覆っている。
- [ ] cancel / timeout が AgentRun status と event ordering を壊していない。
- [ ] `tool_mutating_gateway_stub` と `runner_mutation_gateway` を混同していない。
- [ ] TaskManagedAI 不変条件 trace: `payload_data_class` は artifact metadata 由来、secret 非露出、AgentRunEvent append-only、AC-HARD-06 direct command block が説明できる。
- [ ] Codex App Server / Remote Control adapter の設計余地は残るが、P0 実装に入っていない。

## 残リスク

- AI 出力の subprocess 直結リスク: launcher は registry + argv 配列のみを受け、AI output graph lint で command / SQL / workflow 直結 edge を reject する。
- stdout / stderr の secret 漏洩: redaction を保存前必須にし、raw buffer 永続化を禁止し、pattern hit audit は raw 値なしにする。
- subprocess timeout / cancel propagation 不備: process group 管理、SIGTERM / SIGKILL、orphan process cleanup test、timeout event を release blocker にする。
- CLI result の過信: exit code `0` と `adopt` を分離し、adopt 後も Output Validator / policy / approval / runner gate を必須にする。
- Registry drift: CLI binary / args の allowlist を config schema と contract test で固定し、未登録 CLI は fail-closed にする。
- API contract 拡張の過大化: ADR-00003 に API / event schema の proposed 判断を置き、breaking versioned REST が必要になった時点で ADR-00003 を更新する。

## 次スプリント候補

- Sprint 7: Docker isolated runner。CLI launcher abstraction を RunnerAdapter に接続し、forbidden path、dangerous command、resource cap、`runner_mutation_gateway` を完成させる。
- Sprint 8: GitHub Draft PR Flow。adopt 済み artifact と runner output を RepoProxy / Draft PR 作成へ接続する。
- Sprint 9: Agent Runs UI。CLI stdout / stderr / decision event を Run timeline と Audit Log で確認できるようにする。
- Sprint 11: Eval Harness。AC-HARD-06 `dangerous_command_block` と direct execution prohibition fixture を loader に登録する。
- P0.1 / P1: Codex App Server / Claude Remote Control adapter、remote session management、CLI agent bake-off UI。

## 関連 ADR

- [ADR-00003](../adr/00003_api_contract.md): Sprint 6 で proposed 化する。CLI artifact orchestration の artifact schema、subprocess launcher request / result、AgentRunEvent 拡張、採否判定 API、AI 出力直結禁止 lint を扱う。ADR Gate Criteria #3 (API 契約 / event schema) 該当。
- ADR-00004 は Sprint 4.5 の `tool_mutating_gateway_stub` deny-only と AI エージェント権限の前提として参照する。
- ADR-00008 は destructive operation を runner sandbox 内で扱う Sprint 7 の対象であり、この Sprint では destructive command 実行を許可しない。
- ADR-00012 は Phase 4 hooks の repo 外 trusted wrapper 化を扱う Sprint 7 の対象であり、この Sprint では hook trust boundary を変更しない。

## Review

### changed (2026-05-13 完了)

Sprint 6 を 3 batch 構成で完了。3 commit (`1843054` / `147c433` / 本 commit) を `codex/phase-d-g-multi-agent-vision-host-portable` branch に積み、main へ ff merge する。

**batch 1 (commit `1843054`、14 files / +2381 行)**:
- `docs/adr/00003_api_contract.md`: proposed → accepted、CLI artifact orchestration boundary 5 種 (CliArtifactAdapter / Subprocess Launcher / Cancel Propagation / Direct Execution Lint / Approval Workflow) 固定。
- `backend/app/db/models/artifact.py`: ArtifactKind Literal 11 値 (CLI 5 種追加)、ORM CheckConstraint 同期。
- `migrations/versions/0012_cli_artifact_kind_11.py`: artifacts.kind CHECK 6 → 11 拡張 (additive)。
- `backend/app/domain/cli_artifact/{__init__,schema}.py`: CliArtifactPayload (Pydantic frozen、SHA-256 hex / semver / raw secret scan)、Markdown frontmatter parser。
- `backend/app/services/cli_artifact/{__init__,registry,launcher}.py`: 
  - registry TOML (`config/cli_registry.toml`、binary_path absolute 必須、forbidden ENV denylist 14 種、cwd_allowlist、argv placeholder 3 種制限)
  - launcher (`shell=False`、`start_new_session=True`、process group SIGTERM→SIGKILL escalation、`O_NOFOLLOW` stdin、path containment + symlink reject + 14 forbidden path fragment)。
- `tests/cli_artifact/{__init__,test_artifact_contract,test_registry,test_launcher}.py`: 91 test。
- `.claude/CLAUDE.md §6.5.0`: Codex-first ポリシー明文化。

**batch 2 (commit `147c433`、18 files / +2833 行)**:
- `backend/app/services/cli_artifact/redaction.py`: stdout/stderr → RedactionResult (raw text 戻り値非含、`unicodedata.category` で Cc/Cf carpet-bomb strip、ANSI / C0 / C1 / ZWJ / ZWNJ / BOM / VS / Plane 14 tags / VSS / CGJ 等 default-ignorable 全 strip、21 prohibited key value redaction、8 regex pattern 置換、`[REDACTED:non-utf8]` marker、bounded drain)。
- `backend/app/services/cli_artifact/per_run_workdir.py`: server-owned per-run dir (mode=0o700、uid=getuid()、symlink reject、base_dir owner/mode check、`O_CREAT|O_EXCL|O_NOFOLLOW` 事前作成)。
- `backend/app/services/cli_artifact/exit_mapping.py`: LauncherResult → ExitMappingDecision (cancelled > timeout > non-zero > success priority)、cli_process_completed payload (raw stdout/stderr 非含、redaction hash + hit_count)。
- `backend/app/services/cli_artifact/cancel_propagation.py`: CancelKey (Redis injection 物理削除)、CancelRegistry (bounded pending_signals=1024)、RedisCancelDispatcher、CancelSubscriberDriver。
- `backend/app/services/cli_artifact/orchestrator.py`: CliInvocationOrchestrator wiring (allowlist → workdir → atomic write → cancel race → launch → mapping → redaction)、cancel 経路でも output redaction。
- `backend/app/domain/agent_runtime/event_type.py` + `backend/app/db/models/agent_run_event.py` + `migrations/versions/0013_cli_event_type_28.py` + `tests/runtime/test_agent_run_events.py` + `.claude/rules/agentrun-state-machine.md`: event_type 25 → 28 拡張 (cli_invocation_started / cli_process_completed / cli_decision_recorded)、5+ source 整合維持。
- `backend/app/db/models/{agent_run_event,artifact}.py` + `migrations/versions/{0014_prohibited_event_keys_21,0015_artifact_prohibited_keys_21}.py`: DB CHECK denylist 18 → 21 keys (`secret_capability_token` / `raw_token` / `session_token`)、repository scanner と整合。
- `tests/cli_artifact/{test_redaction,test_per_run_workdir,test_exit_mapping,test_cancel_propagation}.py`: 137 test (Codex 委譲生成)。

**batch 3 (本 commit)**:
- `backend/app/services/cli_artifact/decision.py`: 採否判定 API (record_decision、actor_type=`human` 強制 = self-approval 物理削除、artifact_hash は server-side SHA-256 算出、reason の raw secret + key=value redaction 検証、aware datetime 必須)。
- `backend/app/services/cli_artifact/direct_execution_lint.py`: AI Output Boundary §1 lint (AI / CLI_LAUNCHER source × 6 sink kind = 12 forbidden edge、graph integrity unknown_node も violation 化)。
- `tests/cli_artifact/{test_decision,test_direct_execution_lint}.py`: 86 test。

### verified (2026-05-13)

- **ADR-00003 trace**: artifact schema (11 kinds) + subprocess launcher request/result + AgentRunEvent 拡張 (28 events) + 採否判定 API + AI 出力直結禁止 lint を boundary 全 5 種で fail-closed enforcement。
- **artifact contract**: CliArtifactPayload (Pydantic frozen、SHA-256 hex regex、semver、`extra=forbid`、dict/str body の raw secret scan)。
- **launcher env scrub**: `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GITHUB_TOKEN` / `TAILSCALE_AUTHKEY` / `SOPS_AGE_KEY` 等 14 種 forbidden ENV を registry __post_init__ で reject、launcher 内部 defense-in-depth + scrubbed env baseline。
- **redaction**: 8 regex pattern (OpenAI/Anthropic/GitHub×3/Tailscale/age/PEM) + 21 prohibited key value redaction (fail-closed line-end / delimiter terminate) + Cc/Cf category carpet-bomb (per-char unicodedata) + ANSI strip (closed / unterminated CSI / OSC / bare ESC) + bidi isolate + Plane 14 tag + VSS + CGJ + non-utf8 marker noise allowance。
- **AgentRun 16 状態 mapping**: exit_mapping priority (cancelled > timeout > non-zero > success)。timeout = `blocked + runtime_blocked` (resume 可)、non-zero = `failed` terminal、success = status 維持 (採否判定待ち)。
- **採否判定 API**: actor_type=`human` 強制 (self-approval 物理削除)、artifact_hash server-side 算出、reason の raw secret + key=value + redaction pipeline 3 段 reject、aware datetime 必須、reason_hash のみ AgentRunEvent payload、raw reason は audit_events 専用。
- **direct execution negative**: 12 violation pattern + graph integrity unknown_node + Trusted/Runner/Human allowed pattern、合計 86 lint test。
- **cancel propagation**: process group `os.killpg(pgid, SIGTERM/SIGKILL)` + drain task bounded await + CancelRegistry pending_signals bounded (1024) + Redis pub/sub channel injection 物理削除。
- **raw secret 非露出**: 8 round Codex adversarial review で AC-HARD-02 漏洩経路 (key=value / quoted / unclosed / ANSI / C0 / C1 / non-utf8 / ZWJ / ZWNJ / BOM / VS / bidi isolate / Plane 14 tag / VSS / CGJ / Cc/Cf full category) を全 closure。Confusable Cyrillic key は Sprint 11 eval harness AC-HARD-02 adversarial fixture で defer 明文化。
- **5+ source enum integrity**: ArtifactKind 11 / AgentRunEventType 28 / artifact_kind CHECK (migrations 0012) / event_type CHECK (migrations 0013) / prohibited key CHECK 21 (migrations 0014 + 0015) / pytest EXPECTED 全整合。
- **server-owned-boundary §1**: payload_data_class / content_hash / artifact_hash / cwd / prompt_file / output_file / stream_file 全て server-side で server 側が決定、caller-supplied signature 経路を物理削除。
- **検証コマンド (1766 / 1766 pass)**:
  - `uv run pytest -q`: 1766 passed, 279 skipped
  - `uv run mypy backend`: clean (147 source files)
  - `uv run ruff check backend tests`: All checks passed
  - `uv run alembic check`: migrations 0001-0015 整合
- **固有語なし**: `ruby -e 'forbidden = ["ie","shima"] ...'` で SP-006 自身に旧 project 固有語不在。

### deferred

- **Codex App Server / Claude Remote Control adapter**: P0.1 / P1 で `ADR-00013` accepted 化後 (Sprint 13+)。本 Sprint では subprocess + CLI binary 経由のみ、remote session 管理は scope 外。
- **Docker isolated runner + runner_mutation_gateway 本実装**: Sprint 7 で `RunnerAdapter` 完成 (forbidden path / dangerous command / resource cap / runner_mutation_gateway 本実装)。CLI launcher は interface 互換、Sprint 7 で RunnerAdapter に接続する。
- **採否判定後の Output Validator / policy lint / Approval / Runner / RepoProxy gate 連携**: Sprint 7-8 で実装。本 Sprint は decision record のみで mutation は行わない。
- **AI Output Boundary §1 の lint sink 追加 (secret_ref resolve / URL trust / trusted_instruction 自動昇格)**: 本 Sprint scope は 6 sink kind に限定。Sprint 5.5 Input Trust Layer + Sprint 7 RunnerAdapter で coverage 拡張。
- **caller-supplied ArtifactNode.source 偽装防止 (TRUSTED / RUNNER / HUMAN source の server-side 由来検証)**: Sprint 8 で provenance binding 実装。本 Sprint は lint validation のみ、actual source は別 module で server 側が決定する旨を docstring 明示。
- **Confusable Unicode redaction (Cyrillic key spoofing)**: 依存追加なしでは困難、Sprint 11 eval harness AC-HARD-02 adversarial fixture で扱う。
- **AgentRuntime wiring contract test (CliInvocationOrchestrator caller の AgentRunEvent + artifact persist + status update 同一 transaction)**: 本 Sprint は orchestrator docstring + decision API のみ。Sprint 7 で AgentRuntime に統合し contract test 追加。
- **Codex App Server / Remote Control adapter**: ADR-00013 で boundary 仕様 proposed 済、P0.1 で accepted 化。

### risks

- **subprocess bypass**: registry __post_init__ + launcher path containment + binary absolute + cwd allowlist の 4 段で fail-closed。検出: `tests/cli_artifact/test_launcher.py` 30 件 + Codex 5 round security review。残: shipped registry `binary_path = /opt/homebrew/bin/codex` は Mac 開発機固定、ADR-00021 host-portable で env-overlay 化を Sprint 6 batch 2+ 想定 (Linux/VPS deployment 時に別 path 指定が必要、ADR-00021 §3 で扱う)。
- **redaction miss**: 8 round Codex adversarial review で 18 finding 全 closure、Cc/Cf carpet-bomb で将来の Unicode standard update も自動対応。残: Confusable Unicode (`аpi_key` Cyrillic) は依存追加なしで困難、Sprint 11 AC-HARD-02 adversarial fixture で扱う。
- **cancel orphan**: `start_new_session=True` + `os.killpg(pgid, SIGTERM)` → grace → SIGKILL、drain task bounded await (5s)、CancelRegistry pending_signals bounded。残: subprocess が自身を別 session に move する pathological case は POSIX 仕様上避けられない (acceptable、Sprint 7 RunnerAdapter で Docker cgroup-based termination)。
- **decision bypass**: actor_type=`human` 強制 + artifact_content server-side hash + reason 3 段 redaction (raw_secret_scan / key=value reject / redaction pipeline) で signature レベル防御。残: idempotency key は本 module の責任外 (caller AgentRuntime が同一 (run_id, actor_id, verdict) の重複を防ぐ contract、Sprint 7 で実装)。
- **registry drift**: TOML / __post_init__ / pytest で 14 entry × multi-source 整合、Codex review で確認済。残: registry hot-reload 時 `_FORBIDDEN_ENV_NAMES` の import 時 snapshot 問題 (registry hot-reload は本 Sprint scope 外、再起動必須を明文化)。
- **API scope creep**: ADR-00003 で API 契約を proposed → accepted、breaking change が必要な場合は ADR-00003 update が必要。本 Sprint で API 契約安定化、Sprint 7 以降の internal API 追加は ADR update を介す。

### Codex Adversarial Review Summary

- **batch 1 R1-R5** (5 round): 9 finding (R1 1 HIGH + R2 4 HIGH + R3 3 HIGH + R4 1 HIGH + R5 verdict=clean MEDIUM 1 件)。
- **batch 2 R1-R8** (8 round): 18 finding (R1 1 CRITICAL + 3 HIGH + 4 MEDIUM + 1 LOW、R2-R8 各 1 CRITICAL / HIGH)。8 round で AC-HARD-02 secret canary 漏洩経路を 6 attack 面で全 closure (key=value / ANSI / C0/C1 / Default_Ignorable / bidi / VSS+CGJ / future Cf)。
- **batch 3 R1** (1 round): 8 finding (1 CRITICAL + 4 HIGH + 2 MEDIUM + 1 LOW) 全件採否判定 → adopt / partial / defer 文書化。signature 変更追従 test を Codex 委譲。
- **合計**: 13 round / 35 finding (重複排除後 33 finding)、Claude 単独 review では発見困難な Unicode redaction bypass + caller-supplied path 経路 + self-approval 経路 + graph integrity を Codex multi-round で補完。Codex-first ポリシー §6.5.0 を初期 round から適用。

## QL-B cross-reference (R29 §5 QL-B、2026-05-15 doc-only、F-PR12-004 P2 adopt)

本 Pack の acceptance spec として、QL-B Quality Loop run で記録された future implementation gate を以下の通り cross-reference する:

- `docs/基本設計/06_秘密管理設計.md §13` SecretBroker OperationContext canonical schema (CLI artifact が `secret.verify` operation を内包する場合、broker 側 OperationContext fingerprint binding が必須)
- `docs/基本設計/03_AIオーケストレーション設計.md §13.1` PolicyDecision must-precede (CLI 経由の `task_write` action 実行前に policy_decisions row 記録)
- `docs/adr/00025_autonomy_policy_profiles.md` (proposed) `secret_access` は全 level (L0-L3) で human approval 必須、CLI 経由でも auto-allow されない

