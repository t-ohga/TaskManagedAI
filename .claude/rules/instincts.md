# Instincts

TaskManagedAI 固有の事故予防集。  
過去に起きやすい破壊パターンを先回りして止めるため、実装・レビュー時に常時参照する。

## 1. Sprint Pack を飛ばさない

- 実装前に `docs/sprints/` を確認する。
- Sprint Pack がなければ light / heavy を判断する。
- 認証、DB schema、API 契約、AI 権限、MCP、Secrets、外部公開、破壊的操作、広範囲リファクタ、Provider、GitHub App permission は ADR 必須。
- 「小さい変更」に見えても migration、secret、provider、runner、repo write に触れるなら high-risk。
- Pack なしで実装した緊急修正は 24h 以内に retro Pack / ADR を残す。

## 2. AI 出力を直結しない

- AI 出力 command を shell に渡さない。
- AI 出力 SQL を migration / DB console に貼らない。
- AI 出力 workflow を `.github/workflows/**` に書き込まない。
- AI 出力 patch は artifact 化してから schema validation、policy lint、diff_ready、approval を通す。
- AI 出力から `secret_ref` を resolve しない。
- `approval_required` を人間確認なしの自動承認にしない。

## 3. SecretBroker atomic claim 抜けを疑う

- redeem が check -> execute -> mark used になっていたら危険。
- 必ず atomic claim UPDATE で `status='issued'`, `used_at is null`, `expires_at > now()` を同時に確認する。
- actor / run / request_fingerprint / requested_operation を同一 SQL で binding する。
- `issued_run_id is not distinct from :run_id` を使い、null binding の抜けを防ぐ。
- 0 rows RETURNING は deny audit。
- operation 失敗時も同一 token を再利用しない。

## 4. `payload_data_class` caller 入力混入を疑う

- `payload_data_class` は request / artifact metadata から事前算出する。
- ProviderAdapter は再算出しない。
- `payload_data_class` 未設定は即 deny。
- `allowed_data_class` は Matrix からのみ解決する。
- caller が `allowed_data_class` を渡す interface は設計ミス。
- data class ordinal は `public < internal < confidential < pii`。
- string 比較や別順序を使わない。

## 5. Provider Matrix unverified を甘く見ない

- `unverified` が残る provider / feature に `confidential` 以上を送らない。
- `zdr_eligible=conditional` は `condition_status=verified` がなければ解禁しない。
- `store:false` を ZDR 相当にするなら ADR が必要。
- runtime downgrade により `allowed_data_class <= internal` へ落とす。
- deny 時は provider へ送信せず、`blocked` + `policy_blocked` にする。
- audit payload は `payload_data_class` と `allowed_data_class` を別 dimension で持つ。

## 6. AgentRun 状態遷移漏れを疑う

- AgentRun status は 16 状態に固定。
- `blocked_reason` を status enum に増やして 19 状態にしない。
- `blocked_reason` は `policy_blocked`, `budget_blocked`, `runtime_blocked` のみ。
- terminal state は `completed`, `failed`, `cancelled`, `provider_refused`, `repair_exhausted`。
- `provider_incomplete` を terminal にしない。
- `provider_refused` を retry しない。
- `validation_failed` の repair retry 上限到達は `repair_exhausted`。

## 7. ContextSnapshot 10 カラムを欠かさない

- `prompt_pack_version`
- `prompt_pack_lock`
- `policy_version`
- `policy_pack_lock`
- `repo_state`
- `tool_manifest`
- `evidence_set_hash`
- `provider_continuation_ref`
- `provider_request_fingerprint`
- `snapshot_kind`
- 上記は再現性の contract。省略や名前変更は high-risk。
- secret 値、provider key、capability token 生値は snapshot に入れない。

## 8. tenant / project boundary を DB で閉じる

- P0 は個人 1 user でも multi-tenant-ready の schema を保つ。
- 全主要 table に `tenant_id` を持たせる。
- 親子 FK は `tenant_id` を含む。
- 同一 tenant・別 project の cross reference も禁止する。
- `agent_runs.parent_run_id` は同一 project 内に閉じる。
- `ticket_relations` は project boundary を越えない。
- SELECT / UPDATE / DELETE は repository contract test で `tenant_id` を確認する。

