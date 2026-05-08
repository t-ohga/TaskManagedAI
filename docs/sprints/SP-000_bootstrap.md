---
id: "SP-000_bootstrap"
type: "heavy"
status: "ready"
sprint_no: 0
created_at: "2026-05-07"
updated_at: "2026-05-07"
target_days: 4.7
max_days: 6
adr_refs: []  # Sprint 0 着手と並行で proposed 状態として作成し、accepted 後に下記 planned_adr_refs から昇格させる
planned_adr_refs:
  - "[ADR-00001](../adr/00001_auth_rbac.md) # 認証方式 / dev login Cookie + secret token (Sprint 0-1 で proposed → accepted)"
  - "[ADR-00006](../adr/00006_secrets_management.md) # Secrets 管理方式 / SOPS + age + SecretBroker / atomic claim redeem (Sprint 0 で proposed → Sprint 4 実装前に accepted)"
  - "[ADR-00007](../adr/00007_external_exposure.md) # 外部公開設定 / Tailscale Serve + Funnel 不使用 + tag:taskhub-ci grants (Sprint 0 で proposed → accepted)"
  - "[ADR-00010](../adr/00010_provider_change.md) # Provider Compliance Matrix v2 の運用と更新 / 機械判定 enum (Sprint 0 で proposed → Sprint 5 実装前に accepted)"
related_sprints:
  - "SP-001_project_foundation # Sprint 1 / Project Foundation"
risks:
  - "横断基盤過大化"
  - "Open Questions B 未決"
  - "Provider Compliance Matrix 確認に時間が掛かる"
  - "Tailscale grants 設定ミス"
  - "ADR 4 件 (00001 / 00006 / 00007 / 00010) は proposed 状態で配置済 (2026-05-08)。Sprint 1 / 4 / 5 実装直前の accepted 化が未完了で、未昇格のまま実装に入るリスク"
---

このテンプレの使い方: ADR Gate Criteria に該当する Sprint 0 の横断基盤を、実装前の判断、検証、defer 境界まで固定する。

最終更新: 2026-05-07

## 目的

- Sprint 0 は、P0 実装を始める前に必要な横断基盤を must_ship だけに絞って固定する。
- must_ship は network boundary、`secret_ref`、Worker、Gold Task Seed v0、Provider Compliance Matrix、Sprint Pack template である。
- Hard Gates 自体の最終計測は Sprint 12 で行い、Sprint 0 では fixture、contract、skeleton、文書 gate を準備する。

## 背景

- 計画 v2 の Cross-cutting Foundations では、ネットワーク、observability、backup、secrets、multi-tenant 準備、private staging、Provider Compliance Matrix を Sprint 0 で土台化し、各 Sprint で強化する方針になっている。
- Sprint 0: Bootstrap は、Tailscale Serve / Funnel 不使用 / device approval、`secret_ref`、SecretBroker contract、Python worker arq、Provider Compliance Matrix、Gold Task Seed v0、Sprint Pack template、basic backup、structured logs、CI smoke、E2E skeleton を確定する。
- Observability dashboard、PITR drill、private staging 本運用は価値検証前の過大化を避けるため、Sprint 11.5 / 12 に送る。

## 対象外

- observability dashboard の完成。Prometheus / Loki / Grafana は Sprint 11.5 で本格化する。
- PITR drill。Sprint 12 の P0 Acceptance Test で restore drill と合わせて計測する。
- private staging 本運用接続。Sprint 11.5 で Tailscale GitHub Action 統合を行う。
- Vault 移行。P1 以降の secrets 管理方式変更として ADR 対象にする。
- Tailnet Lock。複数 signing node と disablement secrets escrow 整備後の P1 に送る。
- tsidp。experimental のため P0 認証基盤には採用せず、P1 以降で再評価する。

## 設計判断

