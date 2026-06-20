---
id: "ADR-00036"
title: "API キー管理画面 (R-3: secret_refs read-only インベントリ)"
status: "accepted"
date: "2026-05-29"
deciders: ["t-ohga"]
adr_gate_criteria: [3, 6]
related_adr:
  - "ADR-00035 (プロジェクト設定編集)"
related_dd:
  - "DD-06 (秘密管理設計)"
---

# ADR-00036: API キー管理画面 (R-3)

## 背景

UI 改善計画 R-3「API キー管理画面」を実装する。現状 `/settings` の「シークレット管理」Panel は
静的な `SecretBoundaryNotice` (SecretBroker 境界の説明文) のみで、登録済の secret (provider API key /
GitHub App key 等) の **状態が UI から一切確認できない**。ユーザーは「どの provider/repo の鍵が登録済か、
active か、いつ rotation されたか」を把握できない。

実装計画上 R-3 は **Tier 4「design approval 必須」** で、ADR Gate Criteria #6 (Secrets 管理方式) +
#3 (API 契約: 新 read endpoint) に該当する。Secrets は最も機微な境界であり、break-glass 対象外で
常時 ADR 必須。

**調査済の重要事実**:
- `secret_refs` table / `SecretRef` model は存在し、表示可能な非秘密 metadata を持つ:
  `secret_uri` (opaque reference) / `scope` (p0/workspace/project/repo/agent_run/provider) / `name` /
  `version` / `status` (pending/active/deprecated/revoked) / `runner_injectable` (常に false) /
  `allowed_consumers` / `allowed_operations` / `owner_actor_id` / `rotated_from_id` /
  `created_at` / `updated_at` / `deprecated_at` / `revoked_at`。
- DB CHECK `secret_refs_ck_metadata_no_raw_secret` が metadata jsonb への raw secret 系 key
  (raw_secret/raw_token/api_key/auth_token/secret_value/plaintext/private_key/sops_key/age_key/
  canary/token/raw_value/value) 混入を **物理的に禁止**。raw secret は DB に存在しない。
- `SecretRefRepository` は `get` / `list_by_status` / `assert_active` を持ち、base `list(tenant_id)` で
  全件取得可。UI 向け list endpoint は **未実装** (RepoProxy 内部利用のみ)。
- raw secret の resolve は SecretBroker 内部 (capability token 経由) のみ。本 endpoint は SecretBroker を
  一切呼ばず、metadata カラムを返すだけ。

## 決定対象

`/settings` の「シークレット管理」Panel を、登録済 secret_refs の **read-only インベントリ**に拡張する:

1. tenant 内の secret_refs 一覧 (全 status) を非秘密 metadata で表示。
2. status バッジ (active / deprecated / revoked / pending)、scope、name、version、allowed_operations、
   rotation lineage (rotated_from)、timestamps を表示。
3. **mutation なし** (登録 / rotation / revoke は SOPS+age ops/CLI のまま、UI は表示のみ)。

## 前提 / 制約 (DD-06 / secretbroker-boundary invariant)

- **raw secret は UI / API response / DB に出さない**。本 endpoint は `secret_refs` の **明示 allowlist された
  構造化カラムのみ** 返し、SecretBroker を呼ばない (capability token 発行も resolve もしない)。
- **UI からの secret mutation は P0 deny** (DD-06 / rendering.md §8)。登録 / rotation / revoke は
  SOPS+age + SecretBroker ops/CLI 経路のみ。UI に書込導線を作らない。
- server-owned-boundary §1: tenant_id は session 経由 resolve、caller-supplied 経路なし。
- tenant 越境禁止: 全 query で `tenant_id` filter。cross-tenant negative test 必須 (AC-HARD-03 系)。
- audit: read-only のため mutation audit は発生しない。secret_access (capability token redeem) は
  本 endpoint では起こらない (SecretBroker 非経由)。

### 閲覧権限境界 (Codex plan review R1 HIGH 反映)

secret inventory metadata は raw secret でなくとも **高価値**である (鍵の存在・命名・対象 provider/repo・
rotation 状況・利用主体を列挙でき、session 乗っ取り時の被害範囲を広げる)。よって閲覧境界を明文化する:

- **P0 (single-user)**: 閲覧者は **human owner のみ**。これは運用仮定ではなく **実装で enforce** する
  (Codex plan review R1 / 実装 R1 HIGH)。endpoint は `require_secret_refs_viewer` dependency を通し、
  session で resolve した actor の `actor_type` を DB で検証して `human` 以外 (service / agent / provider /
  github_app) を **403 で fail-closed** する。`tenant_id` filter で tenant に閉じる。single-owner 運用仮定が
  崩れても (同一 tenant に service/agent/追加 human actor が現れても) 非 human actor は列挙できない。