## 9. actor / principal / approval の混同を疑う

- actor は human / service / agent / provider / github_app を表す。
- principal は session / api_token / capability_token / installation / worker を表す。
- requester と decider が同じ approval は禁止。
- AI / worker が作った approval は agent / service actor として記録する。
- GitHub App 操作は `github_app` actor として audit する。
- impersonation は `impersonated_by` を残す。

## 10. Gateway 名の混同を止める

- `tool_mutating_gateway_stub` は MCP / 外部 tool 書込系の deny-only stub。
- `runner_mutation_gateway` は runner sandbox 内で patch を適用する本実装経路。
- `tool_mutating_gateway_stub` を実装したから runner patch が安全になるわけではない。
- `runner_mutation_gateway` を通したから MCP 書込系を許可してよいわけではない。
- audit event は `gateway_kind=tool|runner` を分ける。
- Hard Gate fixture も別々に組む。

## 11. Tailscale grants 設定ミスを疑う

- P0 は Tailscale 閉域。Funnel は使わない。
- public bind、Cloudflare 公開、Funnel 有効化は ADR Gate 対象。
- grants は最小化し、tag / user / device を広げすぎない。
- Docker service は localhost / internal network 待受を優先する。
- private staging CI/E2E は Tailscale auth key を `secret_ref` で扱う。
- Tailscale auth key を runner env に直接注入しない。

## 12. GitHub App permission 変更を軽く扱わない

- GitHub App permission 変更は ADR Gate 対象。
- RepoProxy は installation token を SecretBroker / internal boundary で扱う。
- branch 作成、push、Draft PR 作成、CI status 取得を分けて audit する。
- merge / auto-merge は P0 deny。
- `.github/workflows/**` への AI / runner 書込は forbidden path として扱う。
- permission を増やす場合は rollback と blast radius を書く。

## 13. raw secret 表示を検出したら止める

- DB、log、artifact、audit、ContextSnapshot に raw secret を書かない。
- runner stdout / stderr に canary が出たら Hard Gate failure。
- provider request body に canary が入る前に `provider_request_preflight` で止める。
- audit は pattern hit 種別、hash、reason_code を残し、raw value は残さない。
- `secret_ref` は opaque reference。URI の解釈は SecretBroker 内に閉じる。

## 14. Budget を failure と混同しない

- budget exceeded は provider failure ではない。
- AgentRun は `blocked` + `budget_blocked`。
- budget 更新後に resume 可能。
- global kill switch は新規 AgentRun / provider call を止める。
- max retries / max wall-clock / max tokens / provider cap を別々に監査する。
- `cost_per_completed_task` と provider usage を接続する。

## 15. Eval Anti-Gaming を守る

- `public_regression` は開発中に見てよい。
- `private_holdout` の期待値を見ながら prompt / policy を調整しない。
- `adversarial_new` は月次 1-3 件追加する。
- monthly refresh は append-only。
- fixture ID と dataset version を AgentRun / EvalRun に保存する。
- fixture 作成者と policy / prompt 修正者は履歴上分ける。

## 16. 破壊的操作は rollback から考える

- migration、data backfill、permission 変更、network exposure は rollback を先に書く。
- backup / restore drill と PITR を確認する。
- `alembic check` と DB negative test を走らせる。
- destructive command を runner plan に含めない。
- `rm -rf /`, `curl | sh`, `chmod 777`, fork bomb は fixture 化する。
- rollback できない変更は P0 scope から外す判断を検討する。

## 17. docs drift を放置しない

- `.claude/rules/` は常時制約の正本。
- `.claude/reference/` は ad-hoc 詳細の正本。
- `config/provider_compliance.toml` と Provider Compliance reference は同期する。
- Sprint Pack heavy template と ADR Gate Criteria 11 種は同期する。
- AgentRun status enum は DB / API / frontend / eval で同期する。
- SecretBroker status enum は DD-02 / DD-06 / migration で同期する。