- dev login: Cookie + secret token、個人 1 user 固定。`actor_id=human:default` とし、商用化時は cookie の中身を IdP token に置換する。
- SecretBroker: FastAPI 内 service module。`app.secrets.broker` に HTTP-like interface を持たせ、将来の独立 microservice 化に備える。
- Worker: docker-compose 別 service、Python arq。API と同一 image / 同一 dependency で、起動コマンドだけを分ける。
- ZDR enforcement: Provider Adapter middleware。`ProviderAdapter.execute()` の入口で Provider Compliance Matrix を参照し、`allowed_data_class` 超過を送信前に `policy_blocked` にする。
- Gold Task Seed v0: TaskManagedAI 自体を dogfooding する。Sprint 0-4 の task を保存し、Sprint 5 contract test と Sprint 11 private gold pool 拡張に使う。

## 実装チケット

| ticket_id | title | 機能 ID | target_days | depends_on | 主成果物 | 関連 DD ファイル |
|---|---|---|---:|---|---|---|
| BL-0001 | 軽量 / 重量 Sprint Pack template を正式化する | F-001 | 0.4 | - | `docs/sprints/_template_light.md` / `docs/sprints/_template_heavy.md` の正式運用 | `docs/基本設計/00_全体アーキテクチャ.md` |
| BL-0002 | ADR 番号体系と index 運用を決める | F-001 | 0.3 | BL-0001 | `docs/adr/README.md` と ADR template 運用 | `docs/基本設計/04_セキュリティ_権限_監査設計.md` |
| BL-0003 | Tailscale Serve / Funnel 不使用 / device approval checklist を作る | NF-002 | 0.4 | - | network boundary checklist と ADR-00007 draft | `docs/基本設計/05_ネットワーク境界設計.md` |
| BL-0004 | `secret_ref` URI と SecretBroker contract を固定する | NF-003 | 0.5 | - | `secret://sops/<scope>/<name>#<version>` と `app.secrets.broker` interface draft | `docs/基本設計/06_秘密管理設計.md`, `docs/基本設計/04_セキュリティ_権限_監査設計.md`, `docs/基本設計/01_拡張境界とAdapter設計.md` |
| BL-0005 | Worker / Queue arq job schema と cancel propagation を固定する | F-008,NF-011 | 0.5 | - | arq job schema、idempotency key、retry/backoff、DLQ、Redis pub/sub cancel contract | `docs/基本設計/00_全体アーキテクチャ.md`, `docs/基本設計/03_AIオーケストレーション設計.md` |
| BL-0006 | Gold Task Seed v0 の保存 schema と除外基準を決める | F-019,NF-009 | 0.4 | BL-0001 | Gold Task Seed v0 schema、sanitize / 除外基準、dataset version 方針 | `docs/基本設計/03_AIオーケストレーション設計.md`, `docs/基本設計/07_可観測性設計.md` |
| BL-0007 | Provider Compliance Matrix TOML の列と初期値を確定する | F-012,NF-004 | 0.5 | BL-0004 | `config/provider_compliance.toml` と 5 provider / feature 行 | `docs/基本設計/04_セキュリティ_権限_監査設計.md`, `docs/基本設計/01_拡張境界とAdapter設計.md` |
| BL-0008 | structured logs / correlation id / error taxonomy を固定する | NF-006 | 0.4 | - | JSON Lines log format、correlation id 規約、8 分類 error taxonomy skeleton | `docs/基本設計/07_可観測性設計.md`, `docs/基本設計/04_セキュリティ_権限_監査設計.md` |
| BL-0009 | basic backup script と age 暗号化方針を決める | NF-007 | 0.4 | BL-0004 | `pg_dump` + age 暗号化 backup script、retention 草案、backup key 保管決定 | `docs/基本設計/06_秘密管理設計.md`, `docs/基本設計/07_可観測性設計.md` |
| BL-0010 | CI smoke と E2E skeleton の framework を選定する | NF-011 | 0.4 | - | lint + typecheck + unit 1 件、Playwright + pytest/httpx skeleton | `docs/基本設計/05_ネットワーク境界設計.md`, `docs/基本設計/07_可観測性設計.md`, `docs/基本設計/00_全体アーキテクチャ.md` |
| BL-0011 | Open Questions A 5 項目を決定済み前提として Sprint 0 Pack に参照する | F-001,DEP-A-01〜05 | 0.2 | BL-0001 | Open Questions A の決定済み記録 | `docs/基本設計/00_全体アーキテクチャ.md`, `docs/基本設計/04_セキュリティ_権限_監査設計.md`, `docs/基本設計/05_ネットワーク境界設計.md`, `docs/基本設計/06_秘密管理設計.md` |
| BL-0012 | Sprint 0 Review の `changed / verified / deferred / risks` 雛形を作る | F-001 | 0.3 | BL-0001 | Sprint Review placeholder と追記規約 | `docs/基本設計/00_全体アーキテクチャ.md` |