- **multi-user 化 (P0.1+)**: `require_secret_refs_viewer` を専用の secrets-view permission / role gate に
  置換する (位置を予約)。複数 human owner を区別する必要が出た時点で role を導入。
- **blast-radius 最小化**: 後述の field 分類で security topology (allowed_consumers / allowed_operations /
  owner_actor_id / 完全 secret_uri) を **default で返さない**。

### Field 分類 (Codex plan review R1 HIGH/MEDIUM 反映、response allowlist)

| field | P0 公開 | 理由 |
|---|---|---|
| `id` (UUID) | 公開 | 非秘密の row 識別子 (React key)。capability 操作には別途 token が必要で id 単体では無害 |
| `scope` | 公開 | 「provider 鍵 / repo 鍵」等の分類。管理画面に必要 |
| `name` | 公開 | 鍵の identity (owner が管理する対象)。本機能の目的 |
| `version` | 公開 | rotation version 把握に必要 |
| `status` | 公開 | active/deprecated/revoked/pending バッジ |
| `rotated` (bool) | 公開 | `rotated_from_id is not null` を bool 化 (lineage の有無のみ、別 id は露出しない) |
| `created_at` / `updated_at` / `deprecated_at` / `revoked_at` | 公開 | rotation/失効の時系列 |
| **`secret_uri`** | **非公開** | `secret://<backend>/<scope>/<name>#<version>` (backend=`local`|`sops`、ADR-00058) 文字列は DOM/log/screenshot に残る identifier。scope/name/version を個別に出すため URI 自体は返さない |
| **`allowed_consumers`** | **非公開** | 内部 authz topology (どの actor が使えるか)。管理画面に不要、機微 |
| **`allowed_operations`** | **非公開** | 同上 (どの operation に使えるか) |
| **`owner_actor_id`** | **非公開** | tenant 内 actor 識別子。authz 構造露出。明示除外 |
| **`runner_injectable`** | **非公開** | 常に false (CHECK)、情報価値なし |
| **`metadata_` jsonb** | **非公開** | freeform。CHECK で raw secret は禁止だが保守的に非公開 |

- **実装は ORM/model dump 禁止**。`SecretRefListItem` への明示 mapping のみ (新カラム追加時に自動露出しない)。
- contract test で `secret_uri` / `allowed_consumers` / `allowed_operations` / `owner_actor_id` /
  `metadata_` / raw secret pattern の **非含有を assert** する。

## 選択肢

1. **secret_refs read-only インベントリ (採用)**: 構造化 metadata のみ返す read endpoint + UI 一覧。
   invariant 完全準拠。raw secret 非露出、mutation なし。
2. Provider/Repo 設定状態の集約ビューのみ: provider (openai/anthropic/gemini) / repo 鍵の active/missing
   のみ表示。情報量が少なく、rotation/deprecation の追跡や複数 version 把握ができない。**却下** (R-3 の
   「管理画面」要件を満たさない)。
3. UI から登録 / rotation / revoke を可能にする: raw secret が UI/API を transit し、DD-06 の
   「raw secret を UI に出さない」「UI からの secret mutation は P0 deny」に違反。**却下** (P0 deny)。

## 採用案

### A. read-only list endpoint (新規)

```
GET /api/v1/me/secret-refs
response: { secret_refs: SecretRefListItem[] }
```

`SecretRefListItem` (**明示 allowlist、§Field 分類の「公開」のみ**):
- `id` (UUID) / `scope` / `name` / `version` / `status` / `rotated` (bool = `rotated_from_id is not null`) /
  `created_at` / `updated_at` / `deprecated_at` (| null) / `revoked_at` (| null)。
- **除外 (返さない)**: `secret_uri` / `allowed_consumers` / `allowed_operations` / `owner_actor_id` /
  `runner_injectable` / `metadata_`。
- **ORM/model dump 禁止**: SecretRef row → `SecretRefListItem` を field 明示 mapping (`_to_secret_ref_item`)。
- tenant-scoped: `SecretRefRepository.list_all` 経由で `tenant_id` filter。order by (scope, name, version)。
- SecretBroker を呼ばない (raw secret resolve なし、capability token 発行なし)。
- P0 は session auth のみ (§閲覧権限境界: owner = 唯一 actor)。P0.1 で secrets-view policy gate 追加位置を予約。

### B. frontend

- `frontend/lib/api/session.ts` に `SecretRefListItemSchema` (Zod、公開 field のみ) + `listSecretRefs()` を追加。
- `/settings` の「シークレット管理」Panel に read-only インベントリ table を追加 (Server Component で fetch、
  `SecretBoundaryNotice` は残し、その下に一覧を表示)。空時は「登録済シークレットはありません」表示。