## タスク一覧

- [ ] `_template_light.md` と `_template_heavy.md` の frontmatter key、必須セクション、Review 形式を確定する。
- [ ] Sprint Pack frontmatter の正式キーを Open Questions B-06 として決定し、この Pack に反映する。
- [ ] ADR の 5 桁番号体系、`docs/adr/000NN_<title>.md` 形式、index 更新規約を Open Questions B-07 として決定する。
- [ ] ADR-00001 / 00006 / 00007 / 00010 の draft link を配置し、ADR-00011 を Sprint 8 扱いに残す。
- [ ] Tailscale Serve、Funnel 不使用、device approval、Tailscale SSH、public SSH 原則閉鎖を checklist 化する。
- [ ] machine naming rule `app-<env>-<role>-<NN>` を ADR-00007 に記録し、CT log 漏えい対策として固定する。
- [ ] grants は `src=自分の identity` から `dst=tag:taskhub` の TCP/443 のみを許可する前提で checklist 化する。
- [ ] Docker public bind 禁止、`127.0.0.1` bind、PostgreSQL / Redis no public bind の確認項目を作る。
- [ ] `secret_ref` URI を `secret://sops/<scope>/<name>#<version>` に固定する。
- [ ] SecretBroker の `get_capability_token` / `redeem_token` / `resolve_secret_ref` contract draft を `app.secrets.broker` に書く。
- [ ] SecretBroker が raw secret value を caller、AI、runner、artifact export に返さない invariant を文書と skeleton に入れる。
- [ ] capability token の TTL、scope、operation、actor、run_id、one-time redeem、audit event を固定する。
- [ ] backup 暗号鍵の保管場所を Open Questions B-08 として確定する。
- [ ] basic backup script の `pg_dump`、age 暗号化、別ボリューム保存、retention 草案を用意する。
- [ ] Worker / Queue は Python arq、docker-compose 別 service、Redis pub/sub cancel propagation として job schema を固定する。
- [ ] structured logs の JSON Lines 必須 field、correlation id 伝播、redaction policy を skeleton に入れる。
- [ ] error taxonomy 8 分類を service 共通定義として code skeleton に入れる。
- [ ] Provider Compliance Matrix の TOML 列を `provider` から `last_verified_at` まで固定する。
- [ ] OpenAI Responses / Anthropic Messages / Anthropic Batches / Gemini / Mock の 5 行を `config/provider_compliance.toml` に作る。
- [ ] Gold Task Seed v0 の schema、dataset version、sanitize / 除外基準を決め、5 件以上を記録する。
- [ ] CI smoke として lint、typecheck、単体 test 1 件を実行できる scripts を用意する。
- [ ] E2E skeleton として Playwright + pytest/httpx の起動確認 sample を用意する。
- [ ] secret canary fixture を fake pattern で作成し、漏えい検知用の最小 test に接続する。

## must_ship / defer_if_over_budget 対応表

| Sprint | target_days | max_days | must_ship | defer_if_over_budget |
|--------|-------------|----------|-----------|----------------------|
| Sprint 0 | 4.7 | 6 | ネットワーク境界設計 (`tag:taskhub` + `tag:taskhub-ci` grants 方針) / `secret_ref` 仕様 + SecretBroker atomic claim contract / Worker 確定 / Gold Task Seed v0 (`payload_data_class` 必須) / Provider Compliance Matrix v2 (機械判定 enum + provider_request_preflight 設計) / Sprint Pack テンプレ / ADR 4 件 (00001/00006/00007/00010) proposed 化 | observability dashboard / PITR drill / private staging 本運用 |

## 受け入れ条件

- [ ] `secret_ref` URI 仕様（`secret://sops/<scope>/<name>#<version>`）が決まっており、SecretBroker の draft interface が `app.secrets.broker` に書かれている。
- [ ] **SecretBroker contract** に以下を明記: redeem は check→execute→mark used を**禁止**し、単一 transaction / conditional UPDATE による **atomic claim**（`actor_id` / `run_id` / `expected_request_fingerprint = :computed_fingerprint` (broker-computed canonical OperationContext fingerprint、caller-supplied 不可) / `requested_operation` binding 必須、0 件 RETURNING 時 deny、raw secret 非返却）。Sprint 4 実装前の skeleton comment / test placeholder まで Sprint 0 で固定する。
- [ ] Tailscale Serve / Funnel 不使用 / device approval / 中立 machine 命名規則が ADR-00007 で proposed 化されている。
- [ ] **`tag:taskhub-ci` grants 方針**を ADR-00007 に明記: `tagOwners.tag:taskhub-ci`、`src=tag:taskhub-ci` → `dst=tag:taskhub` TCP/443、ephemeral auth key、reusable key 禁止、Loki log mask。実本運用は Sprint 11.5 で defer、方針固定は Sprint 0 must_ship。
- [ ] Provider Compliance Matrix が `config/provider_compliance.toml` に作成され、**DD-04 v2 列セット**（provider / api_or_feature / zdr_eligible / retention / training_use / region_or_data_transfer / subprocessor_or_doc_url / plan_required / **allowed_data_class (単一 enum)** / **condition_status** / p0_policy_note / last_verified_at）で OpenAI Responses / Anthropic Messages / Anthropic Batches / Gemini / Mock の 5 行が確定している。
- [ ] **data class ordinal 固定** を ADR-00010 に明記: `public < internal < confidential < pii` の単一順序とし、`payload_data_class > allowed_data_class` 等のすべての比較演算は **この ordinal map**（`{public:0, internal:1, confidential:2, pii:3}`）で行う。文字列比較や別順序の実装は禁止。Gold Task Seed の `payload_data_class <= internal` 検証も同じ ordinal map を使う。
- [ ] **Provider Compliance 機械判定 invariant** を ADR-00010 に明記:
  - `payload_data_class > allowed_data_class` 送信は middleware で必ず deny
  - `payload_data_class` 未設定は deny
  - **`zdr_eligible = no` 行 deny**: `zdr_eligible = no` の行への `payload_data_class >= internal` 送信は deny。public-only 例外は別 ADR 必須
  - **`training_use != no` 行 deny**: `training_use=yes` または `training_use=unverified` の行への `payload_data_class >= internal` 送信は deny (effective 上限 `public`)。public-only 例外は別 ADR 必須
  - **`allowed_data_class >= confidential` の解禁条件**:
    1. `zdr_eligible = yes` AND `retention != unverified` AND `training_use=no` AND `region_or_data_transfer = verified` AND `plan_required != none` のみ無条件で許可
    2. `zdr_eligible = conditional` AND `condition_status = verified` (内部に `plan_required` 達成も含む) AND `retention != unverified` AND `training_use=no` AND `region_or_data_transfer = verified` AND `plan_required != none` の場合のみ許可
    3. 上記いずれも満たさない provider は `allowed_data_class <= internal` に強制低下（middleware が runtime で再計算）
    4. `training_use != no` の場合は effective 上限を `public` に強制低下
    5. `plan_required = none` AND effective >= confidential の場合は effective を internal に低下
  - `provider_request_preflight` を ProviderAdapter.execute() の必須段階として固定
  - 実装は Sprint 5、Sprint 0 では contract と policy 草案を固める