- 表示は scope / name / version / status バッジ (active=緑 / deprecated=灰 / revoked=赤 / pending=黄) /
  rotated 表示 / timestamps。**secret_uri / allowed_consumers / allowed_operations / owner_actor_id は表示しない**。
- raw secret / token / 完全 secret_uri は DOM に一切出さない。

### C. repository

- `SecretRefRepository.list_all(tenant_id)` を追加 (全 status、order by scope/name/version)。
  base `list` は order 未指定のため、安定順序の専用 method を足す。

## 却下案

- 集約状態ビューのみ (選択肢 2): 管理画面要件を満たさない。
- UI mutation (選択肢 3): DD-06 invariant 違反、P0 deny。

## リスク

- MEDIUM (Secrets metadata、ADR Gate #6)。read-only で mutation も SecretBroker 呼び出しもないため raw secret
  露出経路は設計上存在しない (model CHECK + 明示 allowlist + metadata_/owner/topology 非公開)。
- **secret inventory enumeration** (Codex R1 HIGH): metadata でも鍵の存在・命名・対象を列挙できる。P0 は
  single-user owner のため session auth で許容するが、security topology (allowed_consumers/operations/
  owner_actor_id/完全 secret_uri) は default 非公開とし blast-radius を最小化。P0.1 multi-user 化時に
  secrets-view policy gate を追加 (位置を ADR に予約)。
- 主リスク: response に誤って `metadata_` / `owner_actor_id` / topology / resolve 値を含めること →
  明示 allowlist mapping (ORM dump 禁止) + contract test で禁止 field 非含有を assert。
- secret_uri を DOM/log に残すリスク → 完全 URI は返さず scope/name/version を個別表示。
- cross-tenant 露出リスク → repository の tenant_id filter + cross-tenant negative test。

## rollback 手順

1. frontend: /settings のインベントリ table を revert (`SecretBoundaryNotice` のみの静的 Panel に戻す)。
2. backend: `GET /api/v1/me/secret-refs` endpoint + `SecretRefListItem` schema + `listSecretRefs()` を削除。
   `SecretRefRepository.list_all` を revert。
3. DB / migration 変更なし (read-only、schema 追加なし)。data loss なし。

## 実装対象ファイル

- `backend/app/api/me.py`: `SecretRefListItem` / `SecretRefListResponse` schema + `GET .../secret-refs` endpoint。
- `backend/app/repositories/secret_ref.py`: `list_all(tenant_id)`。
- `frontend/lib/api/session.ts`: `SecretRefListItemSchema` + `listSecretRefs()`。
- `frontend/app/(admin)/settings/page.tsx` + `_components`: read-only インベントリ table。
- tests: backend contract (metadata 返却 + raw secret 非含有 + tenant-scoped + cross-tenant negative) +
  frontend vitest (一覧描画 / status バッジ / raw secret 非表示)。

## テスト指針

- endpoint が allowlist された公開 metadata のみ返す。
- **禁止 field 非含有 assert** (Codex R1 反映): `secret_uri` / `allowed_consumers` / `allowed_operations` /
  `owner_actor_id` / `runner_injectable` / `metadata_` が response に含まれない。
- `assert_no_raw_secret` 相当: response JSON に raw secret pattern (sk-/Bearer/api_key/secret:// 等) が無い。
- tenant-scoped: 別 tenant の secret_refs を返さない (cross-tenant negative)。
- 空 tenant で空配列を返す。
- status 別 (active/deprecated/revoked/pending) + rotated bool が正しく出る。
- frontend: 一覧描画、status バッジ、scope/name/version 表示、secret_uri / topology / raw secret は DOM に出ない。

## DoD

- [ ] `GET /api/v1/me/secret-refs` が allowlist 公開 metadata のみ返す (SecretBroker 非経由、明示 mapping)。
- [ ] response に raw secret / token / `secret_uri` / `allowed_consumers` / `allowed_operations` /
      `owner_actor_id` / `metadata_` を含めない (contract test で assert)。
- [ ] tenant-scoped + cross-tenant negative test pass。
- [ ] UI に書込導線 (登録/rotation/revoke) が存在しない (read-only)。
- [ ] frontend に raw secret / 完全 secret_uri / topology が DOM 出力されない。
- [ ] 閲覧権限境界 (P0 owner-only / P0.1 policy gate 予約) が ADR に明文化されている。
- [ ] backend ruff/mypy/pytest + frontend tsc/eslint/vitest pass (pre-existing 債務は除く)。
- [ ] Codex adversarial review clean (CRITICAL=0 / HIGH≤2)。
- [ ] Codex adversarial review clean (CRITICAL=0 / HIGH≤2)。