- [ ] structured logs + correlation id + error taxonomy が code skeleton で確認できる。
- [ ] basic backup script (`pg_dump` + age) が dev 環境で動く。
- [ ] CI smoke (lint + typecheck + 単体 test 1 件) が通る。
- [ ] E2E test skeleton (Playwright + pytest/httpx) が起動する。
- [ ] Sprint Pack template (軽量 / 重量) と ADR template が `docs/sprints/` / `docs/adr/` に配置済みである。
- [ ] **ADR 4 件 (ADR-00001 / 00006 / 00007 / 00010) が proposed 状態で `docs/adr/` に配置されている**（accepted は実装直前で行う）。
- [ ] Gold Task Seed v0 が 5 件以上記録されている。
- [ ] **Gold Task Seed v0 schema に `payload_data_class` / `sanitize_status` / `exclusion_reason` / `dataset_version` を必須化**し、全 seed が `payload_data_class <= internal` を満たす。
- [ ] Open Questions A の 5 項目が決定済として記載されている。
- [ ] Open Questions B の 3 項目が確定している。
- [ ] secret canary fixture が漏えい検知できる状態で準備されている。
- [ ] **PRD terminology propagation checklist** が完了: `payload_data_class` / `allowed_data_class` (Matrix から解決) / `tool_mutating_gateway_stub` (P0 deny-only) / `runner_mutation_gateway` (Sprint 7 完成) / AgentRun 16 状態 + blocked サブ 3 / ContextSnapshot 10 カラム / actors-principals / atomic claim を、Sprint Pack template / Gold Task Seed schema / 後続 Sprint Pack の引用先で参照または明示 defer する箇所を文書化する。

## 検証手順

- [ ] `ruby -e 'require "yaml"; YAML.load_file("docs/sprints/SP-000_bootstrap.md")'` で frontmatter が valid YAML として読めることを確認する。
- [ ] `rg -n "BL-0001|BL-0002|BL-0003|BL-0004|BL-0005|BL-0006|BL-0007|BL-0008|BL-0009|BL-0010|BL-0011|BL-0012" docs/sprints/SP-000_bootstrap.md` で 12 チケットが揃っていることを確認する。
- [ ] frontmatter `planned_adr_refs` だけを parse し、集合が `ADR-00001` / `ADR-00006` / `ADR-00007` / `ADR-00010` と完全一致することを確認する（本文中の Sprint 8 defer 言及で ADR-00011 に触れることは許容）。具体: `python -c "import yaml,re; fm=yaml.safe_load(open('docs/sprints/SP-000_bootstrap.md').read().split('---')[1]); ids=sorted([re.search(r'ADR-\d+',x).group() for x in fm['planned_adr_refs']]); assert ids==['ADR-00001','ADR-00006','ADR-00007','ADR-00010'], ids"`
- [ ] `ls docs/adr/00001_*.md docs/adr/00006_*.md docs/adr/00007_*.md docs/adr/00010_*.md` で ADR 4 件が proposed 状態で配置されていることを確認する。
- [ ] `python -c "from app.secrets.broker import SecretBroker; print(SecretBroker)"` で SecretBroker draft interface が import できることを確認する。
- [ ] `python -m tomllib config/provider_compliance.toml` で Provider Compliance Matrix の TOML が parse できることを確認する。
- [ ] **DD-04 v2 列セット検証**: `python` で TOML を parse し、各行の必須列 (`provider`, `api_or_feature`, `zdr_eligible`, `retention`, `training_use`, `region_or_data_transfer`, `subprocessor_or_doc_url`, `plan_required`, `allowed_data_class`, **`condition_status`**, `p0_policy_note`, `last_verified_at`) が全件存在し、`allowed_data_class` が **scalar enum** (`public` / `internal` / `confidential` / `pii`)、`zdr_eligible` が enum (`yes` / `no` / `conditional` / `n/a`)、`condition_status` が enum (`verified` / `unverified` / `not_applicable`)、`retention` が enum (`0d` / `30d` / `90d` / `unverified`) であり、`last_verified_at` が非空の ISO 日付であることを確認する。
- [ ] **Provider Compliance invariant 検証**: `allowed_data_class >= confidential` の行は次のいずれかを満たすことを確認する。
  - (a) `zdr_eligible = yes` AND `retention != unverified` AND `training_use=no` AND `region_or_data_transfer = verified` AND `plan_required != none`
  - (b) `zdr_eligible = conditional` AND **`condition_status = verified`**（`plan_required` / provider 固有条件 / ZDR 設定 / region 条件すべて達成済み） AND `retention != unverified` AND `training_use=no` AND `region_or_data_transfer = verified` AND `plan_required != none`
- [ ] 上記いずれも満たさない行は middleware が runtime で `allowed_data_class <= internal` に強制低下する unit test を追加し、`conditional` 行で `condition_status != verified` の場合に deny される negative test を含める。
- [ ] **`zdr_eligible = no` 行への internal 以上送信 deny** を contract test 化: `zdr_eligible=no` の行に `payload_data_class >= internal` を送ると middleware が deny し、別 ADR の許可なしに通過しないことを確認。
- [ ] **`training_use != no` 行 deny** を contract test 化: `training_use=yes` / `training_use=unverified` の行に `payload_data_class >= internal` を送ると middleware が deny し、effective 上限が `public` に強制低下されることを確認。
- [ ] `pnpm lint` を実行し、CI smoke の lint が通ることを確認する。
- [ ] `pnpm typecheck` を実行し、frontend / shared typecheck が通ることを確認する。
- [ ] `uv run pytest tests/unit -q` を実行し、単体 test 1 件以上が通ることを確認する。
- [ ] `pnpm exec playwright test --list` と `uv run pytest tests/e2e -q` で E2E skeleton が起動することを確認する。
- [ ] `bash <basic-backup-script>` を dev DB に対して実行し、`pg_dump` 出力が age で暗号化され、復号なしに中身が読めないことを確認する。
- [ ] secret canary fixture を含む sample を実行し、raw canary が provider request、runner stdout/stderr、artifact、audit payload に残らないことを確認する。
- [ ] **`tag:taskhub-ci` grants 方針**を ADR-00007 で確認: `tag:taskhub-ci` の tagOwner、`src=tag:taskhub-ci` → `dst=tag:taskhub` TCP/443 の grant、ephemeral key 必須 / reusable key 禁止、Loki log mask が記載されていること。
- [ ] **Gold Task Seed v0 schema 検証**: `python` で seed JSON を parse し、各 seed が `payload_data_class` を持ち、値が `public` / `internal` のいずれかであることを確認する。`sanitize_status` / `exclusion_reason` / `dataset_version` の必須列も検証する。
- [ ] **PRD terminology propagation 確認**: `rg -n "request_data_class|allowed_data_class.*受信" docs/sprints/ docs/実装計画/` で旧用語が残っていないことを確認（hit が 0 件であること）。さらに `rg -n "mutating gateway 完成" docs/sprints/ docs/実装計画/ docs/基本設計/` で旧名「mutating gateway 完成」がテンプレ・ロードマップ・基本設計に残っていないことを確認（自己検証行を除外するため、当 SP-000 ファイルは検索対象から除外: `rg ... --glob '!SP-000_bootstrap.md'`）。

## レビュー観点

- [ ] 権限境界が deny-by-default になっている。
- [ ] 外部入力が検証され、AI 出力が直接 command / SQL / workflow / external tool 操作へ接続されていない。
- [ ] 監査ログ、エラー、失敗時の状態遷移が確認できる。
- [ ] 関連 ADR と実装が乖離していない。
- [ ] Tailscale grants が **2 系統のみ** に最小化されている: ① 人間 identity → `tag:taskhub` TCP/443、② `tag:taskhub-ci` → `tag:taskhub` TCP/443。これ以外の src / dst / protocol は deny。CI 用は ephemeral auth key 必須 / reusable key 禁止 / Loki log mask 適用。
- [ ] CT log 漏えい対策として machine 名、tailnet DNS、docs / screenshot / CI logs の中立命名と redaction 方針が入っている。
- [ ] Provider Compliance Matrix の `last_verified_at` 列が 5 行すべてで埋まっている。

## 残リスク

- 横断基盤の過大化で価値検証前に失速する: Sprint 0 は must_ship だけを出荷し、dashboard / PITR / private staging 本運用は Sprint 11.5 / 12 に送る。
- Provider 仕様変更で Compliance Matrix が陳腐化する: `last_verified_at` を必須列にし、Provider 追加 / 切替や data class 引き上げは ADR-00010 更新を要求する。
- Tailscale grants 設定ミスで意図せず外部公開される: Funnel 不使用、TCP/443 のみ、Docker localhost bind、`ss -lntp` / `docker ps` の smoke を review gate にする。
- 個人運用ゆえ復旧手順が形骸化する: Sprint 0 は basic backup の実行までに止め、Sprint 12 で RPO / RTO と restore drill を acceptance として再計測する。
- secret canary fixture が現実的な攻撃を捕捉できない可能性がある: Sprint 5.5 / 11 / 12 で Output Validator、Input Trust Layer、security eval suite に拡張する。

## 次スプリント候補

- Sprint 1: Project Foundation (BL-0013〜BL-0021)。
- dev login の実装、Cookie + secret token、`human:default` actor injection。
- `api` / `worker` / `postgres` / `redis` の Docker Compose 起動、FastAPI healthcheck、arq worker startup。
- 最小 admin UI shell、navigation skeleton、CI smoke の継続実行。
- Sprint 0 で defer した observability dashboard / PITR drill / private staging 本運用は Sprint 11.5 / 12 へ送る。

## 関連 ADR

- [ADR-00001](../adr/00001_auth_rbac.md): 認証方式。P0 dev login は Cookie + secret token、個人 1 user 固定、`human:default` actor とする。
- [ADR-00006](../adr/00006_secrets_management.md): 秘密管理。SOPS + age + FastAPI 内 SecretBroker、`secret_ref`、capability token、raw secret 非露出を固定する。
- [ADR-00007](../adr/00007_external_exposure.md): 外部公開設定。Tailscale Serve、Funnel 不使用、device approval、中立 machine 命名、grants 最小化を固定する。
- [ADR-00010](../adr/00010_provider_change.md): Provider Compliance Matrix の運用と更新。5 provider / feature 行、`allowed_data_class`、`last_verified_at`、Provider 追加 / 切替時の ADR 更新を扱う。

ADR-00011 は Sprint 8 の GitHub App permission 変更で作成するため、この Sprint 0 Pack の関連 ADR には含めない。

## Review

- changed: Sprint 完了後に、実際に変えたファイル、template、config、skeleton、fixture を追記する。
- verified: Sprint 完了後に、通した lint / typecheck / unit / smoke / manual check を追記する。
- deferred: Sprint 完了後に、Sprint 11.5 / 12 / P1 へ送った項目と理由を追記する。
- risks: Sprint 完了後に、残った security / ops / provider / documentation risk を追記する。
